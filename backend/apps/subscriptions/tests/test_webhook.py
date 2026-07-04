from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.subscriptions.models import SubscriptionPayment

from .base import SubscriptionAPITestCase


def webhook_payload(event, subscription_id, payment_id='pay_test123'):
    return {
        'event': event,
        'payload': {
            'subscription': {'entity': {'id': subscription_id}},
            'payment': {'entity': {'id': payment_id}},
        },
    }


class RazorpayWebhookTests(SubscriptionAPITestCase):
    """RAZORPAY_WEBHOOK_SECRET is unset in test settings, so signature
    verification is skipped — see razorpay_client.verify_webhook_signature."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.plan = self.create_plan()
        self.subscription = self.create_subscription(
            self.tenant, plan=self.plan, razorpay_subscription_id='sub_test123',
        )

    def _post(self, payload):
        return self.client.post(reverse('razorpay-webhook'), payload, format='json')

    def test_subscription_activated_activates_tenant_and_records_payment(self):
        response = self._post(webhook_payload('subscription.activated', 'sub_test123'))

        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.tenant.status, 'active')
        self.assertIsNotNone(self.subscription.current_period_start)
        self.assertIsNotNone(self.subscription.current_period_end)
        with tenant_context(self.tenant.id):
            self.assertEqual(
                SubscriptionPayment.objects.filter(
                    subscription=self.subscription, status=SubscriptionPayment.Status.SUCCESS
                ).count(),
                1,
            )

    def test_payment_failed_sets_grace_period_start(self):
        response = self._post(webhook_payload('payment.failed', 'sub_test123'))

        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.tenant.status, 'payment_failed')
        self.assertIsNotNone(self.subscription.payment_failed_at)
        with tenant_context(self.tenant.id):
            self.assertEqual(
                SubscriptionPayment.objects.filter(
                    subscription=self.subscription, status=SubscriptionPayment.Status.FAILED
                ).count(),
                1,
            )

    def test_subscription_halted_suspends_tenant(self):
        self._post(webhook_payload('subscription.halted', 'sub_test123'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'suspended')

    def test_subscription_cancelled_cancels_tenant(self):
        self._post(webhook_payload('subscription.cancelled', 'sub_test123'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'cancelled')

    def test_unknown_subscription_id_is_a_harmless_no_op(self):
        response = self._post(webhook_payload('subscription.activated', 'sub_does_not_exist'))
        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'trial')

    def test_unhandled_event_type_is_ignored(self):
        response = self._post(webhook_payload('subscription.paused', 'sub_test123'))
        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'trial')
