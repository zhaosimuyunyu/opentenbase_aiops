-- Run as the OpenTenBase database administrator with psql variables.
-- Example:
--   psql -v repair_user=aiops_repair -v repair_password='...' \
--        -v allowed_schema=public -v allowed_table=orders -f bootstrap_repair_access.sql
\set ON_ERROR_STOP on

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
    :'repair_user', :'repair_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :'repair_user'
)\gexec

SELECT format(
    'ALTER ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
    :'repair_user', :'repair_password'
)
WHERE EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :'repair_user'
)\gexec

\ir install_repair_function.sql

-- The view is the administrator's explicit allowlist. Replace the two values
-- or extend the VALUES list before running this file in production.
CREATE OR REPLACE VIEW aiops_admin.repair_targets AS
SELECT * FROM (VALUES (:'allowed_schema', :'allowed_table'))
AS allowed(target_schema, target_table);

REVOKE ALL ON aiops_admin.repair_targets FROM PUBLIC;
GRANT USAGE ON SCHEMA aiops_admin TO :repair_user;
GRANT EXECUTE ON FUNCTION aiops_admin.analyze_table(text, text) TO :repair_user;
