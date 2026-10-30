"""Notices and food-holiday API (Module 24): permissions, finance redaction,
auto-generated notice text, edit lock, overlap, property scope and tenant
isolation; plus the daily sweep's isolation per property."""
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.billing import services as billing_services
from apps.core.tenancy import tenant_context
from apps.residents import services as resident_services
from apps.residents.models import Resident

from apps.notices import sweep
from apps.notices.models import Announcement, FoodHoliday, FoodHolidayCredit

from .base import NoticesTestCase, today

S = FoodHolidayCredit.Status


class FoodHolidayApiTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.authenticate(self.owner)

    def create(self, **overrides):
        payload = {
            'property': str(self.property.pk), 'name': 'Dasara', 'start_date': '2026-03-20',
            'end_date': '2026-03-23', 'adjust_in_bill': True, 'rate_per_day': '100.00',
        }
        payload.update(overrides)
        with today(date(2026, 4, 10)):
            return self.client.post(reverse('food-holiday-list'), payload, format='json')

    def test_create_posts_a_notice_and_creates_credits(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['total_days'], 4)
        self.assertEqual(response.data['credit_total'], '400.00')
        with tenant_context(self.tenant.id):
            holiday = FoodHoliday.objects.get()
            notice = holiday.announcement
        self.assertEqual(notice.category, Announcement.Category.HOLIDAY)
        self.assertTrue(notice.is_auto_text)
        self.assertIn('Dasara', notice.title)
        self.assertIn('adjusted in your next bill', notice.body)
        self.assertNotIn('100', notice.body)  # never the rate
        self.assertEqual(self.credit(holiday, self.resident).status, S.PENDING)

    def test_create_without_a_notice(self):
        response = self.create(post_notice=False)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data['announcement'])

    def test_validation(self):
        self.assertEqual(self.create(rate_per_day=None).data['rate_per_day'][0].code, 'rate_required')
        self.assertEqual(self.create(end_date='2026-03-19').data['end_date'][0].code, 'invalid_dates')
        self.assertEqual(self.create(start_date='2025-01-01', end_date='2026-01-05').data['end_date'][0].code,
                         'holiday_too_long')
        self.assertEqual(self.create(rate_per_day='1000000.00').status_code, 400)
        self.assertEqual(self.create(rate_per_day='-1.00').status_code, 400)
        self.assertEqual(self.create(name='  ').data['name'][0].code, 'blank')

    def test_overlapping_holidays_are_rejected(self):
        self.assertEqual(self.create().status_code, 201)
        response = self.create(name='Diwali', start_date='2026-03-23', end_date='2026-03-25')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'HOLIDAY_OVERLAP')

    def test_property_cannot_change(self):
        holiday_id = self.create().data['id']
        other = self.create_property(self.tenant, name='Second PG')
        response = self.client.patch(reverse('food-holiday-detail', args=[holiday_id]),
                                     {'property': str(other.pk)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['property'][0].code, 'property_immutable')

    def test_dates_rate_and_adjustment_lock_once_on_an_issued_bill(self):
        holiday_id = self.create().data['id']
        self.issue(self.generate(self.resident))
        url = reverse('food-holiday-detail', args=[holiday_id])
        for change in ({'end_date': '2026-03-24'}, {'rate_per_day': '50.00'}, {'adjust_in_bill': False}):
            response = self.client.patch(url, change, format='json')
            self.assertEqual(response.status_code, 409, change)
            self.assertEqual(response.data['code'], 'HOLIDAY_LOCKED')
        self.assertEqual(self.client.delete(url).status_code, 409)
        response = self.client.patch(url, {'name': 'Vijayadashami'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_locked'])

    def test_editing_the_rate_updates_a_draft_line(self):
        holiday_id = self.create().data['id']
        draft = self.generate(self.resident)
        with today(date(2026, 4, 10)):
            response = self.client.patch(reverse('food-holiday-detail', args=[holiday_id]),
                                         {'rate_per_day': '150.00'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.food_lines(draft), [Decimal('-600.00')])

    def test_delete_removes_draft_lines_credits_and_the_auto_notice(self):
        holiday_id = self.create().data['id']
        draft = self.generate(self.resident)
        response = self.client.delete(reverse('food-holiday-detail', args=[holiday_id]))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.food_lines(draft), [])
        with tenant_context(self.tenant.id):
            self.assertFalse(FoodHolidayCredit.objects.exists())
            self.assertFalse(Announcement.objects.exists())

    def test_credits_endpoint_lists_stored_and_estimated_rows(self):
        with today(date(2026, 3, 1)):
            holiday_id = self.client.post(reverse('food-holiday-list'), {
                'property': str(self.property.pk), 'name': 'Dasara', 'start_date': '2026-03-20',
                'end_date': '2026-03-23', 'adjust_in_bill': True, 'rate_per_day': '100.00',
            }, format='json').data['id']
        response = self.client.get(reverse('food-holiday-credits', args=[holiday_id]))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([(row['status'], row['days'], row['amount']) for row in response.data],
                         [('estimated', 4, '400.00')])


class PermissionAndRedactionTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.holiday_obj = self.holiday()
        self.manager = self.create_manager(self.tenant)
        self.assign_staff(self.manager, self.property)
        self.receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(self.receptionist, self.property)

    def test_receptionist_reads_without_money_and_cannot_write(self):
        self.authenticate(self.receptionist)
        response = self.client.get(reverse('food-holiday-list'))
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0] if 'results' in response.data else response.data[0]
        for field in ('rate_per_day', 'credit_total', 'credit_count'):
            self.assertNotIn(field, row)
        self.assertEqual(self.client.get(reverse('food-holiday-credits', args=[self.holiday_obj.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('notice-list')).status_code, 200)
        self.assertEqual(self.client.post(reverse('notice-list'), {
            'property': str(self.property.pk), 'title': 'x', 'body': 'y',
        }, format='json').status_code, 403)
        self.assertEqual(self.client.delete(reverse('food-holiday-detail', args=[self.holiday_obj.pk])).status_code,
                         403)

    def test_manager_without_invoice_rights_cannot_touch_bill_adjustments(self):
        self.customize(self.manager, finance='view')
        self.authenticate(self.manager)
        url = reverse('food-holiday-detail', args=[self.holiday_obj.pk])
        self.assertEqual(self.client.patch(url, {'adjust_in_bill': False}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)
        response = self.client.post(reverse('food-holiday-list'), {
            'property': str(self.property.pk), 'name': 'Diwali', 'start_date': '2026-04-01',
            'end_date': '2026-04-02', 'adjust_in_bill': True, 'rate_per_day': '100.00',
        }, format='json')
        self.assertEqual(response.status_code, 403)
        # A plain closure (no bill change) is fine.
        response = self.client.post(reverse('food-holiday-list'), {
            'property': str(self.property.pk), 'name': 'Diwali', 'start_date': '2026-04-01',
            'end_date': '2026-04-02', 'adjust_in_bill': False,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_notice_responses_never_carry_the_snapshot_or_the_rate(self):
        for user in (self.owner, self.receptionist):
            self.authenticate(user)
            response = self.client.get(reverse('notice-list'))
            rows = response.data['results'] if 'results' in response.data else response.data
            self.assertTrue(rows)
            for row in rows:
                self.assertNotIn('generated_from', row)
                self.assertNotIn('100.00', row['body'])


class NoticeTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.owner)

    def test_owner_posts_and_lists_notices_pinned_first(self):
        for title, pinned in (('Water off Sunday', False), ('House rules', True)):
            response = self.client.post(reverse('notice-list'), {
                'property': str(self.property.pk), 'title': title, 'body': 'Details', 'is_pinned': pinned,
                'category': 'rules' if pinned else 'maintenance',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
        rows = self.client.get(reverse('notice-list')).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual([row['title'] for row in rows], ['House rules', 'Water off Sunday'])

    def test_active_filter_hides_expired_notices(self):
        with tenant_context(self.tenant.id):
            Announcement.objects.create(tenant_id=self.tenant.id, property=self.property, title='Old', body='b',
                                        expires_on=date(2020, 1, 1))
            Announcement.objects.create(tenant_id=self.tenant.id, property=self.property, title='Live', body='b')
        rows = self.client.get(reverse('notice-list'), {'active': 'true'}).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual([row['title'] for row in rows], ['Live'])

    def notice_of(self, holiday):
        with tenant_context(self.tenant.id):
            return FoodHoliday.objects.get(pk=holiday.pk).announcement

    def test_renaming_a_holiday_regenerates_the_auto_title(self):
        holiday = self.holiday()
        self.edit_holiday(holiday, name='Vijayadashami')
        notice = self.notice_of(holiday)
        self.assertIn('Vijayadashami', notice.title)
        self.assertTrue(notice.is_auto_text)

    def test_customised_notice_is_kept_and_flagged_outdated_until_confirmed(self):
        holiday = self.holiday()
        notice = self.notice_of(holiday)
        response = self.client.patch(reverse('notice-detail', args=[notice.pk]),
                                     {'body': 'Mess closed for Dasara. Enjoy the break!'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_auto_text'])
        self.assertFalse(response.data['notice_outdated'])

        self.edit_holiday(holiday, end_date=date(2026, 3, 24))
        notice_url = reverse('notice-detail', args=[notice.pk])
        reloaded = self.client.get(notice_url).data
        self.assertEqual(reloaded['body'], 'Mess closed for Dasara. Enjoy the break!')
        self.assertTrue(reloaded['notice_outdated'])
        holiday_row = self.client.get(reverse('food-holiday-detail', args=[holiday.pk])).data
        self.assertTrue(holiday_row['notice_outdated'])

        response = self.client.post(reverse('notice-mark-current', args=[notice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get(notice_url).data['notice_outdated'])

        self.edit_holiday(holiday, name='Navaratri')
        self.assertTrue(self.client.get(notice_url).data['notice_outdated'])
        self.client.patch(notice_url, {'title': 'Navaratri: mess closed'}, format='json')
        self.assertFalse(self.client.get(notice_url).data['notice_outdated'])

    def test_deleting_a_holiday_keeps_a_customised_notice(self):
        holiday = self.holiday(adjust=False, rate=None)
        notice = self.notice_of(holiday)
        self.client.patch(reverse('notice-detail', args=[notice.pk]), {'body': 'Custom text'}, format='json')
        self.client.delete(reverse('food-holiday-detail', args=[holiday.pk]))
        with tenant_context(self.tenant.id):
            self.assertTrue(Announcement.objects.filter(pk=notice.pk).exists())

    def test_notice_property_is_immutable(self):
        notice_id = self.client.post(reverse('notice-list'), {
            'property': str(self.property.pk), 'title': 'Hello', 'body': 'World',
        }, format='json').data['id']
        other = self.create_property(self.tenant, name='Second PG')
        response = self.client.patch(reverse('notice-detail', args=[notice_id]), {'property': str(other.pk)},
                                     format='json')
        self.assertEqual(response.status_code, 400)


class TenantIsolationTests(NoticesTestCase):
    def test_other_tenant_sees_nothing(self):
        resident = self.admit()
        holiday = self.holiday()
        self.generate(resident)
        other_tenant = self.create_tenant('Other PG Co')
        other_owner = self.create_owner(other_tenant, email='other@example.com')

        self.authenticate(other_owner)
        listed = self.client.get(reverse('food-holiday-list')).data
        listed = listed['results'] if 'results' in listed else listed
        self.assertEqual(listed, [])
        self.assertEqual(self.client.get(reverse('food-holiday-detail', args=[holiday.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('notice-detail', args=[holiday.announcement_id])).status_code, 404)
        response = self.client.post(reverse('food-holiday-list'), {
            'property': str(self.property.pk), 'name': 'X', 'start_date': '2026-05-01', 'end_date': '2026-05-01',
        }, format='json')
        self.assertEqual(response.status_code, 400)

        # RLS, not just view scoping.
        with tenant_context(other_tenant.id):
            self.assertEqual(Announcement.objects.count(), 0)
            self.assertEqual(FoodHoliday.objects.count(), 0)
            self.assertEqual(FoodHolidayCredit.objects.count(), 0)
        with tenant_context(self.tenant.id):
            self.assertEqual(FoodHolidayCredit.objects.count(), 1)


class SweepTests(NoticesTestCase):
    def test_one_property_failing_does_not_stop_the_others(self):
        first = self.admit()
        second_property = self.create_property(self.tenant, name='Second PG')
        second_room = self.create_room(self.create_floor(second_property), room_number='201')
        second = self.admit(prop=second_property, room=second_room)
        self.holiday(on=date(2026, 3, 1))
        self.holiday(on=date(2026, 3, 1), prop=second_property)
        draft_first = self.generate(first, on=date(2026, 3, 1))
        draft_second = self.generate(second, on=date(2026, 3, 1))

        real = sweep.run_for_property

        def flaky(property_id, on_date):
            if property_id == self.property.pk:
                raise RuntimeError('boom')
            return real(property_id, on_date)

        with today(date(2026, 3, 24)), mock.patch.object(sweep, 'run_for_property', side_effect=flaky):
            totals = sweep.allocate_food_holiday_credits()
        self.assertEqual(totals['failed'], 1)
        self.assertEqual(self.food_lines(draft_first), [])
        self.assertEqual(self.food_lines(draft_second), [Decimal('-400.00')])

    def test_command_uses_the_given_date_throughout(self):
        resident = self.admit()
        self.holiday(on=date(2026, 3, 1))
        draft = self.generate(resident, on=date(2026, 3, 1))
        out = StringIO()
        call_command('allocate_food_holiday_credits', '--date', '2026-03-23', stdout=out)
        self.assertEqual(self.food_lines(draft), [])  # holiday not over on its last day
        call_command('allocate_food_holiday_credits', '--date', '2026-03-24', stdout=out)
        self.assertEqual(self.food_lines(draft), [Decimal('-400.00')])
        self.assertIn('attached=1', out.getvalue())


class AdminTests(SimpleTestCase):
    def test_holidays_notices_and_credits_are_view_only_in_admin(self):
        request = RequestFactory().get('/admin/')
        request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True,
                                       has_perm=lambda *a, **k: True)
        for model in (Announcement, FoodHoliday, FoodHolidayCredit):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request), model)
            self.assertFalse(model_admin.has_change_permission(request), model)
            self.assertFalse(model_admin.has_delete_permission(request), model)


class AuditAttributionTests(NoticesTestCase):
    def actors(self, action):
        with tenant_context(self.tenant.id):
            return list(AuditLog.objects.filter(action=action).order_by('created_at')
                        .values_list('actor_id', flat=True))

    def test_staff_actions_are_attributed_and_the_sweep_is_not(self):
        resident = self.admit()
        draft = self.generate(resident, on=date(2026, 3, 1))
        self.holiday(on=date(2026, 3, 1))
        with today(date(2026, 3, 24)):
            sweep.allocate_food_holiday_credits()  # scheduled: no actor
        self.assertEqual(self.actors('food_holiday_credit.invoiced'), [None])

        self.authenticate(self.owner)
        with today(date(2026, 4, 10)):
            self.client.delete(reverse('invoice-detail', args=[draft.pk]))
        self.generate(resident)  # by the owner
        self.assertEqual(self.actors('food_holiday_credit.invoiced'), [None, self.owner.pk])

    def test_recomputed_amounts_and_settlements_name_the_staff_member(self):
        resident = self.admit()
        holiday = self.holiday()
        self.edit_holiday(holiday, rate_per_day=Decimal('150.00'))
        self.assertEqual(self.actors('food_holiday_credit.recomputed'), [self.owner.pk])

        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=resident.pk).update(status=Resident.Status.NOTICE_PERIOD)
        vacate = self.create_vacate(resident, notice_given_date=date(2026, 3, 1),
                                    expected_vacate_date=date(2026, 4, 1))
        with tenant_context(self.tenant.id):
            resident_services.finalize_vacate(
                vacate=vacate, actual_vacate_date=date(2026, 4, 5), maintenance_deduction=Decimal('0.00'),
                maintenance_deduction_note='', refund_date=None, refund_mode='', refund_note='', actor=self.owner,
            )
        self.assertEqual(self.actors('food_holiday_credit.settled'), [self.owner.pk])


class MergedStateTests(NoticesTestCase):
    """The service re-checks the merged holiday under the lock, whatever the
    serializer saw (it validated against the row before any lock)."""

    def test_reversed_dates_are_refused_not_a_500(self):
        holiday = self.holiday(start=date(2026, 3, 20), end=date(2026, 3, 30))
        with self.assertRaises(ValidationError) as ctx:
            self.edit_holiday(holiday, end_date=date(2026, 3, 19))
        self.assertEqual(ctx.exception.get_codes(), {'end_date': ['invalid_dates']})

    def test_a_span_over_the_limit_is_refused(self):
        holiday = self.holiday(start=date(2026, 1, 1), end=date(2026, 6, 30), adjust=False, rate=None)
        with self.assertRaises(ValidationError) as ctx:
            self.edit_holiday(holiday, start_date=date(2025, 7, 1), end_date=date(2026, 12, 31))
        self.assertEqual(ctx.exception.get_codes(), {'end_date': ['holiday_too_long']})

    def test_generating_for_a_resident_who_already_left_is_refused(self):
        resident = self.admit()
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=resident.pk).update(status=Resident.Status.VACATED)
        with self.assertRaises(billing_services.ResidentNotBillable):
            self.generate(resident)  # `resident` still says Active: the lock re-read decides
