"""Postgres tenant context (invariant 1).

RLS policies read three session GUCs:
  app.tenant_id       — UUID of the current tenant ('' = unset)
  app.is_super_admin  — 'true' lets platform staff cross tenants
  app.user_id         — UUID of the signed-in RESIDENT-pool user ('' = unset). A resident
                        account belongs to no tenant, so a few tables (resident_access,
                        residency_link_requests, ...) also admit a row to the person it
                        is about. Staff users never set it. See apps.core.rls.

The GUCs are set per-request by TenantJWTAuthentication and cleared by
TenantContextMiddleware, so a persistent connection can never leak tenant
context into the next request. Celery tasks and scripts must wrap DB work
in tenant_context().
"""
from contextlib import contextmanager

from django.db import connection

TENANT_GUC = 'app.tenant_id'
SUPER_ADMIN_GUC = 'app.is_super_admin'
USER_GUC = 'app.user_id'

# tenant_context() default for user_id: keep whatever identity the request already has.
KEEP_USER = object()


def set_tenant_context(tenant_id=None, is_super_admin=False, user_id=None):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT set_config(%s, %s, false), set_config(%s, %s, false), set_config(%s, %s, false)',
            [
                TENANT_GUC, str(tenant_id) if tenant_id else '',
                SUPER_ADMIN_GUC, 'true' if is_super_admin else '',
                USER_GUC, str(user_id) if user_id else '',
            ],
        )


def clear_tenant_context():
    # Don't open a connection just to clear context on requests that never hit the DB.
    if connection.connection is None:
        return
    set_tenant_context(None, False, None)


def _current_context():
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT current_setting(%s, true), current_setting(%s, true), current_setting(%s, true)',
            [TENANT_GUC, SUPER_ADMIN_GUC, USER_GUC],
        )
        return cursor.fetchone()


@contextmanager
def tenant_context(tenant_id=None, is_super_admin=False, user_id=KEEP_USER):
    """Scoped tenant context that restores the previous one on exit (safe to nest).

    `user_id` defaults to KEEP_USER: entering a tenant keeps the request's resident identity,
    so code that moves into a PG's tenant to act for the signed-in person (a contact reveal,
    accepting an invite) still satisfies the user-keyed policies. Pass None to drop it."""
    previous_tenant, previous_super, previous_user = _current_context()
    set_tenant_context(
        tenant_id, is_super_admin,
        (previous_user or None) if user_id is KEEP_USER else user_id,
    )
    try:
        yield
    finally:
        set_tenant_context(previous_tenant or None, previous_super == 'true', previous_user or None)
