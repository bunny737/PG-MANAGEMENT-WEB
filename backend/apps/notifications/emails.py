"""Email content builders (PRD Module 18 MVP: email only). Each function
returns a plain (subject, body) pair; sending + logging is services.send_and_log.
All user-facing strings go through gettext (invariant 7)."""
from django.utils.translation import gettext as _


def invoice_issued_email(invoice, resident):
    subject = _('Invoice for %(period)s') % {'period': invoice.period_start.strftime('%B %Y')}
    body = _(
        'Dear %(name)s,\n\n'
        'Your invoice for the period %(start)s to %(end)s has been issued.\n'
        'Amount due: %(total)s\n'
        'Due date: %(due)s\n\n'
        'Thank you.'
    ) % {
        'name': resident.first_name,
        'start': invoice.period_start.isoformat(),
        'end': invoice.period_end.isoformat(),
        'total': invoice.total,
        'due': invoice.due_date.isoformat(),
    }
    return subject, body


def payment_receipt_email(payment, invoice, resident):
    subject = _('Payment receipt — %(amount)s received') % {'amount': payment.amount}
    body = _(
        'Dear %(name)s,\n\n'
        'We have received your payment of %(amount)s on %(date)s via %(mode)s.\n'
        'Remaining balance on this invoice: %(balance)s\n\n'
        'Thank you.'
    ) % {
        'name': resident.first_name,
        'amount': payment.amount,
        'date': payment.payment_date.isoformat(),
        'mode': payment.get_payment_mode_display(),
        'balance': invoice.balance_due,
    }
    return subject, body


def trial_expiry_reminder_email(tenant, days_remaining):
    subject = _('Your trial ends in %(days)s day(s)') % {'days': days_remaining}
    body = _(
        'Dear %(name)s,\n\n'
        'Your free trial of the platform for %(business)s ends in %(days)s day(s), '
        'on %(end_date)s. Choose a plan to keep using the platform without interruption.\n\n'
        'Thank you.'
    ) % {
        'name': tenant.name,
        'business': tenant.name,
        'days': days_remaining,
        'end_date': tenant.trial_ends_at.date().isoformat(),
    }
    return subject, body
