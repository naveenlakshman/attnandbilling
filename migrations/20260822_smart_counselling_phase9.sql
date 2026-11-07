-- Smart Counselling Phase 9: reporting index only; no summary or analytics tables.
-- Apply after Phase 2 through Phase 8 migrations.

CREATE INDEX idx_sc_sessions_tenant_analytics
    ON counselling_sessions(institute_id, started_at, branch_id, counsellor_user_id, outcome);

-- Rollback:
-- DROP INDEX idx_sc_sessions_tenant_analytics ON counselling_sessions;
