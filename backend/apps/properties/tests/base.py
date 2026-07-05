from decimal import Decimal

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from apps.properties.models import Bed, Building, Floor, Property, PropertyStaffAssignment, Room


class PropertyAPITestCase(AuthAPITestCase):
    @staticmethod
    def create_property(tenant, name='Sunrise PG - Madhapur', **kwargs):
        kwargs.setdefault('property_type', Property.PropertyType.PG)
        kwargs.setdefault('address_line', '12 Main Road')
        kwargs.setdefault('city', 'Hyderabad')
        kwargs.setdefault('state', 'Telangana')
        kwargs.setdefault('contact_number', '9999999999')
        with tenant_context(tenant.id):
            prop = Property.objects.create(tenant_id=tenant.id, name=name, **kwargs)
            # Mirrors PropertyViewSet.perform_create: every Property always has
            # a default Building (see docs/modules/02-property-hierarchy.md
            # Decisions, 2026-07-05) — this fixture bypasses the view, so
            # provision it here too.
            Building.objects.create(tenant_id=tenant.id, property=prop, name='Main Building', order=0)
            return prop

    @staticmethod
    def create_building(prop, name='Block A', order=None):
        with tenant_context(prop.tenant_id):
            if order is None:
                last = Building.objects.filter(property=prop).order_by('-order').first()
                order = (last.order + 1) if last else 0
            return Building.objects.create(tenant_id=prop.tenant_id, property=prop, name=name, order=order)

    @classmethod
    def create_floor(cls, prop, name='Ground Floor', order=0):
        with tenant_context(prop.tenant_id):
            # Every Property has a default Building in production (auto-created
            # by PropertyViewSet.perform_create); test fixtures built directly
            # from the model bypass that, so lazily provision the same default
            # here rather than forcing every test/module to know about Building.
            building, _ = Building.objects.get_or_create(
                property=prop, order=0, defaults={'tenant_id': prop.tenant_id, 'name': 'Main Building'},
            )
            return Floor.objects.create(tenant_id=prop.tenant_id, building=building, name=name, order=order)

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
