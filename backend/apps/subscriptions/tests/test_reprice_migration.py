import contextlib
import importlib
import io
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

seed = importlib.import_module('apps.subscriptions.migrations.0006_seed_basic_unlimited_plans')
reprice = importlib.import_module('apps.subscriptions.migrations.0016_reprice_basic_unlimited_plans')

BASIC_ID, UNLIMITED_ID = seed.BASIC_ID, seed.UNLIMITED_ID
OLD = {BASIC_ID: Decimal('149.00'), UNLIMITED_ID: Decimal('249.00')}
NEW = {BASIC_ID: Decimal('199.00'), UNLIMITED_ID: Decimal('299.00')}

BEFORE = [('subscriptions', '0015_payment_refund_obligation')]
REPRICED = [('subscriptions', '0016_reprice_basic_unlimited_plans')]


class RepriceBasicUnlimitedPlansTests(TransactionTestCase):
    def _fixture_teardown(self):
        # Keep migration-seeded tables intact for the rest of the run.
        pass

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.loader.build_graph()
        # Only subscriptions is rolled back; accounts stays at its latest migration so the
        # historical Tenant model matches the columns that really exist.
        self.before = BEFORE + self.executor.loader.graph.leaf_nodes('accounts')
        self.executor.migrate(self.before)
        self.old_apps = self.executor.loader.project_state(self.before).apps
        self.Plan = self.old_apps.get_model('subscriptions', 'Plan')
        self.PlatformConfig = self.old_apps.get_model('core', 'PlatformConfig')
        self.trial_days = self.PlatformConfig.objects.get(pk=1).trial_days
        self._clean_up_test_rows()
        # Reversing 0016 is a no-op, so the prices are not back at the seeded values by themselves.
        self._reset_seeded_plans()

    def tearDown(self):
        # Remove everything that references the plans, then put them back at the seeded values
        # (re-creating one a test deleted) so migrating forward to the leaf leaves them repriced.
        self._clean_up_test_rows()
        self.Plan.objects.filter(name__startswith='Reprice ').delete()
        self._reset_seeded_plans()
        seed.seed(self.old_apps, None)
        # seed() also resets trial_days to 45, overwriting the later value (core.0008, which
        # won't run again); with fixture teardown disabled that would leak into other tests.
        self.PlatformConfig.objects.filter(pk=1).update(trial_days=self.trial_days)
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _clean_up_test_rows(self):
        apps = self.old_apps
        subscriptions = apps.get_model('subscriptions', 'Subscription').objects.filter(
            tenant__name__startswith='Reprice '
        )
        apps.get_model('subscriptions', 'RazorpaySubscription').objects.filter(
            subscription__in=subscriptions
        ).delete()
        tenant_ids = list(subscriptions.values_list('tenant_id', flat=True))
        subscriptions.delete()
        apps.get_model('accounts', 'Tenant').objects.filter(pk__in=tenant_ids).delete()

    def _reset_seeded_plans(self):
        for plan_id, price in OLD.items():
            self.Plan.objects.filter(pk=plan_id).update(price_per_month=price, razorpay_plan_id='')

    def _migrate_forward(self):
        self.executor.loader.build_graph()
        self.executor.migrate(REPRICED)

    def _price(self, plan_id):
        return self.Plan.objects.get(pk=plan_id).price_per_month

    def _subscription(self, **kwargs):
        apps = self.old_apps
        tenant = apps.get_model('accounts', 'Tenant').objects.create(
            id=uuid.uuid4(), name=f'Reprice {uuid.uuid4().hex[:6]}', trial_ends_at=timezone.now() + timedelta(days=30),
        )
        # Cleaned up by name in _clean_up_test_rows.
        return apps.get_model('subscriptions', 'Subscription').objects.create(tenant=tenant, **kwargs)

    def test_reprices_both_plans_and_leaves_bed_caps_alone(self):
        stale = timezone.now() - timedelta(days=30)
        self.Plan.objects.filter(pk__in=OLD).update(updated_at=stale)
        caps_before = dict(self.Plan.objects.filter(pk__in=OLD).values_list('pk', 'max_beds'))

        self._migrate_forward()

        self.assertEqual(self._price(BASIC_ID), Decimal('199.00'))
        self.assertEqual(self._price(UNLIMITED_ID), Decimal('299.00'))
        self.assertEqual(dict(self.Plan.objects.filter(pk__in=OLD).values_list('pk', 'max_beds')), caps_before)
        self.assertEqual(caps_before, {BASIC_ID: 500, UNLIMITED_ID: None})
        # The public catalogue's freshness stamp is derived from plan.updated_at.
        for plan in self.Plan.objects.filter(pk__in=OLD):
            self.assertGreater(plan.updated_at, stale + timedelta(days=29))

    def test_skips_a_missing_plan(self):
        self.Plan.objects.filter(pk=BASIC_ID).delete()

        self._migrate_forward()

        self.assertFalse(self.Plan.objects.filter(pk=BASIC_ID).exists())
        self.assertEqual(self._price(UNLIMITED_ID), Decimal('299.00'))

    def test_skips_a_plan_already_at_the_new_price(self):
        self.Plan.objects.filter(pk=BASIC_ID).update(price_per_month=Decimal('199.00'))
        stamp = self.Plan.objects.get(pk=BASIC_ID).updated_at

        self._migrate_forward()

        self.assertEqual(self._price(BASIC_ID), Decimal('199.00'))
        self.assertEqual(self.Plan.objects.get(pk=BASIC_ID).updated_at, stamp)

    def test_leaves_a_manually_edited_price_alone_even_when_the_plan_is_in_use(self):
        self.Plan.objects.filter(pk=BASIC_ID).update(price_per_month=Decimal('179.00'), razorpay_plan_id='plan_live')

        self._migrate_forward()  # no guard error: the row isn't at the old price, so it is skipped

        self.assertEqual(self._price(BASIC_ID), Decimal('179.00'))
        self.assertEqual(self._price(UNLIMITED_ID), Decimal('299.00'))

    # A plan in use keeps its price (it is live), the migration still completes, and it says so.
    def _assert_left_alone_with_warning(self, plan_id, reference):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self._migrate_forward()  # must not raise: that would block every later migrate
        self.assertEqual(self._price(plan_id), OLD[plan_id])
        self.assertIn('was NOT changed', stderr.getvalue())
        self.assertIn(reference, stderr.getvalue())
        self.assertIn('create a new plan', stderr.getvalue())

    def test_leaves_a_plan_with_a_razorpay_plan_id_alone_and_warns(self):
        self.Plan.objects.filter(pk=BASIC_ID).update(razorpay_plan_id='plan_live')

        self._assert_left_alone_with_warning(BASIC_ID, 'a Razorpay plan ID')

    def test_leaves_a_plan_with_a_subscription_alone_and_warns(self):
        self._subscription(plan=self.Plan.objects.get(pk=BASIC_ID))

        self._assert_left_alone_with_warning(BASIC_ID, 'subscriptions')

    def test_leaves_a_plan_that_is_only_a_pending_plan_change_alone_and_warns(self):
        self._subscription(pending_plan=self.Plan.objects.get(pk=UNLIMITED_ID))

        self._assert_left_alone_with_warning(UNLIMITED_ID, 'pending plan changes')

    def test_leaves_a_plan_with_a_razorpay_subscription_record_alone_and_warns(self):
        subscription = self._subscription()
        self.old_apps.get_model('subscriptions', 'RazorpaySubscription').objects.create(
            subscription=subscription, plan=self.Plan.objects.get(pk=UNLIMITED_ID),
            razorpay_subscription_id=f'sub_{uuid.uuid4().hex[:10]}',
        )

        self._assert_left_alone_with_warning(UNLIMITED_ID, 'Razorpay subscriptions')

    def test_a_live_unlimited_plan_does_not_stop_basic_being_repriced(self):
        self.Plan.objects.filter(pk=UNLIMITED_ID).update(razorpay_plan_id='plan_live')

        with contextlib.redirect_stderr(io.StringIO()):
            self._migrate_forward()

        self.assertEqual(self._price(BASIC_ID), Decimal('199.00'))
        self.assertEqual(self._price(UNLIMITED_ID), Decimal('249.00'))

    def test_the_warned_recovery_path_works_and_the_live_plan_stays_frozen(self):
        """Create a plan at the new price and retire the old one, as the warning says. The old plan
        keeps its price and billing references, and re-running the migration code neither raises
        nor touches it."""
        self.Plan.objects.filter(pk=BASIC_ID).update(razorpay_plan_id='plan_live')
        with contextlib.redirect_stderr(io.StringIO()):
            self._migrate_forward()

        replacement = self.Plan.objects.create(
            id=uuid.uuid4(), name='Reprice Basic 199', pricing_type='flat_monthly',
            price_per_month=Decimal('199.00'), max_beds=500,
        )
        self.Plan.objects.filter(pk=BASIC_ID).update(is_active=False)

        with contextlib.redirect_stderr(io.StringIO()):
            reprice.reprice(self.old_apps, None)

        self.assertEqual(self._price(BASIC_ID), Decimal('149.00'))
        self.assertEqual(self.Plan.objects.get(pk=BASIC_ID).razorpay_plan_id, 'plan_live')
        self.assertEqual(self._price(replacement.pk), Decimal('199.00'))
        self.Plan.objects.filter(pk=replacement.pk).delete()

    def test_reversing_is_a_no_op(self):
        self._migrate_forward()

        self.executor.loader.build_graph()
        self.executor.migrate(self.before)

        self.assertEqual(self._price(BASIC_ID), Decimal('199.00'))
        self.assertEqual(self._price(UNLIMITED_ID), Decimal('299.00'))
