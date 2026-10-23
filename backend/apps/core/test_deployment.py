"""Production-readiness pieces (docs/deployment.md, Phase 1): health probes,
IAP on /admin/, GCS signed URLs, bootstrap, fail-open Redis, safe enqueue,
JSON logging."""
import io
import json
import logging
import time
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from google.auth import crypt, jwt
from google.oauth2 import service_account
from kombu.exceptions import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from . import iap
from .cache import FailOpenRedisCache
from .log_format import CloudLoggingFormatter, scrub
from .storage import signed_url
from .tasks import enqueue


class HealthTests(TestCase):
    def test_liveness_needs_no_auth(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertIn('no-cache', response['Cache-Control'])

    def test_readiness_checks_the_database(self):
        response = self.client.get('/health/ready/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['checks'], {'database': 'ok'})

    @override_settings(REQUIRE_RAW_URI=True)
    def test_readiness_fails_without_raw_uri_when_required(self):
        # Django's test client is not gunicorn, so RAW_URI is absent.
        response = self.client.get('/health/ready/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['raw_uri'], 'missing')
        self.assertEqual(self.client.get('/health/ready/', RAW_URI='/health/ready/').status_code, 200)

    def test_readiness_reports_a_database_failure(self):
        with mock.patch('apps.core.health._database_ok', return_value=False):
            response = self.client.get('/health/ready/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['database'], 'error')


AUDIENCE = '/projects/123/global/backendServices/456'


def _es256_keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    return private_pem, public_pem.decode()


class IAPAdminMiddlewareTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_pem, cls.public_pem = _es256_keypair()
        cls.signer = crypt.ES256Signer.from_string(cls.private_pem, key_id='kid-1')

    def setUp(self):
        iap._certs.update(keys={}, fetched_at=0.0)
        patcher = mock.patch.object(iap, '_fetch_certs', return_value={'kid-1': self.public_pem})
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def assertion(self, **overrides):
        now = int(time.time())
        claims = {'iss': iap.IAP_ISSUER, 'aud': AUDIENCE, 'email': 'admin@pglive.in',
                  'sub': 'accounts.google.com:1', 'iat': now, 'exp': now + 600, **overrides}
        return jwt.encode(self.signer, claims).decode()

    def get_admin(self, assertion=None):
        meta = {'HTTP_X_GOOG_IAP_JWT_ASSERTION': assertion} if assertion else {}
        return self.client.get('/admin/', **meta)

    def test_not_enforced_outside_prod(self):
        self.assertEqual(self.get_admin().status_code, 302)  # to the admin login

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_valid_assertion_reaches_admin(self):
        self.assertEqual(self.get_admin(self.assertion()).status_code, 302)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_missing_assertion_is_refused(self):
        self.assertEqual(self.get_admin().status_code, 403)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_wrong_audience_issuer_or_expiry_is_refused(self):
        for overrides in ({'aud': '/projects/123/global/backendServices/999'},
                          {'iss': 'https://evil.example'},
                          {'iat': int(time.time()) - 7200, 'exp': int(time.time()) - 3600}):
            with self.subTest(overrides=list(overrides)):
                self.assertEqual(self.get_admin(self.assertion(**overrides)).status_code, 403)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_assertion_signed_by_another_key_is_refused(self):
        other_private, _ = _es256_keypair()
        forged = jwt.encode(crypt.ES256Signer.from_string(other_private, key_id='kid-1'),
                            {'iss': iap.IAP_ISSUER, 'aud': AUDIENCE, 'iat': int(time.time()),
                             'exp': int(time.time()) + 600}).decode()
        self.assertEqual(self.get_admin(forged).status_code, 403)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE='')
    def test_required_without_audience_fails_closed(self):
        self.assertEqual(self.get_admin(self.assertion()).status_code, 403)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_other_paths_are_not_gated(self):
        self.assertEqual(self.client.get('/health/').status_code, 200)

    @override_settings(IAP_REQUIRED=True, IAP_AUDIENCE=AUDIENCE)
    def test_public_keys_are_cached(self):
        self.get_admin(self.assertion())
        self.get_admin(self.assertion())
        self.assertEqual(self.fetch.call_count, 1)


def _fake_service_account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return service_account.Credentials.from_service_account_info({
        'type': 'service_account', 'project_id': 'test', 'private_key_id': '1', 'private_key': pem,
        'client_email': 'sa-api@test.iam.gserviceaccount.com', 'client_id': '1',
        'token_uri': 'https://oauth2.googleapis.com/token',
    })


class GCSSignedURLTests(SimpleTestCase):
    """Signing happens locally with a throwaway key — no network. In prod the
    same URLs are signed through IAM SignBlob (GS_IAM_SIGN_BLOB)."""

    def storage(self, **settings):
        from storages.backends.gcloud import GoogleCloudStorage
        defaults = dict(bucket_name='pglive-test-media', project_id='test', credentials=_fake_service_account(),
                        querystring_auth=True, default_acl=None, expiration=timedelta(seconds=300),
                        iam_sign_blob=False)
        return GoogleCloudStorage(**{**defaults, **settings})

    def field_file(self, storage, name='residents/t1/r1/aadhaar.pdf'):
        field_file = mock.Mock(storage=storage)
        field_file.name = name  # Mock(name=...) would only set the repr name
        return field_file

    def query(self, url):
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    def test_default_urls_expire_after_five_minutes(self):
        url = self.storage().url('residents/t1/r1/aadhaar.pdf')
        params = self.query(url)
        self.assertEqual(params['X-Goog-Expires'], '300')
        self.assertEqual(params['X-Goog-Algorithm'], 'GOOG4-RSA-SHA256')
        self.assertIn('X-Goog-Signature', params)

    def test_signed_url_helper_can_shorten_the_ttl(self):
        url = signed_url(self.field_file(self.storage()), ttl_seconds=60)
        self.assertEqual(self.query(url)['X-Goog-Expires'], '60')

    def test_signed_url_helper_defaults_to_the_media_ttl(self):
        url = signed_url(self.field_file(self.storage()))
        self.assertEqual(self.query(url)['X-Goog-Expires'], '300')

    def test_never_a_public_url(self):
        url = self.storage().url('complaints/t1/c1/photo.jpg')
        self.assertIn('X-Goog-Signature', url)
        self.assertTrue(url.startswith('https://storage.googleapis.com/pglive-test-media/'))

    def test_local_storage_returns_the_media_url(self):
        from django.core.files.storage import FileSystemStorage
        field_file = mock.Mock(storage=FileSystemStorage(), url='/media/x.pdf')
        field_file.name = 'x.pdf'
        self.assertEqual(signed_url(field_file), '/media/x.pdf')

    def test_production_settings_enable_iam_signing_and_five_minute_expiry(self):
        from config.settings import base
        source = open(base.__file__, encoding='utf-8').read()
        self.assertIn("GS_IAM_SIGN_BLOB = env.bool('GS_IAM_SIGN_BLOB', default=True)", source)
        self.assertIn('GS_EXPIRATION = timedelta(seconds=MEDIA_URL_TTL_SECONDS)', source)
        self.assertIn('GS_DEFAULT_ACL = None', source)


class BootstrapPlatformTests(TestCase):
    env = {'INITIAL_SUPERADMIN_EMAIL': 'root@pglive.in', 'INITIAL_SUPERADMIN_PASSWORD': 'Kq7#vTz!9pLm2&Ww'}

    def run_command(self, **env):
        out = io.StringIO()
        with mock.patch.dict('os.environ', env, clear=False):
            call_command('bootstrap_platform', stdout=out)
        return out.getvalue()

    def test_creates_super_admin_with_audit_entry_and_never_prints_the_password(self):
        output = self.run_command(**self.env)
        user = get_user_model().objects.get(email='root@pglive.in')
        self.assertEqual(user.role, Role.SUPER_ADMIN)
        self.assertIsNone(user.tenant_id)
        self.assertTrue(user.check_password(self.env['INITIAL_SUPERADMIN_PASSWORD']))
        self.assertNotIn(self.env['INITIAL_SUPERADMIN_PASSWORD'], output)
        with tenant_context(None, is_super_admin=True):
            self.assertTrue(AuditLog.objects.filter(action='platform.superadmin_bootstrapped',
                                                    object_id=str(user.pk)).exists())

    def test_is_idempotent_and_never_resets_an_existing_admin(self):
        self.run_command(**self.env)
        output = self.run_command(INITIAL_SUPERADMIN_EMAIL='root@pglive.in',
                                  INITIAL_SUPERADMIN_PASSWORD='Another#Strong9Pass')
        self.assertIn('already exists', output)
        user = get_user_model().objects.get(email='root@pglive.in')
        self.assertTrue(user.check_password(self.env['INITIAL_SUPERADMIN_PASSWORD']))
        self.assertEqual(get_user_model().objects.filter(role=Role.SUPER_ADMIN).count(), 1)

    def test_requires_credentials_and_a_strong_password(self):
        with mock.patch.dict('os.environ', {}, clear=False) as environ:
            environ.pop('INITIAL_SUPERADMIN_EMAIL', None)
            environ.pop('INITIAL_SUPERADMIN_PASSWORD', None)
            with self.assertRaises(CommandError):
                call_command('bootstrap_platform', stdout=io.StringIO())
        with self.assertRaises(CommandError):
            self.run_command(INITIAL_SUPERADMIN_EMAIL='root@pglive.in', INITIAL_SUPERADMIN_PASSWORD='12345')
        self.assertFalse(get_user_model().objects.filter(role=Role.SUPER_ADMIN).exists())


class FailOpenCacheTests(SimpleTestCase):
    def test_redis_errors_become_cache_misses(self):
        cache = FailOpenRedisCache('redis://127.0.0.1:1/0', {})
        broken = mock.Mock(side_effect=RedisConnectionError('down'))
        with mock.patch('django.core.cache.backends.redis.RedisCache.get', broken), \
             mock.patch('django.core.cache.backends.redis.RedisCache.set', broken), \
             mock.patch('django.core.cache.backends.redis.RedisCache.add', broken), \
             self.assertLogs('apps.core.cache', level='WARNING'):
            self.assertEqual(cache.get('throttle_login_1.2.3.4', []), [])
            self.assertIsNone(cache.set('k', 'v'))
            self.assertFalse(cache.add('k', 'v'))


class EnqueueTests(SimpleTestCase):
    def test_broker_outage_is_logged_not_raised(self):
        task = mock.Mock(name='task')
        task.name = 'notifications.send_email'
        task.delay.side_effect = OperationalError('connection refused')
        with self.assertLogs('apps.core.tasks', level='ERROR'):
            self.assertIsNone(enqueue(task, 'abc'))

    def test_other_errors_still_raise(self):
        task = mock.Mock()
        task.delay.side_effect = ValueError('bug')
        with self.assertRaises(ValueError):
            enqueue(task)


class CloudLoggingFormatterTests(SimpleTestCase):
    def test_emits_json_with_severity_and_scrubs_pii(self):
        record = logging.LogRecord('apps.residents', logging.WARNING, __file__, 1,
                                   'Resident %s aadhaar %s pan %s phone %s token %s',
                                   ('ravi@example.com', '1234 5678 9012', 'ABCDE1234F', '+91 98765 43210',
                                    'Bearer eyJhbGciOi.eyJzdWIiOi.sig'), None)
        entry = json.loads(CloudLoggingFormatter().format(record))
        self.assertEqual(entry['severity'], 'WARNING')
        self.assertEqual(entry['logger'], 'apps.residents')
        for secret in ('ravi@example.com', '1234 5678 9012', 'ABCDE1234F', '98765 43210', 'eyJ'):
            self.assertNotIn(secret, entry['message'])
        self.assertIn('[aadhaar]', entry['message'])

    def test_scrub_leaves_ordinary_numbers_alone(self):
        self.assertEqual(scrub('Invoice 2026-10 total 4500.00 for 3 beds'), 'Invoice 2026-10 total 4500.00 for 3 beds')
