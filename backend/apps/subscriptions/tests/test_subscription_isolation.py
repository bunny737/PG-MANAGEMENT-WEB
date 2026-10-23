"""Tenant-isolation proof for the RLS-scoped tables in this module
(invariant 1): `SubscriptionPayment`, and — added for PER_BED_MONTHLY
billing — `BedLedgerEntry`, `SubscriptionInvoice`, `SubscriptionInvoiceLine`.
`Plan`/`Subscription`/`PlanBedTier` are deliberately not under RLS; see the
Module 13 spec's Decisions."""
from datetime import date, datetime
from datetime import timezone as dt_timezone
import uuid

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.subscriptions.models import (
    BedLedgerEntry,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
    SubscriptionPayment,
)

from .base import SubscriptionAPITestCase


class SubscriptionPaymentRowLevelSecurityTests(TestCase):
    @staticmethod
    def _payment(tenant_name):
        tenant = SubscriptionAPITestCase.create_tenant(tenant_name)
        subscription = SubscriptionAPITestCase.create_subscription(tenant)
        with tenant_context(tenant.id):
            return SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription, amount='199.00',
                status=SubscriptionPayment.Status.SUCCESS,
            )

    def setUp(self):
        self.payment_a = self._payment('Tenant A')
        self._payment('Tenant B')

    def test_tenant_context_sees_only_own_payments(self):
        with tenant_context(self.payment_a.tenant_id):
            self.assertEqual(SubscriptionPayment.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(SubscriptionPayment.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        other_tenant = SubscriptionAPITestCase.create_tenant('Tenant C')
        with tenant_context(self.payment_a.tenant_id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    SubscriptionPayment.objects.create(
                        tenant_id=other_tenant.id, subscription=self.payment_a.subscription,
                        amount='1.00', status=SubscriptionPayment.Status.SUCCESS,
                    )


class BedLedgerEntryRowLevelSecurityTests(TestCase):
    @staticmethod
    def _entry(tenant_name):
        tenant = SubscriptionAPITestCase.create_tenant(tenant_name)
        with tenant_context(tenant.id):
            return BedLedgerEntry.objects.create(
                tenant_id=tenant.id, bed_id=uuid.uuid4(), event=BedLedgerEntry.Event.ADDED,
                occurred_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
            )

    def setUp(self):
        self.entry_a = self._entry('Tenant A')
        self._entry('Tenant B')

    def test_tenant_context_sees_only_own_entries(self):
        with tenant_context(self.entry_a.tenant_id):
            self.assertEqual(BedLedgerEntry.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(BedLedgerEntry.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(BedLedgerEntry.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        other_tenant = SubscriptionAPITestCase.create_tenant('Tenant C')
        with tenant_context(self.entry_a.tenant_id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    BedLedgerEntry.objects.create(
                        tenant_id=other_tenant.id, bed_id=uuid.uuid4(),
                        event=BedLedgerEntry.Event.ADDED, occurred_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
                    )


class SubscriptionInvoiceRowLevelSecurityTests(TestCase):
    """Also proves tenant A's beds never affect tenant B's price — each
    tenant's ledger/invoice rows are only ever visible under their own
    tenant context."""

    @staticmethod
    def _invoice(tenant_name):
        tenant = SubscriptionAPITestCase.create_tenant(tenant_name)
        plan = SubscriptionAPITestCase.create_bed_plan(
            name=f'{tenant_name} Plan', bed_tiers=[(None, '2.00')],
        )
        subscription = SubscriptionAPITestCase.create_subscription(tenant, plan=plan)
        with tenant_context(tenant.id):
            invoice = SubscriptionInvoice.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                period_start=date(2026, 7, 1), period_end=date(2026, 8, 1),
                total_amount='10.00', billed_bed_count_start=5, billed_bed_count_end=5,
            )
            SubscriptionInvoiceLine.objects.create(
                tenant_id=tenant.id, invoice=invoice, description='5 beds @ ₹2.00',
                quantity='5', unit_rate='2.00', amount='10.00',
            )
            return invoice

    def setUp(self):
        self.invoice_a = self._invoice('Tenant A')
        self._invoice('Tenant B')

    def test_tenant_context_sees_only_own_invoices_and_lines(self):
        with tenant_context(self.invoice_a.tenant_id):
            self.assertEqual(SubscriptionInvoice.objects.count(), 1)
            self.assertEqual(SubscriptionInvoiceLine.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(SubscriptionInvoice.objects.count(), 0)
        self.assertEqual(SubscriptionInvoiceLine.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(SubscriptionInvoice.objects.count(), 2)
            self.assertEqual(SubscriptionInvoiceLine.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        other_tenant = SubscriptionAPITestCase.create_tenant('Tenant C')
        with tenant_context(self.invoice_a.tenant_id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    SubscriptionInvoice.objects.create(
                        tenant_id=other_tenant.id, subscription=self.invoice_a.subscription,
                        period_start=date(2026, 7, 1), period_end=date(2026, 8, 1),
                        total_amount='1.00', billed_bed_count_start=1, billed_bed_count_end=1,
                    )
