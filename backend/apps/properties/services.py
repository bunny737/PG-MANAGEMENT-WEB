"""Property-visibility scoping (PRD §6 'Property Assignment Rules').

Owner/Super Admin see every property in the tenant; Manager/Receptionist see
only properties they have been explicitly assigned by the Owner.
"""
from apps.core.roles import Role

from .models import Property, PropertyStaffAssignment


def visible_property_ids(user):
    """Queryset of Property ids the user is allowed to see/operate on."""
    if user.role in (Role.SUPER_ADMIN, Role.OWNER):
        return Property.objects.filter(tenant_id=user.tenant_id).values_list('id', flat=True)
    return PropertyStaffAssignment.objects.filter(
        tenant_id=user.tenant_id, staff_id=user.id
    ).values_list('property_id', flat=True)


def can_view_property(user, property_id):
    return visible_property_ids(user).filter(pk=property_id).exists()
