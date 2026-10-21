from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.urls import reverse

from apps.accounts.models import Tenant, User
from apps.accounts.tasks import send_password_changed_task, send_staff_invite_task
from apps.core.roles import Role

from .base import AuthAPITestCase

SMTP_SEND = 'apps.core.email.EmailMultiAlternatives.send'
EMAIL = 'invitee@example.com'


class StaffInviteDeliveryTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def create_staff(self, **payload):
        self.authenticate(self.owner)
        body = {'first_name': 'Kavita', 'email': EMAIL, 'phone': '9876543210', 'role': Role.MANAGER}
        body.update(payload)
        return self.client.post(reverse('staff-list'), body, format='json')

    def test_invite_is_queued_after_commit_not_sent_on_the_request_path(self):
        response = self.create_staff()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mail.outbox, [])

    def test_invite_link_is_a_fragment_with_the_invite_flag(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_staff()
        message = mail.outbox[0]
        self.assertEqual(message.to, [EMAIL])
        self.assertIn('/reset-password#uid=', message.body)
        self.assertIn('&invite=1', message.body)
        self.assertNotIn('?uid=', message.body)
        self.assertIn('Sunrise PG', message.subject)

    def test_an_smtp_outage_cannot_roll_back_staff_creation(self):
        with mock.patch(SMTP_SEND, side_effect=SMTPException('down')), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.create_staff()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email=EMAIL).exists())

    def test_staff_created_with_a_password_gets_a_verification_email_not_an_invite(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_staff(password='Quiet-Harbor-19')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/verify-email#token=', mail.outbox[0].body)

    def test_phone_only_staff_get_no_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.create_staff(email=None, password='Quiet-Harbor-19')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(mail.outbox, [])


class StaffInviteTaskTests(AuthAPITestCase):
    """The job re-checks, on the worker, that the invite is still for this account."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.staff = self.create_user(
            self.tenant, Role.MANAGER, EMAIL, password=None, email_verified=False,
        )

    def run_task(self, expected_email=EMAIL):
        send_staff_invite_task(str(self.staff.id), expected_email)

    def test_sends_to_a_pending_invitee(self):
        self.run_task()
        self.assertEqual([m.to for m in mail.outbox], [[EMAIL]])

    def test_skips_when_the_address_changed_after_queueing(self):
        User.objects.filter(pk=self.staff.pk).update(email='moved@example.com')
        self.run_task()
        self.assertEqual(mail.outbox, [])

    def test_matches_the_address_case_insensitively(self):
        self.run_task('Invitee@Example.com')
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_a_deactivated_account(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.run_task()
        self.assertEqual(mail.outbox, [])

    def test_skips_once_a_password_exists(self):
        self.staff.set_password('Quiet-Harbor-19')
        self.staff.save()
        self.run_task()
        self.assertEqual(mail.outbox, [])

    def test_skips_a_suspended_tenant(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        self.run_task()
        self.assertEqual(mail.outbox, [])

    def test_skips_a_job_queued_without_an_address(self):
        self.run_task(expected_email=None)
        self.assertEqual(mail.outbox, [])

    def test_skips_a_deleted_account(self):
        User.objects.filter(pk=self.staff.pk).delete()
        self.run_task()
        self.assertEqual(mail.outbox, [])


class PasswordChangedTaskTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def run_task(self, expected_email='owner@example.com'):
        send_password_changed_task(str(self.owner.id), expected_email)

    def test_sends_the_notice(self):
        self.run_task()
        self.assertEqual([m.to for m in mail.outbox], [['owner@example.com']])

    def test_still_sends_for_a_suspended_tenant(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        self.run_task()
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_when_the_address_changed(self):
        User.objects.filter(pk=self.owner.pk).update(email='moved@example.com')
        self.run_task()
        self.assertEqual(mail.outbox, [])

    def test_skips_an_inactive_account_and_a_job_without_an_address(self):
        self.run_task(expected_email=None)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.run_task()
        self.assertEqual(mail.outbox, [])
