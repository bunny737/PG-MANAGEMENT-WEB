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
