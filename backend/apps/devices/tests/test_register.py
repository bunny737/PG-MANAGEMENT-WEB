import json
import uuid
from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from rest_framework.throttling import SimpleRateThrottle

from apps.devices.models import AppInstallation, AppInstallationHistory

from .base import DevicesAPITestCase, device_payload


class DeviceRegisterTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    # --- create / link ---------------------------------------------------------

    def test_anonymous_create_returns_201_and_stores_the_install(self):
        payload = device_payload(push={'fcm_token': 'tok-1'})
        response = self.register(payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['installation_id'], payload['installation_id'])
        self.assertTrue(response.data['registered'])
        self.assertFalse(response.data['user_linked'])
        self.assertTrue(response.data['server_time'].endswith('Z'))
        install = AppInstallation.objects.get(installation_id=payload['installation_id'])
        self.assertIsNone(install.user)
        self.assertEqual(install.platform, 'android')
        self.assertEqual(install.build_number, 12)
        self.assertEqual(install.device_model, 'SM-S918B')
        self.assertEqual(install.os_sdk_int, 34)
        self.assertEqual(install.fcm_token, 'tok-1')
        self.assertEqual(install.last_sync_seq, 42)
        self.assertIsNotNone(install.first_seen_at)

    def test_authenticated_create_links_the_user(self):
        self.authenticate(self.owner)
        payload = device_payload()
        response = self.register(payload)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['user_linked'])
        self.assertEqual(AppInstallation.objects.get(installation_id=payload['installation_id']).user, self.owner)

    def test_second_call_is_200_and_updates_in_place(self):
        payload = device_payload()
        self.register(payload)
        first_seen = AppInstallation.objects.get().first_seen_at

        later = {**payload, 'sync_seq': 43, 'network_type': 'mobile'}
        response = self.register(later)

        self.assertEqual(response.status_code, 200)
        install = AppInstallation.objects.get()
        self.assertEqual(install.network_type, 'mobile')
        self.assertEqual(install.first_seen_at, first_seen)
        self.assertGreaterEqual(install.last_seen_at, first_seen)

    def test_account_switch_last_writer_wins(self):
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        payload = device_payload()
        self.authenticate(self.owner)
        self.register(payload)
        self.authenticate(other)
        self.register({**payload, 'sync_seq': 43})

        self.assertEqual(AppInstallation.objects.get().user, other)

    def test_expired_token_is_treated_as_anonymous_not_401(self):
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.accounts.serializers import LoginSerializer

        token = LoginSerializer.get_token(self.owner).access_token
        expired = AccessToken(str(token))
        expired.set_exp(from_time=timezone.now() - timedelta(hours=1), lifetime=timedelta(minutes=1))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {expired}')

        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['user_linked'])
        self.assertIsNone(AppInstallation.objects.get().user)

    def test_garbage_token_is_anonymous_not_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-jwt')
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['user_linked'])

    def test_suspended_tenant_user_is_treated_as_anonymous(self):
        self.authenticate(self.owner)
        self.tenant.status = 'suspended'
        self.tenant.save()
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['user_linked'])

    # --- user link rules -------------------------------------------------------

    def test_signed_in_false_anonymous_clears_the_user(self):
        payload = device_payload()
        self.authenticate(self.owner)
        self.register(payload)
        self.client.credentials()  # token gone (offline logout / expired)

        response = self.register({**payload, 'signed_in': False, 'sync_seq': 43})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['user_linked'])
        self.assertIsNone(AppInstallation.objects.get().user)

    def test_signed_in_true_anonymous_leaves_the_user_unchanged(self):
        payload = device_payload()
        self.authenticate(self.owner)
        self.register(payload)
        self.client.credentials()

        response = self.register({**payload, 'signed_in': True, 'sync_seq': 43})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['user_linked'])
        self.assertEqual(AppInstallation.objects.get().user, self.owner)

    # --- ordering --------------------------------------------------------------

    def test_stale_sync_seq_is_ignored_entirely(self):
        payload = device_payload(sync_seq=10)
        self.authenticate(self.owner)
        self.register(payload)
        self.client.credentials()

        with self.assertLogs('apps.devices.services', level='INFO') as logs:
            response = self.register({**payload, 'sync_seq': 9, 'signed_in': False, 'locale': 'hi-IN'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'registered': True, 'ignored': 'stale_sync_seq'})
        install = AppInstallation.objects.get()
        self.assertEqual(install.user, self.owner)  # the delayed signed_in=false did not unlink
        self.assertEqual(install.locale, 'te-IN')
        self.assertEqual(install.last_sync_seq, 10)
        self.assertTrue(any('stale' in line for line in logs.output))

    def test_equal_sync_seq_is_reprocessed_idempotently(self):
        payload = device_payload(sync_seq=10)
        self.register(payload)
        response = self.register({**payload, 'locale': 'en-IN'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('ignored', response.data)
        self.assertEqual(AppInstallation.objects.get().locale, 'en-IN')
        self.assertEqual(AppInstallation.objects.count(), 1)

    # --- fcm token -------------------------------------------------------------

    def test_fcm_token_moves_between_installs(self):
        a = device_payload(push={'fcm_token': 'shared-token'})
        b = device_payload(push={'fcm_token': 'shared-token'})
        self.register(a)
        self.assertEqual(self.register(b).status_code, 201)

        self.assertIsNone(AppInstallation.objects.get(installation_id=a['installation_id']).fcm_token)
        self.assertEqual(AppInstallation.objects.get(installation_id=b['installation_id']).fcm_token, 'shared-token')

    def test_null_token_clears_the_stored_one(self):
        payload = device_payload(push={'fcm_token': 'tok'})
        self.register(payload)
        self.register({**payload, 'sync_seq': 43, 'push': {'fcm_token': None, 'permission': 'denied'}})

        install = AppInstallation.objects.get()
        self.assertIsNone(install.fcm_token)
        self.assertEqual(install.push_permission, 'denied')

    def test_token_is_never_logged(self):
        payload = device_payload(sync_seq=10, push={'fcm_token': 'super-secret-token'})
        self.register(payload)
        with self.assertLogs('apps.devices.services', level='INFO') as logs:
            self.register({**payload, 'sync_seq': 9})  # stale -> logged
        self.assertNotIn('super-secret-token', ' '.join(logs.output))

    # --- history ---------------------------------------------------------------

    def test_history_row_on_first_sighting_and_on_build_or_os_change_only(self):
        payload = device_payload()
        self.register(payload)
        self.assertEqual(AppInstallationHistory.objects.count(), 1)

        self.register({**payload, 'sync_seq': 43})  # nothing changed
        self.assertEqual(AppInstallationHistory.objects.count(), 1)

        upgraded = device_payload(
            installation_id=payload['installation_id'], sync_seq=44, app={'build_number': 13, 'version_name': '1.2.1'},
        )
        self.register(upgraded)
        self.assertEqual(AppInstallationHistory.objects.count(), 2)

        os_changed = {**upgraded, 'sync_seq': 45, 'os': {**upgraded['os'], 'version': '15'}}
        self.register(os_changed)
        self.assertEqual(AppInstallationHistory.objects.count(), 3)
        latest = AppInstallationHistory.objects.first()
        self.assertEqual((latest.build_number, latest.os_version), (13, '15'))

    # --- validation ------------------------------------------------------------

    def test_invalid_bodies_return_field_errors(self):
        cases = {
            'installation_id': device_payload(installation_id='not-a-uuid'),
            'platform': device_payload(platform='windows'),
            'flavor': device_payload(flavor='staging'),
            'sync_seq': device_payload(sync_seq=-1),
            'app': device_payload(app={'build_number': 0}),
            'locale': device_payload(locale='x' * 17),
        }
        for field, payload in cases.items():
            response = self.register(payload)
            self.assertEqual(response.status_code, 400, field)
            self.assertIn(field, response.data)

    def test_string_length_caps(self):
        response = self.register(device_payload(device={'model': 'm' * 65}))
        self.assertEqual(response.status_code, 400)
        self.assertIn('model', response.data['device'])

    def test_unknown_extra_keys_are_ignored(self):
        payload = {**device_payload(), 'surprise': 'ignored', 'app': {**device_payload()['app'], 'extra': 1}}
        self.assertEqual(self.register(payload).status_code, 201)

    def test_nullable_fields_may_be_null_or_absent(self):
        payload = device_payload(os={'sdk_int': None}, network_type=None)
        self.assertEqual(self.register(payload).status_code, 201)
        install = AppInstallation.objects.get()
        self.assertIsNone(install.os_sdk_int)
        self.assertEqual(install.network_type, '')

        ios = device_payload(platform='ios', device={'manufacturer': 'Apple', 'model': 'iPhone15,2'})
        del ios['os']['sdk_int']
        del ios['network_type']
        self.assertEqual(self.register(ios).status_code, 201)

    def test_body_over_8kb_is_rejected_with_413(self):
        payload = device_payload()
        payload['padding'] = 'x' * 9000
        response = self.client.post(
            reverse('device-register'), data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(AppInstallation.objects.count(), 0)

    def test_body_under_8kb_is_accepted(self):
        self.assertLess(len(json.dumps(device_payload())), 8 * 1024)
        self.assertEqual(self.register().status_code, 201)

    # --- throttles -------------------------------------------------------------

    def test_per_installation_throttle_returns_429_with_retry_after(self):
        payload = device_payload()
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'device_register_installation': '3/hour'}):
            for seq in range(3):
                self.assertIn(self.register({**payload, 'sync_seq': seq}).status_code, (200, 201))
            response = self.register({**payload, 'sync_seq': 3})
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response)
            # A different install is not affected by that install's budget.
            self.assertEqual(self.register(device_payload()).status_code, 201)

    def test_per_ip_throttle_returns_429(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'device_register_ip': '3/hour'}):
            for _ in range(3):
                self.assertEqual(self.register(device_payload()).status_code, 201)
            response = self.register(device_payload())
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response)

    def test_default_rates_match_the_spec(self):
        self.assertEqual(SimpleRateThrottle.THROTTLE_RATES['device_register_installation'], '30/hour')
        self.assertEqual(SimpleRateThrottle.THROTTLE_RATES['device_register_ip'], '120/hour')

    # --- misc ------------------------------------------------------------------

    def test_no_pii_columns_exist_on_the_table(self):
        names = {f.name for f in AppInstallation._meta.get_fields()}
        for forbidden in ('name', 'phone', 'email', 'latitude', 'longitude', 'location', 'advertising_id', 'idfa'):
            self.assertNotIn(forbidden, names)

    def test_deleting_the_user_keeps_an_anonymous_install(self):
        self.authenticate(self.owner)
        self.register()
        self.owner.delete()
        install = AppInstallation.objects.get()
        self.assertIsNone(install.user)

    def test_unique_installation_ids_across_calls(self):
        iid = str(uuid.uuid4())
        self.register(device_payload(installation_id=iid))
        self.register(device_payload(installation_id=iid.upper(), sync_seq=50))
        self.assertEqual(AppInstallation.objects.count(), 1)
