from datetime import timedelta
import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class UserIdentifierMigrationTests(TransactionTestCase):
    pre_step_2 = [('accounts', '0002_schema_prep')]
    step_3 = [('accounts', '0003_normalize_user_identifiers')]
    final_step = [('accounts', '0004_user_auth_version_and_constraints')]

    def _fixture_teardown(self):
        # Prevent TransactionTestCase from flushing migration-seeded tables
        # (feature_catalog, plans, notification templates) for subsequent tests.
        pass

    def setUp(self):
        super().setUp()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM users;")
            cursor.execute("DELETE FROM tenants;")
        self.executor = MigrationExecutor(connection)
        # Migrate to pre-step-2 state
        self.executor.loader.build_graph()
        self.executor.migrate(self.pre_step_2)
        self.old_apps = self.executor.loader.project_state(self.pre_step_2).apps

    def tearDown(self):
        # Clean up database before restoring to final migration state
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM users;")
            cursor.execute("DELETE FROM tenants;")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _create_tenant(self, apps):
        Tenant = apps.get_model('accounts', 'Tenant')
        return Tenant.objects.create(
            id=uuid.uuid4(),
            name='Test Tenant',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )

    def test_clean_data_normalizes_without_incident(self):
        tenant = self._create_tenant(self.old_apps)
        User = self.old_apps.get_model('accounts', 'User')

        # Owner with unnormalized email and phone
        owner = User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='  OWNER@EXAMPLE.COM  ',
            phone='+91 98765 43210',
            role='owner',
            is_active=True,
        )
        # Manager with 11-digit leading 0 phone
        manager = User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email=None,
            phone='09876543211',
            role='manager',
            is_active=True,
        )
        # Inactive user with same phone as owner (cross-tenant reemployment scenario)
        tenant2 = self._create_tenant(self.old_apps)
        inactive = User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant2,
            email=None,
            phone='9876543210',
            role='manager',
            is_active=False,
        )

        # Run step 2 data migration
        self.executor.loader.build_graph()
        self.executor.migrate(self.step_3)

        # Verify values in database were normalized
        apps_step3 = self.executor.loader.project_state(self.step_3).apps
        User3 = apps_step3.get_model('accounts', 'User')
        self.assertEqual(User3.objects.get(id=owner.id).email, 'owner@example.com')
        self.assertEqual(User3.objects.get(id=owner.id).phone, '9876543210')
        self.assertEqual(User3.objects.get(id=manager.id).phone, '9876543211')
        self.assertEqual(User3.objects.get(id=inactive.id).phone, '9876543210')

        # Step 3 final schema migration succeeds because data is clean
        self.executor.loader.build_graph()
        self.executor.migrate(self.final_step)

    def test_migration_aborts_on_malformed_phone(self):
        tenant = self._create_tenant(self.old_apps)
        User = self.old_apps.get_model('accounts', 'User')

        User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='user@example.com',
            phone='12345',  # invalid shape
            role='owner',
            is_active=True,
        )

        self.executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as cm:
            self.executor.migrate(self.step_3)
        self.assertIn('malformed phone', str(cm.exception))

    def test_migration_aborts_on_active_email_collision(self):
        tenant = self._create_tenant(self.old_apps)
        User = self.old_apps.get_model('accounts', 'User')

        User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='dup@example.com',
            phone='9876543210',
            role='owner',
            is_active=True,
        )
        User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='DUP@EXAMPLE.COM',  # collision post-normalization
            phone='9876543211',
            role='owner',
            is_active=True,
        )

        self.executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as cm:
            self.executor.migrate(self.step_3)
        self.assertIn('Active email collision', str(cm.exception))

    def test_migration_aborts_on_owner_with_blank_email(self):
        tenant = self._create_tenant(self.old_apps)
        User = self.old_apps.get_model('accounts', 'User')

        # Blank string normalizes to None, which is invalid for Owner role
        User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='   ',
            phone='9876543210',
            role='owner',
            is_active=True,
        )

        self.executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as cm:
            self.executor.migrate(self.step_3)
        self.assertIn('requires email', str(cm.exception))

    def test_migration_aborts_on_manager_with_blank_phone(self):
        tenant = self._create_tenant(self.old_apps)
        User = self.old_apps.get_model('accounts', 'User')

        # Manager with blank phone
        User.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            email='manager@example.com',
            phone=None,
            role='manager',
            is_active=True,
        )

        self.executor.loader.build_graph()
        with self.assertRaises(RuntimeError) as cm:
            self.executor.migrate(self.step_3)
        self.assertIn('requires phone', str(cm.exception))
