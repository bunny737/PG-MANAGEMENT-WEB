from unittest import mock

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.urls import reverse

from apps.subscriptions.admin import PlanAdmin, PlanBedTierAdmin, PlanBedTierInline
from apps.subscriptions.models import Plan, PlanBedTier

from .base import SubscriptionAPITestCase


class PlanProtectionTestCase(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.super_admin = self.create_super_admin()
        self.authenticate(self.super_admin)

    def admin_request(self):
        # Django admin permission checks need a user holding model perms.
        request = RequestFactory().get('/')
        request.user = mock.Mock(is_active=True, is_staff=True, has_perm=lambda *args: True)
        return request

    def _patch(self, plan, **data):
        return self.client.patch(reverse('plan-detail', args=[plan.id]), data)


class PriceLockTests(PlanProtectionTestCase):
    def test_price_change_rejected_once_razorpay_plan_exists(self):
        plan = self.create_plan(name='Live', razorpay_plan_id='plan_123')
        response = self._patch(plan, price_per_month='299.00')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_PRICING_LOCKED')
        plan.refresh_from_db()
        self.assertEqual(str(plan.price_per_month), '199.00')

    def test_price_change_rejected_when_a_tenant_is_subscribed_without_razorpay_id(self):
        plan = self.create_plan(name='Assigned')
        self.create_subscription(self.tenant, plan=plan)
        response = self._patch(plan, price_per_month='299.00')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_PRICING_LOCKED')

    def test_price_change_allowed_while_plan_is_unused(self):
        plan = self.create_plan(name='Draft')
        self.assertEqual(self._patch(plan, price_per_month='299.00').status_code, 200)

    def test_bed_cap_name_and_active_flag_stay_editable_on_a_locked_plan(self):
        plan = self.create_plan(name='Live', razorpay_plan_id='plan_123')
        self.assertEqual(self._patch(plan, max_beds=700).status_code, 200)
        self.assertEqual(self._patch(plan, name='Live v2').status_code, 200)
        self.assertEqual(self._patch(plan, is_active=False).status_code, 200)

    def test_bed_tiers_of_a_subscribed_per_bed_plan_are_frozen(self):
        plan = self.create_bed_plan(name='Per Bed', bed_tiers=[(None, '2.00')])
        self.create_subscription(self.tenant, plan=plan)

        tier = plan.bed_tiers.get()
        tier.rate_per_bed = '3.00'
        with self.assertRaises(DjangoValidationError):
            tier.full_clean()

        new_tier = PlanBedTier(plan=plan, up_to_beds=10, rate_per_bed='1.00')
        with self.assertRaises(DjangoValidationError):
            new_tier.full_clean()

    def test_bed_tiers_of_an_unused_per_bed_plan_are_editable(self):
        plan = self.create_bed_plan(name='Per Bed', bed_tiers=[(None, '2.00')])
        tier = plan.bed_tiers.get()
        tier.rate_per_bed = '3.00'
        tier.full_clean()

    def test_admin_inline_is_read_only_for_a_locked_plan(self):
        plan = self.create_bed_plan(name='Per Bed', bed_tiers=[(None, '2.00')])
        self.create_subscription(self.tenant, plan=plan)
        request = self.admin_request()
        inline = PlanBedTierInline(Plan, admin.site)

        self.assertFalse(inline.has_add_permission(request, plan))
        self.assertFalse(inline.has_change_permission(request, plan))
        self.assertFalse(inline.has_delete_permission(request, plan))

        unused = self.create_bed_plan(name='Unused Per Bed', bed_tiers=[(None, '2.00')])
        self.assertTrue(inline.has_add_permission(request, unused))

    def test_per_bed_plan_cannot_carry_a_bed_cap(self):
        plan = self.create_bed_plan(name='Per Bed', bed_tiers=[(None, '2.00')], max_beds=10)
        with self.assertRaises(DjangoValidationError):
            plan.full_clean()


    def test_tier_admin_refuses_to_write_a_tier_onto_a_plan_that_went_live(self):
        # The form validated while the plan was unused; by save time a tenant has
        # selected it. save_model re-checks under the plan lock.
        plan = self.create_bed_plan(name='Went Live', bed_tiers=[(None, '2.00')])
        self.create_subscription(self.tenant, plan=plan)
        request = self.admin_request()
        tier_admin = PlanBedTierAdmin(PlanBedTier, admin.site)
        tier = PlanBedTier(plan=plan, up_to_beds=10, rate_per_bed='1.00')

        with self.assertRaises(PermissionDenied):
            tier_admin.save_model(request, tier, form=None, change=False)
        self.assertEqual(plan.bed_tiers.count(), 1)

    def test_standalone_tier_admin_cannot_change_or_delete_a_locked_plans_tiers(self):
        locked = self.create_bed_plan(name='Locked Per Bed', bed_tiers=[(None, '2.00')])
        self.create_subscription(self.tenant, plan=locked)
        unused = self.create_bed_plan(name='Unused Per Bed', bed_tiers=[(None, '2.00')])
        request = self.admin_request()
        tier_admin = PlanBedTierAdmin(PlanBedTier, admin.site)
        locked_tier, unused_tier = locked.bed_tiers.get(), unused.bed_tiers.get()

        self.assertFalse(tier_admin.has_change_permission(request, locked_tier))
        self.assertFalse(tier_admin.has_delete_permission(request, locked_tier))
        self.assertTrue(tier_admin.has_change_permission(request, unused_tier))
        self.assertTrue(tier_admin.has_delete_permission(request, unused_tier))
        self.assertNotIn('delete_selected', tier_admin.get_actions(request))


class PlanApiInvariantTests(PlanProtectionTestCase):
    def _create(self, **data):
        return self.client.post(reverse('plan-list'), data, format='json')

    def test_api_rejects_a_capped_per_bed_plan(self):
        for cap in ({'max_beds': 10}, {'max_properties': 2}, {'max_residents_per_property': 5}):
            response = self._create(name='Capped Per Bed', pricing_type='per_bed_monthly', **cap)
            self.assertEqual(response.status_code, 400, cap)
            self.assertEqual(response.data['code'], 'PLAN_PER_BED_CAPPED')
        self.assertFalse(Plan.objects.filter(name='Capped Per Bed').exists())

    def test_api_cannot_cap_an_existing_per_bed_plan(self):
        plan = self.create_bed_plan(name='Per Bed', bed_tiers=[(None, '2.00')])
        response = self._patch(plan, max_beds=10)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_PER_BED_CAPPED')

    def test_api_cannot_switch_a_capped_flat_plan_to_per_bed(self):
        plan = self.create_plan(name='Flat', max_beds=10)
        response = self._patch(plan, pricing_type='per_bed_monthly')
        self.assertEqual(response.status_code, 400)
        plan.refresh_from_db()
        self.assertEqual(plan.pricing_type, 'flat_monthly')

    def test_api_requires_a_price_for_flat_plans(self):
        response = self._create(name='No Price')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_PRICE_REQUIRED')

    def test_api_accepts_a_valid_flat_plan_with_a_bed_cap(self):
        response = self._create(name='Valid', price_per_month='99.00', max_beds=50)
        self.assertEqual(response.status_code, 201, response.data)


class PlanDeletionTests(PlanProtectionTestCase):
    def _delete(self, plan):
        return self.client.delete(reverse('plan-detail', args=[plan.id]))

    def test_live_plan_without_subscribers_cannot_be_deleted(self):
        plan = self.create_plan(name='Live', razorpay_plan_id='plan_123')
        self.assertEqual(self._delete(plan).status_code, 400)
        self.assertTrue(Plan.objects.filter(pk=plan.pk).exists())

    def test_trial_plan_cannot_be_deleted(self):
        trial = Plan.objects.get(name='Basic')
        self.assertEqual(self._delete(trial).status_code, 400)

    def test_unused_unlocked_plan_can_be_deleted(self):
        plan = self.create_plan(name='Draft')
        self.assertEqual(self._delete(plan).status_code, 204)

    def test_admin_blocks_deleting_live_plans_and_bulk_delete(self):
        request = self.admin_request()
        plan_admin = PlanAdmin(Plan, admin.site)
        live = self.create_plan(name='Live', razorpay_plan_id='plan_123')
        draft = self.create_plan(name='Draft')

        self.assertFalse(plan_admin.has_delete_permission(request, live))
        self.assertFalse(plan_admin.has_delete_permission(request, Plan.objects.get(name='Basic')))
        self.assertTrue(plan_admin.has_delete_permission(request, draft))
        self.assertNotIn('delete_selected', plan_admin.get_actions(request))


class TrialPlanTests(PlanProtectionTestCase):
    def test_marking_another_plan_as_trial_moves_the_flag(self):
        other = self.create_plan(name='Other')
        response = self._patch(other, is_trial_plan=True)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(list(Plan.objects.filter(is_trial_plan=True)), [other])

    def test_creating_a_trial_plan_moves_the_flag(self):
        response = self.client.post(reverse('plan-list'), {
            'name': 'New Trial', 'price_per_month': '99.00', 'is_trial_plan': True,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Plan.objects.get(is_trial_plan=True).name, 'New Trial')

    def test_current_trial_plan_cannot_be_unflagged_or_retired(self):
        basic = Plan.objects.get(name='Basic')

        unflag = self._patch(basic, is_trial_plan=False)
        self.assertEqual(unflag.status_code, 400)
        self.assertEqual(unflag.data['code'], 'TRIAL_PLAN_REQUIRED')

        retire = self._patch(basic, is_active=False)
        self.assertEqual(retire.status_code, 400)
        self.assertEqual(retire.data['code'], 'TRIAL_PLAN_REQUIRED')
        self.assertTrue(Plan.objects.get(name='Basic').is_trial_plan)

    def test_database_rejects_two_trial_plans(self):
        other = self.create_plan(name='Other')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Plan.objects.filter(pk=other.pk).update(is_trial_plan=True)
