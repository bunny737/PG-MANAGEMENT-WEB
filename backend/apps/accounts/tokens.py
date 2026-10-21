"""Stateless signed tokens for email verification, and helpers around
Django's password-reset token generator (also used for staff invites)."""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .normalization import normalize_email

EMAIL_VERIFICATION_SALT = 'accounts.email-verification'


def make_email_verification_token(user):
    """Signed {uid, email}: the link verifies that address only, so a link sent
    before an email change can't verify the new one."""
    return signing.dumps(
        {'uid': str(user.id), 'email': normalize_email(user.email)},
        salt=EMAIL_VERIFICATION_SALT,
    )


def read_email_verification_token(token):
    """Returns (user_id, email), or None if the token is invalid, expired, or a
    legacy uid-only token (issued before tokens carried the address)."""
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=settings.EMAIL_VERIFICATION_TTL_SECONDS,
        )
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    uid, email = payload.get('uid'), payload.get('email')
    if not uid or not email:
        return None
    return uid, email


def make_password_reset_credentials(user):
    return {
        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    }


def read_password_reset_uid(uidb64):
    try:
        return force_str(urlsafe_base64_decode(uidb64))
    except (ValueError, TypeError):
        return None


check_password_reset_token = default_token_generator.check_token
