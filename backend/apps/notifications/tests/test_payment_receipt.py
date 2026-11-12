from datetime import date
from decimal import Decimal

from django.core import mail
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.residents.models import Admission

from .base import NotificationAPITestCase


class PaymentReceiptNotificationTests(NotificationAPITestCase):
    def setUp(self):
        super().setUp()
        invoice = self.generate_invoice()
        self.issue_invoice(invoice['id'])  # not captured — on_commit discarded, no email
        mail.outbox.clear()
        self.invoice_id = invoice['id']

    def test_recording_payment_emails_receipt_and_logs_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.pay(self.invoice_id)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.resident.email, mail.outbox[0].to)
        self.assertIn('2000.00', mail.outbox[0].body)

        # payment_receipt also attempts a push channel (registry.py) — skipped
        # here since Resident has no linked login account (channels/push.py).
        logs = self.notifications_for(self.tenant.id, notification_type='payment_receipt', channel='email')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, 'sent')
        self.assertEqual(logs[0].reference, f'payment:{response.data["id"]}')

    def test_applying_held_advance_does_not_send_payment_received_notification(self):
        with tenant_context(self.tenant.id):
            admission = Admission.objects.get(resident=self.resident)
            admission.advance_amount = Decimal('2000.00')
            admission.advance_collected_date = date(2026, 7, 1)
            admission.advance_mode = Admission.AdvanceMode.UPI
            admission.save(update_fields=[
                'advance_amount', 'advance_collected_date', 'advance_mode', 'updated_at',
            ])

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('invoice-adjust-advance', args=[self.invoice_id]),
                {'amount': '2000.00', 'adjustment_date': '2026-07-05', 'note': ''},
            )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['is_advance_adjustment'])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(
            self.notifications_for(
                self.tenant.id, notification_type='payment_receipt', channel='email',
            ),
            [],
        )
