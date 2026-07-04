from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.audit.models import AuditLog


class AuditLogAPITestCase(AuthAPITestCase):
    @staticmethod
    def create_log(tenant_id=None, actor=None, action='resident.created',
                   object_type='Resident', object_id='', **kwargs):
        with tenant_context(tenant_id, is_super_admin=tenant_id is None):
            return AuditLog.objects.create(
                tenant_id=tenant_id, actor=actor, action=action,
                object_type=object_type, object_id=object_id, **kwargs
            )
