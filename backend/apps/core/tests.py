"""Tenant-isolation proof for the RLS infrastructure (invariant 1).

audit_logs is the first table under RLS, so it doubles as the fixture here.
Every future business table gets the same policy via apps.core.rls.enable_rls()
in its migration, plus its own isolation test.
"""
from datetime import timedelta

from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Tenant
from apps.audit import log as audit_log
from apps.audit.models import AuditLog
from apps.core.roles import Role, permissions_for
from apps.core.tenancy import tenant_context


def make_tenant(name):
    return Tenant.objects.create(name=name, trial_ends_at=timezone.now() + timedelta(days=60))


class RowLevelSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = make_tenant('Tenant A')
        self.tenant_b = make_tenant('Tenant B')
        audit_log.record(action='test.a', tenant_id=self.tenant_a.id)
        audit_log.record(action='test.b', tenant_id=self.tenant_b.id)

    def test_connection_is_not_superuser(self):
        # Superusers bypass RLS entirely — isolation would be silently off.
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user')
            is_super, bypass_rls = cursor.fetchone()
        self.assertFalse(
            is_super or bypass_rls,
            'The app must connect as a non-superuser (see docker/postgres/init.sql) '
            'or PostgreSQL ignores every RLS policy.',
        )

    def test_tenant_context_sees_only_own_rows(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(AuditLog.objects.count(), 1)
            self.assertEqual(AuditLog.objects.first().action, 'test.a')
            # Filtering for the other tenant explicitly still returns nothing.
            self.assertEqual(AuditLog.objects.filter(tenant_id=self.tenant_b.id).count(), 0)

    def test_no_context_sees_nothing(self):
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(AuditLog.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    AuditLog.objects.create(tenant_id=self.tenant_b.id, action='evil.write')

    def test_context_manager_restores_previous_context(self):
        with tenant_context(self.tenant_a.id):
            with tenant_context(self.tenant_b.id):
                self.assertEqual(AuditLog.objects.first().action, 'test.b')
            self.assertEqual(AuditLog.objects.first().action, 'test.a')
        self.assertEqual(AuditLog.objects.count(), 0)


class PermissionMatrixTests(TestCase):
    def test_owner_has_full_tenant_permissions_but_not_platform(self):
        perms = permissions_for(Role.OWNER)
        self.assertIn('manage_staff_accounts', perms)
        self.assertIn('manage_invoices', perms)
        self.assertNotIn('manage_tenants', perms)

    def test_receptionist_is_front_desk_only(self):
        self.assertEqual(
            permissions_for(Role.RECEPTIONIST),
            sorted(['manage_visitors', 'view_resident_profile']),
        )

    def test_manager_cannot_touch_subscription_or_staff(self):
        perms = permissions_for(Role.MANAGER)
        self.assertNotIn('manage_subscription', perms)
        self.assertNotIn('manage_staff_accounts', perms)
        self.assertIn('manage_invoices', perms)

    def test_resident_permissions_are_self_service_only(self):
        self.assertEqual(
            permissions_for(Role.RESIDENT),
            sorted(['view_own_profile', 'view_own_invoices', 'raise_complaint', 'request_visitor']),
        )
