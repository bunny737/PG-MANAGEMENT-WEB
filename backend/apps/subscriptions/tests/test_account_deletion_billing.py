"""Account deletion (Module 22), the billing side: a deleted tenant's subscription is a tombstone.
Late Razorpay events are recorded (sanitized) and charges flagged for refund, but nothing can promote
a subscription, restore a plan or change the tenant; the `deleted` hold cannot be cleared by any
Super Admin path; and the refund obligation is a structured field that survives the purge."""
import importlib
from datetime import date
from decimal import Decimal
from unittest import mock

from django.apps import apps as django_apps
from django.contrib import admin as django_admin
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.admin import TenantAdmin
from apps.accounts.models import Tenant
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions import services
from apps.subscriptions.models import (
    RazorpaySubscription, RazorpayWebhookEvent, Subscription, SubscriptionInvoice, SubscriptionPayment,
)

from .test_plan_change import CANCEL, PlanChangeTestCase
from .test_plan_exit_invoicing import CREATE_INVOICE, PlanExitInvoicingTestCase

State = RazorpaySubscription.State
Refund = SubscriptionPayment.RefundStatus

SECRET = 'owner@secret.example'


def leaky(event, subscription_id, payment_id='pay_late'):
    """A webhook body carrying the customer's contact details, like Razorpay's real ones."""
    return {
        'event': event,
        'created_at': 1_760_000_000,
        'payload': {
            'subscription': {'entity': {'id': subscription_id, 'notes': {'email': SECRET}}},
            'payment': {'entity': {'id': payment_id, 'amount': 24900, 'email': SECRET, 'contact': '+919999999999'}},
        },
    }


class DeletedTenantCase(PlanChangeTestCase):
    """A tenant with a live Basic subscription and an unpaid Unlimited choice (a PENDING ledger
    row), then billing closed for deletion — with Razorpay cancellations failing, so the
    REPLACED/ABANDONED rows are still queued, as they would be during an outage."""

    def setUp(self):
        super().setUp()
        with mock.patch(CANCEL):
            self.select(self.unlimited)
        self.pending_id = self.reload().pending_razorpay_subscription_id
        self.live_id = 'sub_basic_live'
        self.close_billing()

    def close_billing(self, cancel_fails=True):
        side_effect = RuntimeError('razorpay down') if cancel_fails else None
        with mock.patch(CANCEL, side_effect=side_effect), self.captureOnCommitCallbacks(execute=True):
            services.close_billing_for_deletion(self.tenant)

    def post_event(self, body, event_id):
        response = self.client.post(
            reverse('razorpay-webhook'), body, format='json', HTTP_X_RAZORPAY_EVENT_ID=event_id)
        self.assertEqual(response.status_code, 200, getattr(response, 'data', None))
        return response

    def assert_still_a_tombstone(self):
        subscription = self.reload()
        self.assertIsNone(subscription.plan)
        self.assertEqual(subscription.status_hold, Subscription.STATUS_HOLD_DELETED)
        self.assertFalse(RazorpaySubscription.objects.filter(subscription=subscription, state=State.CURRENT).exists())
        return subscription


class CloseBillingTests(DeletedTenantCase):
    def test_close_clears_the_plan_sets_the_hold_and_queues_both_rows_for_cancellation(self):
        subscription = self.assert_still_a_tombstone()
        self.assertIsNone(subscription.pending_plan)
        self.assertEqual(self.ledger(self.live_id).state, State.REPLACED)
        self.assertEqual(self.ledger(self.pending_id).state, State.ABANDONED)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)  # the purge sets DELETED only at the end

    def test_close_is_idempotent(self):
        before = self.reload().updated_at
        self.close_billing()
        self.assertEqual(self.reload().updated_at, before)

    def test_the_existing_cancellation_queue_finishes_the_job(self):
        with mock.patch(CANCEL) as cancel:
            outcome = services.process_razorpay_cancellations(subscription_id=self.subscription.pk)
        self.assertEqual(outcome, {'cancelled': 2, 'failed': 0})
        self.assertEqual({c.args[0] for c in cancel.call_args_list}, {self.live_id, self.pending_id})


class LateWebhookTests(DeletedTenantCase):
    def test_a_late_charge_on_the_old_pending_subscription_is_refunded_not_promoted(self):
        self.post_event(leaky('subscription.charged', self.pending_id, 'pay_pending'), 'evt_1')

        self.assert_still_a_tombstone()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        self.assertEqual(self.ledger(self.pending_id).state, State.ABANDONED)  # still queued for cancellation
        self.assertEqual(services.process_razorpay_cancellations.__name__, 'process_razorpay_cancellations')
        with tenant_context(self.tenant.id):
            payment = SubscriptionPayment.objects.get(razorpay_payment_id='pay_pending')
        self.assertEqual(payment.refund_status, Refund.PENDING)
        self.assertIsNotNone(payment.refund_flagged_at)
        self.assertNotIn(SECRET, str(payment.raw_payload))
        self.assertTrue(payment.raw_payload['redacted'])
        event = RazorpayWebhookEvent.objects.get(event_id='evt_1')
        self.assertNotIn(SECRET, str(event.payload))
        self.assertNotIn('+919999999999', str(event.payload))
        self.assertEqual(event.tenant_id, self.tenant.id)

    def test_a_late_charge_on_the_formerly_live_subscription_is_refunded_too(self):
        self.post_event(leaky('subscription.charged', self.live_id, 'pay_live'), 'evt_2')
        self.assert_still_a_tombstone()
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.get().refund_status, Refund.PENDING)
        self.assertEqual(self.ledger(self.live_id).state, State.REPLACED)

    def test_activation_replays_and_out_of_order_events_all_leave_the_tombstone_alone(self):
        for n, event in enumerate(['subscription.activated', 'subscription.charged', 'subscription.resumed',
                                   'subscription.halted']):
            self.post_event(leaky(event, self.pending_id, f'pay_{n}'), f'evt_x{n}')
        self.assert_still_a_tombstone()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_the_same_payment_is_not_recorded_twice(self):
        self.post_event(leaky('subscription.charged', self.pending_id, 'pay_dup'), 'evt_a')
        self.post_event(leaky('subscription.charged', self.pending_id, 'pay_dup'), 'evt_b')
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.filter(razorpay_payment_id='pay_dup').count(), 1)

    def test_payment_failed_stores_only_a_sanitized_event_and_no_payment_row(self):
        self.post_event(leaky('payment.failed', self.pending_id, 'pay_fail'), 'evt_f')
        with tenant_context(self.tenant.id):
            self.assertFalse(SubscriptionPayment.objects.exists())
        event = RazorpayWebhookEvent.objects.get(event_id='evt_f')
        self.assertNotIn(SECRET, str(event.payload))
        self.assertEqual(event.outcome, RazorpayWebhookEvent.Outcome.TERMINAL_IGNORED)

    def test_a_late_cancelled_event_closes_the_ledger_row(self):
        self.post_event(leaky('subscription.cancelled', self.pending_id), 'evt_c')
        self.assertEqual(self.ledger(self.pending_id).state, State.CANCELLED)
        self.assert_still_a_tombstone()

    def test_invoice_events_are_stored_with_the_tenant_and_sanitized(self):
        with tenant_context(self.tenant.id):
            invoice = SubscriptionInvoice.objects.create(
                tenant_id=self.tenant.id, subscription=self.subscription, period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30), total_amount=Decimal('50.00'), billed_bed_count_start=1,
                billed_bed_count_end=1, razorpay_invoice_id='inv_late', status=SubscriptionInvoice.Status.ISSUED)
        body = {
            'event': 'invoice.paid',
            'payload': {
                'invoice': {'entity': {'id': 'inv_late', 'receipt': str(invoice.pk), 'customer_details': {'email': SECRET}}},
                'payment': {'entity': {'id': 'pay_inv', 'email': SECRET}},
            },
        }
        self.post_event(body, 'evt_inv')
        event = RazorpayWebhookEvent.objects.get(event_id='evt_inv')
        self.assertEqual(event.tenant_id, self.tenant.id)  # invoice events used to be stored without one
        self.assertNotIn(SECRET, str(event.payload))
        with tenant_context(self.tenant.id):
            invoice.refresh_from_db()
            self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)  # a real arrears invoice IS payable
            payment = SubscriptionPayment.objects.get(razorpay_payment_id='pay_inv')
        self.assertNotIn(SECRET, str(payment.raw_payload))
        self.assertEqual(payment.refund_status, Refund.NONE)  # ours to keep: not a refund case
        self.assertEqual(self.reload().status_hold, Subscription.STATUS_HOLD_DELETED)
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_the_sanitizer_is_a_strict_scalar_allow_list(self):
        sanitized = services.sanitized_payload(leaky('subscription.charged', 'sub_1'))
        self.assertEqual(sanitized['subscription_id'], 'sub_1')
        self.assertEqual(sanitized['payment_id'], 'pay_late')
        self.assertEqual(sanitized['amount'], 24900)
        self.assertTrue(all(not isinstance(v, (dict, list)) for v in sanitized.values()))
        self.assertNotIn('email', str(sanitized))
        self.assertEqual(services.sanitized_payload('not a dict'), {'redacted': True})


class ImmutableHoldTests(DeletedTenantCase):
    def assert_hold_survives(self):
        self.assertEqual(Subscription.objects.get(pk=self.subscription.pk).status_hold, Subscription.STATUS_HOLD_DELETED)

    def test_services_refuse_to_touch_a_deleted_subscription(self):
        admin_user = self.create_super_admin()
        for call in (
            lambda: services.suspend_tenant(tenant=self.tenant, actor=admin_user),
            lambda: services.reactivate_tenant(tenant=self.tenant, actor=admin_user),
            lambda: services.set_manual_status_hold(self.tenant, True),
            lambda: services.set_manual_status_hold(self.tenant, False),
            lambda: services.override_limits(
                subscription=self.subscription, max_properties_override=9, max_residents_override=9,
                max_beds_override=9, actor=admin_user),
        ):
            with self.assertRaises(services.TenantDeleted):
                call()
            self.assert_hold_survives()
        self.assertEqual(Tenant.objects.get(pk=self.tenant.pk).status, Tenant.Status.ACTIVE)

    def test_the_owner_cannot_pick_a_plan(self):
        response = self.select(self.unlimited)
        self.assertEqual(response.status_code, 409, getattr(response, 'data', None))
        self.assertEqual(response.data['code'], 'TENANT_DELETED')
        self.assert_hold_survives()

    def test_super_admin_api_actions_are_refused(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        self.authenticate(self.create_super_admin())
        for action in ('suspend', 'reactivate'):
            response = self.client.post(reverse(f'subscription-{action}', args=[self.tenant.id]))
            self.assertIn(response.status_code, (400, 409), (action, response.status_code))
            self.assert_hold_survives()

    def test_a_tenant_admin_status_edit_is_refused(self):
        form = mock.Mock(changed_data=['status'])
        tenant = Tenant.objects.get(pk=self.tenant.pk)
        tenant.status = Tenant.Status.ACTIVE
        request = RequestFactory().post('/admin/')
        request.user = self.create_super_admin()
        with mock.patch('apps.accounts.admin.messages.error') as error:
            TenantAdmin(Tenant, django_admin.site).save_model(request, tenant, form, True)
        error.assert_called_once()
        self.assert_hold_survives()

    def test_reactivation_racing_the_close_always_ends_deleted(self):
        admin_user = self.create_super_admin()
        # Reactivate first (allowed: nothing closed yet), then close: the hold wins.
        other = self.create_tenant('Racer', status=Tenant.Status.SUSPENDED)
        subscription = self.create_subscription(other, plan=self.basic, razorpay_subscription_id='sub_race')
        services.reactivate_tenant(tenant=other, actor=admin_user)
        with mock.patch(CANCEL):
            services.close_billing_for_deletion(other)
        with self.assertRaises(services.TenantDeleted):
            services.reactivate_tenant(tenant=other, actor=admin_user)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status_hold, Subscription.STATUS_HOLD_DELETED)

    def test_the_grace_period_sweep_skips_a_deleted_subscription(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.PAYMENT_FAILED)
        Subscription.objects.filter(pk=self.subscription.pk).update(
            payment_failed_at=timezone.now() - timezone.timedelta(days=30))
        self.assertEqual(services.process_payment_grace_periods(), [])


class RefundFieldTests(PlanChangeTestCase):
    def payment(self, **kwargs):
        with tenant_context(self.tenant.id):
            with transaction.atomic():  # inside the tenant context, so a rejected row rolls back before it restores
                return SubscriptionPayment.objects.create(
                    tenant_id=self.tenant.id, subscription=self.subscription, amount=Decimal('10.00'),
                    status='success', **kwargs)

    def test_valid_states_are_accepted(self):
        now = timezone.now()
        self.payment()
        self.payment(refund_status=Refund.PENDING, refund_flagged_at=now)
        self.payment(refund_status=Refund.REFUNDED, refund_flagged_at=now, refund_resolved_at=now,
                     refund_reference='rfnd_abc123', refund_resolution='refunded_via_razorpay')
        self.payment(refund_status=Refund.WAIVED, refund_flagged_at=now, refund_resolved_at=now,
                     refund_resolution='waived_duplicate')

    def test_the_database_rejects_every_inconsistent_combination(self):
        now = timezone.now()
        bad = [
            dict(refund_status=Refund.REFUNDED, refund_flagged_at=now, refund_resolved_at=now,
                 refund_resolution='refunded_via_razorpay'),                       # refunded without a reference
            dict(refund_status=Refund.WAIVED, refund_flagged_at=now, refund_resolution='waived_other'),  # no resolved_at
            dict(refund_status=Refund.WAIVED, refund_flagged_at=now, refund_resolved_at=now,
                 refund_reference='rfnd_x', refund_resolution='waived_other'),     # waived with a reference
            dict(refund_status=Refund.NONE, refund_resolution='waived_other'),     # none with a code
            dict(refund_status=Refund.PENDING),                                    # pending without a flag time
            dict(refund_status=Refund.PENDING, refund_flagged_at=now, refund_resolved_at=now),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(IntegrityError):
                self.payment(**kwargs)

    def test_admin_form_validation_is_friendly(self):
        from django.core.exceptions import ValidationError

        payment = self.payment(refund_status=Refund.PENDING, refund_flagged_at=timezone.now())
        payment.refund_status = Refund.REFUNDED
        with self.assertRaises(ValidationError):
            payment.clean()  # no refund id
        payment.refund_reference = 'rfnd_ok1'
        payment.clean()
        self.assertEqual(payment.refund_resolution, 'refunded_via_razorpay')
        payment.refund_status = Refund.WAIVED
        payment.refund_resolution = 'refunded_via_razorpay'
        with self.assertRaises(ValidationError):
            payment.clean()  # a waiver needs a waived_* reason

    def test_the_refund_flag_survives_the_audit_row_being_deleted(self):
        # An existing (pre-deletion) refund flag: the obligation is on the retained payment row.
        with mock.patch(CANCEL):
            self.select(self.unlimited)
        pending_id = self.reload().pending_razorpay_subscription_id
        # A worker is mid-cancel on it (CANCELLING): a charge landing now is never honoured.
        RazorpaySubscription.objects.filter(razorpay_subscription_id=pending_id).update(
            state=State.CANCELLING, cancel_from=State.ABANDONED)
        self.client.post(reverse('razorpay-webhook'), leaky('subscription.activated', pending_id, 'pay_flag'),
                         format='json', HTTP_X_RAZORPAY_EVENT_ID='evt_flag')
        with tenant_context(self.tenant.id):
            AuditLog.objects.filter(action='subscription.payment_needs_refund').delete()
            self.assertEqual(
                SubscriptionPayment.objects.get(razorpay_payment_id='pay_flag').refund_status, Refund.PENDING)


class BackfillMigrationTests(PlanChangeTestCase):
    def test_legacy_audit_flags_become_pending_refunds(self):
        migration = importlib.import_module('apps.subscriptions.migrations.0015_payment_refund_obligation')
        with tenant_context(self.tenant.id):
            flagged = SubscriptionPayment.objects.create(
                tenant_id=self.tenant.id, subscription=self.subscription, razorpay_payment_id='pay_old',
                amount=Decimal('5.00'), status='success')
            unflagged = SubscriptionPayment.objects.create(
                tenant_id=self.tenant.id, subscription=self.subscription, razorpay_payment_id='pay_ok',
                amount=Decimal('5.00'), status='success')
            entry = AuditLog.objects.create(
                tenant_id=self.tenant.id, action='subscription.payment_needs_refund',
                after={'razorpay_payment_id': 'pay_old'})
        migration.backfill_pending_refunds(django_apps, None)
        with tenant_context(self.tenant.id):
            flagged.refresh_from_db()
            unflagged.refresh_from_db()
        self.assertEqual((flagged.refund_status, flagged.refund_flagged_at), (Refund.PENDING, entry.created_at))
        self.assertEqual(unflagged.refund_status, Refund.NONE)


class ExitInvoiceSurvivesDeletionTests(PlanExitInvoicingTestCase):
    def test_a_failed_first_issue_is_still_sent_by_the_sweep_after_the_tenant_is_deleted(self):
        with mock.patch(CREATE_INVOICE, side_effect=RuntimeError('razorpay down')), mock.patch(CANCEL), \
                self.captureOnCommitCallbacks(execute=True):
            services.close_billing_for_deletion(self.tenant)
        (invoice,) = self.invoices()
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.DRAFT)
        self.assertEqual(invoice.razorpay_invoice_id, '')
        # The deletion completes: tenant DELETED, plan gone, hold set.
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.DELETED)
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.plan)
        self.assertEqual(self.subscription.status_hold, Subscription.STATUS_HOLD_DELETED)

        outcome = services.process_invoice_issuing()  # the periodic sweep keeps issuing existing drafts

        self.assertEqual(outcome, {'issued': 1, 'failed': 0})
        (invoice,) = self.invoices()
        self.assertNotEqual(invoice.razorpay_invoice_id, '')
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        # ...while nothing new is generated for a tenant without a plan.
        self.assertIsNone(services.generate_invoice_for_subscription(self.subscription))
