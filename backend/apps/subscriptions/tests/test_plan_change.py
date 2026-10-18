"""Switching plans must never grant a plan that hasn't been paid for, or leave the
tenant on two Razorpay subscriptions. A flat plan is only *pending* until Razorpay
confirms its first charge; that webhook promotes it and cancels the old one."""
from unittest import mock

from django.urls import reverse

from apps.accounts.models import Tenant
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import RazorpaySubscription, SubscriptionPayment
from apps.subscriptions.services import process_razorpay_cancellations

from .base import SubscriptionAPITestCase
from .test_webhook import webhook_payload

CANCEL = 'apps.subscriptions.razorpay_client.cancel_razorpay_subscription'


class PlanChangeTestCase(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant(status=Tenant.Status.ACTIVE)
        self.owner = self.create_owner(self.tenant)
        self.basic = self.create_plan(name='Basic Test', max_beds=500, max_properties=None, max_residents_per_property=None)
        self.unlimited = self.create_plan(
            name='Unlimited Test', price_per_month='249.00', max_properties=None, max_residents_per_property=None,
        )
        self.subscription = self.create_subscription(
            self.tenant, plan=self.basic, razorpay_subscription_id='sub_basic_live',
        )
        self.authenticate(self.owner)

    def select(self, plan):
        return self.client.post(
            reverse('subscription-select-plan', args=[self.tenant.id]), {'plan': str(plan.id)}, format='json',
        )

    def webhook(self, event, subscription_id, payment_id='pay_1'):
        return self.client.post(
            reverse('razorpay-webhook'), webhook_payload(event, subscription_id, payment_id), format='json',
        )

    def reload(self):
        self.subscription.refresh_from_db()
        self.tenant.refresh_from_db()
        return self.subscription

    @staticmethod
    def ledger(razorpay_subscription_id):
        return RazorpaySubscription.objects.get(razorpay_subscription_id=razorpay_subscription_id)


class SelectingAFlatPlanTests(PlanChangeTestCase):
    def test_an_active_tenant_keeps_its_plan_and_limits_until_the_new_plan_is_paid(self):
        with mock.patch(CANCEL) as cancel:
            response = self.select(self.unlimited)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['plan']['name'], 'Basic Test')
        self.assertEqual(response.data['max_beds'], 500)  # still Basic's cap
        self.assertEqual(response.data['pending_plan']['name'], 'Unlimited Test')
        self.assertEqual(response.data['razorpay_subscription_id'], 'sub_basic_live')
        cancel.assert_not_called()  # the old subscription keeps running until the new one is paid

    def test_choosing_the_current_plan_again_is_refused_while_active(self):
        response = self.select(self.basic)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'PLAN_UNCHANGED')

    def test_choosing_another_plan_replaces_the_pending_one_and_cancels_the_abandoned_subscription(self):
        third = self.create_plan(name='Third Test', price_per_month='399.00')
        self.select(self.unlimited)
        first_pending = self.reload().pending_razorpay_subscription_id

        with mock.patch(CANCEL) as cancel, self.captureOnCommitCallbacks(execute=True):
            response = self.select(third)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['pending_plan']['name'], 'Third Test')
        self.assertNotEqual(response.data['pending_razorpay_subscription_id'], first_pending)
        cancel.assert_called_once_with(first_pending)

    def test_a_failed_cancel_of_an_abandoned_subscription_does_not_undo_the_new_choice(self):
        third = self.create_plan(name='Third Test', price_per_month='399.00')
        self.select(self.unlimited)

        with mock.patch(CANCEL, side_effect=RuntimeError('razorpay down')), self.captureOnCommitCallbacks(execute=True):
            response = self.select(third)

        self.assertEqual(response.status_code, 200, response.data)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.razorpay_cancel_failed').exists())

    def test_a_trial_tenant_gets_no_new_limits_before_paying_either(self):
        trial_tenant = self.create_tenant(name='Trial PG')
        owner = self.create_owner(trial_tenant, email='trial-owner@example.com')
        self.create_subscription(trial_tenant)
        self.authenticate(owner)

        response = self.client.post(
            reverse('subscription-select-plan', args=[trial_tenant.id]), {'plan': str(self.unlimited.id)}, format='json',
        )

        self.assertIsNone(response.data['plan'])
        self.assertEqual(response.data['pending_plan']['name'], 'Unlimited Test')


class PaymentConfirmationTests(PlanChangeTestCase):
    def pending_unlimited(self):
        self.select(self.unlimited)
        return self.reload().pending_razorpay_subscription_id

    def test_the_first_charge_promotes_the_pending_plan_and_cancels_the_old_subscription(self):
        pending_id = self.pending_unlimited()

        with mock.patch(CANCEL) as cancel, self.captureOnCommitCallbacks(execute=True):
            response = self.webhook('subscription.activated', pending_id)

        self.assertEqual(response.status_code, 200)
        subscription = self.reload()
        self.assertEqual(subscription.plan, self.unlimited)
        self.assertEqual(subscription.razorpay_subscription_id, pending_id)
        self.assertIsNone(subscription.pending_plan)
        self.assertEqual(subscription.pending_razorpay_subscription_id, '')
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        cancel.assert_called_once_with('sub_basic_live')
        with tenant_context(self.tenant.id):
            payment = SubscriptionPayment.objects.get(subscription=subscription)
            self.assertEqual(payment.status, SubscriptionPayment.Status.SUCCESS)
            self.assertTrue(AuditLog.objects.filter(action='subscription.plan_changed').exists())

    def test_a_replayed_confirmation_changes_nothing_and_does_not_cancel_again(self):
        pending_id = self.pending_unlimited()
        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id)

        with mock.patch(CANCEL) as cancel, self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id)

        self.assertEqual(self.reload().plan, self.unlimited)
        cancel.assert_not_called()
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.filter(subscription=self.subscription).count(), 1)

    def test_a_trial_tenant_is_activated_on_the_plan_it_paid_for(self):
        trial_tenant = self.create_tenant(name='Trial PG')
        owner = self.create_owner(trial_tenant, email='trial-owner@example.com')
        subscription = self.create_subscription(trial_tenant)
        self.authenticate(owner)
        self.client.post(
            reverse('subscription-select-plan', args=[trial_tenant.id]), {'plan': str(self.unlimited.id)}, format='json',
        )
        subscription.refresh_from_db()

        with mock.patch(CANCEL) as cancel, self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.charged', subscription.pending_razorpay_subscription_id)

        subscription.refresh_from_db()
        trial_tenant.refresh_from_db()
        self.assertEqual(subscription.plan, self.unlimited)
        self.assertEqual(trial_tenant.status, Tenant.Status.ACTIVE)
        cancel.assert_not_called()  # nothing to cancel: there was no previous subscription

    def test_a_failed_payment_on_the_pending_subscription_does_not_hurt_the_paying_tenant(self):
        pending_id = self.pending_unlimited()

        self.webhook('payment.failed', pending_id, payment_id='pay_failed')

        subscription = self.reload()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        self.assertEqual(subscription.plan, self.basic)
        self.assertEqual(subscription.pending_razorpay_subscription_id, pending_id)

    def test_cancelling_the_pending_subscription_abandons_the_change_only(self):
        pending_id = self.pending_unlimited()

        self.webhook('subscription.cancelled', pending_id)

        subscription = self.reload()
        self.assertIsNone(subscription.pending_plan)
        self.assertEqual(subscription.plan, self.basic)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_the_cancel_we_send_for_the_old_subscription_does_not_cancel_the_tenant(self):
        pending_id = self.pending_unlimited()
        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id)

        # Razorpay now reports the old subscription as cancelled — an id we no longer track.
        self.webhook('subscription.cancelled', 'sub_basic_live')

        self.assertEqual(self.reload().plan, self.unlimited)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_an_event_for_an_id_that_was_superseded_after_the_lookup_is_ignored(self):
        # The unlocked lookup finds the row, then a plan change moves the tenant to a
        # new subscription before our lock is taken; the stale event must do nothing.
        stale_row = type(self.subscription).objects.select_related('tenant', 'plan').get(pk=self.subscription.pk)
        type(self.subscription).objects.filter(pk=self.subscription.pk).update(
            plan=self.unlimited, razorpay_subscription_id='sub_unlimited_live',
        )
        lookup = mock.MagicMock()
        lookup.select_related.return_value.first.return_value = stale_row

        with mock.patch.object(type(self.subscription).objects, 'filter', return_value=lookup):
            response = self.webhook('subscription.cancelled', 'sub_basic_live')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reload().plan, self.unlimited)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_a_charge_that_leaves_a_failed_old_cancel_still_completes_the_switch(self):
        pending_id = self.pending_unlimited()

        with mock.patch(CANCEL, side_effect=RuntimeError('razorpay down')), self.captureOnCommitCallbacks(execute=True):
            response = self.webhook('subscription.activated', pending_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reload().plan, self.unlimited)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.razorpay_cancel_failed').exists())

    def test_a_plan_paid_for_after_the_tenant_outgrew_it_is_still_applied_and_audited(self):
        # Bed counts are checked when the plan is chosen; the tenant then grows before paying.
        self.subscription.plan = self.unlimited
        self.subscription.save(update_fields=['plan'])
        self.basic.max_beds = 2
        self.basic.save(update_fields=['max_beds'])
        self.select(self.basic)
        pending_id = self.reload().pending_razorpay_subscription_id
        for number in range(3):
            self.create_bed(
                self.create_room(self.create_floor(self.create_property(self.tenant)), room_number=f'R{number}'),
                bed_number=f'R{number}-A',
            )

        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id)

        self.assertEqual(self.reload().plan, self.basic)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.promoted_over_bed_limit').exists())


class SwitchingToPerBedTests(PlanChangeTestCase):
    def setUp(self):
        super().setUp()
        self.per_bed = self.create_bed_plan(name='Per Bed Test', bed_tiers=[(None, '2.00')])

    def test_the_switch_is_written_first_and_the_old_flat_subscription_cancelled_after_commit(self):
        with mock.patch(CANCEL) as cancel:
            response = self.select(self.per_bed)
            cancel.assert_not_called()  # nothing remote has happened before the transaction commits

        self.assertEqual(response.status_code, 200, response.data)
        subscription = self.reload()
        self.assertEqual(subscription.plan, self.per_bed)
        self.assertEqual(subscription.razorpay_subscription_id, '')
        self.assertEqual(self.ledger('sub_basic_live').state, 'replaced')

        with mock.patch(CANCEL) as cancel:
            process_razorpay_cancellations()
        cancel.assert_called_once_with('sub_basic_live')
        self.assertEqual(self.ledger('sub_basic_live').state, 'cancelled')

    def test_a_failure_before_commit_cancels_nothing_remotely(self):
        # The old design cancelled first, so a later local failure left Razorpay cancelled
        # while the database still showed the flat subscription as live.
        with mock.patch(CANCEL) as cancel, \
                mock.patch('apps.subscriptions.razorpay_client.create_razorpay_customer', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.select(self.per_bed)

        cancel.assert_not_called()
        subscription = self.reload()
        self.assertEqual(subscription.plan, self.basic)
        self.assertEqual(subscription.razorpay_subscription_id, 'sub_basic_live')

    def test_an_outage_leaves_the_switch_in_place_and_the_cancel_queued_for_retry(self):
        with mock.patch(CANCEL, side_effect=RuntimeError('razorpay down')), self.captureOnCommitCallbacks(execute=True):
            response = self.select(self.per_bed)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.reload().plan, self.per_bed)
        row = self.ledger('sub_basic_live')
        self.assertEqual((row.state, row.cancel_attempts), ('replaced', 1))

    def test_any_pending_flat_change_is_dropped_when_switching_to_per_bed(self):
        self.select(self.unlimited)
        pending_id = self.reload().pending_razorpay_subscription_id

        with mock.patch(CANCEL) as cancel, self.captureOnCommitCallbacks(execute=True):
            self.select(self.per_bed)

        subscription = self.reload()
        self.assertIsNone(subscription.pending_plan)
        self.assertEqual(subscription.pending_razorpay_subscription_id, '')
        self.assertCountEqual(cancel.call_args_list, [mock.call('sub_basic_live'), mock.call(pending_id)])
        self.assertEqual(self.ledger(pending_id).state, 'cancelled')


class SupersededPendingPaymentTests(PlanChangeTestCase):
    """Razorpay webhooks are asynchronous: a payment can land after the tenant has already
    chosen something else. It must be honoured or flagged, never silently dropped."""

    def test_a_payment_that_lands_after_a_newer_choice_is_honoured(self):
        third = self.create_plan(name='Third Test', price_per_month='399.00')
        self.select(self.unlimited)
        paid_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL, side_effect=RuntimeError('razorpay down')), self.captureOnCommitCallbacks(execute=True):
            self.select(third)  # the first choice is abandoned; its cancel fails
        newest_id = self.reload().pending_razorpay_subscription_id
        self.assertEqual(self.ledger(paid_id).state, 'abandoned')

        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', paid_id, payment_id='pay_late')

        subscription = self.reload()
        self.assertEqual(subscription.plan, self.unlimited)  # they paid for it, so they get it
        self.assertEqual(subscription.razorpay_subscription_id, paid_id)
        self.assertEqual(subscription.pending_razorpay_subscription_id, newest_id)  # newest choice still awaits payment
        self.assertEqual(self.ledger(paid_id).state, 'current')
        self.assertEqual(self.ledger('sub_basic_live').state, 'cancelled')
        with tenant_context(self.tenant.id):
            self.assertTrue(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_late').exists())

    def test_the_newest_choice_can_still_be_paid_after_an_earlier_one_was_honoured(self):
        third = self.create_plan(name='Third Test', price_per_month='399.00')
        self.select(self.unlimited)
        first_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL, side_effect=RuntimeError('down')), self.captureOnCommitCallbacks(execute=True):
            self.select(third)
        newest_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', first_id, payment_id='pay_1')
            self.webhook('subscription.activated', newest_id, payment_id='pay_2')

        subscription = self.reload()
        self.assertEqual(subscription.plan, third)
        self.assertEqual(subscription.razorpay_subscription_id, newest_id)
        self.assertEqual(self.ledger(first_id).state, 'cancelled')  # replaced by the later payment, then cancelled

    def test_a_renewal_that_races_the_cancel_of_a_replaced_subscription_is_recorded_and_flagged_for_refund(self):
        self.select(self.unlimited)
        pending_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL, side_effect=RuntimeError('down')), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id, payment_id='pay_new')
        self.assertEqual(self.ledger('sub_basic_live').state, 'replaced')  # cancel failed, still billing

        self.webhook('subscription.charged', 'sub_basic_live', payment_id='pay_old_renewal')

        self.assertEqual(self.reload().plan, self.unlimited)  # no plan change from it
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        with tenant_context(self.tenant.id):
            self.assertTrue(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_old_renewal').exists())
            flag = AuditLog.objects.get(action='subscription.payment_needs_refund')
        self.assertEqual(flag.after['razorpay_payment_id'], 'pay_old_renewal')

        self.webhook('subscription.charged', 'sub_basic_live', payment_id='pay_old_renewal')  # replay
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_old_renewal').count(), 1)
            self.assertEqual(AuditLog.objects.filter(action='subscription.payment_needs_refund').count(), 1)


class CancellationRetryTests(PlanChangeTestCase):
    def replace_basic_with_unlimited(self):
        self.select(self.unlimited)
        pending_id = self.reload().pending_razorpay_subscription_id
        with mock.patch(CANCEL, side_effect=RuntimeError('down')), self.captureOnCommitCallbacks(execute=True):
            self.webhook('subscription.activated', pending_id)
        return self.ledger('sub_basic_live')

    def test_a_failed_cancel_is_retried_until_it_succeeds(self):
        row = self.replace_basic_with_unlimited()
        self.assertEqual((row.state, row.cancel_attempts), ('replaced', 1))
        self.assertIn('down', row.last_cancel_error)

        with mock.patch(CANCEL, side_effect=RuntimeError('still down')):
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 0, 'failed': 1})
        row = self.ledger('sub_basic_live')
        self.assertEqual((row.state, row.cancel_attempts), ('replaced', 2))

        with mock.patch(CANCEL) as cancel:
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 1, 'failed': 0})
        cancel.assert_called_once_with('sub_basic_live')
        row = self.ledger('sub_basic_live')
        self.assertEqual(row.state, 'cancelled')
        self.assertIsNotNone(row.cancelled_at)

        with mock.patch(CANCEL) as cancel:
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 0, 'failed': 0})
        cancel.assert_not_called()  # a confirmed cancellation is never repeated

    def test_failures_are_audited_on_the_first_attempt_only_not_every_retry(self):
        self.replace_basic_with_unlimited()
        with mock.patch(CANCEL, side_effect=RuntimeError('down')):
            for _ in range(3):
                process_razorpay_cancellations()
        with tenant_context(self.tenant.id):
            self.assertEqual(AuditLog.objects.filter(action='subscription.razorpay_cancel_failed').count(), 1)

    def test_a_cancel_that_errors_because_razorpay_already_finished_it_counts_as_cancelled(self):
        self.replace_basic_with_unlimited()
        with mock.patch(CANCEL, side_effect=RuntimeError('already cancelled')), \
                mock.patch('apps.subscriptions.razorpay_client.fetch_razorpay_subscription_status', return_value='cancelled'):
            self.assertEqual(process_razorpay_cancellations(), {'cancelled': 1, 'failed': 0})
        self.assertEqual(self.ledger('sub_basic_live').state, 'cancelled')

    def test_razorpay_confirming_the_cancellation_by_webhook_closes_the_row(self):
        self.replace_basic_with_unlimited()

        self.webhook('subscription.cancelled', 'sub_basic_live')

        self.assertEqual(self.ledger('sub_basic_live').state, 'cancelled')
        self.assertEqual(self.reload().plan, self.unlimited)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_the_periodic_task_is_scheduled_and_runs_the_retry(self):
        from django_celery_beat.models import PeriodicTask

        from apps.subscriptions.tasks import retry_razorpay_cancellations

        task = PeriodicTask.objects.get(name='subscriptions.retry_razorpay_cancellations')
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, 'apps.subscriptions.tasks.retry_razorpay_cancellations')
        self.replace_basic_with_unlimited()

        with mock.patch(CANCEL):
            self.assertEqual(retry_razorpay_cancellations(), {'cancelled': 1, 'failed': 0})
