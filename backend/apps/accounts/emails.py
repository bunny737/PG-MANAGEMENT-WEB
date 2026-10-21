"""Transactional auth emails. The strings already go through gettext
(invariant 7). Verification emails (signup welcome, resend, staff and admin
lifecycle) and sign-in codes are always sent from Celery tasks in
apps.accounts.tasks, which re-check eligibility on the worker. Password-reset
and staff-invite stay synchronous; they're outside Module 14's literal MVP
scope (email-only welcome/trial/invoice/receipt notifications) — revisit
together later if useful."""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .tokens import make_email_verification_token, make_password_reset_credentials


def _send(user, subject, body):
    if not user.email:
        return
    with translation.override(user.language_code or 'en'):
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )


def send_verification_email(user):
    # The token rides in the URL fragment: browsers never send fragments to a
    # server, so the 72-hour token stays out of every access log. The page
    # reads it client-side (frontend features/auth/VerifyEmail.tsx).
    token = make_email_verification_token(user)
    url = f'{settings.FRONTEND_BASE_URL}/verify-email#token={token}'
    # Queued on the worker, where no request language is active, so build the
    # text inside the user's language (as send_login_code_email does).
    with translation.override(user.language_code or 'en'):
        subject = _('Verify your email address')
        body = _('Welcome, %(name)s! Verify your email to activate your account: %(url)s') % {
            'name': user.first_name, 'url': url,
        }
    _send(user, subject, body)


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


def send_login_code_email(user, code):
    # Runs on the Celery worker (apps.accounts.tasks), where no request
    # language is active, so the text is built inside the user's language.
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    with translation.override(user.language_code or 'en'):
        subject = _('Your sign-in code')
        body = '\n\n'.join([
            _('Your sign-in code is %(code)s.') % {'code': code},
            ngettext(
                'It expires in %(count)d minute.',
                'It expires in %(count)d minutes.',
                minutes,
            ) % {'count': minutes},
            _("If you didn't ask for this code, you can ignore this email. "
              'Your password has not changed.'),
        ])
    _send(user, subject, body)


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
