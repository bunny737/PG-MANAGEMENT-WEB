"""POST /devices/ requires proof of possession of an existing install (its
secret), because installation_id is only an identifier — see
apps.devices.services.register_installation."""
from apps.core.tenancy import tenant_context
from apps.devices.models import AppInstallation
from apps.notifications.models import PushSubscription

from .base import DevicesAPITestCase, device_payload


class InstallationSecretTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.create_owner(self.create_tenant())
        self.payload = device_payload(push={'fcm_token': 'victim-tok', 'permission': 'granted'})
        self.authenticate(self.owner)
        self.first = self.register(self.payload)
        self.secret = self.first.data['installation_secret']

    def again(self, secret=None, **overrides):
        body = device_payload(installation_id=self.payload['installation_id'], **overrides)
        kwargs = {} if secret is None else {'HTTP_X_INSTALLATION_SECRET': secret}
        if secret is None:
            kwargs['HTTP_X_INSTALLATION_SECRET'] = ''  # explicitly send none
        return self.register(body, **kwargs)

    def subscription_owner(self):
        with tenant_context(None, is_super_admin=True):
            return PushSubscription.objects.values_list('user_id', flat=True).get(fcm_token='victim-tok')

    def test_first_registration_issues_a_secret_and_stores_only_its_hash(self):
        self.assertEqual(self.first.status_code, 201)
        self.assertGreaterEqual(len(self.secret), 40)
        stored = AppInstallation.objects.get().secret_hash
        self.assertEqual(len(stored), 64)
        self.assertNotIn(self.secret, stored)

    def test_later_calls_with_the_secret_succeed_and_get_no_new_secret(self):
        response = self.again(secret=self.secret, sync_seq=43, locale='en-IN')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('installation_secret', response.data)
        self.assertEqual(AppInstallation.objects.get().locale, 'en-IN')

    def test_missing_or_wrong_secret_is_rejected_and_changes_nothing(self):
        for secret in (None, 'wrong', self.secret[:-1]):
            response = self.again(secret=secret, sync_seq=99, locale='hi-IN')
            self.assertEqual(response.status_code, 403, secret)
            self.assertEqual(response.data['code'], 'INSTALLATION_SECRET_INVALID')

        install = AppInstallation.objects.get()
        self.assertEqual((install.locale, install.last_sync_seq), ('te-IN', 42))

    def test_cross_tenant_user_cannot_take_over_the_install_or_drop_its_push(self):
        attacker = self.create_owner(self.create_tenant('Other PG'), email='attacker@example.com')
        self.authenticate(attacker)

        hijack = self.again(sync_seq=10_000, push={'fcm_token': None, 'permission': 'denied'})

        self.assertEqual(hijack.status_code, 403)
        self.assertEqual(AppInstallation.objects.get().user, self.owner)
        self.assertEqual(self.subscription_owner(), self.owner.id)

    def test_anonymous_unlink_also_needs_the_secret(self):
        # The takeover's first step (clearing the link anonymously) fails too.
        self.client.credentials()
        response = self.again(sync_seq=10_000, signed_in=False)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AppInstallation.objects.get().user, self.owner)

    def test_cross_tenant_user_cannot_claim_a_legacy_install(self):
        AppInstallation.objects.update(secret_hash='')
        attacker = self.create_owner(self.create_tenant('Other PG'), email='attacker@example.com')
        self.authenticate(attacker)

        response = self.again(sync_seq=10_000, push={'fcm_token': None, 'permission': 'denied'})

        self.assertEqual(response.status_code, 403)
        install = AppInstallation.objects.get()
        self.assertEqual((install.user, install.secret_hash), (self.owner, ''))
        self.assertEqual(self.subscription_owner(), self.owner.id)

    def test_anonymous_caller_cannot_claim_a_linked_legacy_install(self):
        AppInstallation.objects.update(secret_hash='')
        self.client.credentials()

        response = self.again(sync_seq=10_000, signed_in=False)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AppInstallation.objects.get().user, self.owner)

    def test_subscription_owner_can_claim_after_an_anonymous_unlink(self):
        AppInstallation.objects.update(secret_hash='', user=None)

        response = self.again(sync_seq=43)  # still authenticated as the owner

        self.assertEqual(response.status_code, 200)
        self.assertIn('installation_secret', response.data)

    def test_an_unowned_legacy_install_can_be_claimed_by_anyone(self):
        AppInstallation.objects.update(secret_hash='', user=None)
        with tenant_context(None, is_super_admin=True):
            PushSubscription.objects.all().delete()
        self.client.credentials()

        response = self.again(sync_seq=43, signed_in=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn('installation_secret', response.data)

    def test_legacy_install_without_a_secret_is_claimed_by_its_next_call(self):
        AppInstallation.objects.update(secret_hash='')

        claim = self.again(secret='anything', sync_seq=43)

        self.assertEqual(claim.status_code, 200)
        new_secret = claim.data['installation_secret']
        self.assertEqual(self.again(secret='anything', sync_seq=44).status_code, 403)
        self.assertEqual(self.again(secret=new_secret, sync_seq=44).status_code, 200)

    def test_secret_is_issued_even_when_the_claiming_call_is_stale(self):
        AppInstallation.objects.update(secret_hash='')

        response = self.again(sync_seq=1)

        self.assertEqual(response.data['ignored'], 'stale_sync_seq')
        self.assertIn('installation_secret', response.data)

    def test_secret_is_never_logged(self):
        with self.assertLogs('apps.devices.services', level='INFO') as logs:
            self.again(secret=self.secret, sync_seq=1)        # stale -> logged
            self.again(secret='wrong-secret', sync_seq=50)    # rejected -> logged
        joined = ' '.join(logs.output)
        self.assertNotIn(self.secret, joined)
        self.assertNotIn('wrong-secret', joined)
