"""Pre-traffic smoke test for a candidate release (docs/deployment.md, "Releases").

Run by the fixed Cloud Run Job `pglive-smoke` (service account sa-smoke, Direct VPC egress, no database,
no bucket, no Razorpay/FCM/application secrets): it hits the tagged candidate revisions, which are only
reachable from inside the VPC, and exits non-zero if anything is wrong. Standard library only on purpose —
Django's production settings need real keys, which this job must not hold.

Environment:
  SMOKE_API_URL   https://candidate---pglive-api-<hash>-el.a.run.app
  SMOKE_WEB_URL   https://candidate---pglive-web-<hash>-el.a.run.app
  SMOKE_USER_CREDENTIALS   {"email": "...", "password": "..."}  — the dedicated smoke account
Checks are GET-only apart from the login, so a bad release can't change data through it.
"""
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 20


def call(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        'Accept': 'application/json', **({'Content-Type': 'application/json'} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def run(api, web, credentials, report=print):
    failures = []

    def check(name, ok, detail=''):
        report(f'{"ok  " if ok else "FAIL"} {name}{": " + detail if detail and not ok else ""}')
        if not ok:
            failures.append(name)

    status, _, body = call('GET', f'{api}/health/ready/')
    check('api readiness', status == 200 and json.loads(body or b'{}').get('status') == 'ok', f'{status} {body[:200]!r}')
    status, _, _ = call('GET', f'{api}/api/v1/support/')
    check('api public support contacts', status == 200, str(status))
    status, _, _ = call('GET', f'{api}/api/v1/public/plans/')
    check('api public plan catalogue', status == 200, str(status))
    status, _, _ = call('GET', f'{api}/api/v1/residents/')
    check('api rejects anonymous access', status in (401, 403), str(status))

    status, _, body = call('POST', f'{api}/api/v1/auth/login/', credentials)
    token = json.loads(body or b'{}').get('access') if status == 200 else None
    check('smoke account can log in', bool(token), str(status))
    if token:
        status, _, body = call('GET', f'{api}/api/v1/auth/me/', headers={'Authorization': f'Bearer {token}'})
        check('authenticated /auth/me', status == 200 and json.loads(body or b'{}').get('email') == credentials['email'],
              str(status))

    status, _, body = call('GET', f'{web}/api/health')
    check('web health', status == 200, str(status))
    for path in ('/', '/login'):
        status, headers, _ = call('GET', f'{web}{path}', headers={'Accept': 'text/html'})
        lowered = {k.lower() for k in headers}
        check(f'web {path} renders with a CSP', status == 200 and (
            'content-security-policy' in lowered or 'content-security-policy-report-only' in lowered),
            f'{status} {sorted(lowered)}')
    return failures


def main():
    api = os.environ.get('SMOKE_API_URL', '').rstrip('/')
    web = os.environ.get('SMOKE_WEB_URL', '').rstrip('/')
    try:
        credentials = json.loads(os.environ.get('SMOKE_USER_CREDENTIALS', ''))
        credentials['email'], credentials['password']
    except (ValueError, KeyError, TypeError):
        print('SMOKE_USER_CREDENTIALS must be JSON with email and password', file=sys.stderr)
        return 2
    if not api or not web:
        print('SMOKE_API_URL and SMOKE_WEB_URL are required', file=sys.stderr)
        return 2
    failures = run(api, web, credentials)
    print(f'{len(failures)} check(s) failed' if failures else 'smoke test passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
