"""Postgres tenant context (invariant 1).

RLS policies read two session GUCs:
  app.tenant_id       — UUID of the current tenant ('' = unset)
  app.is_super_admin  — 'true' lets platform staff cross tenants

The GUCs are set per-request by TenantJWTAuthentication and cleared by
TenantContextMiddleware, so a persistent connection can never leak tenant
context into the next request. Celery tasks and scripts must wrap DB work
in tenant_context().
"""
from contextlib import contextmanager

from django.db import connection

TENANT_GUC = 'app.tenant_id'
SUPER_ADMIN_GUC = 'app.is_super_admin'


def set_tenant_context(tenant_id=None, is_super_admin=False):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT set_config(%s, %s, false), set_config(%s, %s, false)',
            [
                TENANT_GUC, str(tenant_id) if tenant_id else '',
                SUPER_ADMIN_GUC, 'true' if is_super_admin else '',
            ],
        )


def clear_tenant_context():
    # Don't open a connection just to clear context on requests that never hit the DB.
    if connection.connection is None:
        return
    set_tenant_context(None, False)


def _current_context():
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT current_setting(%s, true), current_setting(%s, true)',
            [TENANT_GUC, SUPER_ADMIN_GUC],
        )
        return cursor.fetchone()


@contextmanager
def tenant_context(tenant_id=None, is_super_admin=False):
    """Scoped tenant context that restores the previous one on exit (safe to nest)."""
    previous_tenant, previous_super = _current_context()
    set_tenant_context(tenant_id, is_super_admin)
    try:
        yield
    finally:
        set_tenant_context(previous_tenant or None, previous_super == 'true')
