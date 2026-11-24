CREATE INDEX CONCURRENTLY IF NOT EXISTS audit_records_scheduled_target_idx
    ON audit_records ((COALESCE(evidence->>'statistics_target', '')), created_at DESC, audit_id DESC)
    WHERE audit_type = 'readonly_health_audit' AND evidence->>'trigger' = 'scheduled';
