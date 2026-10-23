from django.urls import Resolver404, resolve
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .roles import Role
from .tenancy import set_tenant_context

# Tenant statuses that block all API access (PRD: suspended accounts — login
# blocked, data preserved; cancelled — data retained, no access; deleted — the
# Module 22 tombstone, which has no logins left anyway).
BLOCKED_TENANT_STATUSES = ('suspended', 'cancelled', 'deleted')

# Module 22: while an account-deletion request is ACTIVE (pending / processing / failed),
# a locked user may only see it and, when allowed, cancel it. Exact (url_name, method) pairs —
# never raw paths — so `PATCH /auth/me/` stays blocked.
DELETION_LOCK_ALLOWED = frozenset({
    ('auth-me', 'GET'),
    ('auth-account-deletion', 'GET'),
    ('auth-account-deletion', 'DELETE'),
})

DELETION_PENDING_CODE = 'account_deletion_pending'
TENANT_DELETION_PENDING_CODE = 'tenant_deletion_pending'


def active_deletion_for(user):
    """The ACTIVE AccountDeletionRequest that locks `user`, or None. The one lookup shared by
    JWT auth, login and refresh, so a locked user is treated the same on all three paths.
    Imported lazily: this module is loaded by DRF settings before the app registry is ready."""
    from apps.accounts.models import AccountDeletionRequest

    return AccountDeletionRequest.objects.active_for(user).order_by('-requested_at').first()


def _deletion_lock_code(user, deletion):
    """403 code for a locked user: their own request vs. their tenant's (staff of a business
    the Owner is deleting)."""
    return DELETION_PENDING_CODE if deletion.user_id == user.pk else TENANT_DELETION_PENDING_CODE


def _route_allowed_while_locked(request):
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    return (match.url_name, request.method) in DELETION_LOCK_ALLOWED


class TenantJWTAuthentication(JWTAuthentication):
    """JWT auth that enforces tenant suspension, token auth_version validity,
    the account-deletion lock, and sets the Postgres tenant context (RLS GUCs)
    for the rest of the request."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result

        # An ACTIVE deletion request is looked up before the tenant-status check so the
        # deletion codes (and the cancel/status allow-list) win over a suspension that
        # happened during the grace period.
        deletion = active_deletion_for(user)

        if deletion is None and user.tenant_id is not None and user.tenant.status in BLOCKED_TENANT_STATUSES:
            # Force logout on plan suspension — the frontend reacts to this code.
            raise AuthenticationFailed(
                _('This account is suspended.'), code='subscription_suspended'
            )

        if token.get('auth_version') != user.auth_version:
            raise AuthenticationFailed(
                _('Password has been changed. Please log in again.'), code='password_changed'
            )

        set_tenant_context(
            tenant_id=user.tenant_id,
            is_super_admin=user.role == Role.SUPER_ADMIN,
        )

        if deletion is not None and not _route_allowed_while_locked(request):
            raise PermissionDenied(
                _('This account is scheduled for deletion.'),
                code=_deletion_lock_code(user, deletion),
            )
        return user, token
