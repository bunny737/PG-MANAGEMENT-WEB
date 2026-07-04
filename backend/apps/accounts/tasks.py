"""Module 14: the signup "welcome" notification (PRD Module 18 MVP). Lives
here (not apps.notifications) because it reuses the existing verification
email, which owns the User/token logic. Runs off the request thread via
Celery; the caller must dispatch it with transaction.on_commit so it never
fires before the signup transaction (and the User row) actually commits."""
from celery import shared_task

from apps.core.tenancy import tenant_context


@shared_task
def send_welcome_email_task(user_id):
    from apps.notifications.services import record_sent

    from .emails import send_verification_email
    from .models import User

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    with tenant_context(user.tenant_id):
        # The verification email already opens with "Welcome, <name>!" — this
        # is the one email a brand-new signup gets, so it doubles as the
        # welcome notification rather than sending a redundant second email
        # (see the Module 14 spec's Decisions). record_sent logs it without
        # sending anything itself.
        send_verification_email(user)
        record_sent(
            tenant_id=user.tenant_id,
            notification_type='welcome',
            recipient_email=user.email,
            subject='Verify your email address',
            reference=f'user:{user.id}',
        )
