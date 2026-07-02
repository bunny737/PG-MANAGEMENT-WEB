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


class PlatformConfig(models.Model):
    """Singleton row of Super-Admin-configurable platform values (invariant 10).

    Never read the field defaults in business code — always go through
    PlatformConfig.get() so a Super Admin edit takes effect without a deploy.
    Per-plan caps (properties, residents) are added by Module 13 on the Plan model.
    """

    trial_days = models.PositiveIntegerField(default=60)
    payment_grace_days = models.PositiveIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'platform_config'

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config
