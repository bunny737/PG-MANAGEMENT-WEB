"""Property-visibility scoping (PRD §6 'Property Assignment Rules').

Owner/Super Admin see every property in the tenant; Manager/Receptionist see
only properties they have been explicitly assigned by the Owner.
"""
import uuid

from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import NotFound

from apps.core.roles import Role

from .models import Property, PropertyStaffAssignment


def visible_property_ids(user):
    """Queryset of Property ids the user is allowed to see/operate on."""
    if user.role in (Role.SUPER_ADMIN, Role.OWNER):
        return Property.objects.filter(tenant_id=user.tenant_id).values_list('id', flat=True)
    return PropertyStaffAssignment.objects.filter(
        tenant_id=user.tenant_id, staff_id=user.id
    ).values_list('property_id', flat=True)


def scoped_property_ids(user, property_id=None):
    """Property ids an aggregate endpoint covers (authorization model, check 1).

    With `property_id`: just that property, or 404 when the caller can't see
    it (unassigned, other tenant, malformed id) — an aggregate must never
    silently answer "0" for a property the caller has no access to. Without
    it ("All properties"): every property the caller is assigned to."""
    ids = list(Property.objects.filter(id__in=visible_property_ids(user)).values_list('id', flat=True))
    if property_id in (None, ''):
        return ids
    try:
        wanted = uuid.UUID(str(property_id))
    except ValueError:
        raise NotFound(_('Property not found.'))
    if wanted not in ids:
        raise NotFound(_('Property not found.'))
    return [wanted]


def can_view_property(user, property_id):
    # visible_property_ids() is a values_list queryset whose underlying model
    # differs by branch (Property for Owner/Super Admin, PropertyStaffAssignment
    # for Manager/Receptionist) — chaining .filter(pk=...) onto it would resolve
    # `pk` against whichever model that branch used, not Property. Re-querying
    # Property directly keeps this correct regardless of branch.
    return Property.objects.filter(id__in=visible_property_ids(user), pk=property_id).exists()
