"""Tenant-isolation proof for invoices + line items (invariant 1)."""
from datetime import date

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.residents.models import Resident
from apps.billing.models import Invoice, InvoiceLineItem

from .base import BillingAPITestCase


class InvoiceRowLevelSecurityTests(TestCase):
    @staticmethod
    def _invoice(tenant, phone, bed_number='101-A'):
        prop = BillingAPITestCase.create_property(tenant, name=f'Prop {phone}')
        room = BillingAPITestCase.create_room(BillingAPITestCase.create_floor(prop))
        bed = BillingAPITestCase.create_bed(room, bed_number=bed_number)
        resident = BillingAPITestCase.create_resident(prop, phone=phone, status=Resident.Status.RESERVED)
        BillingAPITestCase.check_in(resident, bed)
        with tenant_context(tenant.id):
            invoice = Invoice.objects.create(
                tenant_id=tenant.id, resident=resident, period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31), billing_mode='monthly', due_date=date(2026, 7, 10),
            )
            InvoiceLineItem.objects.create(
                tenant_id=tenant.id, invoice=invoice, line_type='accommodation',
                label='Accommodation', amount='7000.00',
            )
            return invoice

    def setUp(self):
        self.tenant_a = BillingAPITestCase.create_tenant('Tenant A')
        self.tenant_b = BillingAPITestCase.create_tenant('Tenant B')
        self.invoice_a = self._invoice(self.tenant_a, '9000000001')
        self._invoice(self.tenant_b, '9000000002')

    def test_tenant_context_sees_only_own_invoices(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Invoice.objects.count(), 1)
            self.assertEqual(InvoiceLineItem.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(InvoiceLineItem.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Invoice.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    InvoiceLineItem.objects.create(
                        tenant_id=self.tenant_b.id, invoice=self.invoice_a,
                        line_type='additional', label='Evil', amount='1.00',
                    )
