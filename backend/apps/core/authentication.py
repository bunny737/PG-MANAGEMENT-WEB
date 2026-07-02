from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .roles import Role
from .tenancy import set_tenant_context

# Tenant statuses that block all API access (PRD: suspended accounts — login
# blocked, data preserved; cancelled — data retained, no access).
BLOCKED_TENANT_STATUSES = ('suspended', 'cancelled')


class TenantJWTAuthentication(JWTAuthentication):
    """JWT auth that enforces tenant suspension and sets the Postgres tenant
    context (RLS GUCs) for the rest of the request."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result

        if user.tenant_id is not None and user.tenant.status in BLOCKED_TENANT_STATUSES:
            # Force logout on plan suspension — the frontend reacts to this code.
            raise AuthenticationFailed(
                _('This account is suspended.'), code='subscription_suspended'
            )

        set_tenant_context(
            tenant_id=user.tenant_id,
            is_super_admin=user.role == Role.SUPER_ADMIN,
        )
        return user, token
