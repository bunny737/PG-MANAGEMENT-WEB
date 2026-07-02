import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import OtpCode

logger = logging.getLogger(__name__)


def issue(user):
    """Create a fresh OTP for the user, invalidating any outstanding ones."""
    code = f'{secrets.randbelow(10**6):06d}'
    OtpCode.objects.filter(user=user, used=False).update(used=True)
    OtpCode.objects.create(
        user=user,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    _deliver(user, code)


def _deliver(user, code):
    # SMS delivery is V2 (PRD Module 18). Dev/MVP: the code lands in the log.
    logger.info('OTP for %s: %s', user.phone, code)


def verify(user, code):
    """True if `code` matches the user's latest active OTP. Consumes the OTP
    on success; counts an attempt (and locks after OTP_MAX_ATTEMPTS) on failure."""
    otp = (
        OtpCode.objects.filter(user=user, used=False, expires_at__gt=timezone.now())
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
        return True
    otp.attempts += 1
    otp.save(update_fields=['attempts'])
    return False
