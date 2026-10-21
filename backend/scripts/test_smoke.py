"""scripts/smoke.py against a fake release: a good one passes, each kind of breakage fails.
Run with:  python -m unittest scripts.test_smoke   (inside backend/)"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts import smoke

CREDENTIALS = {'email': 'smoke@pglive.in', 'password': 'pw'}


def make_handler(overrides):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body=b'{}', headers=None):
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def route(self):
            key = f'{self.command} {self.path}'
            if key in overrides:
                return self.respond(*overrides[key])
            routes = {
                'GET /health/ready/': (200, b'{"status": "ok"}'),
                'GET /api/v1/support/': (200,),
                'GET /api/v1/public/plans/': (200,),
                'GET /api/v1/residents/': (401,),
                'POST /api/v1/auth/login/': (200, b'{"access": "tok"}'),
                'GET /api/v1/auth/me/': (200, json.dumps({'email': CREDENTIALS['email']}).encode()),
                'GET /api/health': (200,),
                'GET /': (200, b'<html></html>', {'Content-Security-Policy-Report-Only': "default-src 'self'"}),
                'GET /login': (200, b'<html></html>', {'Content-Security-Policy-Report-Only': "default-src 'self'"}),
            }
            self.respond(*routes.get(key, (404,)))

        do_GET = do_POST = route

    return Handler


class SmokeTests(unittest.TestCase):
    def run_against(self, overrides=None):
        server = HTTPServer(('127.0.0.1', 0), make_handler(overrides or {}))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        lines = []
        return smoke.run(url, url, CREDENTIALS, report=lines.append), lines

    def test_healthy_release_passes(self):
        failures, _ = self.run_against()
        self.assertEqual(failures, [])

    def test_each_breakage_is_caught(self):
        cases = {
            'api readiness': {'GET /health/ready/': (503, b'{"status": "error"}')},
            'smoke account can log in': {'POST /api/v1/auth/login/': (401,)},
            'api rejects anonymous access': {'GET /api/v1/residents/': (200,)},
            'web / renders with a CSP': {'GET /': (200, b'<html></html>')},
            'web health': {'GET /api/health': (500,)},
            'authenticated /auth/me': {'GET /api/v1/auth/me/': (200, b'{"email": "someone@else.in"}')},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                failures, _ = self.run_against(overrides)
                self.assertIn(name, failures)

    def test_main_requires_configuration(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'SMOKE_API_URL': '', 'SMOKE_WEB_URL': '', 'SMOKE_USER_CREDENTIALS': ''}):
            self.assertEqual(smoke.main(), 2)


if __name__ == '__main__':
    unittest.main()
