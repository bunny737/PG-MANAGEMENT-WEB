from django.core import mail

from apps.residents.models import Resident

from .base import NotificationAPITestCase


class InvoiceIssuedNotificationTests(NotificationAPITestCase):
    def test_issuing_invoice_emails_resident_and_logs_it(self):
        invoice = self.generate_invoice()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.issue_invoice(invoice['id'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.resident.email, mail.outbox[0].to)

        logs = self.notifications_for(self.tenant.id, notification_type='invoice_issued')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, 'sent')
        self.assertEqual(logs[0].reference, f'invoice:{invoice["id"]}')

    def test_draft_invoice_creation_does_not_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.generate_invoice()

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.notifications_for(self.tenant.id), [])

    def test_resident_with_no_email_is_skipped_not_failed(self):
        resident = self.create_resident(
            self.property, first_name='NoEmail', phone='9000000099',
            status=Resident.Status.RESERVED, email='',
        )
        bed = self.create_bed(self.room, bed_number='101-B')
        self.check_in(resident, bed)
        invoice = self.generate_invoice(resident=resident)

        with self.captureOnCommitCallbacks(execute=True):
            self.issue_invoice(invoice['id'])

        self.assertEqual(len(mail.outbox), 0)
        logs = self.notifications_for(self.tenant.id, notification_type='invoice_issued')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, 'skipped')
