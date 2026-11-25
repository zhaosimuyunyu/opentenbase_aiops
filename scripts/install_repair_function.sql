-- Run once as the database administrator on the audited OpenTenBase database.
-- Set repair_user before running this file with psql, for example:
--   \set repair_user aiops_repair
CREATE SCHEMA IF NOT EXISTS aiops_admin;
REVOKE ALL ON SCHEMA aiops_admin FROM PUBLIC;

CREATE TABLE IF NOT EXISTS aiops_admin.repair_targets (
    target_schema text NOT NULL,
    target_table text NOT NULL,
    PRIMARY KEY (target_schema, target_table)
);
REVOKE ALL ON aiops_admin.repair_targets FROM PUBLIC;

CREATE OR REPLACE FUNCTION aiops_admin.analyze_table(target_schema text, target_table text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF target_schema !~ '^[A-Za-z_][A-Za-z0-9_]*$'
       OR target_table !~ '^[A-Za-z_][A-Za-z0-9_]*$' THEN
        RAISE EXCEPTION 'invalid ANALYZE target';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM aiops_admin.repair_targets
        WHERE repair_targets.target_schema = analyze_table.target_schema
          AND repair_targets.target_table = analyze_table.target_table
    ) THEN
        RAISE EXCEPTION 'ANALYZE target is not approved by the database administrator';
    END IF;
    EXECUTE format('ANALYZE %I.%I', target_schema, target_table);
END;
$$;

ALTER FUNCTION aiops_admin.analyze_table(text, text) OWNER TO CURRENT_USER;
REVOKE ALL ON FUNCTION aiops_admin.analyze_table(text, text) FROM PUBLIC;
GRANT USAGE ON SCHEMA aiops_admin TO :repair_user;
GRANT EXECUTE ON FUNCTION aiops_admin.analyze_table(text, text) TO :repair_user;

-- Add explicit targets as administrator, for example:
-- INSERT INTO aiops_admin.repair_targets(target_schema, target_table)
-- VALUES ('public', 'orders');
