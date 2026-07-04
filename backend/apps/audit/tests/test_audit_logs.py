from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import AuditLogAPITestCase


class AuditLogScopingTests(AuditLogAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant_a = self.create_tenant('Tenant A')
        self.tenant_b = self.create_tenant('Tenant B')
        self.owner_a = self.create_owner(self.tenant_a, email='owner-a@example.com')
        self.owner_b = self.create_owner(self.tenant_b, email='owner-b@example.com')
        self.manager_a = self.create_user(self.tenant_a, Role.MANAGER, 'manager-a@example.com')
        self.receptionist_a = self.create_user(self.tenant_a, Role.RECEPTIONIST, 'front-a@example.com')
        self.super_admin = self.create_super_admin()

        self.log_a = self.create_log(self.tenant_a.id, actor=self.owner_a, action='resident.created')
        self.log_b = self.create_log(self.tenant_b.id, actor=self.owner_b, action='resident.created')
        self.platform_log = self.create_log(None, actor=self.super_admin, action='tenant.suspended')

    def test_owner_sees_only_own_tenant_logs(self):
        self.authenticate(self.owner_a)

        response = self.client.get(reverse('audit-log-list'))

        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {str(self.log_a.id)})

    def test_owner_cannot_see_other_tenants_log_by_id(self):
        self.authenticate(self.owner_a)

        response = self.client.get(reverse('audit-log-detail', args=[self.log_b.id]))

        self.assertEqual(response.status_code, 404)

    def test_manager_is_forbidden(self):
        self.authenticate(self.manager_a)

        response = self.client.get(reverse('audit-log-list'))

        self.assertEqual(response.status_code, 403)

    def test_receptionist_is_forbidden(self):
        self.authenticate(self.receptionist_a)

        response = self.client.get(reverse('audit-log-list'))

        self.assertEqual(response.status_code, 403)

    def test_super_admin_sees_all_logs_including_platform_level(self):
        self.authenticate(self.super_admin)

        response = self.client.get(reverse('audit-log-list'))

        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {str(self.log_a.id), str(self.log_b.id), str(self.platform_log.id)})

    def test_super_admin_can_filter_by_tenant_id(self):
        self.authenticate(self.super_admin)

        response = self.client.get(reverse('audit-log-list'), {'tenant_id': str(self.tenant_a.id)})

        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {str(self.log_a.id)})


class AuditLogFilterTests(AuditLogAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.other_actor = self.create_user(self.tenant, Role.MANAGER, 'mgr@example.com')
        self.authenticate(self.owner)

        self.created_log = self.create_log(
            self.tenant.id, actor=self.owner, action='resident.created',
            object_type='Resident', object_id='r-1',
        )
        self.status_log = self.create_log(
            self.tenant.id, actor=self.other_actor, action='resident.status_changed',
            object_type='Resident', object_id='r-1',
        )
        self.other_object_log = self.create_log(
            self.tenant.id, actor=self.owner, action='invoice.issued',
            object_type='Invoice', object_id='inv-1',
        )

    def _ids(self, response):
        return {row['id'] for row in response.data}

    def test_filter_by_action(self):
        response = self.client.get(reverse('audit-log-list'), {'action': 'resident.created'})
        self.assertEqual(self._ids(response), {str(self.created_log.id)})

    def test_filter_by_object_type_and_object_id(self):
        response = self.client.get(
            reverse('audit-log-list'), {'object_type': 'Resident', 'object_id': 'r-1'}
        )
        self.assertEqual(self._ids(response), {str(self.created_log.id), str(self.status_log.id)})

    def test_filter_by_actor(self):
        response = self.client.get(reverse('audit-log-list'), {'actor': str(self.other_actor.id)})
        self.assertEqual(self._ids(response), {str(self.status_log.id)})

    def test_default_ordering_is_newest_first(self):
        response = self.client.get(reverse('audit-log-list'))
        returned_ids = [row['id'] for row in response.data]
        expected_ids = [str(self.other_object_log.id), str(self.status_log.id), str(self.created_log.id)]
        self.assertEqual(returned_ids, expected_ids)

    def test_date_range_filter_excludes_out_of_range_logs(self):
        old_log = self.create_log(self.tenant.id, actor=self.owner, action='old.action')
        with tenant_context(self.tenant.id):
            old_log.created_at = timezone.now() - timedelta(days=30)
            old_log.save(update_fields=['created_at'])

        response = self.client.get(
            reverse('audit-log-list'),
            {'created_at__gte': (timezone.now() - timedelta(days=1)).isoformat()},
        )

        self.assertNotIn(str(old_log.id), self._ids(response))
