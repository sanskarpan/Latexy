-- Harden the append-only admin audit log for the application database role.
--
-- Purpose:
--   * grant the running application only SELECT and INSERT on admin_audit_log
--   * revoke UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER
--   * refuse to run if the application role owns the table, because an owner
--     can bypass table privileges
--   * fail loudly if the append-only trigger from migration 0077 is missing
--     or disabled
--
-- Usage (run as the table owner or a superuser, after migrations):
--   psql "$DATABASE_URL" -v app_role=latexy_app \
--     -f backend/scripts/harden_admin_audit_role.sql
--
-- app_role must be the role the API/worker uses for routine traffic. This is
-- intentionally a manual, auditable operation: it is role-neutral and does not
-- change schema, so it can be applied in any environment without a migration.
-- Re-running is safe.

\set ON_ERROR_STOP on

-- psql variables cannot be interpolated inside dollar-quoted DO blocks, so
-- materialize the role once and read it from a session-local temp table.
DROP TABLE IF EXISTS latexy_audit_hardening_role;
CREATE TEMP TABLE latexy_audit_hardening_role (app_role text NOT NULL);
INSERT INTO latexy_audit_hardening_role (app_role) VALUES (:'app_role');

DO $$
DECLARE
    app_role text;
BEGIN
    SELECT t.app_role INTO app_role FROM latexy_audit_hardening_role t;

    -- Ownership grants DDL and bypasses table privileges.
    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_roles r ON r.oid = c.relowner
        WHERE c.oid = 'admin_audit_log'::regclass
          AND r.rolname = app_role
    ) THEN
        RAISE EXCEPTION 'app_role owns admin_audit_log; use a non-owner application role';
    END IF;

    -- Permissions alone are not enough if the storage-layer guard is absent.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'admin_audit_log'::regclass
          AND tgname = 'admin_audit_log_append_only'
          AND NOT tgisinternal
          AND tgenabled <> 'D'
    ) THEN
        RAISE EXCEPTION 'admin_audit_log append-only trigger is missing or disabled';
    END IF;

    -- Start from an empty privilege set, then grant exactly the append/read pair.
    EXECUTE format(
        'REVOKE ALL PRIVILEGES ON TABLE admin_audit_log FROM %I',
        app_role
    );
    EXECUTE format(
        'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER '
        'ON TABLE admin_audit_log FROM %I',
        app_role
    );
    EXECUTE format(
        'GRANT SELECT, INSERT ON TABLE admin_audit_log TO %I',
        app_role
    );
END
$$;

DROP TABLE latexy_audit_hardening_role;
