-- Runs once on first cluster init (fresh pgdata volume only).
-- The app must connect as a NON-superuser: Postgres superusers bypass
-- Row-Level Security entirely, and tenant isolation (invariant 1) depends
-- on RLS. app_user owns the schema it migrates, and FORCE ROW LEVEL
-- SECURITY in each policy migration makes RLS apply to the owner too.
-- CREATEDB is needed so Django can create the test database.
CREATE ROLE app_user LOGIN PASSWORD 'app_password' NOSUPERUSER CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE pg_platform TO app_user;
\connect pg_platform
GRANT ALL ON SCHEMA public TO app_user;
