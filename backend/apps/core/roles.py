"""Role definitions and the PRD §6 permission matrix.

The matrix is product behaviour defined by the PRD, not a tunable limit,
so it lives in code. Plan limits (trial days, caps) live in PlatformConfig.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    SUPER_ADMIN = 'super_admin', _('Super Admin')
    OWNER = 'owner', _('Owner')
    MANAGER = 'manager', _('Manager')
    RECEPTIONIST = 'receptionist', _('Receptionist')
    RESIDENT = 'resident', _('Resident')


STAFF_ROLES = (Role.MANAGER, Role.RECEPTIONIST)
TENANT_ROLES = (Role.OWNER, Role.MANAGER, Role.RECEPTIONIST, Role.RESIDENT)

_OPS = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER)

PERMISSION_MATRIX = {
    'manage_tenants': (Role.SUPER_ADMIN,),
    'manage_subscription': (Role.SUPER_ADMIN, Role.OWNER),
    'manage_properties': (Role.SUPER_ADMIN, Role.OWNER),
    'manage_property_settings': (Role.SUPER_ADMIN, Role.OWNER),
    'manage_staff_accounts': (Role.SUPER_ADMIN, Role.OWNER),
    'assign_staff_to_properties': (Role.SUPER_ADMIN, Role.OWNER),
    'manage_rooms_beds': _OPS,
    'manage_residents': _OPS,
    'manage_admissions': _OPS,
    'manage_allocations': _OPS,
    'manage_invoices': _OPS,
    'manage_payments': _OPS,
    'manage_deposits': _OPS,
    'manage_discounts': _OPS,
    'manage_complaints': _OPS,
    'manage_visitors': (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.RECEPTIONIST),
    'view_resident_profile': (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.RECEPTIONIST),
    'view_reports': _OPS,
    'view_own_profile': (Role.RESIDENT,),
    'view_own_invoices': (Role.RESIDENT,),
    'raise_complaint': (Role.RESIDENT,),
    'request_visitor': (Role.RESIDENT,),
}


def permissions_for(role):
    """Sorted permission codes for a role — serialized on /auth/me/ so the
    frontend renders actions from the matrix instead of inferring from role names."""
    return sorted(perm for perm, roles in PERMISSION_MATRIX.items() if role in roles)
