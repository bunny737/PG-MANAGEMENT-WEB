"""Automatic resident invoicing (Module 08, owner decision 2026-10-28): the
daily sweep drafts each resident's next cycle the day before it starts and
issues it on the day, unless something needs the owner's confirmation."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.billing import autobilling, services
from apps.billing.autobilling import run_auto_billing
from apps.billing.models import AutoBillingCycle, AutoBillingNotice, Invoice
from apps.core.periods import local_today
from apps.core.tenancy import tenant_context
from apps.notifications.models import NotificationLog
from apps.properties.models import PropertySettings
from apps.residents.models import Admission, Resident

from .base import BillingAPITestCase

R = Invoice.ReviewReason
JULY_15 = date(2026, 7, 15)


class AutoBillingTestCase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.room = self.create_room(
            self.create_floor(self.property), room_number='101',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.residents_made = 0

    def admit(self, joining=JULY_15, prop=None, room=None, **admission):
        """A checked-in resident on contracted rent 7000 (with food)."""
        self.residents_made += 1
        n = self.residents_made
        prop = prop or self.property
        resident = self.create_resident(
            prop, first_name=f'Resident{n}', phone=f'90{n:08d}', status=Resident.Status.RESERVED,
            email=f'resident{n}@example.com',
        )
        bed = self.create_bed(room or self.room, bed_number=f'101-{n}')
        self.check_in(resident, bed, joining_date=joining, **admission)
        return resident

    def settings_for(self, prop=None, **fields):
        prop = prop or self.property
        with tenant_context(prop.tenant_id):
            obj, _ = PropertySettings.objects.get_or_create(property=prop, defaults={'tenant_id': prop.tenant_id})
            for key, value in fields.items():
                setattr(obj, key, value)
            obj.save()
            return obj

    def invoices(self, resident):
        with tenant_context(resident.tenant_id):
            return list(Invoice.objects.filter(resident=resident).order_by('period_start'))

    def billed(self, resident, start, end, status=Invoice.Status.ISSUED):
        """An existing (manual) invoice covering start..end."""
        return self.create_invoice(resident, start, period_end=end, due_date=start + timedelta(days=5),
                                   status=status)

    def lines(self, invoice):
        with tenant_context(invoice.tenant_id):
            return {line.line_type: line.amount for line in invoice.line_items.all()}

    def refreshed(self, invoice):
        with tenant_context(invoice.tenant_id):
            invoice.refresh_from_db()
        return invoice

    def staff_notifications(self, user=None):
        with tenant_context(self.tenant.id):
            logs = NotificationLog.objects.filter(notification_type='invoice_drafts_ready', channel='email')
            if user is not None:
                logs = logs.filter(recipient_user=user)
            return list(logs)


class HappyPathTests(AutoBillingTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.billed(self.resident, JULY_15, date(2026, 8, 14))

    def test_drafts_the_next_cycle_the_day_before(self):
        totals = run_auto_billing(date(2026, 8, 14))

        draft = self.invoices(self.resident)[-1]
        self.assertEqual(totals['created'], 1)
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 8, 15), date(2026, 9, 14)))
        self.assertEqual(draft.status, Invoice.Status.DRAFT)
        self.assertTrue(draft.auto_generated)
        self.assertEqual(draft.review_reasons, [])
        self.assertEqual(draft.auto_issue_on, date(2026, 8, 15))
        # Due = billing date + grace days (default 5).
        self.assertEqual(draft.due_date, date(2026, 8, 20))
        self.assertEqual(self.lines(draft), {'accommodation': Decimal('7000.00')})
        self.assertIsNone(draft.created_by)

    def test_nothing_is_drafted_earlier_than_the_day_before(self):
        run_auto_billing(date(2026, 8, 13))
        self.assertEqual(len(self.invoices(self.resident)), 1)

    def test_issues_on_the_billing_date_and_notifies_the_resident(self):
        run_auto_billing(date(2026, 8, 14))
        with self.captureOnCommitCallbacks(execute=True):
            totals = run_auto_billing(date(2026, 8, 15))

        draft = self.invoices(self.resident)[-1]
        self.assertEqual(totals['issued'], 1)
        self.assertEqual(draft.status, Invoice.Status.ISSUED)
        self.assertEqual(draft.issue_date, date(2026, 8, 15))
        self.assertEqual(draft.due_date, date(2026, 8, 20))
        with tenant_context(self.tenant.id):
            self.assertTrue(NotificationLog.objects.filter(
                notification_type='invoice_issued', reference=f'invoice:{draft.id}',
            ).exists())

    def test_discount_is_its_own_line(self):
        self.create_discount(self.resident, discount_value=Decimal('500.00'), valid_from=JULY_15)
        run_auto_billing(date(2026, 8, 14))

        self.assertEqual(self.lines(self.invoices(self.resident)[-1]),
                         {'accommodation': Decimal('7000.00'), 'discount': Decimal('-500.00')})

    def test_temporary_allocation_still_bills_contracted_rent(self):
        with tenant_context(self.tenant.id):
            allocation = self.resident.allocation
            allocation.is_temporary = True
            allocation.allocated_bed = self.create_bed(
                self.create_room(self.create_floor(self.property, name='First', order=1), room_number='201',
                                 rack_rate_with_food=Decimal('9500.00')),
                bed_number='201-A',
            )
            allocation.save()
        run_auto_billing(date(2026, 8, 14))

        self.assertEqual(self.lines(self.invoices(self.resident)[-1])['accommodation'], Decimal('7000.00'))

    def test_rerunning_the_same_day_is_a_no_op(self):
        run_auto_billing(date(2026, 8, 14))
        totals = run_auto_billing(date(2026, 8, 14))

        self.assertEqual(totals['created'], 0)
        self.assertEqual(len(self.invoices(self.resident)), 2)

    def test_a_deleted_draft_is_not_recreated_and_billing_continues(self):
        run_auto_billing(date(2026, 8, 14))
        draft = self.invoices(self.resident)[-1]
        self.authenticate(self.owner)
        self.assertEqual(self.client.delete(reverse('invoice-detail', args=[draft.id])).status_code, 204)

        run_auto_billing(date(2026, 8, 15))
        self.assertEqual(len(self.invoices(self.resident)), 1)

        run_auto_billing(date(2026, 9, 14))
        latest = self.invoices(self.resident)[-1]
        self.assertEqual((latest.period_start, latest.period_end), (date(2026, 9, 15), date(2026, 10, 14)))

    def test_owner_is_told_what_was_drafted(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)

        run_auto_billing(date(2026, 8, 14))

        self.assertEqual(len(self.staff_notifications(self.owner)), 1)
        self.assertEqual(len(self.staff_notifications(manager)), 1)
        self.assertEqual(self.staff_notifications(receptionist), [])
        self.assertIn('Invoices drafted', self.staff_notifications(self.owner)[0].subject)

    def test_system_audit_rows_belong_to_the_tenant(self):
        run_auto_billing(date(2026, 8, 14))
        run_auto_billing(date(2026, 8, 15))

        with tenant_context(is_super_admin=True):
            rows = AuditLog.objects.filter(action__in=('invoice.generated', 'invoice.issued'), actor__isnull=True)
            self.assertEqual(rows.count(), 2)
            self.assertEqual(set(rows.values_list('tenant_id', flat=True)), {self.tenant.id})

    def test_management_command_uses_the_given_date(self):
        call_command('run_auto_billing', date='2026-08-14')
        call_command('run_auto_billing', date='2026-08-15')

        draft = self.invoices(self.resident)[-1]
        self.assertEqual(draft.issue_date, date(2026, 8, 15))
        self.assertEqual(draft.due_date, date(2026, 8, 20))


class ModeAndRuleTests(AutoBillingTestCase):
    def test_weekly_drafts_always_need_confirmation(self):
        resident = self.admit(joining=date(2026, 7, 1), billing_mode=Admission.BillingMode.WEEKLY,
                              contracted_rent=Decimal('1800.00'))
        self.billed(resident, date(2026, 7, 1), date(2026, 7, 7))

        run_auto_billing(date(2026, 7, 7))
        draft = self.invoices(resident)[-1]
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 7, 8), date(2026, 7, 14)))
        self.assertEqual(draft.review_reasons, [R.WEEKLY])
        self.assertIsNone(draft.auto_issue_on)

        run_auto_billing(date(2026, 7, 8))
        self.assertEqual(self.refreshed(draft).status, Invoice.Status.DRAFT)

    def test_daily_residents_are_never_auto_billed(self):
        resident = self.admit(billing_mode=Admission.BillingMode.DAILY, contracted_rent=Decimal('400.00'))
        run_auto_billing(date(2026, 7, 14))
        run_auto_billing(date(2026, 7, 20))
        self.assertEqual(self.invoices(resident), [])

    def test_new_resident_joining_tomorrow_uses_the_admission_first_month_amount(self):
        resident = self.admit(joining=date(2026, 8, 15), first_month_billing_amount=Decimal('3500.00'),
                              first_month_billing_note='Half month')

        run_auto_billing(date(2026, 8, 14))
        draft = self.invoices(resident)[0]
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 8, 15), date(2026, 9, 14)))
        self.assertEqual(self.lines(draft)['accommodation'], Decimal('3500.00'))
        self.assertEqual(draft.auto_issue_on, date(2026, 8, 15))

    def test_fixed_day_mid_month_joiner_gets_a_prorated_first_draft(self):
        self.settings_for(billing_day_rule=PropertySettings.BillingDayRule.FIXED_DAY, billing_day_of_month=1)
        resident = self.admit(joining=date(2026, 7, 20))

        run_auto_billing(date(2026, 7, 19))
        draft = self.invoices(resident)[0]
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 7, 20), date(2026, 7, 31)))
        self.assertEqual(self.lines(draft)['accommodation'], Decimal('2709.68'))  # 7000 x 12/31
        self.assertEqual(draft.review_reasons, [R.FIRST_PARTIAL])
        self.assertIsNone(draft.auto_issue_on)

    def test_fixed_discount_is_prorated_on_a_partial(self):
        self.settings_for(billing_day_rule=PropertySettings.BillingDayRule.FIXED_DAY, billing_day_of_month=1)
        resident = self.admit(joining=date(2026, 7, 17))  # 15 of 31 days
        self.create_discount(resident, discount_value=Decimal('620.00'), valid_from=date(2026, 7, 17))

        run_auto_billing(date(2026, 7, 16))
        self.assertEqual(self.lines(self.invoices(resident)[0])['discount'], Decimal('-300.00'))

    def test_late_drafts_need_confirmation_and_are_due_from_issue(self):
        # Admitted with today's date already passed: the first cycle is late.
        resident = self.admit(joining=date(2026, 8, 10))
        run_auto_billing(date(2026, 8, 12))

        draft = self.invoices(resident)[0]
        self.assertEqual(draft.review_reasons, [R.LATE])
        self.assertEqual(draft.due_date_policy, Invoice.DueDatePolicy.FROM_ISSUE_DATE)
        self.assertIsNone(draft.auto_issue_on)

        with tenant_context(self.tenant.id):
            services.issue_invoice(invoice_id=draft.id, actor=self.owner, on_date=date(2026, 8, 13))
        draft = self.refreshed(draft)
        self.assertEqual(draft.due_date, date(2026, 8, 18))  # issue date + 5

    def test_multiple_reasons_are_kept_and_late_still_sets_the_due_date(self):
        resident = self.admit(joining=date(2026, 8, 10), billing_mode=Admission.BillingMode.WEEKLY)
        with tenant_context(self.tenant.id):
            resident.status = Resident.Status.NOTICE_PERIOD
            resident.save(update_fields=['status'])
        self.create_vacate(resident, notice_given_date=date(2026, 7, 14), expected_vacate_date=date(2026, 8, 14))

        run_auto_billing(date(2026, 8, 11))
        draft = self.invoices(resident)[0]
        self.assertEqual(set(draft.review_reasons), {R.WEEKLY, R.LATE, R.VACATING})

        with tenant_context(self.tenant.id):
            services.issue_invoice(invoice_id=draft.id, actor=self.owner, on_date=date(2026, 8, 12))
        self.assertEqual(self.refreshed(draft).due_date, date(2026, 8, 17))

    def test_no_draft_for_a_cycle_after_the_resident_leaves(self):
        resident = self.admit()
        self.billed(resident, JULY_15, date(2026, 8, 14))
        self.create_vacate(resident, notice_given_date=date(2026, 7, 14), expected_vacate_date=date(2026, 8, 10))

        run_auto_billing(date(2026, 8, 14))
        self.assertEqual(len(self.invoices(resident)), 1)


class RolloutTests(AutoBillingTestCase):
    def test_continues_after_the_latest_manual_invoice(self):
        resident = self.admit(joining=date(2026, 3, 15))
        self.billed(resident, date(2026, 7, 1), date(2026, 7, 31))  # owner billed by calendar month

        run_auto_billing(date(2026, 7, 31))
        draft = self.invoices(resident)[-1]
        # No overlap: continues on Aug 1, a transition up to the 15th.
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 8, 1), date(2026, 8, 14)))
        self.assertEqual(draft.review_reasons, [R.TRANSITION])
        self.assertEqual(self.lines(draft)['accommodation'], Decimal('3161.29'))  # 7000 x 14/31

    def test_never_billed_resident_starts_at_the_current_cycle_without_concession(self):
        resident = self.admit(joining=date(2026, 3, 15), first_month_billing_amount=Decimal('3000.00'))

        run_auto_billing(date(2026, 8, 20))
        draft = self.invoices(resident)[0]
        self.assertEqual((draft.period_start, draft.period_end), (date(2026, 8, 15), date(2026, 9, 14)))
        self.assertEqual(set(draft.review_reasons), {R.NO_PRIOR_INVOICE, R.LATE})
        # The admission's first-month concession is not reused months later.
        self.assertEqual(self.lines(draft)['accommodation'], Decimal('7000.00'))

    def test_future_manual_invoice_is_never_backfilled_and_the_gap_is_warned_once(self):
        resident = self.admit()
        self.billed(resident, JULY_15, date(2026, 8, 14))
        self.billed(resident, date(2026, 8, 20), date(2026, 9, 19), status=Invoice.Status.DRAFT)

        run_auto_billing(date(2026, 8, 14))
        # Automation bills forward from the latest period only: Aug 15..19 is left alone.
        self.assertEqual(len(self.invoices(resident)), 2)
        self.assertEqual(self.staff_notifications(), [])

        run_auto_billing(date(2026, 8, 15))  # Aug 15 is unbilled, Aug 20 onwards is
        run_auto_billing(date(2026, 8, 16))
        with tenant_context(self.tenant.id):
            self.assertEqual(AutoBillingNotice.objects.filter(resident=resident).count(), 1)
        self.assertEqual(len(self.staff_notifications(self.owner)), 1)

    def test_an_invoice_overlapping_the_cycle_is_skipped_not_duplicated(self):
        # Defensive path: only reachable if an overlapping invoice appears
        # after the cycle was planned (another writer); simulated directly.
        resident = self.admit()
        self.billed(resident, JULY_15, date(2026, 8, 14))
        with mock.patch.object(services, 'generate_invoice', side_effect=services.InvoiceConflict(
                {'period_start': 'overlap'}, code='overlapping_invoice')):
            totals = run_auto_billing(date(2026, 8, 14))

        self.assertEqual(totals['skipped'], 1)
        with tenant_context(self.tenant.id):
            self.assertEqual(AutoBillingCycle.objects.get(resident=resident).outcome,
                             AutoBillingCycle.Outcome.SKIPPED_OVERLAP)
        run_auto_billing(date(2026, 9, 14))
        self.assertEqual(self.invoices(resident)[-1].period_start, date(2026, 9, 15))

    def test_an_ordinary_current_invoice_is_not_a_gap(self):
        resident = self.admit()
        self.billed(resident, JULY_15, date(2026, 8, 14))
        run_auto_billing(date(2026, 7, 20))
        with tenant_context(self.tenant.id):
            self.assertFalse(AutoBillingNotice.objects.filter(resident=resident).exists())


class EligibilityAtIssueTests(AutoBillingTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.billed(self.resident, JULY_15, date(2026, 8, 14))
        run_auto_billing(date(2026, 8, 14))
        self.draft = self.invoices(self.resident)[-1]

    def test_notice_given_after_drafting_flags_instead_of_issuing(self):
        with tenant_context(self.tenant.id):
            self.resident.status = Resident.Status.NOTICE_PERIOD
            self.resident.save(update_fields=['status'])
        self.create_vacate(self.resident, notice_given_date=date(2026, 8, 14), expected_vacate_date=date(2026, 8, 31))

        totals = run_auto_billing(date(2026, 8, 15))
        draft = self.refreshed(self.draft)
        self.assertEqual(totals['flagged'], 1)
        self.assertEqual(draft.status, Invoice.Status.DRAFT)
        self.assertEqual(draft.review_reasons, [R.VACATING])
        self.assertIsNone(draft.auto_issue_on)

    def test_notice_ending_after_the_period_still_auto_issues(self):
        self.create_vacate(self.resident, notice_given_date=date(2026, 8, 14), expected_vacate_date=date(2026, 9, 20))
        run_auto_billing(date(2026, 8, 15))
        self.assertEqual(self.refreshed(self.draft).status, Invoice.Status.ISSUED)

    def test_resident_no_longer_billable_is_flagged(self):
        with tenant_context(self.tenant.id):
            self.resident.status = Resident.Status.VACATED
            self.resident.save(update_fields=['status'])
        run_auto_billing(date(2026, 8, 15))
        self.assertEqual(self.refreshed(self.draft).review_reasons, [R.INELIGIBLE])

    def test_one_missed_run_still_issues_with_due_from_issue_date(self):
        run_auto_billing(date(2026, 8, 16))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.status, Invoice.Status.ISSUED)
        self.assertEqual(draft.issue_date, date(2026, 8, 16))
        self.assertEqual(draft.due_date, date(2026, 8, 21))

    def test_a_stale_schedule_goes_to_review_as_late(self):
        run_auto_billing(date(2026, 8, 17))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.status, Invoice.Status.DRAFT)
        self.assertEqual(draft.review_reasons, [R.LATE])
        self.assertEqual(draft.due_date_policy, Invoice.DueDatePolicy.FROM_ISSUE_DATE)


class HoldResumeTests(AutoBillingTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.billed(self.resident, JULY_15, date(2026, 8, 14))
        run_auto_billing(date(2026, 8, 14))
        self.draft = self.invoices(self.resident)[-1]
        self.authenticate(self.owner)

    def post(self, name, invoice=None):
        return self.client.post(reverse(f'invoice-{name}', args=[(invoice or self.draft).id]))

    def test_held_draft_is_never_issued_or_marked_late(self):
        self.assertEqual(self.post('hold-auto-issue').status_code, 200)
        for day in range(15, 25):
            run_auto_billing(date(2026, 8, day))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.status, Invoice.Status.DRAFT)
        self.assertEqual(draft.review_reasons, [])
        self.assertTrue(draft.can_auto_issue)

    def test_resume_after_the_billing_date_schedules_tomorrow_due_from_issue(self):
        self.post('hold-auto-issue')
        with tenant_context(self.tenant.id):
            services.resume_auto_issue(invoice_id=self.draft.id, actor=self.owner, on_date=date(2026, 8, 20))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.auto_issue_on, date(2026, 8, 21))
        self.assertEqual(draft.due_date_policy, Invoice.DueDatePolicy.FROM_ISSUE_DATE)

        run_auto_billing(date(2026, 8, 21))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.status, Invoice.Status.ISSUED)
        self.assertEqual(draft.due_date, date(2026, 8, 26))

    def test_resume_before_the_billing_date_keeps_the_schedule(self):
        self.post('hold-auto-issue')
        with tenant_context(self.tenant.id):
            services.resume_auto_issue(invoice_id=self.draft.id, actor=self.owner, on_date=date(2026, 8, 13))
        draft = self.refreshed(self.draft)
        self.assertEqual(draft.auto_issue_on, date(2026, 8, 15))
        self.assertEqual(draft.due_date_policy, Invoice.DueDatePolicy.FROM_PERIOD_START)

    def test_hold_and_resume_rejected_for_drafts_needing_confirmation(self):
        weekly = self.admit(joining=date(2026, 8, 15), billing_mode=Admission.BillingMode.WEEKLY)
        run_auto_billing(date(2026, 8, 14))
        draft = self.invoices(weekly)[0]
        for name in ('hold-auto-issue', 'resume-auto-issue'):
            response = self.post(name, draft)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['detail'].code, 'not_auto_issuable')

    def test_editing_the_due_date_keeps_it_on_issue(self):
        response = self.client.patch(reverse('invoice-detail', args=[self.draft.id]), {'due_date': '2026-08-25'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['due_date_policy'], 'manual')
        run_auto_billing(date(2026, 8, 16))
        self.assertEqual(self.refreshed(self.draft).due_date, date(2026, 8, 25))


class SettingsTransitionTests(AutoBillingTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.billed(self.resident, JULY_15, date(2026, 8, 14))
        self.authenticate(self.owner)

    def patch_settings(self, **data):
        return self.client.patch(reverse('property-settings', args=[self.property.id]), data, format='json')

    def test_rule_change_sends_scheduled_drafts_to_review_and_bridges_with_a_transition(self):
        run_auto_billing(date(2026, 8, 14))
        draft = self.invoices(self.resident)[-1]

        response = self.patch_settings(billing_day_rule='fixed_day', billing_day_of_month=1)
        self.assertEqual(response.status_code, 200, response.data)
        draft = self.refreshed(draft)
        self.assertEqual(draft.review_reasons, [R.RULE_CHANGED])
        self.assertIsNone(draft.auto_issue_on)

        run_auto_billing(date(2026, 9, 14))
        latest = self.invoices(self.resident)[-1]
        # Aug 15..Sep 14 is covered by the flagged draft; the transition runs to the 1st.
        self.assertEqual((latest.period_start, latest.period_end), (date(2026, 9, 15), date(2026, 9, 30)))
        self.assertEqual(latest.review_reasons, [R.TRANSITION])

        run_auto_billing(date(2026, 9, 30))
        latest = self.invoices(self.resident)[-1]
        self.assertEqual((latest.period_start, latest.period_end), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(latest.review_reasons, [])

    def test_switching_off_stops_everything_and_switching_on_resumes_from_coverage(self):
        self.patch_settings(auto_billing_enabled=False)
        run_auto_billing(date(2026, 8, 14))
        self.assertEqual(len(self.invoices(self.resident)), 1)

        self.patch_settings(auto_billing_enabled=True)
        run_auto_billing(date(2026, 8, 20))
        draft = self.invoices(self.resident)[-1]
        self.assertEqual(draft.period_start, date(2026, 8, 15))
        self.assertEqual(draft.review_reasons, [R.LATE])

    def test_grace_day_change_does_not_touch_scheduled_drafts(self):
        run_auto_billing(date(2026, 8, 14))
        self.patch_settings(penalty_grace_days=7)
        self.assertEqual(self.invoices(self.resident)[-1].review_reasons, [])

    def test_fixed_day_requires_a_valid_day(self):
        response = self.patch_settings(billing_day_rule='fixed_day')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['billing_day_of_month'][0].code, 'billing_day_required')
        response = self.patch_settings(billing_day_rule='fixed_day', billing_day_of_month=29)
        self.assertEqual(response.status_code, 400)

    def test_defaults_are_on_and_admission_date(self):
        data = self.client.get(reverse('property-settings', args=[self.property.id])).data
        self.assertTrue(data['auto_billing_enabled'])
        self.assertEqual(data['billing_day_rule'], 'admission_date')
        self.assertIsNone(data['billing_day_of_month'])


class ManualPathTests(AutoBillingTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.billed(self.resident, JULY_15, date(2026, 8, 14))
        self.authenticate(self.owner)

    def test_manual_generation_rejects_an_overlapping_period(self):
        response = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id), 'period_start': '2026-08-01',
            'period_end': '2026-08-31', 'due_date': '2026-08-05',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['period_start'][0].code, 'overlapping_invoice')

    def test_bulk_generate_skips_and_reports_overlaps(self):
        response = self.client.post(reverse('invoice-bulk-generate'), {
            'property': str(self.property.id), 'period_start': '2026-08-01',
            'period_end': '2026-08-31', 'due_date': '2026-08-05',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data['created'], response.data['skipped_overlapping']), (0, 1))

    def test_manual_issue_of_a_late_draft_recomputes_the_due_date(self):
        run_auto_billing(date(2026, 8, 20))  # drafted late
        draft = self.invoices(self.resident)[-1]
        response = self.client.post(reverse('invoice-issue', args=[draft.id]))
        self.assertEqual(response.status_code, 200)
        grace = timedelta(days=5)
        self.assertEqual(response.data['issue_date'], local_today().isoformat())
        self.assertEqual(response.data['due_date'], (local_today() + grace).isoformat())

    def test_bulk_issue_confirms_many_and_reports_each(self):
        other = self.admit(joining=date(2026, 8, 1))
        run_auto_billing(date(2026, 8, 20))
        drafts = [self.invoices(self.resident)[-1], self.invoices(other)[-1]]
        issued = self.invoices(self.resident)[0]
        stranger = '00000000-0000-0000-0000-000000000000'

        response = self.client.post(reverse('invoice-bulk-issue'), {
            'ids': [str(drafts[0].id), str(drafts[1].id), str(issued.id), stranger],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['issued'], 2)
        results = {row['id']: row['result'] for row in response.data['results']}
        self.assertEqual(results[str(issued.id)], 'invoice_not_draft')
        self.assertEqual(results[stranger], 'not_found')

    def test_bulk_issue_needs_manage_invoices(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)
        response = self.client.post(reverse('invoice-bulk-issue'), {'ids': [str(self.resident.id)]}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_review_filters(self):
        weekly = self.admit(joining=date(2026, 8, 15), billing_mode=Admission.BillingMode.WEEKLY)
        run_auto_billing(date(2026, 8, 14))
        url = reverse('invoice-list')

        def ids(review):
            response = self.client.get(url, {'review': review})
            self.assertEqual(response.status_code, 200)
            rows = response.data['results'] if isinstance(response.data, dict) else response.data
            return {row['resident'] for row in rows}

        self.assertEqual(ids('needs_confirmation'), {weekly.id})
        self.assertEqual(ids('scheduled'), {self.resident.id})
        self.assertEqual(self.client.get(url, {'review': 'nope'}).status_code, 400)


class FailureIsolationTests(AutoBillingTestCase):
    def test_one_residents_error_does_not_stop_the_rest(self):
        broken = self.admit(joining=date(2026, 8, 15))
        healthy = self.admit(joining=date(2026, 8, 15))
        real_plan = autobilling.plan_next_cycle

        def plan(**kwargs):
            if kwargs['resident'].pk == broken.pk:
                raise RuntimeError('bad data')
            return real_plan(**kwargs)

        with mock.patch.object(autobilling, 'plan_next_cycle', side_effect=plan):
            with self.assertLogs('apps.billing.autobilling', level='ERROR'):
                totals = run_auto_billing(date(2026, 8, 14))

        self.assertEqual((totals['created'], totals['failed']), (1, 1))
        self.assertEqual(self.invoices(broken), [])
        self.assertEqual(len(self.invoices(healthy)), 1)
        with tenant_context(self.tenant.id):
            self.assertFalse(AutoBillingCycle.objects.filter(resident=broken).exists())

        run_auto_billing(date(2026, 8, 14))  # the next run retries
        self.assertEqual(len(self.invoices(broken)), 1)


class TenantIsolationTests(AutoBillingTestCase):
    def test_sweep_keeps_each_tenant_in_its_own_rows(self):
        mine = self.admit(joining=date(2026, 8, 15))
        other_tenant = self.create_tenant('Other PG')
        self.create_owner(other_tenant, email='other-owner@example.com')
        other_property = self.create_property(other_tenant, name='Other PG')
        other_room = self.create_room(self.create_floor(other_property), room_number='9',
                                      rack_rate_with_food=Decimal('6000.00'))
        theirs = self.admit(joining=date(2026, 8, 15), prop=other_property, room=other_room)

        run_auto_billing(date(2026, 8, 14))

        self.assertEqual(self.invoices(mine)[0].tenant_id, self.tenant.id)
        self.assertEqual(self.invoices(theirs)[0].tenant_id, other_tenant.id)
        with tenant_context(self.tenant.id):
            self.assertEqual(set(AutoBillingCycle.objects.values_list('tenant_id', flat=True)), {self.tenant.id})
            self.assertFalse(Invoice.objects.filter(resident=theirs).exists())
        with tenant_context(other_tenant.id):
            self.assertEqual(AutoBillingCycle.objects.count(), 1)
            self.assertFalse(AutoBillingNotice.objects.exclude(tenant_id=other_tenant.id).exists())
