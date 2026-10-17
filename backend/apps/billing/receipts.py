"""Payment receipts (PRD Module 10 "auto-generated receipt", roadmap D4).

One data builder feeds both representations, so the JSON and the PDF can't
disagree. The PDF is rendered with WeasyPrint (already used by the Module 17
exports) from a gettext-translated template.
"""
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import translation


def receipt_data(payment):
    invoice = payment.invoice
    resident = invoice.resident
    prop = resident.property
    allocation = getattr(resident, 'allocation', None)
    recorded_by = payment.recorded_by
    return {
        'payment': payment,
        'invoice': invoice,
        'resident': resident,
        'property': prop,
        'room_number': allocation.allocated_bed.room.room_number if allocation else None,
        'bed_number': allocation.allocated_bed.bed_number if allocation else None,
        'recorded_by_name': (
            (f'{recorded_by.first_name} {recorded_by.last_name}'.strip() or str(recorded_by))
            if recorded_by else None
        ),
        'invoice_total': invoice.total,
        'invoice_paid': invoice.amount_paid,
        'invoice_balance_due': invoice.balance_due,
    }


def receipt_json(data):
    payment, invoice, resident = data['payment'], data['invoice'], data['resident']
    return {
        'receipt_for': str(payment.id),
        'receipt_number': payment.receipt_number,
        'resident': str(resident),
        'resident_id': str(resident.id),
        'property': str(data['property'].id),
        'property_name': data['property'].name,
        'room_number': data['room_number'],
        'bed_number': data['bed_number'],
        'invoice': str(invoice.id),
        'period_start': invoice.period_start,
        'period_end': invoice.period_end,
        'amount': str(payment.amount),
        'payment_date': payment.payment_date,
        'payment_mode': payment.payment_mode,
        'reference': payment.reference,
        'recorded_by': str(payment.recorded_by) if payment.recorded_by else None,
        'recorded_by_name': data['recorded_by_name'],
        'created_at': payment.created_at,
        'invoice_total': str(data['invoice_total']),
        'invoice_paid': str(data['invoice_paid']),
        'invoice_balance_due': str(data['invoice_balance_due']),
        'invoice_status': invoice.status,
    }


def receipt_pdf_response(payment, data):
    from weasyprint import HTML  # heavy import; only on the PDF path

    # Render in the request's active language (LocaleMiddleware); the template
    # carries every label through {% translate %} (invariant 7).
    html = render_to_string('billing/receipt.html', {
        **data,
        'payment_mode_label': payment.get_payment_mode_display(),
        'language_code': translation.get_language(),
    })
    filename = payment.receipt_number or str(payment.id)
    response = HttpResponse(HTML(string=html).write_pdf(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt-{filename}.pdf"'
    return response
