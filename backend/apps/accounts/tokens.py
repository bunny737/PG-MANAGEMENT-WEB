"""Stateless signed tokens for email verification, and helpers around
Django's password-reset token generator (also used for staff invites)."""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

EMAIL_VERIFICATION_SALT = 'accounts.email-verification'


def make_email_verification_token(user):
    return signing.dumps({'uid': str(user.id)}, salt=EMAIL_VERIFICATION_SALT)


def read_email_verification_token(token):
    """Returns the user id or None if the token is invalid/expired."""
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=settings.EMAIL_VERIFICATION_TTL_SECONDS,
        )
    except signing.BadSignature:
        return None
    return payload.get('uid')


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
