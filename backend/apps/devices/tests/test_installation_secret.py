"""POST /devices/ requires proof of possession of an existing install: the
app generates its own secret and sends it on every call, the server stores
only its hash (installation_id alone is an identifier, not a credential) —
see apps.devices.services._check_possession."""
import secrets

from apps.core.tenancy import tenant_context
from apps.devices.models import AppInstallation
from apps.notifications.models import PushSubscription

from .base import DevicesAPITestCase, device_payload

OLD_BUILD = {'HTTP_X_INSTALLATION_SECRET': ''}  # a build that predates secrets


def other_secret():
    return secrets.token_urlsafe(32)


class _Base(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.create_owner(self.create_tenant())
        self.install_id = device_payload()['installation_id']
        self.authenticate(self.owner)

    def sync(self, seq, headers=None, **overrides):
        body = device_payload(installation_id=self.install_id, sync_seq=seq, **overrides)
        return self.register(body, **(headers or {}))

    def install(self):
        return AppInstallation.objects.get(installation_id=self.install_id)

    def subscription_owner(self):
        with tenant_context(None, is_super_admin=True):
            return PushSubscription.objects.values_list('user_id', flat=True).get(fcm_token='tok')


class InstallationSecretTests(_Base):
    def setUp(self):
        super().setUp()
        self.first = self.sync(42, push={'fcm_token': 'tok', 'permission': 'granted'})

    def test_create_stores_only_the_hash_and_never_returns_a_secret(self):
        self.assertEqual(self.first.status_code, 201)
        self.assertNotIn('installation_secret', self.first.data)
        stored = self.install().secret_hash
        self.assertEqual(len(stored), 64)
        self.assertNotIn(self.secret_for(self.install_id), stored)

    def test_later_calls_with_the_secret_succeed(self):
        response = self.sync(43, locale='en-IN')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.install().locale, 'en-IN')

    def test_retrying_a_create_whose_response_was_lost_succeeds(self):
        # Same body, same seq, same secret: no orphan, no 403.
        retry = self.sync(42, push={'fcm_token': 'tok', 'permission': 'granted'})
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(AppInstallation.objects.count(), 1)

    def test_missing_or_wrong_secret_is_rejected_and_changes_nothing(self):
        for headers in (OLD_BUILD, {'HTTP_X_INSTALLATION_SECRET': other_secret()}):
            response = self.sync(99, headers=headers, locale='hi-IN')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data['code'], 'INSTALLATION_SECRET_INVALID')
        install = self.install()
        self.assertEqual((install.locale, install.last_sync_seq), ('te-IN', 42))

    def test_cross_tenant_user_cannot_take_over_the_install_or_drop_its_push(self):
        attacker = self.create_owner(self.create_tenant('Other PG'), email='attacker@example.com')
        self.authenticate(attacker)

        hijack = self.sync(10_000, headers={'HTTP_X_INSTALLATION_SECRET': other_secret()},
                           push={'fcm_token': None, 'permission': 'denied'})

        self.assertEqual(hijack.status_code, 403)
        self.assertEqual(self.install().user, self.owner)
        self.assertEqual(self.subscription_owner(), self.owner.id)

    def test_anonymous_unlink_also_needs_the_secret(self):
        self.client.credentials()
        response = self.sync(10_000, headers={'HTTP_X_INSTALLATION_SECRET': other_secret()}, signed_in=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.install().user, self.owner)

    def test_malformed_secret_is_a_400(self):
        for bad in ('short', 'x' * 129, 'é' * 40):
            body = device_payload()
            response = self.register(body, HTTP_X_INSTALLATION_SECRET=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertEqual(response.data['code'], 'INSTALLATION_SECRET_MALFORMED')
        self.assertEqual(AppInstallation.objects.count(), 1)

    def test_secret_is_never_logged(self):
        wrong = other_secret()
        with self.assertLogs('apps.devices.services', level='INFO') as logs:
            self.sync(1)                                                   # stale -> logged
            self.sync(50, headers={'HTTP_X_INSTALLATION_SECRET': wrong})   # rejected -> logged
        joined = ' '.join(logs.output)
        self.assertNotIn(self.secret_for(self.install_id), joined)
        self.assertNotIn(wrong, joined)


class UnclaimedInstallTests(_Base):
    """Installs registered by builds that predate secrets have none. Only a
    stakeholder is served; a stakeholder sending a secret claims the install
    with it, keeping the same installation_id."""

    def setUp(self):
        super().setUp()
        self.sync(42, headers=OLD_BUILD, push={'fcm_token': 'tok', 'permission': 'granted'})

    def test_old_build_keeps_syncing_without_a_secret(self):
        self.assertEqual(self.install().secret_hash, '')
        for seq in (43, 44):
            self.assertEqual(self.sync(seq, headers=OLD_BUILD).status_code, 200)
        self.assertEqual(self.install().secret_hash, '')

    def test_upgraded_build_claims_with_its_own_secret(self):
        self.sync(43, headers=OLD_BUILD)   # old build kept syncing after the deploy

        upgraded = self.sync(44)           # default helper = current build

        self.assertEqual(upgraded.status_code, 200)
        self.assertNotEqual(self.install().secret_hash, '')
        self.assertEqual(self.sync(45).status_code, 200)
        self.assertEqual(self.sync(46, headers=OLD_BUILD).status_code, 403)

    def test_claim_works_on_a_stale_response(self):
        response = self.sync(1)

        self.assertEqual(response.data['ignored'], 'stale_sync_seq')
        self.assertNotEqual(self.install().secret_hash, '')
        self.assertEqual(self.sync(50, headers=OLD_BUILD).status_code, 403)

    def test_expired_session_on_an_unclaimed_install_is_ignored_not_rejected(self):
        self.client.credentials()   # the owner's access token expired

        response = self.sync(43, signed_in=False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'registered': True, 'ignored': 'unclaimed_install'})
        install = self.install()
        self.assertEqual((install.user, install.secret_hash, install.last_sync_seq), (self.owner, '', 42))
        # The next signed-in sync claims it under the same installation_id.
        self.authenticate(self.owner)
        self.assertEqual(self.sync(44).status_code, 200)
        self.assertNotEqual(self.install().secret_hash, '')

    def test_another_signed_in_user_is_rejected_and_changes_nothing(self):
        attacker = self.create_owner(self.create_tenant('Other PG'), email='attacker@example.com')
        self.authenticate(attacker)

        response = self.sync(10_000, push={'fcm_token': None, 'permission': 'denied'})

        self.assertEqual(response.status_code, 403)
        install = self.install()
        self.assertEqual((install.user, install.secret_hash), (self.owner, ''))
        self.assertEqual(self.subscription_owner(), self.owner.id)

    def test_subscription_owner_can_claim_after_an_anonymous_unlink(self):
        AppInstallation.objects.update(user=None)

        response = self.sync(43)   # still authenticated as the owner

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.install().secret_hash, '')

    def test_an_unowned_install_can_be_claimed_by_anyone(self):
        AppInstallation.objects.update(user=None)
        with tenant_context(None, is_super_admin=True):
            PushSubscription.objects.all().delete()
        self.client.credentials()

        response = self.sync(43, signed_in=False)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.install().secret_hash, '')
