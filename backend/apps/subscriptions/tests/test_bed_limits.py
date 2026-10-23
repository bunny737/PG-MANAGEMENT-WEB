from unittest import mock

from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Room
from apps.subscriptions import razorpay_client
from apps.subscriptions.models import Plan

from .base import SubscriptionAPITestCase


class BedLimitTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor, room_number='101', sharing_type=Room.SharingType.EIGHT)
        self.authenticate(self.owner)

    def _bed_count(self, tenant=None):
        with tenant_context((tenant or self.tenant).id):
            return Bed.objects.count()

    def _add_bed(self, number):
        return self.client.post(reverse('bed-list'), {'room': str(self.room.id), 'bed_number': number})

    def _add_room(self, number, sharing_type=3):
        return self.client.post(reverse('room-list'), {
            'floor': str(self.floor.id), 'room_number': number, 'sharing_type': sharing_type,
            'category': 'ac', 'rack_rate_with_food': '5000.00', 'rack_rate_without_food': '4000.00',
            'auto_create_beds': True,
        })

    def test_no_subscription_configured_is_unlimited(self):
        for i in range(3):
            self.assertEqual(self._add_bed(f'101-{i}').status_code, 201)

    def test_hard_block_when_bed_limit_reached(self):
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=2)
        self.create_subscription(self.tenant, plan=plan)

        self.assertEqual(self._add_bed('101-A').status_code, 201)
        self.assertEqual(self._add_bed('101-B').status_code, 201)
        blocked = self._add_bed('101-C')

        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['code'], 'BED_LIMIT_REACHED')
        self.assertEqual(self._bed_count(), 2)

    def test_auto_created_room_beds_count_against_the_limit_and_roll_back(self):
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=4)
        self.create_subscription(self.tenant, plan=plan)

        self.assertEqual(self._add_room('201', 3).status_code, 201)
        blocked = self._add_room('202', 3)

        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['code'], 'BED_LIMIT_REACHED')
        with tenant_context(self.tenant.id):
            self.assertFalse(Room.objects.filter(room_number='202').exists())
        self.assertEqual(self._bed_count(), 3)

    def test_room_exactly_filling_the_limit_is_allowed(self):
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=3)
        self.create_subscription(self.tenant, plan=plan)
        self.assertEqual(self._add_room('201', 3).status_code, 201)

    def test_room_without_auto_beds_is_not_limited(self):
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=0)
        self.create_subscription(self.tenant, plan=plan)
        response = self.client.post(reverse('room-list'), {
            'floor': str(self.floor.id), 'room_number': '301', 'sharing_type': 3,
            'category': 'ac', 'rack_rate_with_food': '5000.00', 'rack_rate_without_food': '4000.00',
        })
        self.assertEqual(response.status_code, 201, response.data)

    def test_trial_tenant_borrows_the_trial_plan_bed_limit(self):
        self.create_plan(
            name='Trial Cap', max_properties=None, max_residents_per_property=None,
            max_beds=1, is_trial_plan=True,
        )
        self.create_subscription(self.tenant, plan=None)

        self.assertEqual(self._add_bed('101-A').status_code, 201)
        self.assertEqual(self._add_bed('101-B').data['code'], 'BED_LIMIT_REACHED')

    def test_override_takes_precedence_over_the_plan(self):
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=1)
        subscription = self.create_subscription(self.tenant, plan=plan)
        subscription.max_beds_override = 2
        subscription.save()

        self.assertEqual(self._add_bed('101-A').status_code, 201)
        self.assertEqual(self._add_bed('101-B').status_code, 201)
        self.assertEqual(self._add_bed('101-C').status_code, 400)

    def test_null_plan_limit_means_unlimited(self):
        plan = self.create_plan(name='Open', max_properties=None, max_residents_per_property=None, max_beds=None)
        self.create_subscription(self.tenant, plan=plan)
        for i in range(3):
            self.assertEqual(self._add_bed(f'101-{i}').status_code, 201)

    def test_other_tenants_beds_do_not_count(self):
        other = self.create_tenant('Other PG')
        other_property = self.create_property(other)
        other_room = self.create_room(self.create_floor(other_property))
        for i in range(3):
            self.create_bed(other_room, bed_number=f'X-{i}')
        plan = self.create_plan(name='Capped', max_properties=None, max_residents_per_property=None, max_beds=1)
        self.create_subscription(self.tenant, plan=plan)

        self.assertEqual(self._add_bed('101-A').status_code, 201)
        self.assertEqual(self._add_bed('101-B').status_code, 400)

    def test_seeded_basic_plan_caps_at_500_beds_and_unlimited_has_none(self):
        basic = Plan.objects.get(name='Basic')
        unlimited = Plan.objects.get(name='Unlimited')
        self.assertEqual((basic.max_beds, str(basic.price_per_month), basic.is_trial_plan), (500, '149.00', True))
        self.assertEqual((unlimited.max_beds, str(unlimited.price_per_month), unlimited.is_trial_plan),
                         (None, '249.00', False))
        self.assertEqual(Plan.objects.filter(is_trial_plan=True).count(), 1)


class DowngradeBedCheckTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        room = self.create_room(self.create_floor(self.create_property(self.tenant)))
        for i in range(3):
            self.create_bed(room, bed_number=f'101-{i}')
        self.subscription = self.create_subscription(self.tenant)
        self.authenticate(self.owner)

    def _select(self, plan):
        return self.client.post(reverse('subscription-select-plan', args=[self.tenant.id]), {'plan': str(plan.id)})

    def test_cannot_switch_to_a_plan_smaller_than_current_beds(self):
        small = self.create_plan(name='Small', max_properties=None, max_residents_per_property=None, max_beds=2)

        with mock.patch.object(razorpay_client, 'create_razorpay_plan') as create_plan, \
                mock.patch.object(razorpay_client, 'create_razorpay_subscription') as create_sub:
            response = self._select(small)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_BED_LIMIT_EXCEEDED')
        create_plan.assert_not_called()
        create_sub.assert_not_called()
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.plan)

    def test_can_switch_to_a_plan_that_fits_or_is_unlimited(self):
        fits = self.create_plan(name='Fits', max_properties=None, max_residents_per_property=None, max_beds=3)
        self.assertEqual(self._select(fits).status_code, 200)
        unlimited = self.create_plan(name='Open', max_properties=None, max_residents_per_property=None)
        self.assertEqual(self._select(unlimited).status_code, 200)

    def test_override_is_honoured_when_checking_a_switch(self):
        small = self.create_plan(name='Small', max_properties=None, max_residents_per_property=None, max_beds=2)
        self.subscription.max_beds_override = 10
        self.subscription.save()
        self.assertEqual(self._select(small).status_code, 200)
