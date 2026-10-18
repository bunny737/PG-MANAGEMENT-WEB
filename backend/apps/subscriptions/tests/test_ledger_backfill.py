import importlib
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

BEFORE = [('subscriptions', '0008_subscription_pending_plan')]
AFTER = [('subscriptions', '0009_razorpay_subscription_ledger')]


class LedgerBackfillTests(TransactionTestCase):
    """Tenants already on a Razorpay subscription when the ledger shipped must be
    recognised by it, or their first webhook after the deploy would be ignored."""

    def _fixture_teardown(self):
        pass

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.loader.build_graph()
        self.executor.migrate(BEFORE)
        self.old_apps = self.executor.loader.project_state(BEFORE).apps
        self.created = []

    def tearDown(self):
        # Back to the latest schema first, so the ledger table exists to be cleaned
        # (its rows reference the subscriptions we are about to delete).
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        from apps.accounts.models import Tenant
        from apps.subscriptions.models import Plan, RazorpaySubscription, Subscription

        subscription_ids = [s.pk for s in self.created]
        RazorpaySubscription.objects.filter(subscription_id__in=subscription_ids).delete()
        Subscription.objects.filter(pk__in=subscription_ids).delete()
        Tenant.objects.filter(pk__in=[s.tenant_id for s in self.created]).delete()
        Plan.objects.filter(name__startswith='Backfill ').delete()
        super().tearDown()

    def _subscription(self, **kwargs):
        apps = self.old_apps
        tenant = apps.get_model('accounts', 'Tenant').objects.create(
            id=uuid.uuid4(), name=f'Backfill {uuid.uuid4().hex[:6]}', trial_ends_at=timezone.now() + timedelta(days=30),
        )
        subscription = apps.get_model('subscriptions', 'Subscription').objects.create(tenant=tenant, **kwargs)
        self.created.append(subscription)
        return subscription

    def _plan(self, name):
        return self.old_apps.get_model('subscriptions', 'Plan').objects.create(
            id=uuid.uuid4(), name=f'Backfill {name}', pricing_type='flat_monthly', price_per_month=Decimal('99.00'),
        )

    def test_live_and_pending_subscriptions_get_ledger_rows(self):
        live, pending = self._plan('live'), self._plan('pending')
        self._subscription(
            plan=live, razorpay_subscription_id='sub_live_1',
            pending_plan=pending, pending_razorpay_subscription_id='sub_pending_1',
        )
        self._subscription()  # a trial tenant with nothing at Razorpay
        self._subscription(plan=live)  # a plan but no Razorpay subscription (per-bed)

        self.executor.loader.build_graph()
        self.executor.migrate(AFTER)
        Row = self.executor.loader.project_state(AFTER).apps.get_model('subscriptions', 'RazorpaySubscription')

        rows = {r.razorpay_subscription_id: r for r in Row.objects.filter(razorpay_subscription_id__in=['sub_live_1', 'sub_pending_1'])}
        self.assertEqual(rows['sub_live_1'].state, 'current')
        self.assertEqual(rows['sub_live_1'].plan_id, live.pk)
        self.assertEqual(rows['sub_pending_1'].state, 'pending')
        self.assertEqual(rows['sub_pending_1'].plan_id, pending.pk)
        self.assertEqual(Row.objects.filter(subscription_id__in=[s.pk for s in self.created]).count(), 2)

    def test_running_the_backfill_again_does_not_duplicate_rows(self):
        live = self._plan('live')
        self._subscription(plan=live, razorpay_subscription_id='sub_live_2')
        self.executor.loader.build_graph()
        self.executor.migrate(AFTER)
        apps = self.executor.loader.project_state(AFTER).apps

        backfill = importlib.import_module('apps.subscriptions.migrations.0009_razorpay_subscription_ledger').backfill_ledger
        backfill(apps, None)

        Row = apps.get_model('subscriptions', 'RazorpaySubscription')
        self.assertEqual(Row.objects.filter(razorpay_subscription_id='sub_live_2').count(), 1)
