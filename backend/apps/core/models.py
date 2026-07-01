import uuid
from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant_id):
        return self.filter(tenant_id=tenant_id)


class TenantModelMixin(models.Model):
    """
    Abstract base for every business model in the platform.

    Rules (enforced here and in Module 01 RLS migration):
    - tenant_id must be set on every row
    - every query must call .for_tenant(tenant_id) or equivalent
    - RLS policy at the DB level is added in 01-auth-tenancy migration
      (see docs/modules/01-auth-tenancy.md)

    # TODO (Module 01): add PostgreSQL RLS policies in a post-migrate
    #   RunSQL step after the Tenant model is fully created.
    """
    tenant_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True
