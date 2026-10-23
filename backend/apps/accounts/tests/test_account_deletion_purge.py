"""Account deletion (Module 22): the nightly purge — inventory, staff and tenant purges, tenant
isolation, claiming, retry pacing and failure handling."""
import tempfile
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.utils import timezone

from apps.accounts import deletion
from apps.accounts.models import AccountDeletionRequest, Tenant, User
from apps.audit.models import AuditLog
from apps.billing.models import Invoice
from apps.billing.tests.base import BillingAPITestCase
from apps.core.models import ContactMessage, PlatformConfig, TenantModelMixin
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.devices.models import AppInstallation
from apps.notifications.models import NotificationLog
from apps.subscriptions.models import (
    Plan, RazorpaySubscription, RazorpayWebhookEvent, Subscription, SubscriptionInvoice, SubscriptionPayment,
)

Status = AccountDeletionRequest.Status
Scope = AccountDeletionRequest.Scope

PII_PAYLOAD = {
    'event': 'subscription.charged',
    'created_at': 1760000000,
    'payload': {
        'subscription': {'entity': {'id': 'sub_x', 'status': 'active', 'notes': {'email': 'owner@secret.example'}}},
        'payment': {'entity': {'id': 'pay_x', 'amount': 9900, 'email': 'owner@secret.example', 'contact': '+919999999999'}},
    },
}


class PurgeTestCase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def make_due(self, row):
        past = timezone.now() - timedelta(minutes=1)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(scheduled_for=past, next_attempt_at=past)
        return AccountDeletionRequest.objects.get(pk=row.pk)

    def request_for(self, user, scope=None, **extra):
        scope = scope or (Scope.TENANT if user.role == Role.OWNER else Scope.USER)
        now = timezone.now()
        return AccountDeletionRequest.objects.create(
            user=user, tenant=user.tenant, scope=scope, requested_at=now - timedelta(days=8),
            scheduled_for=now - timedelta(minutes=1), next_attempt_at=now - timedelta(minutes=1), **extra,
        )

    def run_to_end(self, row):
        claimed = deletion.claim(row.pk)
        self.assertIsNotNone(claimed)
        return deletion.process(claimed)

    def seed_business(self, tenant, owner, label='A'):
        """A business with data in every PROTECT-linked corner: property -> room -> bed ->
        resident -> admission/allocation, an invoice with a payment, a discount, files, billing."""
        prop = self.create_property(tenant, name=f'PG {label}')
        floor = self.create_floor(prop)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        resident = self.create_resident(prop, phone=f'90000{label.encode()[0]:05d}')
        self.check_in(resident, bed)
        invoice = self.create_invoice(resident, date(2026, 7, 1))
        self.pay(invoice, Decimal('1000.00'))
        self.create_discount(resident)
        for root in deletion.STORAGE_PREFIXES:
            default_storage.save(f'{root}/{tenant.id}/{uuid.uuid4()}/file.txt', ContentFile(b'x'))
        plan = Plan.objects.create(
            name=f'Plan {label}', max_properties=1, max_residents_per_property=10, price_per_month='199.00')
        subscription = Subscription.objects.create(
            tenant=tenant, plan=plan, razorpay_subscription_id=f'sub_{label}')
        RazorpaySubscription.objects.create(
            subscription=subscription, plan=plan, razorpay_subscription_id=f'sub_{label}',
            state=RazorpaySubscription.State.CURRENT)
        with tenant_context(tenant.id):
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription, razorpay_payment_id=f'pay_{label}',
                amount=Decimal('199.00'), status='success', raw_payload=PII_PAYLOAD)
            sub_invoice = SubscriptionInvoice.objects.create(
                tenant_id=tenant.id, subscription=subscription, period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30), total_amount=Decimal('50.00'), billed_bed_count_start=1,
                billed_bed_count_end=1, razorpay_invoice_id=f'inv_{label}')
        return {'prop': prop, 'resident': resident, 'subscription': subscription, 'sub_invoice': sub_invoice}

    def tenant_rows(self, tenant_id, labels):
        out = {}
        with tenant_context(tenant_id, is_super_admin=True):
            for label in labels:
                out[label] = django_apps.get_model(label).objects.filter(tenant_id=tenant_id).count()
        return out


class InventoryTests(PurgeTestCase):
    def test_every_model_has_a_disposition(self):
        ours = {
            m._meta.label for m in django_apps.get_models()
            if m.__module__.startswith('apps.') and not m._meta.abstract
        }
        missing = ours - set(deletion.DISPOSITION)
        self.assertFalse(missing, f'Say what an account deletion does with: {sorted(missing)}')
        self.assertFalse(set(deletion.DISPOSITION) - ours, 'DISPOSITION names a model that no longer exists')

    def test_purge_order_is_exactly_the_tenant_models_marked_purge(self):
        expected = {
            label for label, (tenant_side, _) in deletion.DISPOSITION.items()
            if tenant_side == deletion.PURGE and issubclass(django_apps.get_model(label), TenantModelMixin)
        }
        self.assertEqual(set(deletion.PURGE_ORDER), expected)
        self.assertEqual(len(deletion.PURGE_ORDER), len(set(deletion.PURGE_ORDER)))

    def test_every_tenant_scoped_model_is_either_purged_redacted_or_retained(self):
        for model in django_apps.get_models():
            if issubclass(model, TenantModelMixin) and not model._meta.abstract:
                tenant_side = deletion.DISPOSITION[model._meta.label][0]
                self.assertIn(tenant_side, (deletion.PURGE, deletion.REDACT, deletion.RETAIN), model._meta.label)


class StaffPurgeTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.staff = self.create_user(self.tenant, Role.MANAGER, 'staff@example.com')
        self.other = self.create_user(self.tenant, Role.RECEPTIONIST, 'other@example.com')

    def test_staff_purge_removes_the_login_and_personal_records_only(self):
        seeded = self.seed_business(self.tenant, self.owner)
        install = AppInstallation.objects.create(
            user=self.staff, platform='android', flavor='prod', build_number=1, fcm_token='tok-staff')
        ContactMessage.objects.create(name='S', email='STAFF@example.com', message='hi')
        with tenant_context(self.tenant.id):
            NotificationLog.objects.create(
                tenant_id=self.tenant.id, notification_type='welcome', recipient_email='staff@example.com',
                recipient_user=self.staff, status='sent')
            invoice = Invoice.objects.get(resident=seeded['resident'])
            Invoice.objects.filter(pk=invoice.pk).update(created_by=self.staff)
            # actor IP, an event about the staff member by value, and an unrelated event
            AuditLog.objects.create(tenant_id=self.tenant.id, actor=self.staff, action='x.did', ip_address='10.0.0.9')
            AuditLog.objects.create(
                tenant_id=self.tenant.id, actor=self.owner, action='property_staff_assignment.created',
                object_type='PropertyStaffAssignment', after={'staff': 'staff@example.com', 'property': 'PG A'})
            AuditLog.objects.create(
                tenant_id=self.tenant.id, actor=self.owner, action='x.other', after={'staff': 'other@example.com'})
        row = self.request_for(self.staff)

        self.assertEqual(self.run_to_end(row), 'completed')

        self.assertFalse(User.objects.filter(pk=self.staff.pk).exists())
        self.assertFalse(AppInstallation.objects.filter(pk=install.pk).exists())
        self.assertFalse(ContactMessage.objects.filter(email__iexact='staff@example.com').exists())
        with tenant_context(self.tenant.id):
            self.assertFalse(NotificationLog.objects.filter(recipient_email='staff@example.com').exists())
            # The business's records stay, with the creator reference nulled.
            self.assertIsNone(Invoice.objects.get(pk=invoice.pk).created_by_id)
            self.assertIsNone(AuditLog.objects.get(action='x.did').ip_address)
            assigned = AuditLog.objects.get(action='property_staff_assignment.created')
            self.assertEqual(assigned.after, {'redacted': True})
            self.assertEqual(AuditLog.objects.get(action='x.other').after, {'staff': 'other@example.com'})
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
        self.assertEqual(self.tenant_rows(self.tenant.id, ['residents.Resident'])['residents.Resident'], 1)
        row.refresh_from_db()
        self.assertEqual((row.status, row.last_error, row.reason), (Status.COMPLETED, '', ''))
        self.assertIsNotNone(row.completed_at)
        self.assertEqual(Tenant.objects.get(pk=self.tenant.pk).status, self.tenant.status)  # tenant untouched
        with tenant_context(is_super_admin=True):
            self.assertTrue(AuditLog.objects.filter(tenant_id=None, action='account.deleted').exists())

    def test_staff_purge_is_idempotent_when_the_user_is_already_gone(self):
        row = self.request_for(self.staff)
        User.objects.filter(pk=self.staff.pk).delete()
        row.refresh_from_db()
        self.assertEqual(self.run_to_end(row), 'completed')


class TenantPurgeTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.staff = self.create_user(self.tenant, Role.MANAGER, 'staff@example.com')
        self.other_tenant = self.create_tenant('Other PG')
        self.other_owner = self.create_owner(self.other_tenant, email='o2@example.com')

    def webhook_event(self, event_id, payload, **kwargs):
        return RazorpayWebhookEvent.objects.create(
            event_id=event_id, event_type=payload.get('event', 'x')[:60], payload=payload, **kwargs)

    def test_tenant_purge_end_to_end(self):
        a = self.seed_business(self.tenant, self.owner, 'A')
        b = self.seed_business(self.other_tenant, self.other_owner, 'B')
        # webhook events: by tenant, by subscription id, legacy invoice (tenant NULL) by id and by receipt, other tenant's
        self.webhook_event('e1', PII_PAYLOAD, tenant_id=self.tenant.id, razorpay_subscription_id='sub_A')
        invoice_by_id = {'event': 'invoice.paid', 'payload': {'invoice': {'entity': {
            'id': 'inv_A', 'receipt': 'zzz', 'customer_details': {'email': 'owner@secret.example'}}}}}
        invoice_by_receipt = {'event': 'invoice.paid', 'payload': {'invoice': {'entity': {
            'id': 'inv_unbound', 'receipt': str(a['sub_invoice'].pk), 'customer_details': {'email': 'o@secret'}}}}}
        other_invoice = {'event': 'invoice.paid', 'payload': {'invoice': {'entity': {
            'id': 'inv_B', 'customer_details': {'email': 'b@secret.example'}}}}}
        self.webhook_event('e2', invoice_by_id)
        self.webhook_event('e3', invoice_by_receipt)
        self.webhook_event('e4', other_invoice)
        row = self.request_for(self.owner)
        before = self.tenant_rows(self.other_tenant.id, [l for l in deletion.PURGE_ORDER])

        with mock.patch('apps.subscriptions.razorpay_client.cancel_razorpay_subscription'):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.run_to_end(row), 'completed')

        # Everything the inventory says is purged is gone — and only for this tenant.
        for label, count in self.tenant_rows(self.tenant.id, deletion.PURGE_ORDER).items():
            self.assertEqual(count, 0, label)
        self.assertEqual(self.tenant_rows(self.other_tenant.id, deletion.PURGE_ORDER), before)
        self.assertGreater(sum(before.values()), 0)
        self.assertFalse(User.objects.filter(tenant=self.tenant).exists())
        self.assertTrue(User.objects.filter(pk=self.other_owner.pk).exists())
        with tenant_context(self.tenant.id):
            self.assertFalse(AuditLog.objects.filter(tenant_id=self.tenant.id).exists())
        # Files: this tenant's prefixes are empty, the other's are intact.
        for root in deletion.STORAGE_PREFIXES:
            self.assertEqual(list(deletion._iter_storage_files(f'{root}/{self.tenant.id}')), [], root)
            self.assertEqual(len(list(deletion._iter_storage_files(f'{root}/{self.other_tenant.id}'))), 1, root)
        # Billing is retained; its payloads are redacted.
        tenant = Tenant.objects.get(pk=self.tenant.pk)
        self.assertEqual((tenant.name, tenant.status), ('Sunrise PG', Tenant.Status.DELETED))
        subscription = Subscription.objects.get(tenant=self.tenant)
        self.assertEqual(subscription.status_hold, Subscription.STATUS_HOLD_DELETED)
        self.assertIsNone(subscription.plan)
        with tenant_context(self.tenant.id):
            self.assertEqual(SubscriptionPayment.objects.get().raw_payload, {})
            self.assertEqual(SubscriptionInvoice.objects.count(), 1)
        for event_id in ('e1', 'e2', 'e3'):
            event = RazorpayWebhookEvent.objects.get(event_id=event_id)
            self.assertTrue(event.payload.get('redacted'), event_id)
            self.assertNotIn('secret', str(event.payload), event_id)
            self.assertEqual(event.tenant_id, self.tenant.id, event_id)  # back-filled
        other_event = RazorpayWebhookEvent.objects.get(event_id='e4')
        self.assertIn('b@secret.example', str(other_event.payload))  # another tenant's: untouched
        with tenant_context(self.other_tenant.id):
            self.assertIn('owner@secret.example', str(SubscriptionPayment.objects.get().raw_payload))
        self.assertEqual(Subscription.objects.get(tenant=self.other_tenant).status_hold, '')
        row.refresh_from_db()
        self.assertEqual(row.status, Status.COMPLETED)
        self.assertTrue(all([row.notified_at, row.razorpay_closed_at, row.db_purged_at, row.files_purged_at]))

    def test_tenant_status_becomes_deleted_only_at_the_end(self):
        row = self.request_for(self.owner)
        statuses = []
        original = deletion._phase_files_purge

        def spy(current, token):
            statuses.append(Tenant.objects.get(pk=self.tenant.pk).status)
            return original(current, token)

        with mock.patch.object(deletion, 'TENANT_PHASES', [
            (n, f, spy if n == 'files_purge' else fn) for n, f, fn in deletion.TENANT_PHASES
        ]):
            self.run_to_end(row)
        self.assertNotEqual(statuses[0], Tenant.Status.DELETED)  # logins already gone, status not yet set
        self.assertEqual(Tenant.objects.get(pk=self.tenant.pk).status, Tenant.Status.DELETED)

    def test_pending_staff_requests_are_superseded_and_their_reason_scrubbed(self):
        staff_request = self.request_for(self.staff, reason='leaving')
        row = self.request_for(self.owner)
        self.run_to_end(row)
        staff_request.refresh_from_db()
        self.assertEqual((staff_request.status, staff_request.reason), (Status.SUPERSEDED, ''))

    def test_a_processing_staff_request_and_the_tenant_purge_both_finish(self):
        staff_request = self.request_for(self.staff)
        deletion.claim(staff_request.pk)  # a worker is mid-way through the staff purge
        row = self.request_for(self.owner)
        self.assertEqual(self.run_to_end(row), 'completed')
        staff_request.refresh_from_db()
        self.assertEqual(staff_request.status, Status.PROCESSING)
        # Its own run later finds the user already gone and still completes.
        AccountDeletionRequest.objects.filter(pk=staff_request.pk).update(
            claimed_at=timezone.now() - deletion.LEASE_TIMEOUT - timedelta(minutes=1))
        self.assertEqual(deletion.run_due_requests().get('completed'), 1)

    def test_phase_failures_are_resumable_and_login_state_follows_the_phase(self):
        row = self.request_for(self.owner)
        # Fail files_purge: the database purge already happened and stays stamped.
        with mock.patch.object(deletion, 'purge_tenant_files', side_effect=OSError('gcs down')):
            self.assertEqual(self.run_to_end(row), 'retry')
        row.refresh_from_db()
        self.assertEqual(row.status, Status.PENDING)
        self.assertIsNotNone(row.db_purged_at)
        self.assertIsNone(row.files_purged_at)
        self.assertEqual(row.last_error, 'files_purge: OSError')
        self.assertGreater(row.next_attempt_at, timezone.now())
        self.assertNotEqual(Tenant.objects.get(pk=self.tenant.pk).status, Tenant.Status.DELETED)
        # The rerun deletes files only.
        AccountDeletionRequest.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
        with mock.patch.object(deletion, 'purge_tenant_rows') as rows_purge:
            self.assertEqual(self.run_to_end(row), 'completed')
        rows_purge.assert_not_called()


class SchedulingTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.staff = self.create_user(self.tenant, Role.MANAGER, 'staff@example.com')

    def test_nothing_is_claimable_before_it_is_due(self):
        row = self.request_for(self.staff)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now() + timedelta(days=1))
        self.assertIsNone(deletion.claim(row.pk))
        self.assertEqual(deletion.run_due_requests(), {})

    def test_a_request_can_only_be_claimed_once(self):
        row = self.request_for(self.staff)
        first = deletion.claim(row.pk)
        self.assertIsNotNone(first)
        self.assertIsNone(deletion.claim(row.pk))  # leased: a second worker gets nothing

    def test_an_expired_lease_is_reclaimed_whatever_next_attempt_says(self):
        row = self.request_for(self.staff)
        first = deletion.claim(row.pk)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(
            claimed_at=timezone.now() - deletion.LEASE_TIMEOUT - timedelta(minutes=1),
            next_attempt_at=timezone.now() + timedelta(days=3))
        second = deletion.claim(row.pk)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.claim_token, second.claim_token)
        # The first worker's token is dead: it can no longer stamp or complete anything.
        self.assertEqual(deletion.process(first), 'lease_lost')

    def test_a_failing_request_is_attempted_once_per_run_and_then_waits_for_midnight(self):
        row = self.request_for(self.staff)
        with mock.patch.object(deletion, 'purge_user_rows', side_effect=RuntimeError('boom')) as purge:
            first_run = deletion.run_due_requests()
        self.assertEqual(first_run, {'retry': 1})
        self.assertEqual(purge.call_count, 1)  # not retried in a tight loop
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts), (Status.PENDING, 1))
        self.assertEqual(row.next_attempt_at, deletion.next_midnight_ist())
        self.assertIsNone(deletion.claim(row.pk))  # not claimable until then

    def test_five_failures_across_five_runs_park_the_request_as_failed(self):
        row = self.request_for(self.staff)
        self.assertEqual(PlatformConfig.get().account_deletion_max_attempts, 5)
        with mock.patch.object(deletion, 'purge_user_rows', side_effect=RuntimeError('boom')):
            for night in range(5):
                AccountDeletionRequest.objects.filter(pk=row.pk, status=Status.PENDING).update(
                    next_attempt_at=timezone.now() - timedelta(minutes=1))
                outcome = deletion.run_due_requests()
                self.assertEqual(outcome, {'failed': 1} if night == 4 else {'retry': 1}, night)
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts, row.reason), (Status.FAILED, 5, ''))
        self.assertEqual(deletion.run_due_requests(), {})  # parked: not picked up again

    def test_reaching_failed_alerts_super_admins(self):
        from django.core import mail

        self.create_super_admin()
        row = self.request_for(self.staff)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(attempts=4)
        with mock.patch.object(deletion, 'purge_user_rows', side_effect=RuntimeError('boom')), \
                self.assertLogs('apps.accounts.deletion', level='ERROR') as logs, \
                self.captureOnCommitCallbacks(execute=True):
            deletion.run_due_requests()
        self.assertTrue(any('account_deletion_failed' in line for line in logs.output))
        self.assertIn('Account deletion needs attention', [m.subject for m in mail.outbox])

    def test_retry_now_resets_and_runs_through_the_same_claim(self):
        row = self.request_for(self.staff)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(status=Status.FAILED, attempts=5)
        row.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            deletion.retry_now(row, actor=self.create_super_admin())
        row.refresh_from_db()
        self.assertEqual(row.status, Status.COMPLETED)
        self.assertFalse(User.objects.filter(pk=self.staff.pk).exists())

    def test_two_scheduler_runs_on_the_same_snapshot_purge_once(self):
        row = self.request_for(self.staff)
        snapshot = deletion.due_request_ids()
        results = []
        for _ in range(2):
            for pk in snapshot:
                claimed = deletion.claim(pk)
                if claimed is not None:
                    results.append(deletion.process(claimed))
        self.assertEqual(results, ['completed'])
        row.refresh_from_db()
        self.assertEqual(row.attempts, 0)


class NotifyPhaseTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.staff = self.create_user(self.tenant, Role.MANAGER, 'staff@example.com')

    def test_a_broker_outage_blocks_the_purge_before_anything_is_deleted(self):
        row = self.request_for(self.staff)
        with mock.patch('apps.accounts.tasks.send_account_deletion_begun_task.delay',
                        side_effect=ConnectionError('redis down')):
            self.assertEqual(self.run_to_end(row), 'retry')
        row.refresh_from_db()
        self.assertIsNone(row.notified_at)
        self.assertIsNone(row.db_purged_at)
        self.assertTrue(User.objects.filter(pk=self.staff.pk).exists())

    def test_the_notice_goes_out_before_the_account_is_deleted(self):
        from django.core import mail

        row = self.request_for(self.staff)
        mail.outbox.clear()
        self.run_to_end(row)
        self.assertIn('Your account deletion has started', [m.subject for m in mail.outbox])
        self.assertEqual(mail.outbox[-1].to, ['staff@example.com'])
        row.refresh_from_db()
        self.assertEqual(row.notice_channel, 'email')
        self.assertLessEqual(row.notified_at, row.db_purged_at)

    def test_a_rerun_after_a_later_failure_does_not_resend(self):
        from django.core import mail

        row = self.request_for(self.owner)
        mail.outbox.clear()
        with mock.patch.object(deletion, 'purge_tenant_files', side_effect=OSError('down')):
            self.run_to_end(row)
        sent = len(mail.outbox)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
        self.run_to_end(row)
        self.assertEqual(len(mail.outbox), sent)

    def test_phone_only_staff_get_no_notice_but_the_purge_proceeds(self):
        phone_only = User.objects.create_user(
            tenant=self.tenant, role=Role.RECEPTIONIST, phone='9822222222', first_name='P', password='x-Y9zzzzzz')
        row = self.request_for(phone_only)
        self.assertEqual(self.run_to_end(row), 'completed')
        row.refresh_from_db()
        self.assertEqual(row.notice_channel, 'none')
        self.assertIsNotNone(row.notified_at)

    def test_the_request_row_never_holds_an_address(self):
        row = self.request_for(self.staff)
        self.run_to_end(row)
        row.refresh_from_db()
        self.assertNotIn('staff@example.com', str([getattr(row, f.name) for f in row._meta.fields]))


class RetryGuardTests(PurgeTestCase):
    def test_retry_now_cannot_skip_the_grace_period(self):
        tenant = self.create_tenant()
        staff = self.create_user(tenant, Role.MANAGER, 'staff@example.com')
        waiting = AccountDeletionRequest.objects.create(
            user=staff, tenant=tenant, scope=Scope.USER, requested_at=timezone.now(),
            scheduled_for=timezone.now() + timedelta(days=5), next_attempt_at=timezone.now() + timedelta(days=5))
        with self.assertRaises(Exception):
            deletion.retry_now(waiting, actor=self.create_super_admin())
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Status.PENDING)
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())
