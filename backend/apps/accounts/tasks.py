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


def _send_password_reset(user):
    from .emails import send_password_reset_email

    send_password_reset_email(user)
    return DeliveryResult.SENT


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_password_reset_task(self, email):
    """Queued by the reset-request endpoint for every address alike, so the
    response never reveals whether one is registered (and an SMTP outage can't
    surface as an error for registered addresses only). Tenant users only:
    Super Admins use Django admin behind IAP, and a suspended tenant's users
    can't sign in anyway."""
    from .models import User

    user = User.objects.select_related('tenant').filter(email__iexact=email, is_active=True).first()
    if (
        user is None
        or user.tenant_id is None
        or user.tenant.status in BLOCKED_TENANT_STATUSES
    ):
        return
    _deliver(self, _send_password_reset, user)


def _send_staff_invite(user):
    from .emails import send_staff_invite_email

    send_staff_invite_email(user, user.tenant)
    return DeliveryResult.SENT


def _invite_target(user_id, expected_email):
    """The staff account an invite is still for: active, in an eligible tenant,
    still holding the address it was queued for, and with no password set yet
    (an invite is how they set the first one)."""
    from .models import User

    if expected_email is None:
        return None
    user = User.objects.select_related('tenant').filter(pk=user_id).first()
    if user is None or not user.is_active or not user.email or user.tenant_id is None:
        return None
    if user.tenant.status in BLOCKED_TENANT_STATUSES or user.has_usable_password():
        return None
    if normalize_email(user.email) != normalize_email(expected_email):
        return None
    return user


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_staff_invite_task(self, user_id, expected_email):
    """Queued (on commit) when an owner creates staff without a password. Bound
    to the account and address it was queued for, like the verification emails."""
    user = _invite_target(user_id, expected_email)
    if user is not None:
        _deliver(self, _send_staff_invite, user)


def _send_password_changed(user):
    from .emails import send_password_changed_email

    send_password_changed_email(user)
    return DeliveryResult.SENT


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_password_changed_task(self, user_id, expected_email):
    """Security notice after a reset or a change. Sent whatever the tenant's
    state (the owner of the address should always hear about it), but only to
    the address that was on the account when the password changed."""
    from .models import User

    if expected_email is None:
        return
    user = User.objects.filter(pk=user_id).first()
    if user is None or not user.is_active or not user.email:
        return
    if normalize_email(user.email) != normalize_email(expected_email):
        return
    _deliver(self, _send_password_changed, user)


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


# --- Account deletion (Module 22) ------------------------------------------------------------
def _send_deletion_requested(user, deletion):
    from .emails import send_account_deletion_requested_email

    send_account_deletion_requested_email(user, deletion)
    return DeliveryResult.SENT


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_account_deletion_requested_task(self, request_id):
    """Confirmation of a new request. Courtesy only (the date is also shown in the app), so it is
    queued best-effort; skipped if the request is no longer pending or the user has no email."""
    from .models import AccountDeletionRequest

    deletion = AccountDeletionRequest.objects.select_related('user').filter(pk=request_id).first()
    if deletion is None or deletion.status != AccountDeletionRequest.Status.PENDING:
        return
    user = deletion.user
    if user is None or not user.email:
        return
    _deliver(self, _send_deletion_requested, user, deletion)


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_account_deletion_begun_task(self, request_id, address, channel, language):
    """"Your deletion has started and can no longer be cancelled." Takes the address as an argument
    because the account may already be gone when this runs; it travels in the broker message only
    (Redis, until a worker consumes it) and is never stored. Delivery is best effort."""
    from .emails import send_account_deletion_begun_email

    if channel != 'email' or not address:
        return  # SMS has no backend yet (otp.sms_delivery_available)
    _deliver(self, lambda: (send_account_deletion_begun_email(address, language), DeliveryResult.SENT)[1])


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_account_deletion_cancelled_task(self, user_id):
    from .emails import send_account_deletion_cancelled_email
    from .models import User

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.email:
        return
    _deliver(self, lambda: (send_account_deletion_cancelled_email(user), DeliveryResult.SENT)[1])


@shared_task
def notify_super_admins_deletion_failed_task(request_id):
    """Ops alert: a deletion gave up after its retries and the account is still locked. Internal
    mail to platform staff, deliberately plain English and free of any user data."""
    from django.core.mail import send_mail

    from apps.core.roles import Role

    from .models import User

    recipients = list(
        User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).exclude(email=None).values_list('email', flat=True)
    )
    if not recipients:
        return
    send_mail(
        subject='Account deletion needs attention',
        message=(
            f'Account deletion request {request_id} failed repeatedly and is parked as "failed". '
            'The account stays locked. Open it in Django admin (Accounts > Account deletion requests) '
            'and use "Retry now", or resolve it as cancelled if nothing irreversible has run.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


@shared_task
def purge_due_account_deletions():
    """Nightly (00:00 IST, django-celery-beat PeriodicTask seeded in migration 0010): processes every
    deletion request that is due, once each. See apps.accounts.deletion."""
    from . import deletion

    return deletion.run_due_requests()


@shared_task(bind=True, max_retries=EMAIL_TASK_MAX_RETRIES)
def send_account_deletion_code_task(self, user_id):
    """Issues a deletion-purpose email code and mails it. The code is created here, on the worker,
    so it never travels through the broker (same as the email sign-in code)."""
    from . import otp as otp_service
    from .emails import send_account_deletion_code_email
    from .models import User

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.email:
        return

    def _issue_and_send():
        code = otp_service.issue(
            user, otp_service.Channel.EMAIL, purpose=otp_service.OtpCode.Purpose.ACCOUNT_DELETION,
            still_eligible=lambda locked: locked.is_active and bool(locked.email),
        )
        if code is None:
            return DeliveryResult.SKIPPED
        send_account_deletion_code_email(user, code)
        return DeliveryResult.SENT

    _deliver(self, _issue_and_send)
