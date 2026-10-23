"""Verify the production database role model (WP10, docs/deployment.md).

Prod uses two roles: `migration_user` owns the schema and every table and is
used only by the migration job; `app_user` is the runtime role and may only
read and write rows. A runtime role that owned tables could ALTER them, drop
the tenant_isolation policies or turn FORCE RLS off — so this command fails
the deploy unless:

- the runtime role is not a superuser and cannot bypass RLS;
- it owns nothing in `public` (schema, tables, sequences, views);
- it cannot CREATE in `public`;
- it has SELECT/INSERT/UPDATE/DELETE on every table (default privileges);
- every table with a tenant_id column has RLS enabled AND forced, apart
  from the documented exceptions below.

Run as any role that can read the catalogs (the migration job runs it right
after `migrate`):  manage.py check_db_roles --role app_user [--json]
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# tenant_id tables deliberately outside RLS (module specs, "Decisions"):
# users — looked up during authentication before any tenant context exists (01);
# subscriptions — read by the unauthenticated Razorpay webhook (13);
# razorpay_webhook_events — written by that same webhook before the tenant is known, and readable only by
# Super Admin in Django admin (13): an RLS policy would reject the insert;
# account_deletion_requests — read by the login/refresh lock check before any tenant context exists, and by the
# nightly purge across tenants (22).
RLS_EXEMPT_TABLES = {'users', 'subscriptions', 'razorpay_webhook_events', 'account_deletion_requests'}


class Command(BaseCommand):
    help = 'Fail unless the runtime DB role owns nothing and every tenant table has forced RLS.'

    def add_arguments(self, parser):
        parser.add_argument('--role', default=None, help='Runtime role to check (default: the connected user).')
        parser.add_argument('--json', action='store_true', help='Print a JSON summary (table count etc.).')

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            role = options['role'] or self._scalar(cursor, 'SELECT current_user')
            problems = self._check(cursor, role)
            table_count = self._scalar(cursor, """
                SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')""")

        if options['json']:
            self.stdout.write(json.dumps({'role': role, 'ok': not problems, 'problems': problems,
                                          'table_count': table_count}))
        if problems:
            raise CommandError('Database role check failed:\n- ' + '\n- '.join(problems))
        if not options['json']:
            self.stdout.write(self.style.SUCCESS(
                f'Role {role!r} owns nothing, has DML on all {table_count} tables, and tenant tables have forced RLS.'))

    @staticmethod
    def _scalar(cursor, sql, params=None):
        cursor.execute(sql, params or [])
        return cursor.fetchone()[0]

    @staticmethod
    def _column(cursor, sql, params=None):
        cursor.execute(sql, params or [])
        return [row[0] for row in cursor.fetchall()]

    def _check(self, cursor, role):
        cursor.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s', [role])
        row = cursor.fetchone()
        if row is None:
            return [f'role {role!r} does not exist']
        problems = []
        rolsuper, rolbypassrls = row
        if rolsuper:
            problems.append(f'{role} is a superuser (bypasses RLS)')
        if rolbypassrls:
            problems.append(f'{role} has BYPASSRLS')
        # Membership would let it SET ROLE to (or inherit from) a more powerful
        # role — on Cloud SQL, `gcloud sql users create` adds cloudsqlsuperuser.
        member_of = self._column(cursor, """
            SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
            WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = %s) ORDER BY 1""", [role])
        if member_of:
            problems.append(f'{role} is a member of: {", ".join(member_of)}')

        if self._scalar(cursor, """
                SELECT pg_get_userbyid(nspowner) = %s FROM pg_namespace WHERE nspname = 'public'""", [role]):
            problems.append(f'{role} owns schema public')
        if self._scalar(cursor, "SELECT has_schema_privilege(%s, 'public', 'CREATE')", [role]):
            problems.append(f'{role} can CREATE in schema public')

        owned = self._column(cursor, """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
              AND pg_get_userbyid(c.relowner) = %s
            ORDER BY 1""", [role])
        if owned:
            problems.append(f'{role} owns {len(owned)} relation(s): {", ".join(owned[:10])}')

        # has_table_privilege(..., 'A, B') is true if ANY is held, so check each.
        missing_dml = self._column(cursor, """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
              AND NOT (has_table_privilege(%s, c.oid, 'SELECT') AND has_table_privilege(%s, c.oid, 'INSERT')
                       AND has_table_privilege(%s, c.oid, 'UPDATE') AND has_table_privilege(%s, c.oid, 'DELETE'))
            ORDER BY 1""", [role] * 4)
        if missing_dml:
            problems.append(f'{role} lacks DML on {len(missing_dml)} table(s): {", ".join(missing_dml[:10])}')

        missing_seq = self._column(cursor, """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              -- CASE pins evaluation order: the planner may otherwise call
              -- has_sequence_privilege on non-sequences and error out.
              AND CASE WHEN c.relkind = 'S' THEN NOT has_sequence_privilege(%s, c.oid, 'USAGE') ELSE false END
            ORDER BY 1""", [role])
        if missing_seq:
            problems.append(f'{role} lacks USAGE on {len(missing_seq)} sequence(s): {", ".join(missing_seq[:10])}')

        unprotected = [name for name in self._column(cursor, """
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
              AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
            ORDER BY 1""") if name not in RLS_EXEMPT_TABLES]
        if unprotected:
            problems.append(f'tenant table(s) without forced RLS: {", ".join(unprotected)}')
        return problems
