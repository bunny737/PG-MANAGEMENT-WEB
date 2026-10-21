"""Deploy-time checks (`manage.py check --deploy`) for settings that only matter in production.
Like the Razorpay check, they are system checks rather than settings-import guards so that jobs
and the image build, which never send email, don't need these values."""
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def check_frontend_base_url(app_configs, **kwargs):
    """Every emailed link (verify, reset, invite) is built from FRONTEND_BASE_URL. The localhost
    default, or plain http, would put dead or unsafe links in front of real users."""
    url = settings.FRONTEND_BASE_URL
    if url.startswith('https://'):
        return []
    return [Error(
        f'FRONTEND_BASE_URL must be the public https address of the web app (got {url!r}).',
        hint='Set FRONTEND_BASE_URL, e.g. https://www.pglive.in.',
        id='core.E001',
    )]
