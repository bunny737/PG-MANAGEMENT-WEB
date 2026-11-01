"""Row-Level Security helpers (invariant 1).

Every business-table migration must include enable_rls('<table>') after the
CreateModel operation. FORCE makes the policy apply to the table owner too,
so the app must connect as a non-superuser (superusers always bypass RLS —
see docker/postgres/init.sql).
"""
from django.db import migrations

ENABLE_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {table}
    USING (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = 'true'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    );
"""

DISABLE_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def enable_rls(table):
    return migrations.RunSQL(
        sql=ENABLE_RLS_SQL.format(table=table),
        reverse_sql=DISABLE_RLS_SQL.format(table=table),
    )


# Tables whose rows are about a resident-pool PERSON (Module 26) as well as about a tenant. A
# resident account has no tenant, so the person reads their own rows through `app.user_id`
# (set by TenantJWTAuthentication for resident accounts only). The user clause is on SELECT
# alone — one policy per command, because PostgreSQL ORs permissive policies of the same
# command: a single FOR ALL policy with the user clause would let the person UPDATE or DELETE
# the row too. Every write is tenant-only, exactly like enable_rls().
_TENANT_MATCH_SQL = (
    "current_setting('app.is_super_admin', true) = 'true' "
    "OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)

ENABLE_USER_SELECT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_select ON {table} FOR SELECT
    USING ({tenant_match} OR {user_column} = NULLIF(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY tenant_isolation_insert ON {table} FOR INSERT
    WITH CHECK ({tenant_match});
CREATE POLICY tenant_isolation_update ON {table} FOR UPDATE
    USING ({tenant_match}) WITH CHECK ({tenant_match});
CREATE POLICY tenant_isolation_delete ON {table} FOR DELETE
    USING ({tenant_match});
"""

DISABLE_USER_SELECT_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation_select ON {table};
DROP POLICY IF EXISTS tenant_isolation_insert ON {table};
DROP POLICY IF EXISTS tenant_isolation_update ON {table};
DROP POLICY IF EXISTS tenant_isolation_delete ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def enable_rls_with_user_select(table, user_column):
    """RLS for a table that also lets a resident-pool user SELECT the rows `user_column` names
    as them. See the note above: SELECT-only, writes stay tenant-scoped."""
    return migrations.RunSQL(
        sql=ENABLE_USER_SELECT_RLS_SQL.format(
            table=table, user_column=user_column, tenant_match=_TENANT_MATCH_SQL,
        ),
        reverse_sql=DISABLE_USER_SELECT_RLS_SQL.format(table=table),
    )
