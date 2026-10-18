"""A cancelled Razorpay subscription never restarts, so a subscription we may have
cancelled must not be promoted to the tenant's live one. The cancellation worker claims
the ledger row (CANCELLING) before calling Razorpay; these tests pin the races around that."""
import threading
from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import Tenant
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import BedLedgerEntry, Plan, RazorpaySubscription, Subscription, SubscriptionPayment
from apps.subscriptions.services import handle_webhook_event, process_razorpay_cancellations
from apps.subscriptions.tests.base import SubscriptionAPITestCase

from .test_plan_change import CANCEL, PlanChangeTestCase
from .test_webhook import webhook_payload

State = RazorpaySubscription.State


class CancellationClaimTests(PlanChangeTestCase):
    def abandoned_unlimited(self):
        """A paid-for-later choice: Unlimited was chosen, then replaced by another plan."""
        third = self.create_plan(name='Third Test', price_per_month='399.00')
        self.select(self.unlimited)
        abandoned_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL, side_effect=RuntimeError('down')), self.captureOnCommitCallbacks(execute=True):
            self.select(third)
        self.assertEqual(self.ledger(abandoned_id).state, State.ABANDONED)
        return abandoned_id

    def test_a_charge_on_a_subscription_being_cancelled_is_flagged_not_promoted(self):
        abandoned_id = self.abandoned_unlimited()
        RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(
            state=State.CANCELLING, cancel_from=State.ABANDONED,
        )

        self.webhook('subscription.activated', abandoned_id, payment_id='pay_during_cancel')

        subscription = self.reload()
        self.assertEqual(subscription.plan, self.basic)
        self.assertEqual(subscription.razorpay_subscription_id, 'sub_basic_live')
        self.assertEqual(self.ledger(abandoned_id).state, State.CANCELLING)
        with tenant_context(self.tenant.id):
            self.assertTrue(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_during_cancel').exists())
            flag = AuditLog.objects.get(action='subscription.payment_needs_refund')
        self.assertEqual(flag.after['subscription_state'], State.CANCELLING)

    def test_a_refund_flagged_payment_replayed_after_a_failed_cancel_does_not_promote(self):
        abandoned_id = self.abandoned_unlimited()
        RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(
            state=State.CANCELLING, cancel_from=State.ABANDONED,
        )
        self.webhook('subscription.activated', abandoned_id, payment_id='pay_flagged')  # flagged for refund

        # The cancel then fails, so the row returns to ABANDONED (a state that normally honours payments)...
        RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(
            state=State.CANCELLING, updated_at=timezone.now() - timedelta(minutes=16),
        )
        with mock.patch(CANCEL, side_effect=RuntimeError('down')):
            process_razorpay_cancellations()
        self.assertEqual(self.ledger(abandoned_id).state, State.ABANDONED)

        # ...and Razorpay redelivers the same payment's webhook.
        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', abandoned_id, payment_id='pay_flagged')
            self.webhook('subscription.charged', abandoned_id, payment_id='pay_flagged')

        subscription = self.reload()
        self.assertEqual(subscription.plan, self.basic)
        self.assertEqual(subscription.razorpay_subscription_id, 'sub_basic_live')
        self.assertEqual(self.ledger(abandoned_id).state, State.ABANDONED)
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_flagged').count(), 1)
            self.assertEqual(AuditLog.objects.filter(action='subscription.payment_needs_refund').count(), 1)

    def test_a_failed_cancel_returns_the_row_to_the_state_it_came_from(self):
        abandoned_id = self.abandoned_unlimited()  # that failed attempt already ran once
        self.assertEqual(self.ledger(abandoned_id).cancel_attempts, 1)

        with mock.patch(CANCEL, side_effect=RuntimeError('still down')):
            process_razorpay_cancellations()

        row = self.ledger(abandoned_id)
        self.assertEqual((row.state, row.cancel_attempts), (State.ABANDONED, 2))
        # ...so a payment that lands while the outage lasts is still honoured.
        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', abandoned_id, payment_id='pay_after_failed_cancel')
        self.assertEqual(self.reload().plan, self.unlimited)

    def test_a_ledger_that_changes_under_a_successful_cancel_is_a_conflict_not_a_success(self):
        abandoned_id = self.abandoned_unlimited()

        def cancel_then_row_changes(_id):
            RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(state=State.CURRENT)

        with mock.patch(CANCEL, side_effect=cancel_then_row_changes):
            outcome = process_razorpay_cancellations()

        self.assertEqual(outcome, {'cancelled': 0, 'failed': 1})
        self.assertEqual(self.ledger(abandoned_id).state, State.CURRENT)
        with tenant_context(self.tenant.id):
            conflict = AuditLog.objects.get(action='subscription.cancel_conflict')
        self.assertEqual(conflict.after['ledger_state'], State.CURRENT)

    def test_razorpays_own_cancelled_webhook_arriving_first_is_not_a_conflict(self):
        abandoned_id = self.abandoned_unlimited()

        def cancel_confirmed_by_webhook_meanwhile(_id):
            RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(state=State.CANCELLED)

        with mock.patch(CANCEL, side_effect=cancel_confirmed_by_webhook_meanwhile):
            outcome = process_razorpay_cancellations()

        self.assertEqual(outcome, {'cancelled': 1, 'failed': 0})
        with tenant_context(self.tenant.id):
            self.assertFalse(AuditLog.objects.filter(action='subscription.cancel_conflict').exists())

    def test_a_fresh_claim_is_left_alone_and_a_dead_workers_claim_is_taken_over(self):
        abandoned_id = self.abandoned_unlimited()
        RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(
            state=State.CANCELLING, cancel_from=State.ABANDONED, updated_at=timezone.now(),
        )
        with mock.patch(CANCEL) as cancel:
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 0, 'failed': 0})
        cancel.assert_not_called()  # another worker is mid-call

        RazorpaySubscription.objects.filter(razorpay_subscription_id=abandoned_id).update(
            updated_at=timezone.now() - timedelta(minutes=16),
        )
        with mock.patch(CANCEL) as cancel:
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 1, 'failed': 0})
        cancel.assert_called_once_with(abandoned_id)
        self.assertEqual(self.ledger(abandoned_id).state, State.CANCELLED)

    def test_only_one_worker_cancels_a_row(self):
        abandoned_id = self.abandoned_unlimited()
        row = self.ledger(abandoned_id)

        calls = []

        def second_worker_arrives_mid_call(subscription_id):
            calls.append(subscription_id)
            if len(calls) == 1:
                process_razorpay_cancellations()  # a second sweep while the first is in flight

        with mock.patch(CANCEL, side_effect=second_worker_arrives_mid_call):
            process_razorpay_cancellations()

        self.assertEqual(calls, [abandoned_id])
        self.assertEqual(self.ledger(abandoned_id).state, State.CANCELLED)
        self.assertEqual(row.pk, self.ledger(abandoned_id).pk)


class PaymentRacingACancellationTests(TransactionTestCase):
    """The review's exact ordering, with real threads: a payment for an abandoned
    subscription succeeds at Razorpay, the retry worker cancels it remotely, and the
    delayed payment webhook arrives while the worker is still between the Razorpay call
    and its own database update."""

    def _fixture_teardown(self):
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('Cancel Race Tenant', status=Tenant.Status.ACTIVE)
        self.basic = SubscriptionAPITestCase.create_plan(
            name='Cancel Race Basic', max_properties=None, max_residents_per_property=None,
        )
        self.unlimited = SubscriptionAPITestCase.create_plan(
            name='Cancel Race Unlimited', price_per_month='249.00', max_properties=None, max_residents_per_property=None,
        )
        self.subscription = SubscriptionAPITestCase.create_subscription(
            self.tenant, plan=self.basic, razorpay_subscription_id='sub_race_live',
        )
        self.abandoned = RazorpaySubscription.objects.create(
            subscription=self.subscription, plan=self.unlimited, razorpay_subscription_id='sub_race_abandoned',
            state=State.ABANDONED,
        )

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            SubscriptionPayment.objects.filter(tenant_id=self.tenant.id).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
            BedLedgerEntry.objects.filter(tenant_id=self.tenant.id).delete()
        RazorpaySubscription.objects.filter(subscription=self.subscription).delete()
        Subscription.objects.filter(pk=self.subscription.pk).delete()
        Plan.objects.filter(pk__in=[self.basic.pk, self.unlimited.pk]).delete()
        self.tenant.delete()

    def test_a_payment_arriving_while_the_cancel_is_in_flight_is_flagged_and_never_promoted(self):
        cancelled_remotely, release = threading.Event(), threading.Event()
        worker_errors = []

        def cancel_succeeds_then_pauses(_subscription_id):
            cancelled_remotely.set()
            assert release.wait(timeout=20), 'the test never released the worker'

        def worker():
            try:
                with mock.patch(CANCEL, side_effect=cancel_succeeds_then_pauses):
                    process_razorpay_cancellations()
            except Exception as exc:  # noqa: BLE001 - reported below
                worker_errors.append(exc)
            finally:
                from django.db import connection
                connection.close()

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(cancelled_remotely.wait(timeout=20))
            # The worker has cancelled at Razorpay and not yet updated the ledger.
            handle_webhook_event(webhook_payload('subscription.activated', 'sub_race_abandoned', 'pay_race'))
        finally:
            release.set()
            thread.join(timeout=30)

        self.assertEqual(worker_errors, [])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.basic)
        self.assertEqual(self.subscription.razorpay_subscription_id, 'sub_race_live')  # never the cancelled one
        self.abandoned.refresh_from_db()
        self.assertEqual(self.abandoned.state, State.CANCELLED)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        with tenant_context(self.tenant.id):
            self.assertTrue(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_race').exists())
            self.assertEqual(AuditLog.objects.filter(action='subscription.payment_needs_refund').count(), 1)

    def test_a_payment_that_arrives_before_the_worker_claims_wins_and_the_worker_stands_down(self):
        with mock.patch(CANCEL) as cancel:
            # Committing the promotion runs its own post-commit sweep, which cancels what it replaced.
            handle_webhook_event(webhook_payload('subscription.activated', 'sub_race_abandoned', 'pay_first'))
            outcome = process_razorpay_cancellations()  # a later sweep finds nothing left to do

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.unlimited)
        self.assertEqual(self.subscription.razorpay_subscription_id, 'sub_race_abandoned')
        # Only the subscription it replaced is cancelled, once; the one just paid for never is.
        self.assertEqual(cancel.call_args_list, [mock.call('sub_race_live')])
        self.assertEqual(outcome, {'cancelled': 0, 'failed': 0})
        self.assertEqual(
            RazorpaySubscription.objects.get(razorpay_subscription_id='sub_race_live').state, State.CANCELLED,
        )
        self.assertEqual(RazorpaySubscription.objects.get(razorpay_subscription_id='sub_race_abandoned').state, State.CURRENT)
