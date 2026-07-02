import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only log of critical mutations (invariant 9). Created here in
    Module 01 so every module can write logs from day one; Module 15 adds the
    query API. tenant_id is NULL only for platform-level (Super Admin) actions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='audit_logs',
    )
    action = models.CharField(max_length=100, db_index=True)  # e.g. 'staff.role_changed'
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
