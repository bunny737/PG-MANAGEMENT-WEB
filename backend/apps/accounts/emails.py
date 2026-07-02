"""Transactional auth emails. Module 14 will move these onto Celery with
per-language templates; the strings already go through gettext (invariant 7)."""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import translation
from django.utils.translation import gettext as _

from .tokens import make_email_verification_token, make_password_reset_credentials


def _send(user, subject, body):
    with translation.override(user.language_code or 'en'):
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )


def send_verification_email(user):
    token = make_email_verification_token(user)
    url = f'{settings.FRONTEND_BASE_URL}/verify-email?token={token}'
    _send(
        user,
        _('Verify your email address'),
        _('Welcome, %(name)s! Verify your email to activate your account: %(url)s')
        % {'name': user.first_name, 'url': url},
    )


def send_password_reset_email(user):
    creds = make_password_reset_credentials(user)
    url = (
        f'{settings.FRONTEND_BASE_URL}/reset-password'
        f'?uid={creds["uid"]}&token={creds["token"]}'
    )
    _send(
        user,
        _('Reset your password'),
        _('Use this link to reset your password: %(url)s') % {'url': url},
    )


def send_staff_invite_email(user, tenant):
    # Invites reuse the password-reset token: setting the password proves
    # email ownership, so the confirm step also marks the email verified.
    creds = make_password_reset_credentials(user)
    url = (
        f'{settings.FRONTEND_BASE_URL}/reset-password'
        f'?uid={creds["uid"]}&token={creds["token"]}&invite=1'
    )
    _send(
        user,
        _('You have been invited to %(business)s') % {'business': tenant.name},
        _('%(name)s, an account was created for you at %(business)s. '
          'Set your password to get started: %(url)s')
        % {'name': user.first_name, 'business': tenant.name, 'url': url},
    )
