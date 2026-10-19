"""GET /api/v1/public/plans/ — the anonymous plan catalogue behind the marketing
site. Platform data only: nothing tenant-scoped may ever appear in it."""
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import PlatformConfig
from apps.subscriptions.models import Plan

from .base import SubscriptionAPITestCase

PLAN_FIELDS = {'id', 'name', 'pricing_type', 'price_per_month', 'max_beds', 'bed_tiers', 'is_trial_plan'}


class PublicPlanCatalogTests(SubscriptionAPITestCase):
    url = reverse('public-plan-catalog')

    def setUp(self):
        super().setUp()
        # Migration 0006 seeds Basic/Unlimited; these tests control the catalogue.
        Plan.objects.all().delete()
        self.anonymous = APIClient()

    def test_anonymous_can_read_the_catalogue(self):
        self.create_plan(name='Basic', price_per_month='149.00', max_beds=500, is_trial_plan=True)
        response = self.anonymous.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['currency'], 'INR')
        self.assertEqual([p['name'] for p in response.data['plans']], ['Basic'])

    def test_only_active_plans_are_listed(self):
        self.create_plan(name='Basic', price_per_month='149.00')
        self.create_plan(name='Retired', price_per_month='99.00', is_active=False)
        names = [p['name'] for p in self.anonymous.get(self.url).data['plans']]
        self.assertEqual(names, ['Basic'])

    def test_plan_fields_are_an_exact_allow_list(self):
        plan = self.create_plan(name='Basic', price_per_month='149.00', max_beds=500)
        plan.razorpay_plan_id = 'plan_secret123'
        plan.save()
        data = self.anonymous.get(self.url).data['plans'][0]
        self.assertEqual(set(data), PLAN_FIELDS)
        self.assertEqual(data['price_per_month'], '149.00')
        self.assertEqual(data['max_beds'], 500)
        self.assertNotIn('plan_secret123', str(self.anonymous.get(self.url).content))

    def test_per_bed_plan_exposes_its_tiers(self):
        self.create_bed_plan(name='Per-Bed', bed_tiers=[(50, '0.00'), (None, '2.00')])
        data = self.anonymous.get(self.url).data['plans'][0]
        self.assertEqual(data['pricing_type'], 'per_bed_monthly')
        self.assertIsNone(data['price_per_month'])
        self.assertEqual(
            [(t['up_to_beds'], t['rate_per_bed']) for t in data['bed_tiers']],
            [(50, '0.00'), (None, '2.00')],
        )
        self.assertEqual(set(data['bed_tiers'][0]), {'up_to_beds', 'rate_per_bed'})

    def test_trial_days_follow_platform_config(self):
        config = PlatformConfig.get()
        config.trial_days = 30
        config.save()
        self.assertEqual(self.anonymous.get(self.url).data['trial_days'], 30)

    def test_empty_catalogue_still_answers(self):
        PlatformConfig.objects.all().delete()
        response = self.anonymous.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['plans'], [])
        self.assertIsNone(response.data['updated_at'])
        self.assertFalse(PlatformConfig.objects.exists(), 'a public GET must not write')

    def test_read_only(self):
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.anonymous, method)(self.url, {})
            self.assertEqual(response.status_code, 405, method)

    def test_response_is_publicly_cacheable(self):
        self.assertIn('max-age=300', self.anonymous.get(self.url)['Cache-Control'])

    def test_exposes_no_tenant_data(self):
        """Tenant isolation: the catalogue is identical with or without tenants,
        and carries nothing about them (Subscription rows, Razorpay ids, emails)."""
        plan = self.create_plan(name='Basic', price_per_month='149.00')
        before = self.anonymous.get(self.url).content

        tenant = self.create_tenant()
        owner = self.create_owner(tenant)
        self.create_subscription(
            tenant, plan=plan, razorpay_subscription_id='sub_tenant_secret',
        )
        response = self.anonymous.get(self.url)

        self.assertEqual(response.content, before)
        body = response.content.decode()
        for leaked in (str(tenant.id), 'sub_tenant_secret', owner.email):
            self.assertNotIn(leaked, body)

    def test_response_does_not_depend_on_who_asks(self):
        self.create_plan(name='Basic', price_per_month='149.00')
        tenant = self.create_tenant()
        self.authenticate(self.create_owner(tenant))
        self.assertEqual(self.client.get(self.url).content, self.anonymous.get(self.url).content)
