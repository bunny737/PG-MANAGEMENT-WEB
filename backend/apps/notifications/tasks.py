"""Celery tasks for the notifications this module owns directly (invoice
issued, payment receipt, trial expiry reminder). The welcome-email task lives
in apps.accounts.tasks since it owns the User/verification-email logic (see
that module's spec for why) and calls back into `services.send_and_log` here.

Models referenced by task bodies are imported locally (not at module top) so
this module — imported by apps.billing and apps.accounts at their call sites
— never becomes the other side of a circular import."""
from celery import shared_task
from django.utils import translation

from apps.core.tenancy import tenant_context

from . import emails, services


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
        with translation.override('en'):
            subject, body = emails.invoice_issued_email(invoice, resident)
        services.send_and_log(
            tenant_id=invoice.tenant_id,
            notification_type='invoice_issued',
            recipient_email=resident.email,
            subject=subject, body=body,
            reference=f'invoice:{invoice.id}',
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
        with translation.override('en'):
            subject, body = emails.payment_receipt_email(payment, invoice, resident)
        services.send_and_log(
            tenant_id=payment.tenant_id,
            notification_type='payment_receipt',
            recipient_email=resident.email,
            subject=subject, body=body,
            reference=f'payment:{payment.id}',
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
        recipient_email = owner.email if owner else ''
        language_code = owner.language_code if owner else tenant.default_language
        with translation.override(language_code or 'en'):
            subject, body = emails.trial_expiry_reminder_email(tenant, days_remaining)
        services.send_and_log(
            tenant_id=tenant.id,
            notification_type='trial_expiry_reminder',
            recipient_email=recipient_email,
            subject=subject, body=body,
            reference=reference,
        )
