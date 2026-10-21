"""Auth emails sent from Celery: the signup "welcome" notification (Module 14),
verification emails, and email sign-in codes. Lives here (not
apps.notifications) because these reuse the account/token logic.

Every task re-checks on the worker whether the email should still go out — the
account can change between queueing and running — and delivers through
`_deliver`, which owns retries. Callers dispatching from a transaction must use
transaction.on_commit (capturing plain values, never model objects), so a job
never runs before its rows commit."""
import logging
from enum import Enum
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings

from apps.core.authentication import BLOCKED_TENANT_STATUSES
from apps.core.tenancy import tenant_context

from .normalization import normalize_email

logger = logging.getLogger(__name__)

EMAIL_TASK_MAX_RETRIES = 2
EMAIL_TASK_RETRY_COUNTDOWN_S = 5


class DeliveryResult(str, Enum):
    """What a delivery attempt did. Internal: tasks return None, so this never
    reaches the Celery result backend (str-based so it would serialize anyway)."""

    SENT = 'sent'
    SKIPPED = 'skipped'
    FAILED = 'failed'


def _deliver(task, fn, *args):
    """Run `fn(*args)` (returns SENT or SKIPPED) for a bound task. SMTP/OS errors
    are retried when running on a worker; in eager mode (dev/test, with
    CELERY_TASK_EAGER_PROPAGATES the task runs inside the HTTP request, where
    raising would turn one address into a 500) or once retries are exhausted
    they are logged and reported as FAILED. Logs never carry the address."""
    try:
        return fn(*args)
    except (SMTPException, OSError) as exc:
        if not task.request.is_eager and task.request.retries < task.max_retries:
            raise task.retry(exc=exc, countdown=EMAIL_TASK_RETRY_COUNTDOWN_S)
        logger.error('%s: email could not be delivered: %s', task.name, type(exc).__name__)
        return DeliveryResult.FAILED


def _send_verification(user):
    from .emails import send_verification_email

    send_verification_email(user)
    return DeliveryResult.SENT


def _verification_target(user_id, expected_email):
    """The account a lifecycle verification email is for, if it should still
    get one: active, unverified, and still holding the address the email was
    queued for. If the address changed or moved to another account while the
    job sat in the queue, the job must not mail a link for it. A job without
    `expected_email` (queued before it was passed) can't prove which address it
    was for, so it is dropped; the owner can request a link from sign-in."""
    from .models import User

    if expected_email is None:
        return None
    user = User.objects.filter(pk=user_id).first()
    if user is None or not user.is_active or user.email_verified or not user.email:
        return None
    if normalize_email(user.email) != normalize_email(expected_email):
        return None
    return user


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_welcome_email_task(self, user_id, expected_email=None):
    """Signup. The verification email opens with "Welcome, <name>!" and is the
    one email a brand-new signup gets, so it doubles as the welcome
    notification (Module 14 Decisions). It is recorded as sent only when it
    actually was. `expected_email` defaults to None only so a pre-deploy
    one-argument job is skipped instead of failing with a TypeError."""
    from apps.notifications.services import record_sent

    user = _verification_target(user_id, expected_email)
    if user is None:
        return
    with tenant_context(user.tenant_id):
        if _deliver(self, _send_verification, user) is DeliveryResult.SENT:
            record_sent(
                tenant_id=user.tenant_id,
                notification_type='welcome',
                recipient_email=user.email or '',
                recipient_user=user,
                subject='Verify your email address',
                reference=f'user:{user.id}',
            )


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_verification_email_to_user_task(self, user_id, expected_email):
    """Account lifecycle: staff creation, Django-admin create / "send" action /
    email change. Bound to the account and the address it was queued for."""
    user = _verification_target(user_id, expected_email)
    if user is not None:
        _deliver(self, _send_verification, user)


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_verification_email_to_address_task(self, email):
    """Anonymous resend: whichever active, unverified account owns the address
    now. Queued for every requested address alike; silent for the rest."""
    from .models import User

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is not None and not user.email_verified:
        _deliver(self, _send_verification, user)


def _can_use_email_login(user, email):
    """Email code login is for tenant users only: Super Admins (no tenant) sign
    in through Django admin behind IAP. Checked on the row `otp.issue` has
    locked, so the answer can't go stale before the code is created."""
    return (
        user.is_active
        and user.tenant_id is not None
        and user.tenant.status not in BLOCKED_TENANT_STATUSES
        and (user.email or '').lower() == email
    )


def deliver_login_code(email):
    """Issue an email login code for `email` and send it. Silent for any
    address that can't use email login — the request endpoint has already
    answered the same way for every address. The plaintext code is generated
    here, on the worker, so it never sits in the broker payload. SMTP errors
    propagate to the task, which decides whether to retry."""
    from . import otp
    from .emails import send_login_code_email
    from .models import User

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return DeliveryResult.SKIPPED
    code = otp.issue(
        user, otp.Channel.EMAIL,
        still_eligible=lambda locked: _can_use_email_login(locked, email),
    )
    if code is None:
        return DeliveryResult.SKIPPED
    send_login_code_email(user, code)
    return DeliveryResult.SENT


# expires: the code must arrive within its lifetime, so a backlog older than
# that (e.g. a worker outage) is dropped rather than mailing dead codes.
@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES, expires=settings.OTP_TTL_SECONDS)
def send_login_code_task(self, email):
    """Queued by the email-code request endpoint for every address alike.
    Each retry issues a fresh code (invalidating the undelivered one), so if
    delayed emails arrive out of order only the newest code works. Neither the
    code nor the address is ever logged."""
    _deliver(self, deliver_login_code, email)
