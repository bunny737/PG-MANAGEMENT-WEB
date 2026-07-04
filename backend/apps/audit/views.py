from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import require_permission
from apps.core.roles import Role

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only query API over the append-only audit trail (PRD Module 21;
    the model + write path — `apps.audit.log.record` — have existed since
    Module 01 so every module could log from day one). Owner sees only their
    own tenant's entries (RLS already enforces this; the explicit filter
    below is defense-in-depth, matching every other tenant-scoped viewset).
    Super Admin sees everything, including platform-level entries
    (`tenant_id` is null — tenant signup, cross-tenant actions), and can
    narrow to one tenant with `?tenant_id=`."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, require_permission('view_audit_logs')]
    filterset_fields = {
        'action': ['exact'],
        'object_type': ['exact'],
        'object_id': ['exact'],
        'actor': ['exact'],
        'tenant_id': ['exact'],
        'created_at': ['gte', 'lte'],
    }

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return AuditLog.objects.none()
        queryset = AuditLog.objects.select_related('actor')
        if self.request.user.role == Role.SUPER_ADMIN:
            return queryset
        return queryset.filter(tenant_id=self.request.user.tenant_id)
