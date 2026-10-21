"""Module 14: the signup "welcome" notification (PRD Module 18 MVP). Lives
here (not apps.notifications) because it reuses the existing verification
email, which owns the User/token logic. Runs off the request thread via
Celery; the caller must dispatch it with transaction.on_commit so it never
fires before the signup transaction (and the User row) actually commits."""
import logging
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings

from apps.core.authentication import BLOCKED_TENANT_STATUSES
from apps.core.tenancy import tenant_context

logger = logging.getLogger(__name__)

LOGIN_CODE_MAX_RETRIES = 2
LOGIN_CODE_RETRY_COUNTDOWN_S = 5


@shared_task
def send_welcome_email_task(user_id):
    from apps.notifications.services import record_sent

    from .emails import send_verification_email
    from .models import User

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    with tenant_context(user.tenant_id):
        # The verification email already opens with "Welcome, <name>!" — this
        # is the one email a brand-new signup gets, so it doubles as the
        # welcome notification rather than sending a redundant second email
        # (see the Module 14 spec's Decisions). record_sent logs it without
        # sending anything itself.
        send_verification_email(user)
        record_sent(
            tenant_id=user.tenant_id,
            notification_type='welcome',
            recipient_email=user.email or '',
            recipient_user=user,
            subject='Verify your email address',
            reference=f'user:{user.id}',
        )


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
        return
    code = otp.issue(
        user, otp.Channel.EMAIL,
        still_eligible=lambda locked: _can_use_email_login(locked, email),
    )
    if code is None:
        return
    send_login_code_email(user, code)


# expires: the code must arrive within its lifetime, so a backlog older than
# that (e.g. a worker outage) is dropped rather than mailing dead codes.
@shared_task(bind=True, max_retries=LOGIN_CODE_MAX_RETRIES, expires=settings.OTP_TTL_SECONDS)
def send_login_code_task(self, email):
    """Queued by the email-code request endpoint for every address alike.
    Each retry issues a fresh code (invalidating the undelivered one), so if
    delayed emails arrive out of order only the newest code works."""
    try:
        deliver_login_code(email)
    except (SMTPException, OSError) as exc:
        # Eager mode (dev/test, CELERY_TASK_EAGER_PROPAGATES) runs this inside
        # the HTTP request: raising would turn a registered address into a 500
        # while unknown ones get 200. Log instead; production retries below.
        if not self.request.is_eager and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=LOGIN_CODE_RETRY_COUNTDOWN_S)
        # Neither the code nor the address goes in the log.
        logger.error('Login code email could not be delivered: %s', type(exc).__name__)
