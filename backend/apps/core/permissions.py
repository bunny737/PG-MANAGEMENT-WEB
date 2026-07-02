from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import BasePermission

from .roles import Role, permissions_for


def require_permission(permission):
    """DRF permission class factory driven by the PRD §6 matrix.

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
                and permission in permissions_for(user.role)
            )

    HasMatrixPermission.__name__ = f'Requires_{permission}'
    return HasMatrixPermission


class IsSuperAdmin(BasePermission):
    message = _('Only platform administrators can perform this action.')

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.SUPER_ADMIN)
