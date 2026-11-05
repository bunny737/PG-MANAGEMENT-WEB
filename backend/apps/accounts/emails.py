"""Transactional auth emails: branded multipart (text + HTML) messages rendered
from templates/emails/ by apps.core.email, always in the recipient's language
(invariant 7). Verification emails (signup welcome, resend, staff and admin
lifecycle) and sign-in codes are sent from Celery tasks in apps.accounts.tasks,
which re-check eligibility on the worker. Password-reset, staff-invite and
password-changed emails are sent the same way (see tasks.py)."""
from django.conf import settings
from django.utils.translation import gettext as _

from apps.core.email import send_templated_email

from .tokens import make_email_verification_token, make_password_reset_credentials


def _send(user, *, subject, template, context):
    if not user.email:
        return
    send_templated_email(
        to=user.email,
        subject=subject,
        template=template,
        context={'name': user.first_name, **context},
        language=user.language_code,
    )


def send_verification_email(user):
    # The token rides in the URL fragment: browsers never send fragments to a
    # server, so the 72-hour token stays out of every access log. The page
    # reads it client-side (frontend features/auth/VerifyEmail.tsx).
    token = make_email_verification_token(user)
    _send(
        user,
        subject=lambda: _('Verify your email address'),
        template='verify_email',
        context={
            'cta_url': f'{settings.FRONTEND_BASE_URL}/verify-email#token={token}',
            'valid_hours': settings.EMAIL_VERIFICATION_TTL_SECONDS // 3600,
        },
    )


def send_password_reset_email(user):
    # Like the verification link, uid and token ride in the URL fragment so the
    # reset token never reaches a server access log.
    creds = make_password_reset_credentials(user)
    _send(
        user,
        subject=lambda: _('Reset your password'),
        template='password_reset',
        context={
            'cta_url': (
                f'{settings.FRONTEND_BASE_URL}/reset-password'
                f'#uid={creds["uid"]}&token={creds["token"]}'
            ),
            'valid_hours': settings.PASSWORD_RESET_TIMEOUT // 3600,
        },
    )


def send_password_changed_email(user):
    # A resident account resets with a code in the app; the staff web's forgot-password page
    # would not find it, so point them at the site instead.
    reset_path = '' if user.role == 'resident' else '/forgot-password'
    _send(
        user,
        subject=lambda: _('Your password was changed'),
        template='password_changed',
        context={'reset_url': f'{settings.FRONTEND_BASE_URL}{reset_path}'},
    )


def send_login_code_email(user, code):
    _send(
        user,
        subject=lambda: _('Your sign-in code'),
        template='login_code',
        context={'code': code, 'minutes': max(1, settings.OTP_TTL_SECONDS // 60)},
    )


def send_staff_invite_email(user, tenant):
    # Invites reuse the password-reset token: setting the password proves
    # email ownership, so the confirm step also marks the email verified.
    creds = make_password_reset_credentials(user)
    business = tenant.name
    _send(
        user,
        subject=lambda: _('You have been invited to %(business)s') % {'business': business},
        template='staff_invite',
        context={
            'business': business,
            'cta_url': (
                f'{settings.FRONTEND_BASE_URL}/reset-password'
                f'#uid={creds["uid"]}&token={creds["token"]}&invite=1'
            ),
        },
    )


# --- Account deletion (Module 22) ------------------------------------------------------------
def send_account_deletion_requested_email(user, deletion):
    """Confirmation with the date and how to cancel. The date is rendered in the recipient's
    language by the template (it runs under translation.override)."""
    from django.utils import timezone

    _send(
        user,
        subject=lambda: _('Your account is scheduled for deletion'),
        template='account_deletion_requested',
        context={
            'scheduled_for': timezone.localtime(deletion.scheduled_for),
            'whole_business': deletion.scope == 'tenant',
            'cta_url': f'{settings.FRONTEND_BASE_URL}/account/deletion-pending',
        },
    )


def send_account_deletion_begun_email(address, language):
    """Sent by address, not by user: by the time the worker runs, the purge may have deleted the
    account. The text is generic so it needs nothing else from the (possibly gone) user."""
    send_templated_email(
        to=address,
        subject=lambda: _('Your account deletion has started'),
        template='account_deletion_begun',
        context={},
        language=language or 'en',
    )


def send_account_deletion_cancelled_email(user):
    _send(
        user,
        subject=lambda: _('Your account deletion was cancelled'),
        template='account_deletion_cancelled',
        context={},
    )


def send_account_deletion_code_email(user, code):
    _send(
        user,
        subject=lambda: _('Your account deletion code'),
        template='account_deletion_code',
        context={'code': code, 'minutes': max(1, settings.OTP_TTL_SECONDS // 60)},
    )


# --- Resident app accounts (Module 26) -------------------------------------------------------
# Residents use short codes, not links: the app has no page to open a reset or verification link
# in, and a code works the same on the web.
def send_resident_verification_code_email(user, code):
    _send(
        user,
        subject=lambda: _('Verify your email address'),
        template='resident_verification_code',
        context={'code': code, 'minutes': max(1, settings.OTP_TTL_SECONDS // 60)},
    )


def send_resident_password_reset_code_email(user, code):
    _send(
        user,
        subject=lambda: _('Your password reset code'),
        template='resident_password_reset_code',
        context={'code': code, 'minutes': max(1, settings.OTP_TTL_SECONDS // 60)},
    )


def send_resident_account_exists_email(user):
    _send(
        user,
        subject=lambda: _('You already have an account'),
        template='resident_account_exists',
        context={},
    )


def send_resident_invite_email(*, to, name, business, property_name, token, language, hours):
    """Sent by address: an invite is for an email, and no User exists for it. The token rides in
    the URL fragment, so it stays out of server access logs."""
    send_templated_email(
        to=to,
        subject=lambda: _('%(business)s invited you to its app') % {'business': business},
        template='resident_invite',
        context={
            'name': name, 'business': business, 'property': property_name, 'hours': hours,
            'cta_url': f'{settings.FRONTEND_BASE_URL}/join#token={token}',
        },
        language=language or 'en',
    )
