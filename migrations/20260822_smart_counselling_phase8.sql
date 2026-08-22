-- Smart Counselling Phase 8: durable CRM follow-up linkage for idempotent completion.
-- Apply after Phase 2 through Phase 7 migrations.

ALTER TABLE counselling_sessions
    ADD COLUMN completion_followup_id INT NULL AFTER completed_at,
    ADD KEY idx_sc_session_completion_followup(institute_id, completion_followup_id),
    ADD CONSTRAINT fk_sc_session_completion_followup
        FOREIGN KEY(completion_followup_id) REFERENCES followups(id);

-- Destructive rollback only after clearing Phase 8 completion linkage:
-- ALTER TABLE counselling_sessions DROP FOREIGN KEY fk_sc_session_completion_followup,
--   DROP INDEX idx_sc_session_completion_followup, DROP COLUMN completion_followup_id;
