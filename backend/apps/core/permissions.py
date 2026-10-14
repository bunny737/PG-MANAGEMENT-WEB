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


class IsSuperAdmin(BasePermission):
    message = _('Only platform administrators can perform this action.')

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.SUPER_ADMIN)
