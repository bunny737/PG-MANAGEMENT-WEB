-- Part 2 of the production role model (docs/deployment.md, "Database roles").
-- Run as `postgres` (a member of migration_user) connected to the app database:
-- after the first `migrate`, after every restore drill import, and safe to
-- re-run any time. Idempotent.
--
--   psql "host=127.0.0.1 port=5432 user=postgres dbname=pg_platform" -f infra/sql/roles-2-grants.sql
--
-- migration_user owns the schema and every object; app_user may only read and
-- write rows. Then: manage.py check_db_roles --role app_user
\set ON_ERROR_STOP on

ALTER SCHEMA public OWNER TO migration_user;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM app_user;
GRANT USAGE ON SCHEMA public TO app_user;

-- Objects that already exist (e.g. after importing an export).
SELECT format('ALTER TABLE public.%I OWNER TO migration_user', c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
  AND pg_get_userbyid(c.relowner) <> 'migration_user'\gexec
SELECT format('ALTER SEQUENCE public.%I OWNER TO migration_user', c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'S'
  AND pg_get_userbyid(c.relowner) <> 'migration_user'
  -- identity/serial sequences follow their table's owner
  AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i'))\gexec

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Objects future migrations create.
ALTER DEFAULT PRIVILEGES FOR ROLE migration_user IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_user IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_user;
