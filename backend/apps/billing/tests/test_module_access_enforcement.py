"""Module access is enforced by the API, method by method, and "off" really is off.

A manager whose module access is customized must see exactly what the Owner
configured: reads need the view code, writes the manage code, and the money /
occupant fields on resident and bed views follow the Finance / Tenants split.
"""
import uuid
from decimal import Decimal

from django.urls import reverse

from apps.core.modules import FULL, OFF, VIEW, role_default_levels, storage_value
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.billing.models import Invoice
from apps.operations.tests.base import OperationsAPITestCase
from apps.residents.models import Resident

from .base import BillingAPITestCase

PERIOD = {'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10'}
BILLING_FIELDS = {'contracted_rent', 'billing_mode'}
DEPOSIT_FIELDS = {'security_deposit_amount', 'advance_amount', 'advance_refundable'}


class ModuleAccessEnforcementBase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor, room_number='101', rack_rate_with_food=Decimal('7000.00'))
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed)

        self.staff = self.create_manager(self.tenant)
        self.assign_staff(self.staff, self.property)

        self.authenticate(self.owner)
        created = self.client.post(
            reverse('invoice-list'), {'resident': str(self.resident.id), **PERIOD}
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.invoice_id = created.data['id']
        with tenant_context(self.tenant.id):
            self.invoice = Invoice.objects.get(pk=self.invoice_id)
        # The payment hangs off a second invoice so the writes under test can touch
        # the first one (an invoice that has payments is protected from deletion).
        august = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-08-01', 'period_end': '2026-08-31', 'due_date': '2026-08-10',
        })
        self.assertEqual(august.status_code, 201, august.data)
        with tenant_context(self.tenant.id):
            self.paid_invoice = Invoice.objects.get(pk=august.data['id'])
        self.payment = self.create_payment(self.paid_invoice)
        self.discount = self.create_discount(self.resident)

    def set_levels(self, user=None, **changes):
        """Customize `user`'s (default: the manager's) module access and act as them."""
        user = user or self.staff
        levels = role_default_levels(user.role)
        levels.update(changes)
        user.module_access = storage_value(user.role, levels)
        user.save(update_fields=['module_access', 'updated_at'])
        self.authenticate(user)

    def call(self, method, path, body=None):
        return getattr(self.client, method)(path, body or {}, format='json')


class FinanceEnforcementTests(ModuleAccessEnforcementBase):
    def reads(self):
        inv, pay, disc = self.invoice_id, self.payment.id, self.discount.id
        return [
            reverse('invoice-list'),
            reverse('invoice-detail', args=[inv]),
            '/api/v1/invoices/outstanding/',
            reverse('payment-list'),
            reverse('payment-detail', args=[pay]),
            f'/api/v1/payments/{pay}/receipt/',
            reverse('discount-list'),
            reverse('discount-detail', args=[disc]),
            reverse('export-payments'),
            reverse('export-outstanding-dues'),
        ]

    def writes(self):
        inv, pay, disc = self.invoice_id, self.payment.id, self.discount.id
        return [
            ('post', reverse('invoice-list')),
            ('patch', reverse('invoice-detail', args=[inv])),
            ('delete', reverse('invoice-detail', args=[inv])),
            ('post', f'/api/v1/invoices/{inv}/issue/'),
            ('post', '/api/v1/invoices/bulk-generate/'),
            ('post', f'/api/v1/invoices/{inv}/line-items/'),
            ('patch', f'/api/v1/invoices/{inv}/line-items/{uuid.uuid4()}/'),
            ('delete', f'/api/v1/invoices/{inv}/line-items/{uuid.uuid4()}/'),
            ('post', reverse('payment-list')),
            ('delete', reverse('payment-detail', args=[pay])),
            ('post', reverse('discount-list')),
            ('patch', reverse('discount-detail', args=[disc])),
        ]

    def test_finance_off_blocks_every_read_and_write(self):
        self.set_levels(finance=OFF)
        for path in self.reads():
            self.assertEqual(self.client.get(path).status_code, 403, path)
        for method, path in self.writes():
            self.assertEqual(self.call(method, path).status_code, 403, (method, path))
        self.assertEqual(self.client.options(reverse('invoice-list')).status_code, 403)

    def test_finance_view_allows_reads_and_no_write_method(self):
        self.set_levels(finance=VIEW)
        for path in self.reads():
            self.assertEqual(self.client.get(path).status_code, 200, path)
        # These viewsets list only the real verbs, so HEAD/OPTIONS answer 405 — what
        # matters is that a view-only user is not *forbidden* from the safe methods.
        self.assertNotEqual(self.client.head(reverse('invoice-list')).status_code, 403)
        self.assertNotEqual(self.client.options(reverse('invoice-list')).status_code, 403)
        for method, path in self.writes():
            self.assertEqual(self.call(method, path).status_code, 403, (method, path))

    def test_finance_full_passes_the_permission_check_for_writes(self):
        self.set_levels(finance=FULL)
        for path in self.reads():
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for method, path in self.writes():
            # Permission passes; the request may still 400/404/405 on its own merits.
            self.assertNotEqual(self.call(method, path).status_code, 403, (method, path))

    def test_nothing_mutating_is_reachable_by_get(self):
        """Every route a view-only user can GET is read-only: the writes list never
        contains a GET, and a finance=view user's GET calls leave the data untouched."""
        self.set_levels(finance=VIEW)
        before = Invoice.objects.filter(tenant_id=self.tenant.id).count()
        for path in self.reads():
            self.client.get(path)
        self.assertEqual(Invoice.objects.filter(tenant_id=self.tenant.id).count(), before)
        self.assertTrue(all(method != 'get' for method, _ in self.writes()))


class TenantsAndFinanceFieldTests(ModuleAccessEnforcementBase):
    def resident_data(self):
        response = self.client.get(reverse('resident-detail', args=[self.resident.id]))
        self.assertEqual(response.status_code, 200, response.data)
        return set(response.data)

    def test_manager_defaults_see_every_money_field(self):
        self.authenticate(self.staff)
        self.assertTrue((BILLING_FIELDS | DEPOSIT_FIELDS) <= self.resident_data())

    def test_tenants_view_without_finance_hides_all_money_fields(self):
        self.set_levels(tenants=VIEW, finance=OFF)
        self.assertFalse(self.resident_data() & (BILLING_FIELDS | DEPOSIT_FIELDS))

    def test_tenants_full_without_finance_sees_settlement_figures_but_not_billing(self):
        self.set_levels(tenants=FULL, finance=OFF)
        data = self.resident_data()
        self.assertTrue(DEPOSIT_FIELDS <= data)
        self.assertFalse(data & BILLING_FIELDS)

    def test_finance_view_reveals_money_fields(self):
        self.set_levels(tenants=VIEW, finance=VIEW)
        self.assertTrue((BILLING_FIELDS | DEPOSIT_FIELDS) <= self.resident_data())

    def test_receptionist_defaults_still_see_no_money_fields(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)
        self.assertFalse(self.resident_data() & (BILLING_FIELDS | DEPOSIT_FIELDS))

    def test_tenants_full_finance_off_can_use_exit_workflow_but_not_invoices(self):
        self.set_levels(tenants=FULL, finance=OFF)
        self.assertEqual(self.client.get(reverse('vacate-list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('absconded-record-list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('payment-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('discount-list')).status_code, 403)

    def test_tenants_off_blocks_resident_endpoints(self):
        self.set_levels(tenants=OFF, finance=VIEW)
        self.assertEqual(self.client.get(reverse('resident-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('resident-detail', args=[self.resident.id])).status_code, 403)
        self.assertEqual(self.client.get(reverse('admission-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('vacate-list')).status_code, 403)

    def test_timeline_needs_both_tenants_and_finance(self):
        timeline = reverse('resident-timeline', args=[self.resident.id])
        self.set_levels(tenants=OFF, finance=VIEW)
        self.assertEqual(self.client.get(timeline).status_code, 403)
        self.set_levels(tenants=FULL, finance=OFF)
        self.assertEqual(self.client.get(timeline).status_code, 403)
        self.set_levels(tenants=VIEW, finance=VIEW)
        self.assertEqual(self.client.get(timeline).status_code, 200)

    def test_bed_occupant_follows_tenants_and_rent_follows_finance(self):
        bed = reverse('bed-detail', args=[self.bed.id])

        self.authenticate(self.staff)
        default = self.client.get(bed).data
        self.assertEqual(default['current_occupant']['id'], str(self.resident.id))
        self.assertIn('rent', default['current_occupant'])
        self.assertIn('history', default)

        self.set_levels(finance=OFF)
        no_money = self.client.get(bed).data
        self.assertIsNotNone(no_money['current_occupant'])
        self.assertNotIn('rent', no_money['current_occupant'])
        self.assertNotIn('history', no_money)

        self.set_levels(tenants=OFF)
        no_tenants = self.client.get(bed)
        self.assertEqual(no_tenants.status_code, 200)  # structural reads stay open
        self.assertIsNone(no_tenants.data['current_occupant'])
        self.assertNotIn('history', no_tenants.data)


class PropertiesVisitorsComplaintsReportsTests(ModuleAccessEnforcementBase):
    def test_properties_levels(self):
        features = reverse('property-features', args=[self.property.id])
        settings = reverse('property-settings', args=[self.property.id])

        self.set_levels(properties=OFF)
        self.assertEqual(self.client.get(features).status_code, 403)

        self.set_levels(properties=VIEW)
        self.assertEqual(self.client.get(features).status_code, 200)
        self.assertEqual(self.client.post(features, {}, format='json').status_code, 403)
        # Property settings (late fees, penalties) are revoked by dropping to View.
        self.assertEqual(self.client.get(settings).status_code, 403)

        self.set_levels(properties=FULL)
        self.assertEqual(self.client.get(settings).status_code, 200)

    def test_property_structure_writes_need_properties_full(self):
        buildings = reverse('building-list')
        self.set_levels(properties=VIEW)
        self.assertEqual(self.client.get(buildings).status_code, 200)
        self.assertEqual(
            self.client.post(buildings, {'property': str(self.property.id), 'name': 'Block Z'}, format='json').status_code,
            403,
        )

    def test_visitors_off_blocks_logging_and_confirming(self):
        self.set_levels(visitors=OFF)
        self.assertEqual(self.client.get(reverse('visitor-list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('visitor-list'), {}, format='json').status_code, 403)
        confirm = f'/api/v1/visitors/{uuid.uuid4()}/confirm/'
        self.assertEqual(self.client.post(confirm).status_code, 403)

        self.set_levels(visitors=FULL)
        self.assertEqual(self.client.get(reverse('visitor-list')).status_code, 200)
        self.assertEqual(self.client.post(confirm).status_code, 404)  # permission passed; no such visitor

    def test_receptionist_with_visitors_full_still_cannot_confirm(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)
        self.assertEqual(self.client.post(f'/api/v1/visitors/{uuid.uuid4()}/confirm/').status_code, 403)

    def test_complaints_off_blocks_the_module_and_assignment(self):
        complaint = OperationsAPITestCase.create_complaint(self.resident)
        assign = f'/api/v1/complaints/{complaint.id}/assign/'

        self.set_levels(complaints=OFF)
        self.assertEqual(self.client.get(reverse('complaint-list')).status_code, 403)

        self.authenticate(self.owner)
        rejected = self.client.post(assign, {'assigned_to': str(self.staff.id)})
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn('assigned_to', rejected.data)

        self.set_levels(complaints=FULL)
        self.authenticate(self.owner)
        accepted = self.client.post(assign, {'assigned_to': str(self.staff.id)})
        self.assertEqual(accepted.status_code, 200, accepted.data)

    def test_reports_off_blocks_occupancy_export(self):
        self.set_levels(reports=OFF)
        self.assertEqual(self.client.get(reverse('export-occupancy')).status_code, 403)
        self.set_levels(reports=FULL)
        self.assertEqual(self.client.get(reverse('export-occupancy')).status_code, 200)

    def test_dashboard_code_is_ui_visibility_only(self):
        """view_dashboard rides on /auth/me/ but gates no endpoint: data is enforced
        per module regardless of the dashboard toggle."""
        self.set_levels(dashboard=OFF)
        me = self.client.get(reverse('auth-me'))
        self.assertNotIn('view_dashboard', me.data['permissions'])
        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 200)

        self.set_levels(dashboard=FULL, finance=OFF)
        me = self.client.get(reverse('auth-me'))
        self.assertIn('view_dashboard', me.data['permissions'])
        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 403)

    def test_owner_is_never_affected(self):
        self.authenticate(self.owner)
        for name in ('invoice-list', 'payment-list', 'discount-list', 'resident-list', 'visitor-list'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        me = self.client.get(reverse('auth-me')).data['permissions']
        self.assertTrue({'view_dashboard', 'view_finance', 'manage_staff_accounts'} <= set(me))
