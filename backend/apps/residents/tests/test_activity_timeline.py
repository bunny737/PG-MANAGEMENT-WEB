from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.billing.tests.base import BillingAPITestCase
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.operations.models import Complaint
from apps.properties.models import Room
from apps.residents.models import Resident

TODAY = date.today()
# Narrative dates are relative to TODAY, never hardcoded — several timeline
# events are sourced from auto_now(_add) fields (AuditLog.created_at,
# Complaint.created_at, BlacklistEntry.created_at, AbscondedRecord.updated_at)
# which always reflect the real test-run clock. A hardcoded fictional date
# would sort inconsistently against those real timestamps.
PERIOD = {
    'period_start': TODAY.isoformat(),
    'period_end': (TODAY + timedelta(days=30)).isoformat(),
    'due_date': (TODAY + timedelta(days=10)).isoformat(),
}


class ActivityTimelineTestCase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.receptionist = self.create_user(self.tenant, Role.RECEPTIONIST, 'front@example.com')
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room_a = self.create_room(
            self.floor, room_number='101', sharing_type=Room.SharingType.FOUR, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.room_b = self.create_room(
            self.floor, room_number='201', sharing_type=Room.SharingType.TWO, category=Room.Category.AC,
            rack_rate_with_food=Decimal('10000.00'), rack_rate_without_food=Decimal('8000.00'),
        )
        self.bed_a = self.create_bed(self.room_a, bed_number='101-A')
        self.bed_b = self.create_bed(self.room_b, bed_number='201-A')
        self.authenticate(self.owner)

    def _timeline(self, resident):
        return self.client.get(reverse('resident-timeline', args=[resident.id]))

    def _generate_and_issue_invoice(self, resident, **period_overrides):
        period = {**PERIOD, **period_overrides}
        generated = self.client.post(
            reverse('invoice-list'), {'resident': str(resident.id), **period}
        ).data
        self.client.post(reverse('invoice-issue', args=[generated['id']]))
        return generated['id']

    def _pay(self, invoice_id, amount, payment_date):
        return self.client.post(reverse('payment-list'), {
            'invoice': invoice_id, 'amount': str(amount),
            'payment_date': payment_date.isoformat(), 'payment_mode': 'upi',
        })

    def _create_complaint(self, resident, **kwargs):
        with tenant_context(resident.tenant_id):
            return Complaint.objects.create(
                tenant_id=resident.tenant_id, resident=resident,
                category=Complaint.Category.ELECTRICAL, description='Fan not working', **kwargs
            )


class CoreLifecycleTimelineTests(ActivityTimelineTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.create_resident(self.property, status=Resident.Status.INQUIRY)

    def _events(self, resident):
        response = self._timeline(resident)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_inquiry_event_present_from_creation(self):
        events = self._events(self.resident)
        self.assertEqual(events[0]['event'], 'Inquiry Received')

    def test_reserved_event_sourced_from_status_change(self):
        self.client.patch(
            reverse('resident-status', args=[self.resident.id]), {'status': Resident.Status.RESERVED}
        )

        labels = [e['event'] for e in self._events(self.resident)]
        self.assertIn('Room Reserved', labels)

    def test_full_lifecycle_events_appear_in_chronological_order(self):
        self.client.patch(
            reverse('resident-status', args=[self.resident.id]), {'status': Resident.Status.RESERVED}
        )
        self.check_in(self.resident, self.bed_a)  # joining_date defaults to today

        invoice_id = self._generate_and_issue_invoice(self.resident)
        pay_response = self._pay(invoice_id, Decimal('2000.00'), TODAY)
        self.assertEqual(pay_response.status_code, 201, pay_response.data)
        self._pay(invoice_id, Decimal('5000.00'), TODAY)  # 7000 total -> fully paid, same day

        self._create_complaint(self.resident)

        labels = [e['event'] for e in self._events(self.resident)]

        self.assertEqual(labels[0], 'Inquiry Received')
        self.assertIn('Room Reserved', labels)
        self.assertIn('Admission Completed — Checked In', labels)
        self.assertIn('Invoice Generated', labels)
        self.assertIn('Partial Payment', labels)
        self.assertIn('Remaining Paid', labels)
        self.assertIn('Complaint Raised', labels)

        # Chronological: index ordering must match narrative ordering.
        self.assertLess(labels.index('Inquiry Received'), labels.index('Room Reserved'))
        self.assertLess(labels.index('Room Reserved'), labels.index('Admission Completed — Checked In'))
        self.assertLess(labels.index('Admission Completed — Checked In'), labels.index('Invoice Generated'))
        self.assertLess(labels.index('Invoice Generated'), labels.index('Partial Payment'))
        self.assertLess(labels.index('Partial Payment'), labels.index('Remaining Paid'))
        self.assertLess(labels.index('Remaining Paid'), labels.index('Complaint Raised'))

    def test_admission_event_detail_names_room_and_bed(self):
        self.check_in(self.resident, self.bed_a)

        events = self._events(self.resident)
        admission_event = next(e for e in events if e['event'] == 'Admission Completed — Checked In')
        self.assertIn('101', admission_event['detail'])
        self.assertIn('101-A', admission_event['detail'])

    def test_single_full_payment_labeled_payment_received(self):
        self.check_in(self.resident, self.bed_a)
        invoice_id = self._generate_and_issue_invoice(self.resident)
        self._pay(invoice_id, Decimal('7000.00'), TODAY)  # full amount, one shot

        labels = [e['event'] for e in self._events(self.resident)]
        self.assertIn('Payment Received', labels)
        self.assertNotIn('Partial Payment', labels)
        self.assertNotIn('Remaining Paid', labels)

    def test_overdue_invoice_shows_overdue_event_when_still_unpaid(self):
        self.check_in(self.resident, self.bed_a)
        past_due_date = (TODAY - timedelta(days=5)).isoformat()
        self._generate_and_issue_invoice(self.resident, due_date=past_due_date)

        labels = [e['event'] for e in self._events(self.resident)]
        self.assertIn('Invoice Overdue', labels)

    def test_fully_paid_invoice_past_due_date_has_no_overdue_event(self):
        self.check_in(self.resident, self.bed_a)
        past_due_date = (TODAY - timedelta(days=5)).isoformat()
        invoice_id = self._generate_and_issue_invoice(self.resident, due_date=past_due_date)
        self._pay(invoice_id, Decimal('7000.00'), TODAY)

        labels = [e['event'] for e in self._events(self.resident)]
        self.assertNotIn('Invoice Overdue', labels)

    def test_transfer_event_names_destination_room_and_bed(self):
        self.check_in(self.resident, self.bed_a)
        self.client.post(reverse('transfer-list'), {
            'resident': str(self.resident.id), 'new_bed': str(self.bed_b.id),
            'transfer_date': TODAY.isoformat(),
        })

        events = self._events(self.resident)
        transfer_event = next(e for e in events if e['event'] == 'Transferred')
        self.assertIn('201', transfer_event['detail'])
        self.assertIn('201-A', transfer_event['detail'])


class ExitLifecycleTimelineTests(ActivityTimelineTestCase):
    def test_vacate_timeline_shows_notice_and_settlement(self):
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(resident, self.bed_a, advance_amount=Decimal('1000.00'))
        self.client.post(reverse('vacate-list'), {
            'resident': str(resident.id), 'notice_given_date': TODAY.isoformat(),
        })
        vacate_id = self.client.get(reverse('vacate-list')).data[0]['id']
        finalize_response = self.client.post(reverse('vacate-finalize', args=[vacate_id]), {
            'actual_vacate_date': (TODAY + timedelta(days=30)).isoformat(),
            'maintenance_deduction': '500.00', 'maintenance_deduction_note': 'Cleaning',
            'refund_date': (TODAY + timedelta(days=31)).isoformat(), 'refund_mode': 'upi', 'refund_note': '',
        })
        self.assertEqual(finalize_response.status_code, 200, finalize_response.data)

        labels = [e['event'] for e in self._timeline(resident).data]
        self.assertIn('Notice Given', labels)
        self.assertIn('Vacated', labels)
        self.assertLess(labels.index('Notice Given'), labels.index('Vacated'))

    def test_absconded_lifecycle_shows_forfeit_writeoff_and_blacklist(self):
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(resident, self.bed_a, advance_amount=Decimal('2000.00'))
        self._generate_and_issue_invoice(resident)  # outstanding dues to forfeit against

        self.client.post(reverse('absconded-record-list'), {
            'resident': str(resident.id), 'absconded_date': TODAY.isoformat(),
            'last_seen_date': (TODAY - timedelta(days=2)).isoformat(), 'absconded_note': 'Room found empty',
        })
        record_id = self.client.get(reverse('absconded-record-list')).data[0]['id']
        self.client.post(reverse('absconded-record-write-off', args=[record_id]), {
            'note': 'Unrecoverable',
        })
        self.client.post(reverse('blacklist-entry-list'), {
            'resident': str(resident.id), 'reason': 'Absconded with dues',
        })

        labels = [e['event'] for e in self._timeline(resident).data]
        self.assertIn('Marked Absconded', labels)
        self.assertIn('Advance Forfeited', labels)
        self.assertIn('Dues Written Off', labels)
        self.assertIn('Blacklisted', labels)
        self.assertLess(labels.index('Marked Absconded'), labels.index('Advance Forfeited'))
        self.assertLessEqual(labels.index('Advance Forfeited'), labels.index('Dues Written Off'))
        self.assertLessEqual(labels.index('Dues Written Off'), labels.index('Blacklisted'))


class TimelinePermissionTests(ActivityTimelineTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.create_resident(self.property, status=Resident.Status.INQUIRY)

    def test_manager_assigned_to_property_can_view(self):
        self.assign_staff(self.manager, self.property)
        self.authenticate(self.manager)

        response = self._timeline(self.resident)
        self.assertEqual(response.status_code, 200)

    def test_receptionist_is_forbidden(self):
        self.authenticate(self.receptionist)

        response = self._timeline(self.resident)
        self.assertEqual(response.status_code, 403)

    def test_manager_not_assigned_to_property_gets_404(self):
        self.authenticate(self.manager)

        response = self._timeline(self.resident)
        self.assertEqual(response.status_code, 404)
