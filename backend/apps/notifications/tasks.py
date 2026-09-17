"""Celery tasks for the notifications this module owns directly (invoice
issued, payment receipt, trial expiry reminder), plus the generic scheduling
machinery (recurring sweeps via django-celery-beat, one-off scheduled
sends). The welcome-email task lives in apps.accounts.tasks since it owns
the User/verification-email logic (see that module's spec for why) and
calls back into `services.record_sent` here.

Models referenced by task bodies are imported locally (not at module top) so
this module — imported by apps.billing and apps.accounts at their call sites
— never becomes the other side of a circular import."""
from celery import shared_task
from django.utils import timezone

from apps.core.tenancy import tenant_context

from . import services


@shared_task
def send_invoice_issued_email_task(invoice_id):
    from apps.billing.models import Invoice

    # Invoice is RLS-enforced and no tenant context exists yet at task start —
    # look it up as super admin just to learn its tenant_id, same pattern as
    # the Module 13 webhook handler.
    with tenant_context(None, is_super_admin=True):
        invoice = Invoice.objects.filter(pk=invoice_id).select_related('resident').first()
    if invoice is None:
        return
    with tenant_context(invoice.tenant_id):
        resident = invoice.resident
        context = {
            'name': resident.first_name,
            'period': invoice.period_start.strftime('%B %Y'),
            'start': invoice.period_start.isoformat(),
            'end': invoice.period_end.isoformat(),
            'total': invoice.total,
            'due': invoice.due_date.isoformat(),
        }
        services.notify(
            tenant_id=invoice.tenant_id, notification_type='invoice_issued',
            recipient_user=resident, context=context, reference=f'invoice:{invoice.id}',
        )


@shared_task
def send_payment_receipt_email_task(payment_id):
    from apps.billing.models import Payment

    with tenant_context(None, is_super_admin=True):
        payment = Payment.objects.filter(pk=payment_id).select_related('invoice', 'invoice__resident').first()
    if payment is None:
        return
    with tenant_context(payment.tenant_id):
        invoice = payment.invoice
        resident = invoice.resident
        context = {
            'name': resident.first_name,
            'amount': payment.amount,
            'date': payment.payment_date.isoformat(),
            'mode': payment.get_payment_mode_display(),
            'balance': invoice.balance_due,
        }
        services.notify(
            tenant_id=payment.tenant_id, notification_type='payment_receipt',
            recipient_user=resident, context=context, reference=f'payment:{payment.id}',
        )


@shared_task
def send_trial_expiry_reminder_task(tenant_id, days_remaining):
    from apps.accounts.models import Tenant

    tenant = Tenant.objects.filter(pk=tenant_id).first()
    if tenant is None:
        return
    reference = f'tenant_trial:{tenant.id}:{days_remaining}'
    with tenant_context(tenant.id):
        from .models import NotificationLog
        if NotificationLog.objects.filter(reference=reference).exists():
            return  # already sent for this offset (idempotency)
        owner = tenant.users.filter(role='owner').order_by('created_at').first()
        context = {
            'name': tenant.name,
            'business': tenant.name,
            'days': days_remaining,
            'end_date': tenant.trial_ends_at.date().isoformat(),
        }
        services.notify(
            tenant_id=tenant.id, notification_type='trial_expiry_reminder',
            recipient_user=owner, context=context, reference=reference,
        )


# --- Scheduling: recurring sweeps (django-celery-beat PeriodicTask) -------

SWEEPS = {
    'trial_expiry_reminders': lambda: [
        (str(tenant.id), days_remaining) for tenant, days_remaining in services.due_trial_reminders()
    ],
}


@shared_task
def run_due_sweep(sweep_key):
    """Generic recurring-sweep entry point. A django-celery-beat
    `PeriodicTask` targets this task with `sweep_key` as its argument, so a
    Super Admin can change a sweep's cadence (or add a new one) from Django
    admin — no code deploy, no new Celery task per sweep. `SWEEPS` maps a key
    to a "who's due today" scan; today only `trial_expiry_reminders` exists,
    generalized from the original Module 14 MVP's dedicated daily command."""
    scan = SWEEPS.get(sweep_key)
    if scan is None:
        return
    for tenant_id, days_remaining in scan():
        send_trial_expiry_reminder_task.delay(tenant_id, days_remaining)


# --- Scheduling: one-off ScheduledNotification -----------------------------

@shared_task
def dispatch_scheduled_notifications():
    """Polled every minute by a django-celery-beat IntervalSchedule. Sends
    every PENDING ScheduledNotification whose send_at has passed, across
    tenants — looked up as super admin first (task start has no tenant
    context), then dispatched under each row's own tenant context so the
    resulting NotificationLog insert passes RLS's WITH CHECK."""
    from .models import ScheduledNotification

    with tenant_context(None, is_super_admin=True):
        due_ids = list(
            ScheduledNotification.objects.filter(
                status=ScheduledNotification.Status.PENDING, send_at__lte=timezone.now(),
            ).values_list('id', 'tenant_id')
        )
    for scheduled_id, tenant_id in due_ids:
        _dispatch_one_scheduled_notification(scheduled_id, tenant_id)


def _dispatch_one_scheduled_notification(scheduled_id, tenant_id):
    from .models import ScheduledNotification

    with tenant_context(tenant_id):
        scheduled = ScheduledNotification.objects.filter(
            pk=scheduled_id, status=ScheduledNotification.Status.PENDING,
        ).select_related('recipient_user').first()
        if scheduled is None:
            return  # already sent/cancelled by a concurrent run
        services.notify(
            tenant_id=tenant_id, notification_type=scheduled.notification_type,
            recipient_user=scheduled.recipient_user, context=scheduled.context,
            channels=scheduled.channels or None,
            reference=f'scheduled:{scheduled.id}',
        )
        scheduled.status = ScheduledNotification.Status.SENT
        scheduled.save(update_fields=['status', 'updated_at'])
