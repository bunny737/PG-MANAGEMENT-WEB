import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import OtpCode, User

logger = logging.getLogger(__name__)

Channel = OtpCode.Channel


@transaction.atomic
def issue(user, channel, *, still_eligible=None):
    """Create a fresh OTP for the user on `channel`, invalidating only that
    channel's outstanding codes. Returns the plaintext code (the caller
    delivers it), or None when the user is gone or `still_eligible` rejects
    the freshly locked row.

    Issuance locks the user row: without it, two concurrent requests both
    invalidate the old codes and then each create one, leaving two usable
    codes. The eligibility predicate runs on the locked row so a deactivation
    or email change between the caller's lookup and here is seen."""
    locked = (
        User.objects.select_for_update(of=('self',))
        .select_related('tenant')
        .filter(pk=user.pk)
        .first()
    )
    if locked is None:
        return None
    if still_eligible is not None and not still_eligible(locked):
        return None
    code = f'{secrets.randbelow(10**6):06d}'
    OtpCode.objects.filter(user=locked, channel=channel, used=False).update(used=True)
    OtpCode.objects.create(
        user=locked,
        channel=channel,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    return code


def _deliver(user, code):
    # SMS delivery is V2 (PRD Module 18). Until then the code only reaches the
    # log in DEBUG — never in production, where logs are shipped and retained.
    if settings.DEBUG:
        logger.info('OTP for %s: %s', user.phone, code)
    else:
        logger.warning('SMS delivery is not configured; phone OTP was not sent.')


@transaction.atomic
def verify(user, code, channel):
    """True if `code` matches the user's latest active OTP on `channel`.
    Consumes the OTP on success; counts an attempt (and locks after
    OTP_MAX_ATTEMPTS) on failure. A successful email code also marks the
    email verified — in the same transaction, so the code is never consumed
    without the verification sticking.

    The row is locked for the duration: without it, N concurrent verify calls
    all read attempts=0, all get a guess, and the failed-attempt counter barely
    moves — defeating the OTP_MAX_ATTEMPTS lockout for a 6-digit code.
    Callers must not wrap this in an outer transaction they roll back on
    failure, or the attempt counter rolls back with it.

    Lock order is user row, then OTP row — the same as issue(). Taking the OTP
    row first and the user row later (for email_verified) would deadlock
    against a concurrent resend holding the user row and invalidating codes."""
    locked_pk = (
        User.objects.select_for_update(of=('self',))
        .filter(pk=user.pk)
        .values_list('pk', flat=True)
        .first()
    )
    if locked_pk is None:
        return False
    otp = (
        OtpCode.objects.select_for_update()
        .filter(user=user, channel=channel, used=False, expires_at__gt=timezone.now())
        .order_by('-created_at')
        .first()
    )
    if otp is None:
        return False
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False
    if check_password(code, otp.code_hash):
        otp.used = True
        otp.save(update_fields=['used'])
        if channel == Channel.EMAIL:
            # update() skips auto_now, so set updated_at explicitly. Filtering on
            # email_verified=False leaves an already-verified row untouched.
            User.objects.filter(pk=user.pk, email_verified=False).update(
                email_verified=True, updated_at=timezone.now()
            )
            user.email_verified = True
        return True
    otp.attempts += 1
    otp.save(update_fields=['attempts'])
    return False
