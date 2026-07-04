from apps.core.tenancy import tenant_context

from apps.audit.models import AuditLog

from .base import AuditLogAPITestCase


class AuditLogRLSIsolationTests(AuditLogAPITestCase):
    def test_tenant_cannot_query_another_tenants_audit_logs(self):
        tenant_a = self.create_tenant('Tenant A')
        tenant_b = self.create_tenant('Tenant B')
        log_a = self.create_log(tenant_a.id, action='resident.created')
        log_b = self.create_log(tenant_b.id, action='resident.created')

        with tenant_context(tenant_a.id):
            visible = list(AuditLog.objects.all())
        self.assertEqual([row.id for row in visible], [log_a.id])

        with tenant_context(tenant_b.id):
            visible = list(AuditLog.objects.all())
        self.assertEqual([row.id for row in visible], [log_b.id])

        with tenant_context(None, is_super_admin=True):
            self.assertEqual(AuditLog.objects.filter(id__in=[log_a.id, log_b.id]).count(), 2)
