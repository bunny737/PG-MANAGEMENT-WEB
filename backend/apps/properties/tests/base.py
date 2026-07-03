from decimal import Decimal

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from apps.properties.models import Bed, Floor, Property, PropertyStaffAssignment, Room


class PropertyAPITestCase(AuthAPITestCase):
    @staticmethod
    def create_property(tenant, name='Sunrise PG - Madhapur', **kwargs):
        kwargs.setdefault('property_type', Property.PropertyType.PG)
        kwargs.setdefault('address_line', '12 Main Road')
        kwargs.setdefault('city', 'Hyderabad')
        kwargs.setdefault('state', 'Telangana')
        kwargs.setdefault('contact_number', '9999999999')
        with tenant_context(tenant.id):
            return Property.objects.create(tenant_id=tenant.id, name=name, **kwargs)

    @staticmethod
    def create_floor(prop, name='Ground Floor', order=0):
        with tenant_context(prop.tenant_id):
            return Floor.objects.create(tenant_id=prop.tenant_id, property=prop, name=name, order=order)

    @staticmethod
    def create_room(
        floor, room_number='101', sharing_type=Room.SharingType.FOUR,
        category=Room.Category.NON_AC,
        rack_rate_with_food=Decimal('5500.00'), rack_rate_without_food=Decimal('4000.00'),
        **kwargs,
    ):
        with tenant_context(floor.tenant_id):
            return Room.objects.create(
                tenant_id=floor.tenant_id, floor=floor, room_number=room_number,
                sharing_type=sharing_type, category=category,
                rack_rate_with_food=rack_rate_with_food,
                rack_rate_without_food=rack_rate_without_food, **kwargs,
            )

    @staticmethod
    def create_bed(room, bed_number='101-A', **kwargs):
        with tenant_context(room.tenant_id):
            return Bed.objects.create(tenant_id=room.tenant_id, room=room, bed_number=bed_number, **kwargs)

    @classmethod
    def create_manager(cls, tenant, email='manager@example.com', **kwargs):
        return cls.create_user(tenant, Role.MANAGER, email, **kwargs)

    @classmethod
    def create_receptionist(cls, tenant, email='reception@example.com', **kwargs):
        return cls.create_user(tenant, Role.RECEPTIONIST, email, **kwargs)

    @staticmethod
    def assign_staff(staff, prop):
        with tenant_context(prop.tenant_id):
            return PropertyStaffAssignment.objects.create(
                tenant_id=prop.tenant_id, staff=staff, property=prop,
            )
