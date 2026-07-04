from django.core import mail

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

        logs = self.notifications_for(self.tenant.id, notification_type='payment_receipt')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, 'sent')
        self.assertEqual(logs[0].reference, f'payment:{response.data["id"]}')
