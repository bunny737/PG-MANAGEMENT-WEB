from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .base import DevicesAPITestCase


class VersionPolicyAPITests(DevicesAPITestCase):
    def get(self, **params):
        params.setdefault('platform', 'android')
        params.setdefault('build', 12)
        return self.client.get(reverse('app-version-policy'), params)

    def policy_queries(self, **params):
        """How many queries against the policy table a request makes."""
        with CaptureQueriesContext(connection) as queries:
            self.get(**params)
        return sum('app_version_policies' in q['sql'] for q in queries)

    def test_build_below_min_is_force(self):
        self.create_policy(min_build=10, latest_build=14)
        self.assertEqual(self.get(build=9).data['update_mode'], 'force')

    def test_build_equal_to_min_is_not_force(self):
        self.create_policy(min_build=10, latest_build=14)
        self.assertEqual(self.get(build=10).data['update_mode'], 'soft')

    def test_build_between_min_and_latest_is_soft(self):
        self.create_policy(min_build=10, latest_build=14)
        self.assertEqual(self.get(build=12).data['update_mode'], 'soft')

    def test_soft_update_disabled_gives_none(self):
        self.create_policy(min_build=10, latest_build=14, soft_update_enabled=False)
        self.assertEqual(self.get(build=12).data['update_mode'], 'none')

    def test_build_at_or_above_latest_is_none(self):
        self.create_policy(min_build=10, latest_build=14)
        self.assertEqual(self.get(build=14).data['update_mode'], 'none')
        self.assertEqual(self.get(build=99).data['update_mode'], 'none')

    def test_response_shape_and_caching_header(self):
        self.create_policy()
        response = self.get(build=12)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'public, max-age=60')
        data = response.data
        self.assertEqual(data['min_supported_build'], 10)
        self.assertEqual(data['latest_build'], 14)
        self.assertEqual(data['latest_version'], '1.3.0')
        self.assertIn('play.google.com', data['store_url'])
        self.assertEqual(data['release_notes']['en'], 'Bug fixes')
        self.assertEqual(data['maintenance'], {'enabled': False, 'message': None, 'expires_at': None})
        self.assertEqual(data['check_interval_seconds'], 21600)
        self.assertTrue(data['server_time'].endswith('Z'))

    def test_no_policy_row_returns_none_never_an_error(self):
        response = self.get(platform='ios', build=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['update_mode'], 'none')
        self.assertIsNone(response.data['min_supported_build'])
        self.assertFalse(response.data['maintenance']['enabled'])

    def test_flavor_defaults_to_prod_and_is_isolated(self):
        self.create_policy(flavor='prod', min_build=10)
        self.create_policy(flavor='dev', min_build=1)
        self.assertEqual(self.get(build=5).data['update_mode'], 'force')
        self.assertEqual(self.get(build=5, flavor='dev').data['min_supported_build'], 1)

    def test_bad_or_missing_params_return_400_with_field_errors(self):
        for params in ({'platform': 'windows', 'build': 1}, {'platform': 'android', 'build': 'abc'},
                       {'platform': 'android', 'build': -1}, {'platform': 'android', 'build': 1, 'flavor': 'x'}):
            response = self.client.get(reverse('app-version-policy'), params)
            self.assertEqual(response.status_code, 400, params)
        response = self.client.get(reverse('app-version-policy'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('platform', response.data)
        self.assertIn('build', response.data)

    def test_maintenance_still_returns_200_with_flag(self):
        expires = timezone.now() + timedelta(hours=2)
        self.create_policy(
            maintenance_enabled=True, maintenance_message='Back at 3 PM', maintenance_expires_at=expires,
        )
        response = self.get(build=1)  # even a force-update build
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['maintenance']['enabled'])
        self.assertEqual(response.data['maintenance']['message'], 'Back at 3 PM')
        self.assertTrue(response.data['maintenance']['expires_at'].endswith('Z'))

    def test_expired_maintenance_is_reported_disabled(self):
        self.create_policy(
            maintenance_enabled=True, maintenance_expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(self.get().data['maintenance']['enabled'])

    def test_needs_no_auth_and_ignores_a_bad_token(self):
        self.create_policy()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer garbage')
        self.assertEqual(self.get().status_code, 200)

    def test_lookup_is_cached_but_saving_the_policy_invalidates(self):
        policy = self.create_policy(min_build=10)
        self.get(build=5)
        self.assertEqual(self.policy_queries(build=5), 0)
        policy.min_build = 3
        policy.save()
        self.assertEqual(self.get(build=5).data['update_mode'], 'soft')

    def test_missing_policy_lookup_is_cached_too(self):
        self.get()
        self.assertEqual(self.policy_queries(), 0)
