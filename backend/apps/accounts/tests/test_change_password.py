from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase

NEW_PASSWORD = 'Copper-Meadow-42'


class ChangePasswordTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.url = reverse('auth-change-password')
        self.authenticate(self.owner)

    def change(self, current=STRONG_PASSWORD, new=NEW_PASSWORD):
        return self.client.post(self.url, {'current_password': current, 'new_password': new})

    def login(self, password):
        self.client.credentials()
        return self.client.post(reverse('auth-login'), {'email': 'owner@example.com', 'password': password})

    def test_changes_the_password(self):
        self.assertEqual(self.change().status_code, 200)

        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 401)
        self.assertEqual(self.login(NEW_PASSWORD).status_code, 200)

    def test_wrong_current_password_is_rejected_and_nothing_changes(self):
        response = self.change(current='Not-My-Password-1')

        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', response.data)
        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 200)

    def test_new_password_must_differ_from_the_current_one(self):
        response = self.change(new=STRONG_PASSWORD)

        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password', response.data)

    def test_weak_new_password_is_rejected(self):
        for weak in ('short1', '12345678', 'password'):
            with self.subTest(weak=weak):
                response = self.change(new=weak)
                self.assertEqual(response.status_code, 400)
                self.assertIn('new_password', response.data)
        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 200)

    def test_requires_authentication(self):
        self.client.credentials()
        response = self.change()

        self.assertEqual(response.status_code, 401)

    def test_every_existing_session_is_revoked(self):
        # auth_version is bumped, so the access token used for this very request stops working.
        self.assertEqual(self.change().status_code, 200)

        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)

    def test_writes_an_audit_log_without_the_password(self):
        self.change()

        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='user.password_changed')
        self.assertEqual(entry.actor_id, self.owner.id)
        self.assertEqual(entry.object_id, str(self.owner.id))
        self.assertNotIn(NEW_PASSWORD, str(entry.before) + str(entry.after))

    def test_only_changes_the_callers_own_password_never_another_tenants(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other@example.com')

        self.assertEqual(self.change().status_code, 200)

        other_owner.refresh_from_db()
        self.assertTrue(other_owner.check_password(STRONG_PASSWORD))
        self.client.credentials()
        still_works = self.client.post(
            reverse('auth-login'), {'email': 'other@example.com', 'password': STRONG_PASSWORD}
        )
        self.assertEqual(still_works.status_code, 200)

    def test_is_rate_limited_per_user(self):
        statuses = [self.change(current='Wrong-Guess-1').status_code for _ in range(7)]

        self.assertEqual(statuses[:5], [400] * 5)
        self.assertEqual(statuses[5:], [429, 429])
