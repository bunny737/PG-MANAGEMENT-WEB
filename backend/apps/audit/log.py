"""Write helper for audit logs. Usage from any module:

    from apps.audit import log as audit_log
    audit_log.record(action='staff.role_changed', actor=request.user,
                     obj=staff, before={'role': old}, after={'role': new},
                     request=request)
"""
from apps.core.tenancy import tenant_context

from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def record(*, action, actor=None, tenant_id=None, obj=None,
           before=None, after=None, request=None):
    if tenant_id is None and actor is not None:
        tenant_id = actor.tenant_id
    # audit_logs is under RLS; set matching context for the insert. Platform-level
    # records (no tenant) are written — and later readable — only as super admin.
    with tenant_context(tenant_id, is_super_admin=tenant_id is None):
        return AuditLog.objects.create(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            object_type=obj.__class__.__name__ if obj is not None else '',
            object_id=str(obj.pk) if obj is not None else '',
            before=before,
            after=after,
            ip_address=client_ip(request),
        )
