import importlib
import uuid
from decimal import Decimal

from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

seed = importlib.import_module('apps.subscriptions.migrations.0006_seed_basic_unlimited_plans')
reprice = importlib.import_module('apps.subscriptions.migrations.0016_reprice_basic_unlimited_plans')

BEFORE = [('subscriptions', '0005_plan_max_beds_subscription_max_beds_override')]
SEEDED = [('subscriptions', '0006_seed_basic_unlimited_plans')]


class SeedBasicUnlimitedPlansTests(TransactionTestCase):
    def _fixture_teardown(self):
        # Keep migration-seeded tables intact for the rest of the run.
        pass

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.loader.build_graph()
        self.executor.migrate(BEFORE)
        self.old_apps = self.executor.loader.project_state(BEFORE).apps
        # The historical state at BEFORE has no core app; core stays at its latest migration anyway.
        self.PlatformConfig = django_apps.get_model('core', 'PlatformConfig')
        self.trial_days = self.PlatformConfig.objects.get(pk=1).trial_days
        self._wipe_plans(self.old_apps)

    def tearDown(self):
        self._wipe_plans(self.old_apps)
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        # When 0006 was already applied, the wipe above leaves the DB without its seeded plans
        # for every later test on a kept DB. Put them back as a fresh migrate leaves them.
        if not django_apps.get_model('subscriptions', 'Plan').objects.filter(pk=seed.BASIC_ID).exists():
            seed.seed(django_apps, None)
            reprice.reprice(django_apps, None)
        # Both the seed (here and in the tests) set trial_days to 45, overwriting the later value
        # (core.0008, which won't run again); with fixture teardown disabled that leaks across tests.
        self.PlatformConfig.objects.filter(pk=1).update(trial_days=self.trial_days)
        super().tearDown()

    @staticmethod
    def _wipe_plans(apps):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM subscriptions;')
        apps.get_model('subscriptions', 'Plan').objects.all().delete()

    def _migrate_forward(self):
        self.executor.loader.build_graph()
        self.executor.migrate(SEEDED)
        return self.executor.loader.project_state(SEEDED).apps

    def _create_plan(self, **kwargs):
        Plan = self.old_apps.get_model('subscriptions', 'Plan')
        kwargs.setdefault('id', uuid.uuid4())
        kwargs.setdefault('pricing_type', 'flat_monthly')
        kwargs.setdefault('price_per_month', Decimal('99.00'))
        return Plan.objects.create(**kwargs)

    def test_seeds_the_two_plans_the_trial_flag_and_45_day_trial(self):
        self._create_plan(name='Legacy Trial', is_trial_plan=True)

        apps = self._migrate_forward()
        Plan = apps.get_model('subscriptions', 'Plan')

        basic = Plan.objects.get(pk=seed.BASIC_ID)
        unlimited = Plan.objects.get(pk=seed.UNLIMITED_ID)
        self.assertEqual(
            (basic.name, basic.pricing_type, basic.price_per_month, basic.max_beds, basic.max_properties,
             basic.max_residents_per_property, basic.is_trial_plan, basic.is_active),
            ('Basic', 'flat_monthly', Decimal('149.00'), 500, None, None, True, True),
        )
        self.assertEqual(
            (unlimited.name, unlimited.price_per_month, unlimited.max_beds, unlimited.is_trial_plan),
            ('Unlimited', Decimal('249.00'), None, False),
        )
        self.assertEqual(list(Plan.objects.filter(is_trial_plan=True)), [basic])
        self.assertEqual(apps.get_model('core', 'PlatformConfig').objects.get(pk=1).trial_days, 45)

    def test_aborts_when_another_plan_already_uses_a_seeded_name(self):
        self._create_plan(name='Basic')

        with self.assertRaises(RuntimeError) as cm:
            self._migrate_forward()
        self.assertIn('Rename it', str(cm.exception))

    def test_aborts_when_a_seeded_uuid_holds_unexpected_data(self):
        self._create_plan(id=seed.BASIC_ID, name='Basic', price_per_month=Decimal('999.00'))

        with self.assertRaises(RuntimeError) as cm:
            self._migrate_forward()
        self.assertIn('unexpected values', str(cm.exception))

    def test_accepts_rows_that_already_match_and_reversing_changes_nothing(self):
        apps = self._migrate_forward()
        Plan = apps.get_model('subscriptions', 'Plan')

        self.executor.loader.build_graph()
        self.executor.migrate(BEFORE)  # reverse is a no-op
        self.assertEqual(Plan.objects.filter(pk__in=[seed.BASIC_ID, seed.UNLIMITED_ID]).count(), 2)

        self._migrate_forward()  # re-running over matching rows is fine
        self.assertEqual(Plan.objects.filter(pk__in=[seed.BASIC_ID, seed.UNLIMITED_ID]).count(), 2)
