"""Trusted client IP (apps.core.net, WP7 in docs/deployment.md).

X-Forwarded-For is never trusted; the load balancer's own header is (when
configured), and the BFF's signed origin IP is (when it verifies). Requests
whose origin headers don't verify are rejected, never downgraded."""
import json
import time
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from . import net
from .models import ContactMessage

VECTORS = json.loads(
    (Path(__file__).parent / 'tests_fixtures' / 'origin_signature_vectors.json').read_text(encoding='utf-8')
)
SECRET = 'unit-test-origin-secret'


def origin_headers(ip, method, path, query='', ts=None, secret=SECRET, raw_uri=True):
    ts = str(int(time.time()) if ts is None else ts)
    meta = {
        'HTTP_X_PGLIVE_ORIGIN_IP': ip,
        'HTTP_X_PGLIVE_ORIGIN_TS': ts,
        'HTTP_X_PGLIVE_ORIGIN_SIG': net.sign(secret, ip, ts, method, path, query),
    }
    if raw_uri:
        meta['RAW_URI'] = path + (f'?{query}' if query else '')
    return meta


class SharedVectorTests(SimpleTestCase):
    """The frontend asserts the very same file (originSignature.test.ts)."""

    def test_canonical_strings_and_signatures(self):
        for case in VECTORS['signatures']:
            with self.subTest(case['name']):
                args = (case['ip'], case['ts'], case['method'], case['path'], case['query'])
                self.assertEqual(net.canonical_string(*args), case['canonical'])
                self.assertEqual(net.sign(VECTORS['secret'], *args), case['signature'])

    def test_ip_normalisation(self):
        for case in VECTORS['normalize_ip']:
            with self.subTest(case['input']):
                self.assertEqual(net.normalize_ip(case['input']), case['expected'])


@override_settings(BFF_ORIGIN_SECRET=SECRET)
class VerifyOriginTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, path='/api/v1/residents/', query='', method='get', **meta):
        return getattr(self.factory, method)(path + (f'?{query}' if query else ''), **meta)

    def test_valid_signature_returns_the_origin_ip(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/', 'page=2')
        self.assertEqual(net.verify_origin(self.request(query='page=2', **meta)), '203.0.113.9')

    def test_encoded_path_is_verified_against_the_raw_uri(self):
        path = '/api/v1/files/a%2Fb/'
        meta = origin_headers('203.0.113.9', 'GET', path)
        self.assertEqual(net.verify_origin(self.request(path=path, **meta)), '203.0.113.9')

    def assertRejected(self, request, reason_fragment):
        with self.assertRaises(net.OriginSignatureError) as ctx:
            net.verify_origin(request)
        self.assertIn(reason_fragment, ctx.exception.reason)

    def test_tampered_path_is_rejected(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/')
        meta['RAW_URI'] = '/api/v1/invoices/'
        self.assertRejected(self.request(**meta), 'signature mismatch')

    def test_tampered_method_is_rejected(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/')
        self.assertRejected(self.request(method='post', **meta), 'signature mismatch')

    def test_wrong_secret_is_rejected(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/', secret='someone-else')
        self.assertRejected(self.request(**meta), 'signature mismatch')

    def test_stale_and_future_timestamps_are_rejected(self):
        for skew in (-61, 61):
            with self.subTest(skew=skew):
                meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/', ts=int(time.time()) + skew)
                self.assertRejected(self.request(**meta), 'window')

    def test_missing_raw_uri_fails_closed(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/', raw_uri=False)
        self.assertRejected(self.request(**meta), 'raw request URI unavailable')

    def test_non_canonical_ip_is_rejected(self):
        meta = origin_headers('2001:DB8::1', 'GET', '/api/v1/residents/')
        self.assertRejected(self.request(**meta), 'canonical')

    def test_incomplete_headers_are_rejected(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/')
        del meta['HTTP_X_PGLIVE_ORIGIN_SIG']
        self.assertRejected(self.request(**meta), 'incomplete')

    @override_settings(BFF_ORIGIN_SECRET='')
    def test_without_a_configured_secret_origin_headers_are_rejected(self):
        meta = origin_headers('203.0.113.9', 'GET', '/api/v1/residents/')
        self.assertRejected(self.request(**meta), 'no BFF_ORIGIN_SECRET')


class EdgeIPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_x_forwarded_for_is_ignored(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.5', HTTP_X_FORWARDED_FOR='198.51.100.7')
        self.assertEqual(net.get_client_ip(request), '10.0.0.5')

    @override_settings(CLIENT_IP_HEADER='X-PGLive-Client-IP')
    def test_load_balancer_header_is_used_when_configured(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.5', HTTP_X_PGLIVE_CLIENT_IP='203.0.113.9',
                                   HTTP_X_FORWARDED_FOR='198.51.100.7')
        self.assertEqual(net.get_client_ip(request), '203.0.113.9')

    @override_settings(CLIENT_IP_HEADER='X-PGLive-Client-IP')
    def test_garbage_load_balancer_header_falls_back_to_remote_addr(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.5', HTTP_X_PGLIVE_CLIENT_IP='not-an-ip')
        self.assertEqual(net.get_client_ip(request), '10.0.0.5')

    def test_load_balancer_header_is_ignored_when_not_configured(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.5', HTTP_X_PGLIVE_CLIENT_IP='203.0.113.9')
        self.assertEqual(net.get_client_ip(request), '10.0.0.5')


@override_settings(BFF_ORIGIN_SECRET=SECRET, CLIENT_IP_HEADER='X-PGLive-Client-IP')
class ClientIPMiddlewareTests(APITestCase):
    """End to end through the public contact form, which stores the caller's IP."""

    url = reverse('contact-message')
    body = {'name': 'Ravi Kumar', 'email': 'ravi@example.com',
            'message': 'I run a 60-bed PG in Hyderabad and would like early access.'}

    def setUp(self):
        cache.clear()
        patcher = mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES,
                                  {'contact_message': '1000/hour', 'contact_message_email': '1000/hour'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **meta):
        return self.client.post(self.url, self.body, format='json', **meta)

    def test_signed_origin_ip_is_recorded(self):
        meta = origin_headers('203.0.113.9', 'POST', self.url)
        response = self.post(HTTP_X_PGLIVE_CLIENT_IP='35.191.0.10', **meta)  # LB saw the BFF
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ContactMessage.objects.get().ip_address, '203.0.113.9')

    def test_direct_call_records_the_load_balancer_client_ip(self):
        self.assertEqual(self.post(HTTP_X_PGLIVE_CLIENT_IP='198.51.100.20',
                                   HTTP_X_FORWARDED_FOR='1.2.3.4').status_code, 201)
        self.assertEqual(ContactMessage.objects.get().ip_address, '198.51.100.20')

    def test_forged_origin_headers_are_rejected_and_nothing_is_stored(self):
        meta = origin_headers('203.0.113.9', 'POST', self.url, secret='guessed')
        response = self.post(HTTP_X_PGLIVE_CLIENT_IP='198.51.100.20', **meta)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'INVALID_ORIGIN_SIGNATURE')
        self.assertFalse(ContactMessage.objects.exists())

    def test_spoofed_x_forwarded_for_does_not_escape_the_ip_throttle(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'contact_message': '2/hour'}):
            statuses = [
                self.client.post(self.url, {**self.body, 'email': f'p{n}@example.com'}, format='json',
                                 HTTP_X_PGLIVE_CLIENT_IP='198.51.100.20',
                                 HTTP_X_FORWARDED_FOR=f'10.9.9.{n}').status_code
                for n in range(3)
            ]
        self.assertEqual(statuses, [201, 201, 429])
