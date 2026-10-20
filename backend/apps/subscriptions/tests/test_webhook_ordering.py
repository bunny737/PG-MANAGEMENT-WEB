"""Out-of-order and conflicting Razorpay webhooks, through the real endpoint
(owner decision 2026-10-20; the rules themselves are in webhook_policy and its matrix tests).

Terminal and manual states win first; otherwise the newest event by occurrence time (the payload's
top-level `created_at`) wins, not the last one delivered. Every valid event is stored; a captured payment
that access must not honour is kept and flagged for refund; Razorpay is asked before changing access when
an event is undated or contradicts a halt."""
from unittest import mock

from django.urls import reverse

from apps.accounts.models import Tenant
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions import services
from apps.subscriptions.models import (
    RazorpaySubscription, RazorpayWebhookEvent, Subscription, SubscriptionInvoice, SubscriptionPayment,
)

from .base import SubscriptionAPITestCase

T = 1_760_000_000          # an arbitrary base instant; events are T + n minutes
SUB = 'sub_live1'


def minutes(n):
    return T + n * 60


def event(name, at, *, payment_id='', amount=99900, subscription_id=SUB, **extra):
    body = {
        'event': name,
        'payload': {
            'subscription': {'entity': {'id': subscription_id}},
            'payment': {'entity': {'id': payment_id, 'amount': amount}},
        },
    }
    if at is not None:
        body['created_at'] = minutes(at)
    return {**body, **extra}


class OrderingTestCase(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.subscription = self.create_subscription(
            self.tenant, plan=self.create_plan(), razorpay_subscription_id=SUB)
        self._seq = 0

    def post(self, payload, event_id=None):
        self._seq += 1
        response = self.client.post(
            reverse('razorpay-webhook'), payload, format='json',
            HTTP_X_RAZORPAY_EVENT_ID=event_id or f'evt_{self._seq}')
        self.assertEqual(response.status_code, 200, getattr(response, 'data', None))

    def deliver(self, *payloads):
        for payload in payloads:
            self.post(payload)

    def status(self):
        self.tenant.refresh_from_db()
        return self.tenant.status

    def payments(self, status=None):
        with tenant_context(self.tenant.id):
            rows = SubscriptionPayment.objects.filter(subscription=self.subscription)
            if status:
                rows = rows.filter(status=status)
            return sorted(rows.values_list('razorpay_payment_id', flat=True))

    def audits(self, action):
        with tenant_context(self.tenant.id):
            return list(AuditLog.objects.filter(action=action, object_id=str(self.subscription.pk)))

    def stored(self, outcome=None):
        rows = RazorpayWebhookEvent.objects.filter(razorpay_subscription_id=SUB)
        return rows.filter(outcome=outcome) if outcome else rows

    def ledger(self):
        return RazorpaySubscription.objects.get(razorpay_subscription_id=SUB)

    def active_tenant(self):
        """Take the tenant to ACTIVE with an applied charge at minute 10."""
        self.post(event('subscription.charged', 10, payment_id='pay_first'))
        self.assertEqual(self.status(), 'active')


class StaleEventTests(OrderingTestCase):
    def test_late_failure_after_a_newer_charge_is_recorded_but_changes_nothing(self):
        self.active_tenant()
        self.post(event('payment.failed', 5, payment_id='pay_late_fail'))
        self.assertEqual(self.status(), 'active')
        self.assertIsNone(self.subscription.__class__.objects.get(pk=self.subscription.pk).payment_failed_at)
        self.assertEqual(self.payments(SubscriptionPayment.Status.FAILED), ['pay_late_fail'])  # kept for audit
        self.assertEqual(len(self.audits('subscription.stale_event_ignored')), 1)
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.STALE_IGNORED).count(), 1)

    def test_delivery_order_does_not_matter(self):
        # The same two events, delivered either way round, end in the same place.
        self.deliver(event('payment.failed', 5, payment_id='pay_f'), event('subscription.charged', 10, payment_id='pay_c'))
        self.assertEqual(self.status(), 'active')

    def test_a_newer_failure_moves_active_to_payment_failed(self):
        self.active_tenant()
        self.post(event('payment.failed', 20, payment_id='pay_fail'))
        self.assertEqual(self.status(), 'payment_failed')
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.payment_failed_at)

    def test_a_newer_charge_recovers_payment_failed(self):
        self.active_tenant()
        self.post(event('payment.failed', 20, payment_id='pay_fail'))
        self.post(event('subscription.charged', 30, payment_id='pay_retry'))
        self.assertEqual(self.status(), 'active')
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.payment_failed_at)

    def test_an_older_charge_does_not_recover_a_newer_failure_but_keeps_the_money(self):
        self.active_tenant()
        self.post(event('payment.failed', 30, payment_id='pay_fail'))
        self.post(event('subscription.charged', 20, payment_id='pay_old_charge'))
        self.assertEqual(self.status(), 'payment_failed')
        self.assertIn('pay_old_charge', self.payments(SubscriptionPayment.Status.SUCCESS))
        self.assertEqual(self.audits('subscription.payment_needs_refund'), [])   # stale, not unwanted

    def test_equal_timestamps_follow_the_precedence_in_either_delivery_order(self):
        for first, second in ((('subscription.charged', 'pay_c'), ('subscription.halted', '')),
                              (('subscription.halted', ''), ('subscription.charged', 'pay_c'))):
            with self.subTest(order=(first[0], second[0])):
                Tenant.objects.filter(pk=self.tenant.pk).update(status='trial')
                RazorpaySubscription.objects.all().delete()
                self.post(event(first[0], 50, payment_id=first[1]))
                self.post(event(second[0], 50, payment_id=second[1]))
                self.assertEqual(self.status(), 'suspended')          # halted outranks charged
                SubscriptionPayment.objects.all().delete()

    def test_the_ledger_remembers_the_last_applied_event(self):
        self.active_tenant()
        row = self.ledger()
        self.assertEqual(row.last_status_event_type, 'subscription.charged')
        self.assertEqual(int(row.last_status_event_at.timestamp()), minutes(10))
        self.assertTrue(row.last_status_event_id.startswith('evt_'))
        self.assertIsNotNone(row.activated_at)
        self.post(event('payment.failed', 5, payment_id='pay_stale'))     # stale: must not move the marker
        self.assertEqual(self.ledger().last_status_event_type, 'subscription.charged')


class ActivationTests(OrderingTestCase):
    def test_activation_performs_the_initial_activation(self):
        self.post(event('subscription.activated', 1, payment_id='pay_1'))
        self.assertEqual(self.status(), 'active')

    def test_activation_is_not_a_recovery_event(self):
        self.active_tenant()
        self.post(event('payment.failed', 20, payment_id='pay_fail'))
        self.post(event('subscription.activated', 30, payment_id='pay_act'))
        self.assertEqual(self.status(), 'payment_failed')
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.NOT_RECOVERY_IGNORED).count(), 1)
        self.assertEqual(len(self.audits('subscription.event_ignored')), 1)


class CancelledIsTerminalTests(OrderingTestCase):
    def test_nothing_reactivates_a_cancelled_subscription(self):
        self.active_tenant()
        self.post(event('subscription.cancelled', 20))
        self.assertEqual(self.status(), 'cancelled')
        self.assertEqual(self.ledger().state, RazorpaySubscription.State.CANCELLED)
        for n, name in enumerate(('subscription.activated', 'subscription.charged', 'subscription.resumed'), start=30):
            self.post(event(name, n, payment_id=f'pay_{n}' if name != 'subscription.resumed' else ''))
            self.assertEqual(self.status(), 'cancelled', name)
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.TERMINAL_IGNORED).count(), 3)

    def test_cancelled_applies_even_if_older_than_a_charge(self):
        self.active_tenant()                                       # charge at minute 10
        self.post(event('subscription.cancelled', 5))              # delivered late, occurred earlier
        self.assertEqual(self.status(), 'cancelled')

    def test_a_captured_payment_after_cancellation_is_preserved_and_flagged_for_refund(self):
        self.post(event('subscription.cancelled', 20))
        self.post(event('subscription.charged', 30, payment_id='pay_after_cancel', amount=19900))
        self.assertEqual(self.status(), 'cancelled')
        self.assertEqual(self.payments(SubscriptionPayment.Status.SUCCESS), ['pay_after_cancel'])
        flags = self.audits('subscription.payment_needs_refund')
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].after['razorpay_payment_id'], 'pay_after_cancel')
        self.assertEqual(flags[0].after['reason'], 'subscription is cancelled')

    def test_a_redelivered_late_payment_is_flagged_once(self):
        self.post(event('subscription.cancelled', 20))
        late = event('subscription.charged', 30, payment_id='pay_after_cancel')
        self.post(late, event_id='evt_same')
        self.post(late, event_id='evt_same')
        self.post(late, event_id='evt_other_delivery_id')            # different delivery id, same payment
        self.assertEqual(len(self.audits('subscription.payment_needs_refund')), 1)
        self.assertEqual(self.payments(), ['pay_after_cancel'])


class HaltedTests(OrderingTestCase):
    def halt(self):
        self.active_tenant()
        self.post(event('subscription.halted', 20))
        self.assertEqual(self.status(), 'suspended')

    def test_a_newer_resume_recovers(self):
        self.halt()
        self.post(event('subscription.resumed', 30))
        self.assertEqual(self.status(), 'active')

    def test_an_older_resume_does_not(self):
        self.halt()
        self.post(event('subscription.resumed', 15))
        self.assertEqual(self.status(), 'suspended')

    def test_a_charge_after_halt_stays_suspended_when_razorpay_still_says_halted(self):
        self.halt()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status',
                        return_value='halted') as fetch:
            self.post(event('subscription.charged', 30, payment_id='pay_after_halt'))
        fetch.assert_called_once_with(SUB)
        self.assertEqual(self.status(), 'suspended')
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.VERIFICATION_DECLINED).count(), 1)
        self.assertIn('pay_after_halt', self.payments(SubscriptionPayment.Status.SUCCESS))   # money kept
        self.assertEqual(len(self.audits('subscription.payment_needs_refund')), 1)           # and flagged

    def test_a_charge_after_halt_recovers_only_if_razorpay_confirms_active(self):
        self.halt()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status', return_value='active'):
            self.post(event('subscription.charged', 30, payment_id='pay_recovered'))
        self.assertEqual(self.status(), 'active')
        self.assertEqual(self.audits('subscription.payment_needs_refund'), [])

    def test_a_charge_after_halt_without_razorpay_never_grants_access(self):
        self.halt()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status',
                        side_effect=RuntimeError('razorpay unreachable')):
            self.post(event('subscription.charged', 30, payment_id='pay_unverified'))
        self.assertEqual(self.status(), 'suspended')
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.NEEDS_VERIFICATION).count(), 1)
        self.assertEqual(len(self.audits('subscription.event_needs_verification')), 1)
        self.assertEqual(len(self.audits('subscription.payment_needs_refund')), 1)

    def test_activation_after_halt_is_not_a_recovery(self):
        self.halt()
        self.post(event('subscription.activated', 30, payment_id='pay_act'))
        self.assertEqual(self.status(), 'suspended')


class ManualHoldTests(OrderingTestCase):
    def suspend_by_hand(self):
        self.active_tenant()
        services.suspend_tenant(tenant=self.tenant, actor=None)
        self.assertEqual(self.status(), 'suspended')

    def test_a_manual_suspension_survives_every_webhook(self):
        self.suspend_by_hand()
        for n, (name, paid) in enumerate((('subscription.activated', True), ('subscription.charged', True),
                                          ('subscription.resumed', False), ('payment.failed', True),
                                          ('subscription.halted', False)), start=100):
            self.post(event(name, n, payment_id=f'pay_{n}' if paid else ''))
            self.assertEqual(self.status(), 'suspended', name)
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.MANUAL_HOLD_IGNORED).count(), 5)

    def test_a_payment_under_a_manual_hold_is_kept_and_flagged(self):
        self.suspend_by_hand()
        self.post(event('subscription.charged', 100, payment_id='pay_held'))
        self.assertIn('pay_held', self.payments(SubscriptionPayment.Status.SUCCESS))
        self.assertEqual(len(self.audits('subscription.payment_needs_refund')), 1)

    def test_a_manual_cancellation_is_held_too(self):
        self.active_tenant()
        Tenant.objects.filter(pk=self.tenant.pk).update(status='cancelled')
        services.set_manual_status_hold(self.tenant, True)
        self.post(event('subscription.charged', 100, payment_id='pay_x'))
        self.assertEqual(self.status(), 'cancelled')

    def test_only_an_explicit_reactivation_lifts_the_hold(self):
        self.suspend_by_hand()
        services.reactivate_tenant(tenant=self.tenant, actor=None)
        self.assertEqual(self.status(), 'active')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status_hold, '')
        self.post(event('payment.failed', 200, payment_id='pay_fail'))     # webhooks work again
        self.assertEqual(self.status(), 'payment_failed')

    def test_a_django_admin_status_change_sets_and_clears_the_hold(self):
        from django.contrib import admin
        from apps.accounts.admin import TenantAdmin
        model_admin = TenantAdmin(Tenant, admin.site)
        form = mock.Mock(changed_data=['status'])
        for status, held in (('suspended', 'manual'), ('cancelled', 'manual'), ('active', '')):
            with self.subTest(status):
                self.tenant.status = status
                model_admin.save_model(mock.Mock(), self.tenant, form, change=True)
                self.subscription.refresh_from_db()
                self.assertEqual(self.subscription.status_hold, held)

    def test_arrears_invoice_events_respect_the_hold_and_terminal_states(self):
        for month, status in ((7, 'suspended'), (8, 'cancelled')):     # one invoice per billing cycle
            with self.subTest(status):
                Tenant.objects.filter(pk=self.tenant.pk).update(status=status)
                self.tenant.refresh_from_db()
                with tenant_context(self.tenant.id):
                    invoice = SubscriptionInvoice.objects.create(
                        tenant_id=self.tenant.id, subscription=self.subscription, total_amount='100.00',
                        period_start=f'2026-0{month}-01', period_end=f'2026-0{month}-28',
                        billed_bed_count_start=10, billed_bed_count_end=10,
                        status=SubscriptionInvoice.Status.ISSUED, razorpay_invoice_id=f'inv_{status}')
                    services._apply_invoice_event('invoice.expired', invoice, '', {})
                self.assertEqual(self.status(), status)

    def test_a_late_expiry_for_an_invoice_that_was_paid_is_ignored(self):
        self.active_tenant()
        with tenant_context(self.tenant.id):
            invoice = SubscriptionInvoice.objects.create(
                tenant_id=self.tenant.id, subscription=self.subscription, total_amount='100.00',
                period_start='2026-09-01', period_end='2026-09-30',
                        billed_bed_count_start=10, billed_bed_count_end=10,
                status=SubscriptionInvoice.Status.PAID, razorpay_invoice_id='inv_paid')
            services._apply_invoice_event('invoice.expired', invoice, '', {})
            invoice.refresh_from_db()
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(self.status(), 'active')


class MissingTimestampTests(OrderingTestCase):
    def test_an_undated_event_is_resolved_by_asking_razorpay(self):
        self.active_tenant()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status',
                        return_value='pending') as fetch:
            self.post(event('payment.failed', None, payment_id='pay_undated'))
        fetch.assert_called_once_with(SUB)
        self.assertEqual(self.status(), 'payment_failed')                 # Razorpay says "pending": a retry is due

    def test_an_undated_event_razorpay_does_not_confirm_changes_nothing(self):
        self.active_tenant()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status', return_value='active'):
            self.post(event('payment.failed', None, payment_id='pay_undated'))
        self.assertEqual(self.status(), 'active')

    def test_an_undated_event_with_razorpay_unreachable_never_changes_access(self):
        self.active_tenant()
        with mock.patch('apps.subscriptions.razorpay_client.is_configured', return_value=True), \
             mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status',
                        side_effect=ConnectionError):
            self.post(event('subscription.halted', None))
        self.assertEqual(self.status(), 'active')
        self.assertEqual(self.stored(RazorpayWebhookEvent.Outcome.NEEDS_VERIFICATION).count(), 1)

    def test_an_undated_cancellation_still_applies_because_it_is_terminal(self):
        self.active_tenant()
        self.post(event('subscription.cancelled', None))
        self.assertEqual(self.status(), 'cancelled')


class EventStoreTests(OrderingTestCase):
    def test_every_valid_event_is_stored_including_ignored_ones(self):
        self.active_tenant()
        self.post(event('payment.failed', 5, payment_id='pay_stale'))
        self.post(event('subscription.paused', 40))
        self.post(event('subscription.charged', 50, subscription_id='sub_nobody_knows'))
        outcomes = sorted(self.stored().values_list('outcome', flat=True)) + \
            list(RazorpayWebhookEvent.objects.filter(razorpay_subscription_id='sub_nobody_knows')
                 .values_list('outcome', flat=True))
        self.assertEqual(sorted(outcomes), sorted(['applied', 'stale_ignored', 'unhandled', 'unknown_subscription']))
        stored = self.stored().get(event_type='payment.failed')
        self.assertEqual(stored.payload['payload']['payment']['entity']['id'], 'pay_stale')
        self.assertEqual(int(stored.occurred_at.timestamp()), minutes(5))

    def test_a_redelivered_event_id_does_nothing(self):
        charge = event('subscription.charged', 10, payment_id='pay_1')
        for _ in range(3):
            self.post(charge, event_id='evt_dup')
        self.assertEqual(self.stored().count(), 1)
        self.assertEqual(self.payments(), ['pay_1'])

    def test_without_an_event_id_the_body_identifies_a_redelivery(self):
        charge = event('subscription.charged', 10, payment_id='pay_1')
        for _ in range(2):
            response = self.client.post(reverse('razorpay-webhook'), charge, format='json')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored().count(), 1)

    def test_events_for_old_subscriptions_are_still_reconciled_not_applied_to_the_tenant(self):
        self.active_tenant()
        RazorpaySubscription.objects.create(
            subscription=self.subscription, plan=self.subscription.plan, razorpay_subscription_id='sub_old',
            state=RazorpaySubscription.State.REPLACED)
        self.post(event('subscription.halted', 30, subscription_id='sub_old'))
        self.assertEqual(self.status(), 'active')
        self.assertEqual(RazorpayWebhookEvent.objects.get(razorpay_subscription_id='sub_old').outcome, 'non_current')


class RazorpayClientTimeoutTests(SubscriptionAPITestCase):
    def test_every_razorpay_request_has_a_timeout(self):
        from apps.subscriptions import razorpay_client
        with self.settings(RAZORPAY_KEY_ID='rzp_test_x', RAZORPAY_KEY_SECRET='secret'):
            client = razorpay_client.get_client()
        with mock.patch('requests.Session.request') as request:
            request.return_value = mock.Mock(status_code=200, json=lambda: {'status': 'active'})
            client.subscription.fetch('sub_1')
        self.assertEqual(request.call_args.kwargs['timeout'], razorpay_client.REQUEST_TIMEOUT)


class TenantIsolationTests(OrderingTestCase):
    def test_recorded_payments_stay_inside_their_tenant(self):
        self.active_tenant()
        other = self.create_tenant(name='Other PG')
        with tenant_context(other.id):
            self.assertEqual(SubscriptionPayment.objects.count(), 0)
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.count(), 1)
