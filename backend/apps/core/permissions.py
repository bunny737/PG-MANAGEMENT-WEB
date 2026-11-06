from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .roles import Role, permissions_for_user


def require_permission(permission):
    """DRF permission class factory driven by the PRD §6 matrix, adjusted per
    staff member by their module access (see apps/core/modules.py).

    Usage: permission_classes = [require_permission('manage_staff_accounts')]
    """

    class HasMatrixPermission(BasePermission):
        message = _('You do not have permission to perform this action.')
        code = 'permission_denied'

        def has_permission(self, request, view):
            user = request.user
            return bool(
                user
                and user.is_authenticated
                and permission in permissions_for_user(user)
            )

    HasMatrixPermission.__name__ = f'Requires_{permission}'
    return HasMatrixPermission


def require_permission_by_method(read, write):
    """Like `require_permission`, but `read` guards SAFE_METHODS (GET/HEAD/OPTIONS)
    and `write` guards everything else — for resources with a view-only level."""
    read_class = require_permission(read)
    write_class = require_permission(write)

    class HasMethodPermission(BasePermission):
        def has_permission(self, request, view):
            checker = read_class if request.method in SAFE_METHODS else write_class
            return checker().has_permission(request, view)

        @property
        def message(self):
            return write_class.message

        code = 'permission_denied'

    HasMethodPermission.__name__ = f'Requires_{read}_or_{write}'
    return HasMethodPermission


def require_any_permission(*permissions):
    """Entry gate for read endpoints that several modules legitimately reach
    (e.g. the property layout serves the Properties screen, the admission bed
    picker and the transfer dialog). Nested fields are then redacted by their
    own permission — see apps/core/redaction.py."""

    class HasAnyPermission(BasePermission):
        message = _('You do not have permission to perform this action.')
        code = 'permission_denied'

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            return bool(set(permissions) & set(permissions_for_user(user)))

    HasAnyPermission.__name__ = 'Requires_any_of_' + '_'.join(permissions)
    return HasAnyPermission


class IsTenantStaff(BasePermission):
    """Owner, Manager or Receptionist of a business — the staff app's audience.
    Residents and Super Admins (no tenant) are refused."""

    message = _('You do not have permission to perform this action.')
    code = 'permission_denied'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.tenant_id
            and user.role in (Role.OWNER, Role.MANAGER, Role.RECEPTIONIST)
        )


class IsSuperAdmin(BasePermission):
    message = _('Only platform administrators can perform this action.')

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.SUPER_ADMIN)


class IsAuthenticatedStaffPool(BasePermission):
    """The project-wide default (REST_FRAMEWORK DEFAULT_PERMISSION_CLASSES): signed in AND not a
    resident-pool account (Module 26).

    A resident account is a person's own login, linked to residencies by ResidentAccess, with
    no tenant of its own. Every endpoint that predates residents was written for staff, so the
    default fails closed: a resident reaches only views that name `IsAuthenticated` (or a
    resident permission) explicitly, which is a decision a reviewer can see."""

    message = _('You do not have permission to perform this action.')
    code = 'permission_denied'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role != Role.RESIDENT)


class IsResidentAccount(BasePermission):
    """A signed-in resident-pool account (a person's own app login, Module 26)."""

    message = _('This action is for resident app accounts.')
    code = 'resident_account_required'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.RESIDENT)


class IsVerifiedResidentAccount(IsResidentAccount):
    """A resident-pool account whose email is verified. Contact and linking actions need it, so
    an anonymous throw-away signup can't reveal numbers or create requests."""

    message = _('Verify your email address first.')
    code = 'email_not_verified'

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.email_verified
