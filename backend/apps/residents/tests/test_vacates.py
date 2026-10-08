import threading
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Property
from apps.residents import services
from apps.residents.models import Admission, Allocation, Resident, Vacate

from .base import ResidentAPITestCase


class VacateTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor)
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed, security_deposit_amount=Decimal('1500.00'))
        self.authenticate(self.owner)

    def _give_notice(self, **overrides):
        payload = {'resident': str(self.resident.id), 'notice_given_date': '2026-07-01'}
        payload.update(overrides)
        return self.client.post(reverse('vacate-list'), payload)

    def test_give_notice_moves_resident_to_notice_period(self):
        response = self._give_notice()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['expected_vacate_date'], '2026-08-01')
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.NOTICE_PERIOD)

    def test_expected_vacate_date_clamps_to_shorter_month(self):
        response = self._give_notice(notice_given_date='2026-01-31')
        self.assertEqual(response.data['expected_vacate_date'], '2026-02-28')

    def test_cannot_give_notice_for_non_active_resident(self):
        reserved = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        response = self._give_notice(resident=str(reserved.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_cannot_give_notice_twice(self):
        self._give_notice()
        with tenant_context(self.tenant.id):
            self.resident.status = Resident.Status.ACTIVE
            self.resident.save(update_fields=['status', 'updated_at'])
        response = self._give_notice()
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_give_notice_is_audit_logged(self):
        self._give_notice()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.notice_given').exists())
            self.assertTrue(AuditLog.objects.filter(action='resident.status_changed').exists())


class VacateFinalizeTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor)
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed, security_deposit_amount=Decimal('1500.00'))
        self.authenticate(self.owner)
        self.vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        }).data

    def _finalize(self, **overrides):
        payload = {'actual_vacate_date': '2026-08-01'}
        payload.update(overrides)
        return self.client.post(reverse('vacate-finalize', args=[self.vacate['id']]), payload)

    def test_finalize_with_zero_deduction_refunds_full_deposit(self):
        response = self._finalize()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['refund_amount'], '1500.00')
        self.assertTrue(response.data['is_settled'])

        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.bed.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.VACATED)
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)

    def test_finalize_with_deduction_reduces_refund(self):
        response = self._finalize(maintenance_deduction='500.00', maintenance_deduction_note='Wall damage')
        self.assertEqual(response.data['refund_amount'], '1000.00')

    def test_unapplied_advance_surplus_is_refunded_with_the_deposit(self):
        with tenant_context(self.tenant.id):
            admission = self.resident.admission
            admission.advance_amount = Decimal('7000.00')
            admission.advance_applied_amount = Decimal('3500.00')  # first invoice used half
            admission.save(update_fields=['advance_amount', 'advance_applied_amount'])

        response = self._finalize(maintenance_deduction='500.00')

        # 1500 deposit - 500 deduction + 3500 unapplied advance
        self.assertEqual(response.data['advance_refundable'], '3500.00')
        self.assertEqual(response.data['security_deposit_amount'], '1500.00')
        self.assertEqual(response.data['refund_amount'], '4500.00')

    def test_deduction_cannot_exceed_deposit(self):
        response = self._finalize(maintenance_deduction='2000.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('maintenance_deduction', response.data)

    def test_deduction_cannot_be_negative(self):
        response = self._finalize(maintenance_deduction='-1.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('maintenance_deduction', response.data)

    def test_cannot_finalize_twice(self):
        self._finalize()
        response = self._finalize()
        self.assertEqual(response.status_code, 400)

    def test_finalize_is_audit_logged(self):
        self._finalize()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.vacated').exists())

    def test_receptionist_cannot_manage_vacates(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('vacate-list')).status_code, 403)
        self.assertEqual(self._finalize().status_code, 403)

    def test_manager_scoped_to_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_room = self.create_room(self.create_floor(other_property))
        other_resident = self.create_resident(other_property, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(other_resident, self.create_bed(other_room))

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        blocked = self.client.post(reverse('vacate-list'), {
            'resident': str(other_resident.id), 'notice_given_date': '2026-07-01',
        })
        self.assertEqual(blocked.status_code, 400)

    def test_vacate_detail_is_tenant_scoped(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('vacate-detail', args=[self.vacate['id']]))
        self.assertEqual(response.status_code, 404)


class VacateCancelTests(ResidentAPITestCase):
    """Withdrawing a notice: Notice Period -> Active (owner request
    2026-10-07). The defining property of this action is how little it touches
    — bed, allocation and contracted rent must all come out unchanged."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor)
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.allocation = self.check_in(
            self.resident, self.bed, security_deposit_amount=Decimal('1500.00')
        )
        self.contracted_rent = self.allocation.contracted_rent
        self.authenticate(self.owner)
        self.vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        }).data

    def _cancel(self, vacate_id=None, **overrides):
        payload = {'cancellation_reason': 'Resident decided to stay on'}
        payload.update(overrides)
        return self.client.post(
            reverse('vacate-cancel', args=[vacate_id or self.vacate['id']]), payload
        )

    def test_cancel_returns_resident_to_active(self):
        response = self._cancel(cancelled_date='2026-07-10')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_cancelled'])
        self.assertFalse(response.data['is_open'])
        self.assertEqual(response.data['cancelled_date'], '2026-07-10')
        self.assertEqual(response.data['cancellation_reason'], 'Resident decided to stay on')

        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.ACTIVE)

    def test_cancel_leaves_bed_allocation_and_rent_untouched(self):
        self._cancel()

        with tenant_context(self.tenant.id):
            self.bed.refresh_from_db()
            self.allocation.refresh_from_db()
            admission = self.resident.admission
        # give_notice never released the bed, so it must still be taken.
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        self.assertEqual(self.allocation.allocated_bed_id, self.bed.id)
        # Invariant 2: contracted rent stays as snapshotted, never re-derived.
        self.assertEqual(self.allocation.contracted_rent, self.contracted_rent)
        self.assertEqual(admission.contracted_rent, self.contracted_rent)
        self.assertEqual(admission.security_deposit_amount, Decimal('1500.00'))

    def test_cancelled_date_defaults_to_today(self):
        response = self._cancel()
        self.assertEqual(response.data['cancelled_date'], timezone.localdate().isoformat())

    def test_resident_can_give_notice_again_after_cancelling(self):
        self._cancel()

        second = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-09-01',
        })

        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(second.data['id'], self.vacate['id'])
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.assertEqual(Vacate.objects.filter(resident=self.resident).count(), 2)
        self.assertEqual(self.resident.status, Resident.Status.NOTICE_PERIOD)

    def test_cannot_cancel_twice(self):
        self._cancel()
        response = self._cancel()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'].code, 'already_cancelled')

    def test_cannot_cancel_a_settled_vacate(self):
        self.client.post(
            reverse('vacate-finalize', args=[self.vacate['id']]),
            {'actual_vacate_date': '2026-08-01'},
        )
        response = self._cancel()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'].code, 'already_settled')

    def test_cannot_finalize_a_cancelled_vacate(self):
        """The regression this feature could otherwise introduce: settling a
        withdrawn notice would re-vacate an Active resident and free their
        bed."""
        self._cancel()

        response = self.client.post(
            reverse('vacate-finalize', args=[self.vacate['id']]),
            {'actual_vacate_date': '2026-08-01'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'].code, 'already_cancelled')
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.bed.refresh_from_db()
            self.allocation.refresh_from_db()
            vacate = Vacate.objects.get(pk=self.vacate['id'])
        self.assertEqual(self.resident.status, Resident.Status.ACTIVE)
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        self.assertEqual(self.allocation.contracted_rent, self.contracted_rent)
        self.assertIsNone(vacate.actual_vacate_date)
        self.assertIsNone(vacate.maintenance_deduction)

    def test_reason_is_mandatory(self):
        for reason in ('', '   '):
            response = self._cancel(cancellation_reason=reason)
            self.assertEqual(response.status_code, 400, reason)
            self.assertIn('cancellation_reason', response.data)

    def test_cancelled_date_cannot_predate_the_notice(self):
        response = self._cancel(cancelled_date='2026-06-30')
        self.assertEqual(response.status_code, 400)
        self.assertIn('cancelled_date', response.data)

    def test_cancelled_date_cannot_be_in_the_future(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        response = self._cancel(cancelled_date=tomorrow.isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn('cancelled_date', response.data)

    def test_cancel_is_audit_logged_with_date_and_reason(self):
        self._cancel(cancelled_date='2026-07-10')

        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='resident.notice_cancelled')
            status_entry = AuditLog.objects.filter(
                action='resident.status_changed', object_id=str(self.resident.id),
            ).order_by('-created_at').first()
        self.assertEqual(entry.after['cancelled_date'], '2026-07-10')
        self.assertEqual(entry.after['cancellation_reason'], 'Resident decided to stay on')
        self.assertEqual(entry.before['notice_given_date'], '2026-07-01')
        self.assertEqual(status_entry.before['status'], Resident.Status.NOTICE_PERIOD)
        self.assertEqual(status_entry.after['status'], Resident.Status.ACTIVE)

    def test_receptionist_cannot_cancel(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self._cancel().status_code, 403)

    def test_manager_cannot_cancel_outside_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_resident = self.create_resident(
            other_property, phone='9000000002', status=Resident.Status.RESERVED
        )
        self.check_in(
            other_resident,
            self.create_bed(self.create_room(self.create_floor(other_property))),
        )
        other_vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(other_resident.id), 'notice_given_date': '2026-07-01',
        }).data

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        self.assertEqual(self._cancel(vacate_id=other_vacate['id']).status_code, 404)

    def test_cannot_cancel_another_tenants_vacate(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        self.assertEqual(self._cancel().status_code, 404)
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.NOTICE_PERIOD)


class VacateConstraintTests(ResidentAPITestCase):
    """Database-level backstops. The services enforce these too, but Django
    admin and management commands bypass the services entirely."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.property = self.create_property(self.tenant)
        self.bed = self.create_bed(
            self.create_room(self.create_floor(self.property)), bed_number='101-A'
        )
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed)

    def _assert_insert_rejected(self, **kwargs):
        """The atomic savepoint has to sit INSIDE the tenant context: the failed
        INSERT poisons the transaction, and tenant_context's exit runs a query
        of its own to restore the previous context. Rolling the savepoint back
        first leaves it a healthy transaction to do that in."""
        kwargs.setdefault('notice_given_date', date(2026, 9, 1))
        kwargs.setdefault('expected_vacate_date', date(2026, 10, 1))
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Vacate.objects.create(
                        tenant_id=self.resident.tenant_id, resident=self.resident, **kwargs
                    )

    def test_two_open_vacates_are_rejected(self):
        self.create_vacate(self.resident)

        self._assert_insert_rejected()

    def test_a_closed_vacate_does_not_block_a_new_one(self):
        self.create_vacate(self.resident, cancelled_date=date(2026, 7, 5))
        self.create_vacate(self.resident, notice_given_date=date(2026, 9, 1))

        with tenant_context(self.tenant.id):
            self.assertEqual(Vacate.objects.filter(resident=self.resident).count(), 2)

    def test_cancelled_and_settled_cannot_coexist(self):
        self._assert_insert_rejected(
            cancelled_date=date(2026, 7, 5), actual_vacate_date=date(2026, 8, 1),
        )

    def test_accessors_pick_by_state_not_position(self):
        settled = self.create_vacate(
            self.resident, notice_given_date=date(2026, 1, 1),
            actual_vacate_date=date(2026, 2, 1), maintenance_deduction=Decimal('0.00'),
        )
        cancelled = self.create_vacate(
            self.resident, notice_given_date=date(2026, 3, 1), cancelled_date=date(2026, 3, 5),
        )
        open_vacate = self.create_vacate(self.resident, notice_given_date=date(2026, 5, 1))

        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.assertEqual(self.resident.open_vacate.id, open_vacate.id)
            # latest_vacate is positional; latest_settled_vacate must skip the
            # later cancelled row and find the genuinely settled one.
            self.assertEqual(self.resident.latest_vacate.id, open_vacate.id)
            self.assertEqual(self.resident.latest_settled_vacate.id, settled.id)
            self.assertNotEqual(self.resident.latest_settled_vacate.id, cancelled.id)


class BedOccupancyHistoryTests(ResidentAPITestCase):
    """Module 02's bed `history` field reads a resident's vacates (Module 10).
    With several rows per resident it has to pick by STATE, and must not fall
    into a query per admission."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.room = self.create_room(self.create_floor(self.property))
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.authenticate(self.owner)

    def _history(self):
        response = self.client.get(reverse('bed-detail', args=[self.bed.id]))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['history']

    def _occupy(self, phone, status):
        resident = self.create_resident(
            self.property, phone=phone, status=Resident.Status.RESERVED
        )
        self.check_in(resident, self.bed)
        with tenant_context(self.tenant.id):
            resident.status = status
            resident.save(update_fields=['status', 'updated_at'])
        return resident

    def test_notice_period_shows_the_open_notice_not_a_cancelled_one(self):
        resident = self._occupy('9000000011', Resident.Status.NOTICE_PERIOD)
        # An earlier notice that was withdrawn, then the one now running.
        self.create_vacate(
            resident, notice_given_date=date(2026, 1, 1),
            expected_vacate_date=date(2026, 2, 1), cancelled_date=date(2026, 1, 5),
        )
        self.create_vacate(
            resident, notice_given_date=date(2026, 6, 1), expected_vacate_date=date(2026, 7, 1),
        )

        move_out = self._history()[0]['moveOut']

        self.assertIn('07/01/26', move_out)
        self.assertNotIn('02/01/26', move_out)

    def test_vacated_shows_the_settled_notice_not_a_later_cancelled_one(self):
        resident = self._occupy('9000000012', Resident.Status.VACATED)
        self.create_vacate(
            resident, notice_given_date=date(2026, 1, 1),
            expected_vacate_date=date(2026, 2, 1), actual_vacate_date=date(2026, 2, 3),
            maintenance_deduction=Decimal('0.00'),
        )
        # A cancelled row dated later must not be mistaken for the move-out.
        self.create_vacate(
            resident, notice_given_date=date(2026, 5, 1),
            expected_vacate_date=date(2026, 6, 1), cancelled_date=date(2026, 5, 4),
        )

        self.assertEqual(self._history()[0]['moveOut'], '02/03/26')

    def test_history_does_not_query_per_admission(self):
        """The vacates are prefetched, so adding occupants must not add queries
        — guards the N+1 the OneToOne -> FK change could have introduced. The
        assertion is that the count does not GROW, not what the count is."""
        first = self._occupy('9000000013', Resident.Status.VACATED)
        self.create_vacate(
            first, actual_vacate_date=date(2026, 8, 1), maintenance_deduction=Decimal('0.00'),
        )
        with CaptureQueriesContext(connection) as one_occupant:
            self._history()

        for index, phone in enumerate(('9000000014', '9000000015', '9000000016')):
            resident = self._occupy(phone, Resident.Status.NOTICE_PERIOD)
            self.create_vacate(resident, notice_given_date=date(2026, 9, 1 + index))

        with CaptureQueriesContext(connection) as four_occupants:
            history = self._history()

        self.assertEqual(len(history), 4)
        self.assertEqual(len(four_occupants), len(one_occupant))


class VacateConcurrencyTests(TransactionTestCase):
    """The Resident -> Vacate lock order in services.lock_resident. Needs real
    commits on separate connections, so this can't be a transaction-wrapped
    TestCase. Service-level, not through the API: the loser surfaces as a
    ValidationError rather than a 400, and the threads stay off DRF clients."""

    def _fixture_teardown(self):
        # The default flush would also wipe migration-seeded tables (plans,
        # feature_catalog, notification templates) for the rest of the run;
        # tearDown removes exactly what this test created instead.
        pass

    def setUp(self):
        self.tenant = ResidentAPITestCase.create_tenant('Vacate Concurrency Tenant')
        # Per-test unique email: _fixture_teardown is a no-op here, so a row
        # this test leaves behind would collide with the next one.
        self.owner = ResidentAPITestCase.create_owner(
            self.tenant, email=f'{self._testMethodName}@concurrency.example.com'
        )
        self.property = ResidentAPITestCase.create_property(self.tenant)
        bed = ResidentAPITestCase.create_bed(
            ResidentAPITestCase.create_room(ResidentAPITestCase.create_floor(self.property)),
            bed_number='101-A',
        )
        self.resident = ResidentAPITestCase.create_resident(
            self.property, status=Resident.Status.RESERVED
        )
        ResidentAPITestCase.check_in(self.resident, bed, security_deposit_amount=Decimal('1000.00'))

    def tearDown(self):
        # Resident is PROTECTed by Vacate/Allocation/Admission, and Bed by
        # Admission/Allocation — so unwind in dependency order rather than
        # relying on a cascade.
        with tenant_context(is_super_admin=True):
            Vacate.objects.filter(resident=self.resident).delete()
            Allocation.objects.filter(resident=self.resident).delete()
            Admission.objects.filter(resident=self.resident).delete()
            Resident.objects.filter(pk=self.resident.pk).delete()
            Property.objects.filter(pk=self.property.pk).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        self.owner.delete()
        self.tenant.delete()

    def _run_together(self, *callables):
        """Fire each callable on its own connection, released together at a
        barrier. Returns (successes, ValidationErrors) and re-raises anything
        else — an IntegrityError here would mean the lock isn't holding."""
        barrier = threading.Barrier(len(callables))
        successes, rejections, unexpected = [], [], []

        def worker(fn):
            try:
                barrier.wait(timeout=10)
                with tenant_context(self.tenant.id):
                    successes.append(fn())
            except ValidationError as exc:
                rejections.append(exc)
            except Exception as exc:  # noqa: BLE001 — surfaced through `unexpected`
                unexpected.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(fn,)) for fn in callables]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(unexpected, [], f'unexpected errors: {unexpected}')
        return successes, rejections

    def test_cancel_and_finalize_cannot_both_succeed(self):
        with tenant_context(self.tenant.id):
            vacate = services.give_notice(
                resident=self.resident, notice_given_date=date(2026, 7, 1), actor=self.owner,
            )

        def cancel():
            return services.cancel_notice(
                vacate=vacate, cancelled_date=date(2026, 7, 10),
                cancellation_reason='Staying on', actor=self.owner,
            )

        def finalize():
            return services.finalize_vacate(
                vacate=vacate, actual_vacate_date=date(2026, 8, 1),
                maintenance_deduction=Decimal('0.00'), maintenance_deduction_note='',
                refund_date=None, refund_mode='', refund_note='', actor=self.owner,
            )

        successes, rejections = self._run_together(cancel, finalize)

        self.assertEqual(len(successes), 1, 'exactly one of cancel/finalize must win')
        self.assertEqual(len(rejections), 1)
        with tenant_context(self.tenant.id):
            vacate.refresh_from_db()
            self.resident.refresh_from_db()
        # Whichever won, the row is closed exactly once and the resident's
        # status matches it — never both cancelled and settled.
        self.assertFalse(vacate.is_open)
        self.assertNotEqual(vacate.is_cancelled, vacate.is_settled)
        expected = (
            Resident.Status.ACTIVE if vacate.is_cancelled else Resident.Status.VACATED
        )
        self.assertEqual(self.resident.status, expected)

    def test_concurrent_give_notice_yields_one_clean_rejection(self):
        """Pre-existing race, now guarded: without the resident lock both calls
        pass the unlocked `exists()` check and the second hits
        unique_open_vacate_per_resident as an uncaught IntegrityError (a 500)."""
        def give_notice():
            return services.give_notice(
                resident=self.resident, notice_given_date=date(2026, 7, 1), actor=self.owner,
            )

        successes, rejections = self._run_together(give_notice, give_notice)

        self.assertEqual(len(successes), 1, 'exactly one give-notice must win')
        self.assertEqual(len(rejections), 1)
        with tenant_context(self.tenant.id):
            self.assertEqual(Vacate.objects.filter(resident=self.resident).count(), 1)
