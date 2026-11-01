"""Partial security-deposit collection (Module 10, 2026-11-01): the agreed deposit vs what has been
collected, the ledger behind it, and recording the rest later."""
import importlib
from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Room
from apps.residents.models import Admission, DepositPayment, Resident

from .base import ResidentAPITestCase
from .test_admissions import admission_payload


def payment_payload(resident, **overrides):
    payload = {
        'resident': str(resident.id), 'amount': '3000.00',
        'payment_date': '2026-07-04', 'payment_mode': 'upi',
    }
    payload.update(overrides)
    return payload


class DepositSetUp(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=Room.SharingType.ONE, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room)
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.authenticate(self.owner)

    def admit(self, **overrides):
        """Admit through the API with a partial deposit by default: 2000 of an agreed 5000."""
        overrides = {
            'advance_amount': '0.00', 'security_deposit_agreed': '5000.00',
            'security_deposit_amount': '2000.00', **overrides,
        }
        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed, **overrides))
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def admission(self):
        with tenant_context(self.tenant.id):
            return Admission.objects.get(resident=self.resident)

    def ledger(self):
        with tenant_context(self.tenant.id):
            return list(DepositPayment.objects.filter(admission__resident=self.resident).order_by('created_at'))

    def pay(self, **overrides):
        return self.client.post(reverse('deposit-payment-list'), payment_payload(self.resident, **overrides))


class AdmissionWithPartialDepositTests(DepositSetUp):
    def test_partial_deposit_is_stored_with_the_agreed_total_and_one_ledger_row(self):
        response = self.admit()

        self.assertEqual(response.data['security_deposit_amount'], '2000.00')
        self.assertEqual(response.data['security_deposit_agreed'], '5000.00')
        self.assertEqual(response.data['security_deposit_pending'], '3000.00')
        ledger = self.ledger()
        self.assertEqual([(p.amount, p.payment_mode, p.payment_date) for p in ledger],
                         [(Decimal('2000.00'), 'cash', date(2026, 7, 1))])

    def test_rent_advance_may_be_zero_with_nothing_collected_for_it(self):
        response = self.admit(advance_amount='0.00')

        self.assertEqual(response.data['advance_amount'], '0.00')

    def test_agreed_defaults_to_the_collected_amount_for_clients_that_do_not_send_it(self):
        payload = admission_payload(self.resident, self.bed)  # sends only security_deposit_amount 1500
        response = self.client.post(reverse('admission-list'), payload)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['security_deposit_agreed'], '1500.00')
        self.assertEqual(response.data['security_deposit_pending'], '0.00')

    def test_collected_cannot_exceed_agreed(self):
        response = self.client.post(reverse('admission-list'), admission_payload(
            self.resident, self.bed, security_deposit_agreed='1000.00', security_deposit_amount='1500.00',
        ))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['security_deposit_amount'][0].code, 'deposit_exceeds_agreed')

    def test_nothing_collected_at_admission_means_no_ledger_row_and_all_pending(self):
        response = self.admit(security_deposit_amount='0.00', security_deposit_collected_date='',
                              security_deposit_mode='')

        self.assertEqual(response.data['security_deposit_pending'], '5000.00')
        self.assertEqual(self.ledger(), [])

    def test_resident_detail_shows_agreed_collected_and_pending(self):
        self.admit()

        detail = self.client.get(reverse('resident-detail', args=[self.resident.id])).data

        self.assertEqual(
            (detail['security_deposit_agreed'], detail['security_deposit_amount'], detail['security_deposit_pending']),
            ('5000.00', '2000.00', '3000.00'),
        )


class RecordDepositPaymentTests(DepositSetUp):
    def setUp(self):
        super().setUp()
        self.admit()

    def test_recording_the_rest_updates_collected_pending_and_the_ledger(self):
        response = self.pay()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['amount'], '3000.00')
        admission = self.admission()
        self.assertEqual(admission.security_deposit_amount, Decimal('5000.00'))
        self.assertEqual(admission.security_deposit_pending, Decimal('0.00'))
        self.assertEqual(len(self.ledger()), 2)

    def test_it_is_audit_logged_with_before_and_after(self):
        response = self.pay(amount='1000.00')

        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='deposit.payment_recorded', object_id=response.data['id'])
        self.assertEqual(entry.actor_id, self.owner.id)
        self.assertEqual(entry.before['security_deposit_collected'], '2000.00')
        self.assertEqual(entry.after['security_deposit_collected'], '3000.00')
        self.assertEqual(entry.after['security_deposit_pending'], '2000.00')

    def test_paying_more_than_pending_is_rejected(self):
        response = self.pay(amount='3000.01')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['amount'][0].code, 'deposit_overpaid')
        self.assertEqual(self.admission().security_deposit_amount, Decimal('2000.00'))

    def test_two_payments_cannot_together_exceed_the_agreed_deposit(self):
        self.assertEqual(self.pay(amount='2000.00').status_code, 201)

        second = self.pay(amount='1500.00')

        self.assertEqual(second.status_code, 400)
        self.assertEqual(self.admission().security_deposit_amount, Decimal('4000.00'))

    def test_zero_and_negative_amounts_are_rejected(self):
        for amount in ('0.00', '-5.00'):
            self.assertEqual(self.pay(amount=amount).status_code, 400, amount)

    def test_unknown_payment_mode_is_rejected(self):
        self.assertEqual(self.pay(payment_mode='card').status_code, 400)

    def test_a_vacated_resident_cannot_pay_a_deposit(self):
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(status=Resident.Status.VACATED)

        response = self.pay()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['resident'].code, 'resident_not_current')

    def test_a_resident_on_notice_can_still_pay(self):
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(status=Resident.Status.NOTICE_PERIOD)

        self.assertEqual(self.pay().status_code, 201)

    def test_resident_who_was_never_admitted_is_rejected(self):
        other = self.create_resident(self.property, phone='9000000009', status=Resident.Status.RESERVED)

        response = self.client.post(reverse('deposit-payment-list'), payment_payload(other))

        self.assertEqual(response.status_code, 400)

    def test_receptionist_cannot_record_or_list_deposit_payments(self):
        self.authenticate(self.create_receptionist(self.tenant))

        self.assertEqual(self.pay().status_code, 403)
        self.assertEqual(self.client.get(reverse('deposit-payment-list')).status_code, 403)

    def test_manager_can_only_record_for_assigned_properties(self):
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)  # not assigned to this property

        self.assertEqual(self.pay().status_code, 400)
        self.assertEqual(self.admission().security_deposit_amount, Decimal('2000.00'))

        self.assign_staff(manager, self.property)
        self.assertEqual(self.pay().status_code, 201)

    def test_list_filters_by_resident_and_is_property_scoped(self):
        self.pay(amount='1000.00')
        other_property = self.create_property(self.tenant, name='Other Property')
        other_bed = self.create_bed(self.create_room(self.create_floor(other_property)))
        other = self.create_resident(other_property, phone='9000000008', status=Resident.Status.RESERVED)
        self.check_in(other, other_bed, security_deposit_agreed=Decimal('900.00'))
        with tenant_context(self.tenant.id):
            DepositPayment.objects.create(
                tenant_id=self.tenant.id, admission=other.admission, amount=Decimal('400.00'),
                payment_date=date(2026, 7, 1), payment_mode='cash',
            )

        mine = self.client.get(reverse('deposit-payment-list'), {'resident': str(self.resident.id)})
        everything = self.client.get(reverse('deposit-payment-list'))

        self.assertEqual(len(mine.data['results'] if 'results' in mine.data else mine.data), 2)
        self.assertEqual(len(everything.data['results'] if 'results' in everything.data else everything.data), 3)

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, other_property)
        self.authenticate(manager)
        scoped = self.client.get(reverse('deposit-payment-list'))
        rows = scoped.data['results'] if 'results' in scoped.data else scoped.data
        self.assertEqual([row['amount'] for row in rows], ['400.00'])

    def test_the_list_never_includes_another_tenants_payments(self):
        other_tenant = self.create_tenant('Other Tenant')
        other_property = self.create_property(other_tenant)
        other_bed = self.create_bed(self.create_room(self.create_floor(other_property)))
        other = self.create_resident(other_property, phone='9000000007', status=Resident.Status.RESERVED)
        self.check_in(other, other_bed, security_deposit_agreed=Decimal('900.00'))
        with tenant_context(other_tenant.id):
            DepositPayment.objects.create(
                tenant_id=other_tenant.id, admission=other.admission, amount=Decimal('400.00'),
                payment_date=date(2026, 7, 1), payment_mode='cash',
            )

        rows = self.client.get(reverse('deposit-payment-list'))

        data = rows.data['results'] if 'results' in rows.data else rows.data
        self.assertEqual([row['amount'] for row in data], ['2000.00'])  # only this tenant's admission payment
        # ...and recording against another tenant's resident is refused.
        foreign = self.client.post(reverse('deposit-payment-list'), payment_payload(other))
        self.assertEqual(foreign.status_code, 400)

    def test_a_malformed_resident_filter_is_a_400_not_a_500(self):
        response = self.client.get(reverse('deposit-payment-list'), {'resident': 'not-a-uuid'})

        self.assertEqual(response.status_code, 400)

    def test_there_is_no_update_or_delete(self):
        created = self.pay().data
        url = reverse('deposit-payment-list') + f"{created['id']}/"

        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'amount': '1.00'}).status_code, 404)


class DepositPaymentIdempotencyTests(DepositSetUp):
    def setUp(self):
        super().setUp()
        self.admit()

    def _pay(self, key, **overrides):
        return self.client.post(
            reverse('deposit-payment-list'), payment_payload(self.resident, **overrides), HTTP_IDEMPOTENCY_KEY=key,
        )

    def test_a_retry_with_the_same_key_returns_the_original_and_records_nothing_twice(self):
        first = self._pay('dep-1', amount='3000.00')
        retry = self._pay('dep-1', amount='3000.00')  # the deposit is now fully paid: replay, not 400

        self.assertEqual((first.status_code, retry.status_code), (201, 200))
        self.assertEqual(retry['Idempotent-Replayed'], 'true')
        self.assertEqual(retry.data['id'], first.data['id'])
        self.assertEqual(len(self.ledger()), 2)
        self.assertEqual(self.admission().security_deposit_amount, Decimal('5000.00'))

    def test_the_same_key_with_a_different_body_is_a_409(self):
        self.assertEqual(self._pay('dep-2', amount='1000.00').status_code, 201)

        clash = self._pay('dep-2', amount='1500.00')

        self.assertEqual(clash.status_code, 409)
        self.assertEqual(self.admission().security_deposit_amount, Decimal('3000.00'))


class DepositRefundUsesCollectedOnlyTests(DepositSetUp):
    """The agreed-but-uncollected part of a deposit was never received, so it must not be
    refunded or forfeited: every consumer reads the COLLECTED amount."""

    def _vacate_and_finalize(self):
        notice = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        })
        self.assertEqual(notice.status_code, 201, notice.data)
        return self.client.post(
            reverse('vacate-finalize', args=[notice.data['id']]), {'actual_vacate_date': '2026-08-01'},
        )

    def test_refund_is_only_what_was_collected(self):
        self.admit()  # 2000 of 5000 collected

        response = self._vacate_and_finalize()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['security_deposit_amount'], '2000.00')
        self.assertEqual(response.data['refund_amount'], '2000.00')

    def test_refund_includes_a_later_payment(self):
        self.admit()
        self.assertEqual(self.pay(amount='3000.00').status_code, 201)

        self.assertEqual(self._vacate_and_finalize().data['refund_amount'], '5000.00')

    def test_maintenance_deduction_is_capped_at_what_was_collected(self):
        self.admit()
        notice = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        })

        over = self.client.post(reverse('vacate-finalize', args=[notice.data['id']]), {
            'actual_vacate_date': '2026-08-01', 'maintenance_deduction': '2500.00',
            'maintenance_deduction_note': 'Damage',
        })

        self.assertEqual(over.status_code, 400)


class BackfillMigrationTests(ResidentAPITestCase):
    """0010 must make agreed == collected and add one ledger row per admission that collected a
    deposit, even though `admissions` and `deposit_payments` are FORCE-RLS and the migration runs
    with no tenant context (the lesson of 0007)."""

    def test_backfill_sql_runs_under_force_rls(self):
        migration = importlib.import_module('apps.residents.migrations.0010_deposit_payments')
        tenant = self.create_tenant()
        prop = self.create_property(tenant)
        room = self.create_room(self.create_floor(prop))
        paid = self.create_resident(prop, phone='9000000001', status=Resident.Status.RESERVED)
        unpaid = self.create_resident(prop, phone='9000000002', status=Resident.Status.RESERVED)
        self.create_admission(
            paid, self.create_bed(room, bed_number='A'), security_deposit_amount=Decimal('1500.00'),
            security_deposit_collected_date=date(2026, 7, 2), security_deposit_mode='upi',
        )
        self.create_admission(unpaid, self.create_bed(room, bed_number='B'))

        with connection.cursor() as cursor:  # no tenant context, like a migration
            cursor.execute(migration.BACKFILL_SQL)

        with tenant_context(tenant.id):
            paid_admission = Admission.objects.get(resident=paid)
            unpaid_admission = Admission.objects.get(resident=unpaid)
            rows = list(DepositPayment.objects.filter(admission=paid_admission))
            self.assertEqual(paid_admission.security_deposit_agreed, Decimal('1500.00'))
            self.assertEqual([(r.amount, r.payment_date, r.payment_mode) for r in rows],
                             [(Decimal('1500.00'), date(2026, 7, 2), 'upi')])
            self.assertEqual(unpaid_admission.security_deposit_agreed, Decimal('0.00'))
            self.assertEqual(DepositPayment.objects.filter(admission=unpaid_admission).count(), 0)


class DepositPaymentRowLevelSecurityTests(TestCase):
    """Tenant-isolation proof for deposit_payments (invariant 1)."""

    @staticmethod
    def _payment(tenant, phone):
        prop = ResidentAPITestCase.create_property(tenant, name=f'Prop {phone}')
        bed = ResidentAPITestCase.create_bed(ResidentAPITestCase.create_room(ResidentAPITestCase.create_floor(prop)))
        resident = ResidentAPITestCase.create_resident(prop, phone=phone, status=Resident.Status.RESERVED)
        ResidentAPITestCase.check_in(resident, bed)
        with tenant_context(tenant.id):
            return DepositPayment.objects.create(
                tenant_id=tenant.id, admission=resident.admission, amount=Decimal('100.00'),
                payment_date=date(2026, 7, 1), payment_mode='cash',
            )

    def setUp(self):
        self.tenant_a = ResidentAPITestCase.create_tenant('Tenant A')
        self.tenant_b = ResidentAPITestCase.create_tenant('Tenant B')
        self.payment_a = self._payment(self.tenant_a, '9000000001')
        self.payment_b = self._payment(self.tenant_b, '9000000002')

    def test_tenant_context_sees_only_own_rows(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(list(DepositPayment.objects.values_list('id', flat=True)), [self.payment_a.id])

    def test_no_context_sees_nothing(self):
        self.assertEqual(DepositPayment.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(DepositPayment.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    DepositPayment.objects.create(
                        tenant_id=self.tenant_b.id, admission=self.payment_a.admission, amount=Decimal('1.00'),
                        payment_date=date(2026, 7, 1), payment_mode='cash',
                    )
