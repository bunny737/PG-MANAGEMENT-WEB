"""Branded multipart (text + HTML) transactional email.

Every template lives in templates/emails/ as a `<name>.html` + `<name>.txt` pair
extending base.html / base.txt. Copy is translated inside the recipient's
language, because most callers run on a Celery worker with no request language.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import translation

from apps.core.models import PlatformConfig


def _common_context():
    # Read-only (never PlatformConfig.get(), which creates the row): an email must not write.
    config = PlatformConfig.objects.filter(pk=1).first()
    base_url = settings.FRONTEND_BASE_URL.rstrip('/')
    return {
        'logo_url': f'{base_url}/brand/pglive-logo.png',
        'site_url': base_url,
        'company_name': settings.COMPANY_NAME,
        'company_address': settings.COMPANY_ADDRESS,
        'support_email': config.support_email if config else '',
        'support_phone': config.support_phone if config else '',
    }


def render_email(template, context, language):
    """Return (html, text) for `emails/<template>.{html,txt}`."""
    with translation.override(language or 'en'):
        ctx = {**_common_context(), **context}
        return (
            render_to_string(f'emails/{template}.html', ctx),
            render_to_string(f'emails/{template}.txt', ctx),
        )


def send_templated_email(*, to, subject, template, context, language='en'):
    """Send one branded email. `subject` is a string, or a callable evaluated in
    the recipient's language (so gettext lookups don't use the worker's locale).
    Raises on delivery failure; callers own retry policy."""
    language = language or 'en'
    html, text = render_email(template, context, language)
    if callable(subject):
        with translation.override(language):
            subject = subject()
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    message.attach_alternative(html, 'text/html')
    message.send(fail_silently=False)
