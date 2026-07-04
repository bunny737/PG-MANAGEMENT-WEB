from decimal import Decimal

from django.urls import reverse

from apps.properties.models import Room
from apps.residents.models import Resident

from .base import SubscriptionAPITestCase


def property_payload(**overrides):
    payload = {
        'name': 'Sunrise PG - Madhapur', 'property_type': 'pg', 'address_line': '12 Main Road',
        'city': 'Hyderabad', 'state': 'Telangana', 'contact_number': '9999999999',
    }
    payload.update(overrides)
    return payload


class PropertyLimitTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def test_no_subscription_configured_is_unlimited(self):
        for i in range(3):
            response = self.client.post(reverse('property-list'), property_payload(name=f'Prop {i}'))
            self.assertEqual(response.status_code, 201, response.data)

    def test_hard_block_when_property_limit_reached(self):
        plan = self.create_plan(max_properties=1)
        self.create_subscription(self.tenant, plan=plan)

        first = self.client.post(reverse('property-list'), property_payload(name='Prop 1'))
        self.assertEqual(first.status_code, 201, first.data)

        second = self.client.post(reverse('property-list'), property_payload(name='Prop 2'))
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data['code'], 'PROPERTY_LIMIT_REACHED')

    def test_override_raises_the_property_limit(self):
        plan = self.create_plan(max_properties=1)
        subscription = self.create_subscription(self.tenant, plan=plan)
        subscription.max_properties_override = 2
        subscription.save()

        self.client.post(reverse('property-list'), property_payload(name='Prop 1'))
        second = self.client.post(reverse('property-list'), property_payload(name='Prop 2'))
        self.assertEqual(second.status_code, 201, second.data)

    def test_unlimited_plan_has_no_property_cap(self):
        plan = self.create_plan(max_properties=None)
        self.create_subscription(self.tenant, plan=plan)

        for i in range(3):
            response = self.client.post(reverse('property-list'), property_payload(name=f'Prop {i}'))
            self.assertEqual(response.status_code, 201, response.data)

    def test_trial_tenant_borrows_trial_default_plan_limits(self):
        # tenant.status defaults to TRIAL; Subscription has no plan selected.
        self.create_plan(name='Starter', max_properties=1, is_trial_plan=True)
        self.create_subscription(self.tenant, plan=None)

        first = self.client.post(reverse('property-list'), property_payload(name='Prop 1'))
        self.assertEqual(first.status_code, 201, first.data)

        second = self.client.post(reverse('property-list'), property_payload(name='Prop 2'))
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data['code'], 'PROPERTY_LIMIT_REACHED')


class ResidentLimitTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=Room.SharingType.FOUR, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.authenticate(self.owner)

    def _admit(self, bed_number, phone):
        bed = self.create_bed(self.room, bed_number=bed_number)
        resident = self.create_resident(self.property, phone=phone, status=Resident.Status.RESERVED)
        return self.client.post(reverse('admission-list'), {
            'resident': str(resident.id), 'bed': str(bed.id), 'joining_date': '2026-07-01',
            'billing_mode': 'monthly', 'food_preference': 'with_food', 'advance_amount': '1500.00',
        }), resident

    def test_hard_block_when_resident_limit_reached(self):
        plan = self.create_plan(max_residents_per_property=1)
        self.create_subscription(self.tenant, plan=plan)

        first, _ = self._admit('101-A', '9000000001')
        self.assertEqual(first.status_code, 201, first.data)

        second, _ = self._admit('101-B', '9000000002')
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data['code'], 'RESIDENT_LIMIT_REACHED')

    def test_resident_limit_is_checked_per_property(self):
        plan = self.create_plan(max_residents_per_property=1)
        self.create_subscription(self.tenant, plan=plan)
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        other_room = self.create_room(other_floor)
        other_bed = self.create_bed(other_room, bed_number='201-A')
        other_resident = self.create_resident(other_property, phone='9000000003', status=Resident.Status.RESERVED)

        first, _ = self._admit('101-A', '9000000001')
        self.assertEqual(first.status_code, 201, first.data)

        # Different property, same tenant — its own count starts at 0.
        second = self.client.post(reverse('admission-list'), {
            'resident': str(other_resident.id), 'bed': str(other_bed.id), 'joining_date': '2026-07-01',
            'billing_mode': 'monthly', 'food_preference': 'with_food', 'advance_amount': '1500.00',
        })
        self.assertEqual(second.status_code, 201, second.data)

    def test_resident_override_raises_the_limit(self):
        plan = self.create_plan(max_residents_per_property=1)
        subscription = self.create_subscription(self.tenant, plan=plan)
        subscription.max_residents_override = 2
        subscription.save()

        first, _ = self._admit('101-A', '9000000001')
        self.assertEqual(first.status_code, 201, first.data)
        second, _ = self._admit('101-B', '9000000002')
        self.assertEqual(second.status_code, 201, second.data)

    def test_generic_status_endpoint_also_enforces_the_limit(self):
        # Closes the "bare status flip" loophole documented in Module 05/10 —
        # a plan-limit bypass is consequential enough to guard explicitly.
        plan = self.create_plan(max_residents_per_property=1)
        self.create_subscription(self.tenant, plan=plan)
        self._admit('101-A', '9000000001')

        bed = self.create_bed(self.room, bed_number='101-B')
        resident = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)

        response = self.client.patch(
            reverse('resident-status', args=[resident.id]), {'status': 'active'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'RESIDENT_LIMIT_REACHED')

    def test_active_to_notice_period_does_not_recheck_the_limit(self):
        plan = self.create_plan(max_residents_per_property=1)
        self.create_subscription(self.tenant, plan=plan)
        _, resident = self._admit('101-A', '9000000001')

        response = self.client.patch(
            reverse('resident-status', args=[resident.id]), {'status': 'notice_period'}
        )
        self.assertEqual(response.status_code, 200, response.data)
