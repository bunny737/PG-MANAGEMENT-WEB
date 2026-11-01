"""Resident app accounts (Module 26): deleting one, and the nightly housekeeping.

Deleting a resident-pool account removes the PERSON'S login and their own rows. The PG's records
(the Resident, its invoices and payments, its invites) stay: they are the PG's. A tenant purge, in
turn, removes the PG's side of every link and leaves the person's account alone."""
from datetime import timedelta

from django.apps import apps as django_apps
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts import deletion
from apps.accounts.models import AccountDeletionRequest, User
from apps.accounts.tasks import purge_unverified_resident_accounts
from apps.accounts.tests.base import STRONG_PASSWORD
from apps.audit import log as audit_log
from apps.audit.models import AuditLog
from apps.core.models import PlatformConfig
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.residents.models import ResidencyLinkRequest, Resident, ResidentAccess, ResidentInvite
from apps.residents.tasks import tidy_resident_access

from .test_account_deletion_purge import PurgeTestCase

Status = AccountDeletionRequest.Status
Scope = AccountDeletionRequest.Scope


class ResidentDeletionTestCase(PurgeTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.resident = self.create_resident(
            self.prop, email='ravi@example.com', status=Resident.Status.ACTIVE,
        )
        self.alice = self.create_user(None, Role.RESIDENT, 'alice@example.com')
        self.link = self.grant(self.alice, self.resident)

    def grant(self, user, resident, **kwargs):
        with tenant_context(resident.tenant_id):
            return ResidentAccess.objects.create(
                tenant_id=resident.tenant_id, user=user, resident=resident,
                origin=ResidentAccess.Origin.INVITE, activated_at=timezone.now(), **kwargs,
            )

    def request_deletion(self, user):
        self.authenticate(User.objects.get(pk=user.pk))
        return self.client.post(
            reverse('auth-account-deletion'), {'password': STRONG_PASSWORD, 'confirm': True}, format='json',
        )

    def purge(self, user):
        row = AccountDeletionRequest.objects.get(user=user)
        return self.run_to_end(self.make_due(row))


class ResidentRequestsDeletionTests(ResidentDeletionTestCase):
    def test_a_resident_can_request_deletion_and_it_is_user_scope_with_no_tenant(self):
        response = self.request_deletion(self.alice)
        self.assertEqual(response.status_code, 201, response.data)
        row = AccountDeletionRequest.objects.get(user=self.alice)
        self.assertEqual(row.scope, Scope.USER)
        self.assertIsNone(row.tenant_id)
        self.assertTrue(response.data['deletion']['can_cancel'])

    def test_the_account_locks_immediately_but_can_still_see_and_cancel_the_request(self):
        response = self.request_deletion(self.alice)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get(reverse('my-residencies')).status_code, 403)
        self.assertEqual(self.client.get(reverse('my-residencies')).data['code'], 'ACCOUNT_DELETION_PENDING')
        self.assertEqual(self.client.get(reverse('auth-account-deletion')).status_code, 200)
        self.assertEqual(self.client.delete(reverse('auth-account-deletion')).status_code, 204)
        self.assertEqual(self.client.get(reverse('my-residencies')).status_code, 200)

    def test_a_confirming_email_code_works_and_a_super_admin_still_cannot_delete(self):
        self.authenticate(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(reverse('auth-account-deletion-otp')).status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        admin = self.create_super_admin()
        self.authenticate(admin)
        self.assertEqual(self.client.post(reverse('auth-account-deletion-otp')).status_code, 403)


class ResidentPurgeTests(ResidentDeletionTestCase):
    def test_deleting_the_account_removes_the_person_and_keeps_the_pgs_records(self):
        invite_user = self.create_user(None, Role.RESIDENT, 'ravi@example.com')
        with tenant_context(self.tenant.id):
            invite = ResidentInvite.objects.create(
                tenant_id=self.tenant.id, resident=self.resident, email='ravi@example.com',
                status=ResidentInvite.Status.ACCEPTED, accepted_by=self.alice, accepted_at=timezone.now(),
                resulting_access=self.link, expires_at=timezone.now() + timedelta(days=1),
            )
            request = ResidencyLinkRequest.objects.create(
                tenant_id=self.tenant.id, requester=self.alice, property=self.prop,
                status=ResidencyLinkRequest.Status.APPROVED,
            )
        self.request_deletion(self.alice)
        self.assertEqual(self.purge(self.alice), 'completed')

        self.assertFalse(User.objects.filter(pk=self.alice.pk).exists())
        with tenant_context(self.tenant.id):
            # The person's own rows are gone ...
            self.assertFalse(ResidentAccess.objects.filter(pk=self.link.pk).exists())
            self.assertFalse(ResidencyLinkRequest.objects.filter(pk=request.pk).exists())
            # ... the PG's records stay, with the reference to the person cleared.
            self.assertTrue(Resident.objects.filter(pk=self.resident.pk).exists())
            kept = ResidentInvite.objects.get(pk=invite.pk)
            self.assertIsNone(kept.accepted_by_id)
            self.assertIsNone(kept.resulting_access_id)
        # Nobody else is touched.
        self.assertTrue(User.objects.filter(pk=invite_user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())

    def test_other_peoples_links_survive(self):
        bob = self.create_user(None, Role.RESIDENT, 'bob@example.com')
        second = self.create_resident(self.prop, first_name='Sita', phone='9000000030', status=Resident.Status.ACTIVE)
        bobs = self.grant(bob, second)
        self.request_deletion(self.alice)
        self.purge(self.alice)
        with tenant_context(self.tenant.id):
            self.assertTrue(ResidentAccess.objects.filter(pk=bobs.pk).exists())

    def test_a_staff_account_sharing_the_email_is_untouched(self):
        shared = self.create_owner(self.create_tenant('Other'), email='alice@example.com')
        self.request_deletion(self.alice)
        self.purge(self.alice)
        self.assertTrue(User.objects.staff_pool().filter(pk=shared.pk).exists())

    def test_their_footprints_in_the_audit_log_lose_the_ip_and_the_naming(self):
        audit_log.record(
            action='resident.link_requested', actor=self.alice, tenant_id=self.tenant.id, obj=self.resident,
            after={'requester': str(self.alice.pk), 'email': 'alice@example.com'},
        )
        with tenant_context(self.tenant.id):
            AuditLog.objects.filter(action='resident.link_requested').update(ip_address='203.0.113.9')
        self.request_deletion(self.alice)
        self.purge(self.alice)
        with tenant_context(self.tenant.id):
            row = AuditLog.objects.get(action='resident.link_requested')
        self.assertIsNone(row.ip_address)
        self.assertEqual(row.after, {'redacted': True})

    def test_a_tenant_purge_removes_the_pgs_side_and_keeps_the_persons_account(self):
        owner_request = self.request_for(self.owner)
        self.assertEqual(self.run_to_end(owner_request), 'completed')
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())
        with tenant_context(self.tenant.id, is_super_admin=True):
            self.assertEqual(ResidentAccess.objects.filter(tenant_id=self.tenant.id).count(), 0)
            self.assertEqual(Resident.objects.filter(tenant_id=self.tenant.id).count(), 0)

    def test_every_module_26_reference_to_the_user_does_what_the_inventory_says(self):
        for key, expected in deletion.RESIDENT_ACCOUNT_REFERENCES.items():
            app_label, model_name, field_name = key.split('.')
            field = django_apps.get_model(app_label, model_name)._meta.get_field(field_name)
            self.assertEqual(field.remote_field.on_delete.__name__, expected, key)


class TidyTaskTests(ResidentDeletionTestCase):
    def test_tidy_marks_expired_links_and_invites_and_nothing_else(self):
        now = timezone.now()
        with tenant_context(self.tenant.id):
            ResidentAccess.objects.filter(pk=self.link.pk).update(access_expires_at=now - timedelta(days=1))
            stale = ResidentInvite.objects.create(
                tenant_id=self.tenant.id, resident=self.resident, email='ravi@example.com',
                expires_at=now - timedelta(minutes=1),
            )
        result = tidy_resident_access()
        self.assertEqual(result, {'links_expired': 1, 'invites_expired': 1})
        with tenant_context(self.tenant.id):
            self.assertEqual(ResidentAccess.objects.get(pk=self.link.pk).status, 'expired')
            self.assertEqual(ResidentInvite.objects.get(pk=stale.pk).status, 'expired')

    def test_tidy_leaves_live_links_alone(self):
        self.assertEqual(tidy_resident_access(), {'links_expired': 0, 'invites_expired': 0})
        with tenant_context(self.tenant.id):
            self.assertEqual(ResidentAccess.objects.get(pk=self.link.pk).status, 'active')

    def test_both_jobs_are_scheduled_by_the_migration(self):
        from django_celery_beat.models import PeriodicTask

        names = set(PeriodicTask.objects.values_list('name', flat=True))
        self.assertIn('residents.tidy_resident_access', names)
        self.assertIn('accounts.purge_unverified_resident_accounts', names)


class UnverifiedCleanupTests(ResidentDeletionTestCase):
    def make_account(self, email, age_days, **kwargs):
        user = self.create_user(None, Role.RESIDENT, email, email_verified=False, **kwargs)
        User.objects.filter(pk=user.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        return user

    def setUp(self):
        super().setUp()
        config = PlatformConfig.get()
        config.unverified_resident_purge_days = 14
        config.save()

    def test_old_unverified_accounts_are_removed_and_recent_or_verified_ones_are_not(self):
        old = self.make_account('old@example.com', 30)
        recent = self.make_account('recent@example.com', 2)
        verified_old = self.create_user(None, Role.RESIDENT, 'verified@example.com')
        User.objects.filter(pk=verified_old.pk).update(created_at=timezone.now() - timedelta(days=90))
        self.assertEqual(purge_unverified_resident_accounts(), 1)
        self.assertFalse(User.objects.filter(pk=old.pk).exists())
        self.assertTrue(User.objects.filter(pk=recent.pk).exists())
        self.assertTrue(User.objects.filter(pk=verified_old.pk).exists())

    def test_an_account_with_a_link_request_is_not_an_abandoned_signup(self):
        waiting = self.make_account('waiting@example.com', 30)
        with tenant_context(self.tenant.id):
            ResidencyLinkRequest.objects.create(tenant_id=self.tenant.id, requester=waiting, property=self.prop)
        self.assertEqual(purge_unverified_resident_accounts(), 0)
        self.assertTrue(User.objects.filter(pk=waiting.pk).exists())

    def test_the_window_follows_platform_config(self):
        account = self.make_account('mid@example.com', 20)
        config = PlatformConfig.get()
        config.unverified_resident_purge_days = 30
        config.save()
        self.assertEqual(purge_unverified_resident_accounts(), 0)
        config.unverified_resident_purge_days = 14
        config.save()
        self.assertEqual(purge_unverified_resident_accounts(), 1)
        self.assertFalse(User.objects.filter(pk=account.pk).exists())

    def test_staff_accounts_are_never_touched(self):
        staff = self.create_owner(self.create_tenant('Other'), email='unverified-owner@example.com', email_verified=False)
        User.objects.filter(pk=staff.pk).update(created_at=timezone.now() - timedelta(days=400))
        self.assertEqual(purge_unverified_resident_accounts(), 0)
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())
