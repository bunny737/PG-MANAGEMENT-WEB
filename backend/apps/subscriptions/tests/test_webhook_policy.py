"""webhook_policy.decide(): the ordering and recovery matrix, with no database.

Rule (owner decision 2026-10-20): terminal and manual states win first; otherwise the newest event by
occurrence time wins, not the last webhook delivered."""
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from apps.accounts.models import Tenant
from apps.subscriptions.webhook_policy import Action, Facts, LastEvent, decide

Status = Tenant.Status
T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def facts(tenant_status=Status.ACTIVE, *, last=None, row_cancelled=False, manual_hold=False, activated_before=True):
    return Facts(tenant_status, row_cancelled, manual_hold, activated_before, last or LastEvent())


def last(event_type, minutes):
    return LastEvent(at(minutes), event_type, f'evt_{event_type}_{minutes}')


class StaleAndNewerTests(SimpleTestCase):
    def test_late_failure_after_newer_charge_changes_nothing(self):
        decision = decide('payment_failed', at(5), facts(Status.ACTIVE, last=last('subscription.charged', 10)))
        self.assertEqual(decision.action, Action.STALE)

    def test_newer_failure_moves_active_to_payment_failed(self):
        decision = decide('payment_failed', at(20), facts(Status.ACTIVE, last=last('subscription.charged', 10)))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.PAYMENT_FAILED))

    def test_newer_charge_recovers_payment_failed(self):
        decision = decide('charged', at(30), facts(Status.PAYMENT_FAILED, last=last('payment.failed', 20)))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))

    def test_older_charge_does_not_recover_a_newer_failure(self):
        decision = decide('charged', at(10), facts(Status.PAYMENT_FAILED, last=last('payment.failed', 20)))
        self.assertEqual(decision.action, Action.STALE)

    def test_a_charge_after_the_grace_suspension_recovers_the_tenant(self):
        # Suspended by the grace sweep, not by a Razorpay halt: the customer finally paid.
        decision = decide('charged', at(40), facts(Status.SUSPENDED, last=last('payment.failed', 20)))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))

    def test_first_event_ever_applies(self):
        decision = decide('charged', at(1), facts(Status.TRIAL, activated_before=False))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))


class EqualTimestampPrecedenceTests(SimpleTestCase):
    """cancelled > halted > charged/resumed > activated > payment.failed"""

    def test_higher_precedence_replaces_lower_at_the_same_time(self):
        for kind, previous in (('charged', 'payment.failed'), ('halted', 'subscription.charged'),
                               ('activated', 'payment.failed'), ('charged', 'subscription.activated')):
            with self.subTest(f'{kind} over {previous}'):
                status = Status.SUSPENDED if previous == 'subscription.halted' else Status.ACTIVE
                self.assertEqual(
                    decide(kind, at(10), facts(status, last=last(previous, 10), activated_before=False)).action,
                    Action.APPLY)

    def test_lower_or_equal_precedence_loses_at_the_same_time(self):
        for kind, previous in (('payment_failed', 'subscription.charged'), ('charged', 'subscription.halted'),
                               ('activated', 'subscription.charged'), ('charged', 'subscription.charged'),
                               ('payment_failed', 'payment.failed'), ('resumed', 'subscription.charged')):
            with self.subTest(f'{kind} vs {previous}'):
                self.assertEqual(decide(kind, at(10), facts(last=last(previous, 10))).action, Action.STALE)

    def test_delivery_order_does_not_matter(self):
        # Simulate both orders of {charged, halted} that happened at the same instant.
        first = decide('halted', at(10), facts(Status.ACTIVE, last=last('subscription.charged', 10)))
        second = decide('charged', at(10), facts(Status.SUSPENDED, last=last('subscription.halted', 10)))
        self.assertEqual((first.action, first.target), (Action.APPLY, Status.SUSPENDED))
        self.assertEqual(second.action, Action.STALE)


class TerminalTests(SimpleTestCase):
    def test_cancelled_applies_whatever_its_age(self):
        decision = decide('cancelled', at(1), facts(Status.ACTIVE, last=last('subscription.charged', 99)))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.CANCELLED))

    def test_nothing_reactivates_a_cancelled_subscription(self):
        for kind in ('activated', 'charged', 'resumed', 'payment_failed', 'halted'):
            for cancelled in ({'row_cancelled': True}, {'tenant_status': Status.CANCELLED}):
                with self.subTest(kind=kind, **{k: str(v) for k, v in cancelled.items()}):
                    f = facts(**{'tenant_status': Status.CANCELLED, **cancelled},
                              last=last('subscription.cancelled', 10))
                    decision = decide(kind, at(500), f)
                    self.assertEqual(decision.action, Action.TERMINAL)
                    self.assertIsNone(decision.target)

    def test_a_payment_after_cancellation_is_flagged_not_honoured(self):
        for kind, flagged in (('charged', True), ('activated', True), ('resumed', False), ('payment_failed', False)):
            with self.subTest(kind):
                decision = decide(kind, at(500), facts(Status.CANCELLED, row_cancelled=True))
                self.assertEqual(decision.flag_payment, flagged)

    def test_a_repeat_cancellation_changes_nothing(self):
        self.assertEqual(decide('cancelled', at(5), facts(Status.CANCELLED, row_cancelled=True)).action, Action.NO_CHANGE)


class HaltedTests(SimpleTestCase):
    halted = dict(tenant_status=Status.SUSPENDED, last=last('subscription.halted', 10))

    def test_halted_suspends(self):
        decision = decide('halted', at(10), facts(Status.ACTIVE))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.SUSPENDED))

    def test_a_charge_after_halt_is_not_trusted_without_razorpay(self):
        decision = decide('charged', at(50), facts(**self.halted))
        self.assertEqual((decision.action, decision.reason), (Action.VERIFY, 'charged_after_halt'))
        self.assertTrue(decision.flag_payment)

    def test_only_a_newer_resume_recovers(self):
        decision = decide('resumed', at(20), facts(**self.halted))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))

    def test_an_older_resume_does_not(self):
        self.assertEqual(decide('resumed', at(5), facts(**self.halted)).action, Action.STALE)

    def test_activation_is_never_a_recovery(self):
        self.assertEqual(decide('activated', at(50), facts(**self.halted)).action, Action.NOT_RECOVERY)

    def test_a_failure_while_halted_changes_nothing(self):
        self.assertEqual(decide('payment_failed', at(50), facts(**self.halted)).action, Action.NO_CHANGE)

    def test_resume_without_a_halt_is_a_no_op(self):
        self.assertEqual(decide('resumed', at(50), facts(Status.ACTIVE, last=last('subscription.charged', 10))).action,
                         Action.NO_CHANGE)


class ActivationTests(SimpleTestCase):
    def test_activation_performs_the_initial_activation(self):
        decision = decide('activated', at(1), facts(Status.TRIAL, activated_before=False))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))

    def test_activation_after_a_first_failed_attempt_is_still_initial(self):
        decision = decide('activated', at(30), facts(Status.PAYMENT_FAILED, last=last('payment.failed', 20),
                                                     activated_before=False))
        self.assertEqual((decision.action, decision.target), (Action.APPLY, Status.ACTIVE))

    def test_activation_is_not_general_recovery(self):
        decision = decide('activated', at(30), facts(Status.PAYMENT_FAILED, last=last('payment.failed', 20),
                                                     activated_before=True))
        self.assertEqual(decision.action, Action.NOT_RECOVERY)


class ManualHoldTests(SimpleTestCase):
    def test_no_event_changes_a_manually_held_tenant(self):
        for kind in ('activated', 'charged', 'resumed', 'halted', 'cancelled', 'payment_failed'):
            with self.subTest(kind):
                decision = decide(kind, at(500), facts(Status.SUSPENDED, manual_hold=True))
                self.assertEqual(decision.action, Action.MANUAL_HOLD)
                self.assertIsNone(decision.target)

    def test_a_payment_under_a_hold_is_flagged(self):
        self.assertTrue(decide('charged', at(5), facts(Status.SUSPENDED, manual_hold=True)).flag_payment)
        self.assertFalse(decide('payment_failed', at(5), facts(Status.SUSPENDED, manual_hold=True)).flag_payment)


class MissingTimestampTests(SimpleTestCase):
    def test_an_undated_event_is_verified_with_razorpay(self):
        for kind in ('activated', 'charged', 'resumed', 'halted', 'payment_failed'):
            with self.subTest(kind):
                decision = decide(kind, None, facts())
                self.assertEqual((decision.action, decision.reason), (Action.VERIFY, 'missing_timestamp'))

    def test_terminal_and_manual_states_still_win_first(self):
        self.assertEqual(decide('charged', None, facts(Status.CANCELLED, row_cancelled=True)).action, Action.TERMINAL)
        self.assertEqual(decide('charged', None, facts(Status.SUSPENDED, manual_hold=True)).action, Action.MANUAL_HOLD)
        self.assertEqual(decide('cancelled', None, facts()).action, Action.APPLY)
