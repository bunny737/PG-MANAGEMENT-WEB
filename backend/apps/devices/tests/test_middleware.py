import uuid
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.devices.client import AppClient, parse_app_client

from .base import DevicesAPITestCase, app_headers, device_payload

PROTECTED = 'notification-history-list'  # authenticated endpoint: 401 == the request got through


class AppClientMiddlewareTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.create_policy(min_build=10, latest_build=14)
        self.url = reverse(PROTECTED)

    def get(self, url=None, **headers):
        return self.client.get(url or self.url, **headers)

    # --- outdated build --------------------------------------------------------

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_old_build_gets_426_with_exact_code(self):
        response = self.get(**app_headers(build=9))
        self.assertEqual(response.status_code, 426)
        body = response.json()
        self.assertEqual(body['code'], 'APP_UPDATE_REQUIRED')
        self.assertEqual(body['detail'], 'Please update the app')
        self.assertEqual(body['min_supported_build'], 10)
        self.assertIn('play.google.com', body['store_url'])

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_build_at_min_passes(self):
        self.assertEqual(self.get(**app_headers(build=10)).status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_login_from_an_old_build_gets_426(self):
        response = self.client.post(
            reverse('auth-login'), {'email': 'a@b.co', 'password': 'x'}, **app_headers(build=9),
        )
        self.assertEqual(response.status_code, 426)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_otp_and_refresh_are_not_exempt(self):
        for name in ('auth-otp-request', 'auth-token-refresh'):
            response = self.client.post(reverse(name), {}, **app_headers(build=9))
            self.assertEqual(response.status_code, 426, name)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_flavor_selects_the_policy(self):
        self.create_policy(flavor='dev', min_build=1)
        self.assertEqual(self.get(**app_headers(build=5, flavor='dev')).status_code, 401)
        self.assertEqual(self.get(**app_headers(build=5, flavor='prod')).status_code, 426)

    # --- maintenance -----------------------------------------------------------

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_maintenance_returns_503_with_exact_code(self):
        expires = timezone.now() + timedelta(hours=2)
        self.create_policy(platform='ios', maintenance_enabled=True, maintenance_message='Back at 3 PM',
                           maintenance_expires_at=expires)
        response = self.get(**app_headers(platform='ios', build=99))
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['code'], 'MAINTENANCE')
        self.assertEqual(body['detail'], 'Down for maintenance')
        self.assertEqual(body['message'], 'Back at 3 PM')
        self.assertTrue(body['expires_at'].endswith('Z'))
        self.assertIn('Retry-After', response)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_expired_maintenance_does_not_block(self):
        AppVersionPolicyUpdate = type(self.create_policy(platform='ios'))
        AppVersionPolicyUpdate.objects.filter(platform='ios').update(
            maintenance_enabled=True, maintenance_expires_at=timezone.now() - timedelta(minutes=1),
        )
        from django.core.cache import cache
        cache.clear()
        self.assertEqual(self.get(**app_headers(platform='ios', build=99)).status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='on', APP_MAINTENANCE_BYPASS_TOKEN='qa-secret')
    def test_staff_bypass_header_skips_maintenance_only(self):
        self.create_policy(platform='ios', maintenance_enabled=True)
        headers = app_headers(platform='ios', build=99)
        self.assertEqual(self.get(**headers).status_code, 503)
        self.assertEqual(self.get(HTTP_X_MAINTENANCE_BYPASS='qa-secret', **headers).status_code, 401)
        self.assertEqual(self.get(HTTP_X_MAINTENANCE_BYPASS='wrong', **headers).status_code, 503)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_bypass_is_disabled_when_no_token_is_configured(self):
        self.create_policy(platform='ios', maintenance_enabled=True)
        response = self.get(HTTP_X_MAINTENANCE_BYPASS='', **app_headers(platform='ios'))
        self.assertEqual(response.status_code, 503)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_plain_server_errors_do_not_use_the_maintenance_code(self):
        from unittest import mock

        self.client.raise_request_exception = False
        self.authenticate(self.create_owner(self.create_tenant()))
        with mock.patch('apps.notifications.views.NotificationHistoryViewSet.get_queryset', side_effect=RuntimeError):
            response = self.client.get(self.url, **app_headers(build=12))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('MAINTENANCE', response.content.decode())

    # --- exemptions & pass-through ----------------------------------------------

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_exempt_paths_pass_through_even_for_old_builds_and_maintenance(self):
        self.create_policy(platform='ios', maintenance_enabled=True, min_build=50)
        for headers in (app_headers(build=1), app_headers(platform='ios', build=1)):
            policy = self.client.get(reverse('app-version-policy'), {'platform': 'android', 'build': 1}, **headers)
            self.assertEqual(policy.status_code, 200)
            register = self.client.post(reverse('device-register'), device_payload(), format='json', **headers)
            self.assertEqual(register.status_code, 201)
            self.authenticate(self.create_owner(self.create_tenant(), email=f'{uuid.uuid4().hex[:6]}@x.co'))
            unlink = self.client.delete(reverse('device-unlink-user', args=[uuid.uuid4()]), **headers)
            self.assertEqual(unlink.status_code, 204)
            self.client.credentials()

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_admin_and_static_paths_are_exempt(self):
        self.assertEqual(self.client.get('/admin/login/', **app_headers(build=1)).status_code, 200)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_requests_without_app_headers_are_never_blocked(self):
        self.assertEqual(self.get().status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_garbage_headers_never_fail_a_request(self):
        for headers in (
            {'HTTP_X_APP_PLATFORM': 'toaster', 'HTTP_X_APP_BUILD': 'abc', 'HTTP_X_INSTALLATION_ID': 'zzz'},
            {'HTTP_X_APP_BUILD': '-5'},
            {'HTTP_X_APP_BUILD': '9' * 40, 'HTTP_X_APP_PLATFORM': 'android'},
            {'HTTP_X_APP_PLATFORM': 'android'},          # no build: cannot be outdated
            {'HTTP_X_APP_BUILD': '3'},                   # no platform: no policy to compare
            {'HTTP_X_APP_VERSION': 'é' * 500, 'HTTP_X_APP_FLAVOR': '???'},
        ):
            self.assertEqual(self.get(**headers).status_code, 401, headers)

    # --- modes -----------------------------------------------------------------

    @override_settings(APP_VERSION_ENFORCEMENT='off')
    def test_off_mode_never_blocks_and_never_logs(self):
        self.create_policy(platform='ios', maintenance_enabled=True)
        with self.assertNoLogs('apps.devices.middleware', level='WARNING'):
            self.assertEqual(self.get(**app_headers(build=1)).status_code, 401)
            self.assertEqual(self.get(**app_headers(platform='ios')).status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='log')
    def test_log_mode_lets_requests_through_but_logs_what_would_block(self):
        self.create_policy(platform='ios', maintenance_enabled=True)
        with self.assertLogs('apps.devices.middleware', level='WARNING') as logs:
            self.assertEqual(self.get(**app_headers(build=9)).status_code, 401)
            self.assertEqual(self.get(**app_headers(platform='ios', build=99)).status_code, 401)
        joined = ' '.join(logs.output)
        self.assertIn('APP_UPDATE_REQUIRED', joined)
        self.assertIn('MAINTENANCE', joined)

    @override_settings(APP_VERSION_ENFORCEMENT='log')
    def test_log_mode_is_silent_for_current_builds(self):
        with self.assertNoLogs('apps.devices.middleware', level='WARNING'):
            self.get(**app_headers(build=12))

    @override_settings(APP_VERSION_ENFORCEMENT='bogus')
    def test_unknown_mode_fails_safe_to_off(self):
        self.assertEqual(self.get(**app_headers(build=1)).status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_no_policy_row_never_blocks(self):
        self.assertEqual(self.get(**app_headers(platform='ios', build=1)).status_code, 401)

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_policy_lookup_failure_fails_open(self):
        from unittest import mock

        with mock.patch('apps.devices.middleware.get_policy', side_effect=RuntimeError('cache down')):
            with self.assertLogs('apps.devices.middleware', level='ERROR'):
                self.assertEqual(self.get(**app_headers(build=1)).status_code, 401)


class ParseAppClientTests(DevicesAPITestCase):
    def parse(self, **meta):
        from django.test import RequestFactory

        return parse_app_client(RequestFactory().get('/', **meta))

    def test_parses_all_headers(self):
        iid = str(uuid.uuid4())
        client = self.parse(**app_headers(platform='IOS', build=7, flavor='Dev', version='1.0', installation_id=iid))
        self.assertEqual(client, AppClient('ios', '1.0', 7, 'dev', iid))

    def test_none_when_no_usable_headers(self):
        self.assertIsNone(self.parse())
        self.assertIsNone(self.parse(HTTP_X_APP_PLATFORM='toaster', HTTP_X_APP_BUILD='x'))

    def test_request_gets_app_client_attribute(self):
        from apps.devices.middleware import AppClientMiddleware
        from django.test import RequestFactory

        seen = {}

        def view(request):
            seen['client'] = request.app_client
            from django.http import HttpResponse
            return HttpResponse('ok')

        AppClientMiddleware(view)(RequestFactory().get('/', **app_headers(build=3)))
        self.assertEqual(seen['client'].build, 3)
        AppClientMiddleware(view)(RequestFactory().get('/'))
        self.assertIsNone(seen['client'])
