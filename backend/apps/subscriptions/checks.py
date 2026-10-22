"""Deploy-time check (`manage.py check --deploy`) for the Razorpay settings.

Production must never run on the local stub client, with a forgeable webhook, or on a test-mode
key, so a revision with missing, malformed, placeholder or wrong-mode keys must refuse to start
(backend/bin/start-api.sh runs this check before gunicorn) rather than quietly bill nobody or bill
for real against a test key. It lives in a system check rather than in settings so that jobs which
never touch Razorpay (migrate, bootstrap, exports, the image build) don't need the keys.

Staging intentionally runs on Razorpay test keys (infra/README.md), so the live-mode requirement
is itself a setting (RAZORPAY_REQUIRE_LIVE_MODE) rather than hardcoded — prod.py defaults it to
True, infra/30-services.sh sets it to false for a staging deploy.
"""
import re

from django.conf import settings
from django.core.checks import Error, Tags, register

KEY_ID_RE = re.compile(r'^rzp_(live|test)_[A-Za-z0-9]{14,}$')
# Wording that marks a value somebody forgot to replace (the deployment manual's examples use these).
PLACEHOLDER_MARKERS = ('placeholder', 'changeme', 'change-me', 'replace-me', 'your-', 'your_', 'xxxx', 'todo')


def _is_placeholder(value):
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _secret_problem(name, value):
    if not value:
        return f'{name} is not set.'
    if _is_placeholder(value):
        return f'{name} still holds a placeholder value.'
    return None


@register(Tags.security, deploy=True)
def check_razorpay_settings(app_configs, **kwargs):
    problems = []

    key_id = settings.RAZORPAY_KEY_ID
    if not key_id:
        problems.append(('E001', 'RAZORPAY_KEY_ID is not set.'))
    elif not KEY_ID_RE.match(key_id) or _is_placeholder(key_id):
        problems.append(('E002', 'RAZORPAY_KEY_ID is not a Razorpay key id (expected rzp_live_… or rzp_test_…).'))
    elif settings.RAZORPAY_REQUIRE_LIVE_MODE and not key_id.startswith('rzp_live_'):
        problems.append(('E006', 'RAZORPAY_KEY_ID is a test-mode key; this environment requires rzp_live_….'))

    for code, name in (('E003', 'RAZORPAY_KEY_SECRET'), ('E004', 'RAZORPAY_WEBHOOK_SECRET')):
        problem = _secret_problem(name, getattr(settings, name))
        if problem:
            problems.append((code, problem))

    if settings.RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS:
        problems.append(('E005', 'RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS must be False in production.'))

    return [
        Error(message, hint='Set the Razorpay credentials in Secret Manager (docs/deployment.md).', id=f'subscriptions.{code}')
        for code, message in problems
    ]
