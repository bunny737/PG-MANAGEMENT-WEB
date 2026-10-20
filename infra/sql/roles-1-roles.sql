-- Part 1 of the production role model (docs/deployment.md, "Database roles").
-- Run as `postgres` connected to the `postgres` database, BEFORE the first
-- migration and before every restore drill (a logical export carries no
-- server-level roles). Idempotent.
--
--   psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
--     -v migration_password="$DB_MIGRATION_PASSWORD" -v app_password="$DB_PASSWORD" \
--     -v db_name=pg_platform -f infra/sql/roles-1-roles.sql
--
-- Create these roles here, NOT with `gcloud sql users create`: Cloud SQL adds
-- users created that way to cloudsqlsuperuser, which check_db_roles rejects.
\set ON_ERROR_STOP on

SELECT 'CREATE ROLE migration_user LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migration_user')\gexec
SELECT 'CREATE ROLE app_user LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user')\gexec

-- Re-assert attributes on pre-existing roles too.
ALTER ROLE migration_user LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'migration_password';
ALTER ROLE app_user LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'app_password';

-- Cloud SQL's postgres is not a real superuser: it must be a member of
-- migration_user to create a database owned by it (and to run part 2).
GRANT migration_user TO postgres;

SELECT format('CREATE DATABASE %I OWNER migration_user', :'db_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')\gexec
SELECT format('ALTER DATABASE %I OWNER TO migration_user', :'db_name')\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name')\gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO app_user', :'db_name')\gexec
