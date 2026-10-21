"""Razorpay delivers webhooks at least once and possibly out of order
(docs/deployment.md, WP12). Replays must never double-record a charge or a
failure, nor write duplicate status audit entries.

Ordering of stale and conflicting events is covered in test_webhook_ordering.py."""
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import SubscriptionPayment

from .base import SubscriptionAPITestCase


def event(name, subscription_id='sub_live1', payment_id='pay_1', amount=99900, created_at=1760000000):
    return {
        'event': name,
        'created_at': created_at,
        'payload': {
            'subscription': {'entity': {'id': subscription_id}},
            'payment': {'entity': {'id': payment_id, 'amount': amount}},
        },
    }


class WebhookDeliveryTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.subscription = self.create_subscription(
            self.tenant, plan=self.create_plan(), razorpay_subscription_id='sub_live1')

    def deliver(self, *payloads):
        for payload in payloads:
            response = self.client.post(reverse('razorpay-webhook'), payload, format='json')
            self.assertEqual(response.status_code, 200, getattr(response, 'data', None))

    # RLS-scoped tables: evaluate inside the tenant context, never return lazy querysets.
    def payment_ids(self, status):
        with tenant_context(self.tenant.id):
            return sorted(SubscriptionPayment.objects.filter(subscription=self.subscription, status=status)
                          .values_list('razorpay_payment_id', flat=True))

    def status_audit_count(self):
        with tenant_context(self.tenant.id):
            return AuditLog.objects.filter(action='tenant.status_changed', object_id=str(self.tenant.pk)).count()

    def test_duplicate_charge_is_recorded_once(self):
        charged = event('subscription.charged', payment_id='pay_2')
        self.deliver(charged, charged, charged)
        self.assertEqual(self.payment_ids(SubscriptionPayment.Status.SUCCESS), ['pay_2'])
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'active')
        self.assertEqual(self.status_audit_count(), 1)

    def test_duplicate_failure_is_recorded_once(self):
        failed = event('payment.failed', payment_id='pay_f1')
        self.deliver(failed, failed)
        self.assertEqual(self.payment_ids(SubscriptionPayment.Status.FAILED), ['pay_f1'])
        self.assertEqual(self.status_audit_count(), 1)

    def test_duplicate_cancellation_changes_status_once(self):
        cancelled = event('subscription.cancelled', payment_id='')
        self.deliver(cancelled, cancelled)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'cancelled')
        self.assertEqual(self.status_audit_count(), 1)

    def test_charge_before_activation_records_both_payments_once(self):
        activated = event('subscription.activated', payment_id='pay_1', created_at=1760000000)
        charged = event('subscription.charged', payment_id='pay_2', created_at=1762600000)
        self.deliver(charged, activated, charged, activated)
        self.assertEqual(self.payment_ids(SubscriptionPayment.Status.SUCCESS), ['pay_1', 'pay_2'])
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'active')

    def test_recorded_amount_is_what_razorpay_charged(self):
        self.deliver(event('subscription.charged', payment_id='pay_3', amount=123456))
        with tenant_context(self.tenant.id):
            payment = SubscriptionPayment.objects.get(subscription=self.subscription)
            self.assertEqual(str(payment.amount), '1234.56')
