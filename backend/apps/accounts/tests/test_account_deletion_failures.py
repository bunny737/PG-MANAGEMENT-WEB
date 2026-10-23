"""Account deletion (Module 22): failures in each phase, the lease heartbeat, and the admin actions."""
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib import admin as django_admin
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import deletion
from apps.accounts.admin import AccountDeletionRequestAdmin, UserAdmin, create_deletion_request_on_behalf
from apps.accounts.models import AccountDeletionRequest, Tenant, User
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import Plan, Subscription

from .base import STRONG_PASSWORD
from .test_account_deletion_purge import PurgeTestCase, Scope, Status


class FailureAfterEachPhaseTests(PurgeTestCase):
    """Whatever phase gives up, the account stays locked and reachable (login, /auth/me/) until it
    completes, and what an admin may do depends only on whether anything irreversible has run."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.admin = self.create_super_admin()
        plan = Plan.objects.create(name='P', max_properties=1, max_residents_per_property=5, price_per_month='99.00')
        Subscription.objects.create(tenant=self.tenant, plan=plan, razorpay_subscription_id='sub_f')

    def fail_until_parked(self, row, phase_patch):
        """Runs the request on five separate nights with `phase_patch` raising, so it ends `failed`."""
        for _ in range(5):
            AccountDeletionRequest.objects.filter(pk=row.pk, status=Status.PENDING).update(
                next_attempt_at=timezone.now() - timedelta(minutes=1))
            with phase_patch:
                deletion.run_due_requests()
        row.refresh_from_db()
        self.assertEqual(row.status, Status.FAILED)
        return row

    def assert_reachable(self):
        client = APIClient()
        login = client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': STRONG_PASSWORD}, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        me = client.get(reverse('auth-me'))
        self.assertEqual((me.status_code, me.data['deletion']['status']), (200, 'failed'))
        self.assertFalse(me.data['deletion']['can_cancel'])
        self.assertEqual(client.get(reverse('tenant-current')).status_code, 403)

    def test_failing_notify_leaves_it_reversible_and_an_admin_may_cancel(self):
        row = self.request_for(self.owner)
        row = self.fail_until_parked(row, mock.patch(
            'apps.accounts.tasks.send_account_deletion_begun_task.delay', side_effect=ConnectionError('down')))
        self.assertIsNone(row.razorpay_closed_at)
        self.assert_reachable()
        cancelled = deletion.resolve_as_cancelled(row, actor=self.admin, note='verified')
        self.assertEqual(cancelled.status, Status.CANCELLED)

    def test_failing_razorpay_close_is_still_reversible(self):
        row = self.request_for(self.owner)
        row = self.fail_until_parked(row, mock.patch(
            'apps.subscriptions.services.close_billing_for_deletion', side_effect=RuntimeError('boom')))
        self.assertTrue(row.is_reversible)
        self.assert_reachable()

    def test_failing_db_purge_after_razorpay_close_is_past_the_point_of_no_return(self):
        row = self.request_for(self.owner)
        with mock.patch('apps.subscriptions.razorpay_client.cancel_razorpay_subscription'):
            row = self.fail_until_parked(
                row, mock.patch.object(deletion, 'purge_tenant_rows', side_effect=OSError('x')))
        self.assertIsNotNone(row.razorpay_closed_at)
        self.assertFalse(row.is_reversible)
        self.assertEqual(Subscription.objects.get(tenant=self.tenant).status_hold, Subscription.STATUS_HOLD_DELETED)
        self.assert_reachable()  # the logins are still there until db_purge succeeds
        self.assertNotEqual(Tenant.objects.get(pk=self.tenant.pk).status, Tenant.Status.DELETED)
        with self.assertRaises(Exception):
            deletion.resolve_as_cancelled(row, actor=self.admin, note='too late')
        # The only way out is retry-to-completion.
        with mock.patch('apps.subscriptions.razorpay_client.cancel_razorpay_subscription'), \
                self.captureOnCommitCallbacks(execute=True):
            deletion.retry_now(row, actor=self.admin)
        row.refresh_from_db()
        self.assertEqual(row.status, Status.COMPLETED)
        self.assertEqual(Tenant.objects.get(pk=self.tenant.pk).status, Tenant.Status.DELETED)

    def test_failing_files_purge_keeps_the_database_purge_and_retries_only_files(self):
        row = self.request_for(self.owner)
        row = self.fail_until_parked(
            row, mock.patch.object(deletion, 'purge_tenant_files', side_effect=OSError('gcs')))
        self.assertIsNotNone(row.db_purged_at)
        self.assertFalse(User.objects.filter(tenant=self.tenant).exists())  # logins gone
        with mock.patch.object(deletion, 'purge_tenant_rows') as rows_purge, \
                self.captureOnCommitCallbacks(execute=True):
            deletion.retry_now(row, actor=self.admin)
        rows_purge.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, Status.COMPLETED)


class LeaseHeartbeatTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_files_purge_refreshes_the_lease_by_count(self):
        for n in range(3):
            default_storage.save(f'residents/{self.tenant.id}/{n}/f.txt', ContentFile(b'x'))
        row = self.request_for(self.owner)
        claimed = deletion.claim(row.pk)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - timedelta(minutes=10))
        with mock.patch.object(deletion, 'HEARTBEAT_OBJECTS', 1):
            deletion._phase_files_purge(AccountDeletionRequest.objects.get(pk=row.pk), claimed.claim_token)
        refreshed = AccountDeletionRequest.objects.get(pk=row.pk).claimed_at
        self.assertGreater(refreshed, timezone.now() - timedelta(minutes=1))

    def test_files_purge_refreshes_the_lease_by_time_even_before_any_object_is_deleted(self):
        default_storage.save(f'residents/{self.tenant.id}/z/f.txt', ContentFile(b'x'))
        row = self.request_for(self.owner)
        claimed = deletion.claim(row.pk)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - timedelta(minutes=10))
        real_now = timezone.now()
        # The first call fixes the start; every later one is 61 s on: a slow listing, one object.
        ticks = [real_now] + [real_now + timedelta(seconds=61)] * 50
        with mock.patch.object(deletion.timezone, 'now', side_effect=ticks):
            deletion._phase_files_purge(AccountDeletionRequest.objects.get(pk=row.pk), claimed.claim_token)
        self.assertGreater(AccountDeletionRequest.objects.get(pk=row.pk).claimed_at, real_now - timedelta(minutes=1))

    def test_a_worker_that_lost_its_lease_stops(self):
        default_storage.save(f'residents/{self.tenant.id}/a/f.txt', ContentFile(b'x'))
        row = self.request_for(self.owner)
        claimed = deletion.claim(row.pk)
        AccountDeletionRequest.objects.filter(pk=row.pk).update(claim_token=uuid.uuid4())  # taken over
        with mock.patch.object(deletion, 'HEARTBEAT_OBJECTS', 1):
            with self.assertRaises(deletion.LeaseLost):
                deletion._phase_files_purge(AccountDeletionRequest.objects.get(pk=row.pk), claimed.claim_token)


class AdminActionTests(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.admin_user = self.create_super_admin()
        self.factory = RequestFactory()
        self.deletion_admin = AccountDeletionRequestAdmin(AccountDeletionRequest, django_admin.site)
        self.user_admin = UserAdmin(User, django_admin.site)

    def post(self, note=''):
        request = self.factory.post('/admin/', {'note': note})
        request.user = self.admin_user
        return request

    def test_resolve_needs_a_note_and_only_works_while_reversible(self):
        row = self.request_for(self.owner)
        queryset = AccountDeletionRequest.objects.filter(pk=row.pk)
        with mock.patch.object(self.deletion_admin, 'message_user') as message:
            self.deletion_admin.resolve_as_cancelled(self.post(''), queryset)
        self.assertEqual(AccountDeletionRequest.objects.get(pk=row.pk).status, Status.PENDING)
        self.assertIn('note', message.call_args[0][1].lower())
        with mock.patch.object(self.deletion_admin, 'message_user'):
            self.deletion_admin.resolve_as_cancelled(self.post('verified'), queryset)
        self.assertEqual(AccountDeletionRequest.objects.get(pk=row.pk).status, Status.CANCELLED)

    def test_create_on_behalf_needs_a_note_and_locks_a_suspended_owner(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        users = User.objects.filter(pk=self.owner.pk)
        with mock.patch.object(self.user_admin, 'message_user'):
            create_deletion_request_on_behalf(self.user_admin, self.post(''), users)
            self.assertFalse(AccountDeletionRequest.objects.exists())
            with self.captureOnCommitCallbacks(execute=True):
                create_deletion_request_on_behalf(self.user_admin, self.post('confirmed on a call'), users)
        created = AccountDeletionRequest.objects.get()
        self.assertEqual((created.scope, created.tenant_id), (Scope.TENANT, self.tenant.id))
        with tenant_context(self.tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='account.deletion_requested', after__on_behalf=True).exists())

    def test_the_request_admin_is_read_only(self):
        request = self.post()
        self.assertFalse(self.deletion_admin.has_add_permission(request))
        self.assertFalse(self.deletion_admin.has_change_permission(request))
        self.assertFalse(self.deletion_admin.has_delete_permission(request))
