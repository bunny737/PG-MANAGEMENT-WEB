"""The production settings, exercised the way production loads them: in a fresh interpreter with
DJANGO_SETTINGS_MODULE=config.settings.prod (the test process itself runs on the dev settings)."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.core import checks
from django.test import SimpleTestCase, override_settings

from apps.core.checks import check_frontend_base_url

BACKEND = Path(__file__).resolve().parents[2]

# Syntactically valid but non-functional: what CI uses, and what production must never look like.
VALID_ENV = {
    'SECRET_KEY': 's' * 60,
    'JWT_SIGNING_KEY': 'j' * 60,
    'FRONTEND_BASE_URL': 'https://www.pglive.in',
    'RAZORPAY_KEY_ID': 'rzp_live_CIonlyNotReal00',
    'RAZORPAY_KEY_SECRET': 'ci-razorpay-secret-0123456789',
    'RAZORPAY_WEBHOOK_SECRET': 'ci-razorpay-webhook-0123456789',
}


def run_prod(args, **env_overrides):
    env = {
        'PATH': os.environ.get('PATH', ''),
        'DJANGO_SETTINGS_MODULE': 'config.settings.prod',
        **VALID_ENV,
        **env_overrides,
    }
    env = {key: value for key, value in env.items() if value is not None}
    return subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120,
    )


PRINT_SETTINGS = """
import json, django
django.setup()
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from apps.subscriptions import razorpay_client
try:
    razorpay_client.get_client()
    client = 'created'
except ImproperlyConfigured:
    client = 'refused'
print(json.dumps({
    'kyc': settings.KYC_UPLOADS_ENABLED,
    'unsigned_webhooks': settings.RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS,
    'email_timeout': settings.EMAIL_TIMEOUT,
    'reset_timeout': settings.PASSWORD_RESET_TIMEOUT,
    'docs_auth': settings.SPECTACULAR_SETTINGS['SERVE_AUTHENTICATION'],
    'docs_perms': settings.SPECTACULAR_SETTINGS['SERVE_PERMISSIONS'],
    'client': client,
}))
"""


class ProductionDeployCheckTests(SimpleTestCase):
    def test_valid_configuration_passes_the_deploy_check(self):
        result = run_prod(['manage.py', 'check', '--deploy', '--fail-level', 'ERROR'])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_each_kind_of_misconfiguration_fails_it(self):
        cases = {
            'subscriptions.E001': {'RAZORPAY_KEY_ID': ''},
            'subscriptions.E003': {'RAZORPAY_KEY_SECRET': 'placeholder'},
            'core.E001': {'FRONTEND_BASE_URL': 'http://www.pglive.in'},
        }
        for check_id, overrides in cases.items():
            with self.subTest(check=check_id):
                result = run_prod(['manage.py', 'check', '--deploy', '--fail-level', 'ERROR'], **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(check_id, result.stderr + result.stdout)

    def test_the_default_frontend_url_fails_it(self):
        result = run_prod(['manage.py', 'check', '--deploy', '--fail-level', 'ERROR'], FRONTEND_BASE_URL=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('core.E001', result.stderr + result.stdout)

    def test_jobs_that_never_use_razorpay_or_email_still_load_with_only_the_django_keys(self):
        """migrate, bootstrap, exports and the image build set nothing else."""
        result = run_prod(
            ['manage.py', 'diffsettings'],
            RAZORPAY_KEY_ID=None, RAZORPAY_KEY_SECRET=None, RAZORPAY_WEBHOOK_SECRET=None, FRONTEND_BASE_URL=None,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class ProductionSettingsValuesTests(SimpleTestCase):
    def setUp(self):
        result = run_prod(['-c', PRINT_SETTINGS])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.values = json.loads(result.stdout.strip().splitlines()[-1])

    def test_kyc_uploads_are_off_by_default(self):
        self.assertIs(self.values['kyc'], False)

    def test_unsigned_razorpay_webhooks_are_never_accepted(self):
        self.assertIs(self.values['unsigned_webhooks'], False)
        forced = run_prod(['-c', PRINT_SETTINGS], RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS='true')
        self.assertIs(json.loads(forced.stdout.strip().splitlines()[-1])['unsigned_webhooks'], False)

    def test_a_hung_smtp_server_cannot_hold_a_request_thread(self):
        self.assertEqual(self.values['email_timeout'], 10)

    def test_reset_links_last_24_hours(self):
        self.assertEqual(self.values['reset_timeout'], 24 * 60 * 60)

    def test_the_api_docs_need_a_django_admin_session(self):
        self.assertEqual(self.values['docs_auth'], ['rest_framework.authentication.SessionAuthentication'])
        self.assertEqual(self.values['docs_perms'], ['rest_framework.permissions.IsAdminUser'])

    def test_razorpay_never_falls_back_to_the_local_stub(self):
        blank = run_prod(['-c', PRINT_SETTINGS], RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
        self.assertEqual(json.loads(blank.stdout.strip().splitlines()[-1])['client'], 'refused')
        self.assertEqual(self.values['client'], 'created')


class StartApiScriptTests(SimpleTestCase):
    script = (BACKEND / 'bin' / 'start-api.sh').read_text(encoding='utf-8')

    def test_it_runs_the_deploy_check_before_it_starts_gunicorn(self):
        check = self.script.index('manage.py check --deploy --fail-level ERROR')
        serve = self.script.index('exec gunicorn')
        self.assertLess(check, serve)
        self.assertIn('set -e', self.script)

    def test_the_production_image_starts_through_it(self):
        dockerfile = (BACKEND / 'Dockerfile.prod').read_text(encoding='utf-8')
        self.assertIn('CMD ["sh", "bin/start-api.sh"]', dockerfile)


class FrontendBaseUrlCheckTests(SimpleTestCase):
    def ids(self, url):
        with override_settings(FRONTEND_BASE_URL=url):
            return [error.id for error in check_frontend_base_url(None)]

    def test_https_passes(self):
        self.assertEqual(self.ids('https://www.pglive.in'), [])

    def test_http_and_localhost_fail(self):
        self.assertEqual(self.ids('http://www.pglive.in'), ['core.E001'])
        self.assertEqual(self.ids('http://localhost:3000'), ['core.E001'])
        self.assertEqual(self.ids(''), ['core.E001'])

    def test_it_is_a_deploy_only_check(self):
        from django.core.checks import registry

        self.assertIn(check_frontend_base_url, registry.registry.get_checks(include_deployment_checks=True))
        self.assertNotIn(check_frontend_base_url, registry.registry.get_checks(include_deployment_checks=False))


class RegisteredChecksTests(SimpleTestCase):
    def test_django_collects_both_deploy_checks(self):
        messages = checks.run_checks(include_deployment_checks=True)
        with override_settings(FRONTEND_BASE_URL='http://x', RAZORPAY_KEY_ID=''):
            ids = {message.id for message in checks.run_checks(include_deployment_checks=True)}
        self.assertTrue({'core.E001', 'subscriptions.E001'} <= ids)
        self.assertIsInstance(messages, list)
