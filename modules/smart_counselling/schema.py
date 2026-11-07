"""SQLite bootstrap schema for the additive Smart Counselling foundation."""


def ensure_smart_counselling_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            lead_id INTEGER,
            counsellor_user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'IDENTIFICATION_PENDING'
                CHECK(status IN (
                    'STARTED', 'IDENTIFICATION_PENDING', 'IDENTIFIED', 'IN_PROGRESS',
                    'OUTCOME_PENDING', 'COMPLETED', 'ABANDONED'
                )),
            mobile_verified INTEGER NOT NULL DEFAULT 0 CHECK(mobile_verified IN (0, 1)),
            verification_method TEXT,
            primary_interested_course_id INTEGER,
            secondary_interested_course_id INTEGER,
            outcome TEXT,
            outcome_reason TEXT,
            next_action TEXT,
            next_followup_date TEXT,
            staff_notes TEXT,
            abandon_reason TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            abandoned_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (institute_id) REFERENCES institutes(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id),
            FOREIGN KEY (lead_id) REFERENCES leads(id),
            FOREIGN KEY (counsellor_user_id) REFERENCES users(id),
            FOREIGN KEY (primary_interested_course_id) REFERENCES courses(id),
            FOREIGN KEY (secondary_interested_course_id) REFERENCES courses(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_sessions_tenant_status_started
        ON counselling_sessions(institute_id, status, started_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_sessions_tenant_branch_status
        ON counselling_sessions(institute_id, branch_id, status, started_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_sessions_tenant_counsellor_open
        ON counselling_sessions(institute_id, counsellor_user_id, status, updated_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_sessions_tenant_lead_history
        ON counselling_sessions(institute_id, lead_id, started_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_sessions_tenant_analytics
        ON counselling_sessions(institute_id, started_at, branch_id, counsellor_user_id, outcome)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            counselling_session_id INTEGER NOT NULL,
            lead_id INTEGER,
            actor_user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (institute_id) REFERENCES institutes(id),
            FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY (lead_id) REFERENCES leads(id),
            FOREIGN KEY (actor_user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_events_tenant_session_created
        ON counselling_events(institute_id, counselling_session_id, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_counselling_events_tenant_actor_created
        ON counselling_events(institute_id, actor_user_id, created_at)
    """)

    session_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(counselling_sessions)").fetchall()
    }
    if "verified_mobile_normalized" not in session_columns:
        conn.execute(
            "ALTER TABLE counselling_sessions ADD COLUMN verified_mobile_normalized TEXT"
        )
    if "identification_status" not in session_columns:
        conn.execute(
            "ALTER TABLE counselling_sessions ADD COLUMN identification_status TEXT"
        )
    if "identity_mobile_normalized" not in session_columns:
        conn.execute(
            "ALTER TABLE counselling_sessions ADD COLUMN identity_mobile_normalized TEXT"
        )
        conn.execute("""
            UPDATE counselling_sessions
            SET identity_mobile_normalized = verified_mobile_normalized
            WHERE identity_mobile_normalized IS NULL AND verified_mobile_normalized IS NOT NULL
        """)
    if "completion_followup_id" not in session_columns:
        conn.execute(
            "ALTER TABLE counselling_sessions ADD COLUMN completion_followup_id INTEGER"
        )
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_sessions_tenant_verified_mobile
        ON counselling_sessions(institute_id, verified_mobile_normalized)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_otp_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            counselling_session_id INTEGER NOT NULL,
            mobile_normalized TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'LOCKED', 'INVALIDATED')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            send_sequence INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT NOT NULL,
            resend_available_at TEXT NOT NULL,
            verified_at TEXT,
            invalidated_at TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(delivery_status IN ('PENDING', 'SENT', 'FAILED')),
            provider_message_id TEXT,
            created_by_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (institute_id) REFERENCES institutes(id),
            FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY (created_by_user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_otp_tenant_session_created
        ON counselling_otp_challenges(institute_id, counselling_session_id, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_otp_tenant_mobile_created
        ON counselling_otp_challenges(institute_id, mobile_normalized, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_otp_tenant_creator_created
        ON counselling_otp_challenges(institute_id, created_by_user_id, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_otp_tenant_status_expiry
        ON counselling_otp_challenges(institute_id, status, expires_at)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            counselling_session_id INTEGER NOT NULL UNIQUE,
            lead_id INTEGER NOT NULL,
            assessment_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'IN_PROGRESS'
                CHECK(status IN ('IN_PROGRESS', 'COMPLETED')),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (institute_id) REFERENCES institutes(id),
            FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_assessment_tenant_status
        ON counselling_assessments(institute_id, status, updated_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_assessment_tenant_lead
        ON counselling_assessments(institute_id, lead_id, created_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_assessment_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id INTEGER NOT NULL,
            question_key TEXT NOT NULL,
            answer_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (assessment_id, question_key),
            FOREIGN KEY (assessment_id) REFERENCES counselling_assessments(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sc_answer_assessment
        ON counselling_assessment_answers(assessment_id, question_key)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counselling_lead_creation_requests (
            counselling_session_id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            lead_id INTEGER UNIQUE,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY (institute_id) REFERENCES institutes(id),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)

    ensure_course_intelligence_schema(conn)
    ensure_recommendation_schema(conn)
    ensure_course_experience_schema(conn)


def ensure_course_intelligence_schema(conn):
    """SQLite/test equivalent of the additive Phase 5 MySQL migration."""
    # Production MySQL DDL is intentionally owned by the reviewed additive
    # migration. The compatibility wrapper has no executescript method.
    if not hasattr(conn, "executescript"):
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS course_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            short_description TEXT,
            detailed_description TEXT,
            course_purpose TEXT,
            minimum_education_level TEXT,
            preferred_background TEXT,
            target_audience TEXT,
            hard_eligibility_text TEXT,
            starting_skill_level TEXT,
            certification_title TEXT,
            certification_issuing_body TEXT,
            certification_included INTEGER NOT NULL DEFAULT 0 CHECK(certification_included IN (0,1)),
            external_exam_required INTEGER NOT NULL DEFAULT 0 CHECK(external_exam_required IN (0,1)),
            certification_details TEXT,
            recommendation_enabled INTEGER NOT NULL DEFAULT 0 CHECK(recommendation_enabled IN (0,1)),
            created_by_user_id INTEGER NOT NULL,
            updated_by_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(institute_id, course_id),
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(created_by_user_id) REFERENCES users(id),
            FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_course_profiles_tenant_enabled ON course_profiles(institute_id, recommendation_enabled, course_id);
        CREATE TABLE IF NOT EXISTS course_supported_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            goal_code TEXT NOT NULL, match_strength TEXT NOT NULL DEFAULT 'SUPPORTED', is_primary INTEGER NOT NULL DEFAULT 0,
            UNIQUE(institute_id, course_id, goal_code), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_course_goals_lookup ON course_supported_goals(institute_id, goal_code, course_id);
        CREATE TABLE IF NOT EXISTS course_supported_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            interest_code TEXT NOT NULL, match_strength TEXT NOT NULL DEFAULT 'SUPPORTED', is_primary INTEGER NOT NULL DEFAULT 0,
            UNIQUE(institute_id, course_id, interest_code), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_course_interests_lookup ON course_supported_interests(institute_id, interest_code, course_id);
        CREATE TABLE IF NOT EXISTS course_education_suitability (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            education_code TEXT NOT NULL, suitability_type TEXT NOT NULL CHECK(suitability_type IN ('ALLOWED','PREFERRED')),
            UNIQUE(institute_id, course_id, education_code, suitability_type), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS course_skill_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            skill_dimension TEXT NOT NULL, minimum_level TEXT NOT NULL,
            UNIQUE(institute_id, course_id, skill_dimension), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS course_skills_taught (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            skill_code TEXT NOT NULL, is_primary INTEGER NOT NULL DEFAULT 0,
            UNIQUE(institute_id, course_id, skill_code), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS course_profile_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('LEARNING_OUTCOME','CAREER_OUTCOME','JOB_ROLE')),
            item_text TEXT NOT NULL, display_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(institute_id, course_id, item_type, item_text), FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS course_profile_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            actor_user_id INTEGER NOT NULL, event_type TEXT NOT NULL, changed_fields_json TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id), FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_course_profile_events ON course_profile_events(institute_id, course_id, created_at);
    """)


def ensure_recommendation_schema(conn):
    """SQLite/test equivalent of the additive Phase 6 MySQL migration."""
    if not hasattr(conn, "executescript"):
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recommendation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            counselling_session_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            assessment_id INTEGER NOT NULL,
            assessment_version TEXT NOT NULL,
            engine_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING','COMPLETED','FAILED')),
            outcome_status TEXT,
            prospect_snapshot_json TEXT NOT NULL,
            created_by_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(assessment_id) REFERENCES counselling_assessments(id),
            FOREIGN KEY(created_by_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_rec_runs_tenant_session_created ON recommendation_runs(institute_id,counselling_session_id,status,created_at);
        CREATE INDEX IF NOT EXISTS idx_sc_rec_runs_tenant_assessment ON recommendation_runs(institute_id,assessment_id,created_at);
        CREATE TABLE IF NOT EXISTS recommendation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_run_id INTEGER NOT NULL,
            institute_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            course_name_snapshot TEXT NOT NULL,
            course_category_snapshot TEXT,
            course_profile_updated_at TEXT,
            result_rank INTEGER,
            raw_score REAL,
            normalized_score INTEGER,
            match_label TEXT,
            eligibility_status TEXT NOT NULL CHECK(eligibility_status IN ('ELIGIBLE','INELIGIBLE')),
            matched_factors_json TEXT NOT NULL,
            unmatched_factors_json TEXT NOT NULL,
            ineligibility_reasons_json TEXT NOT NULL,
            skill_chips_json TEXT NOT NULL,
            explanation TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(recommendation_run_id,course_id),
            FOREIGN KEY(recommendation_run_id) REFERENCES recommendation_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sc_rec_results_run_rank ON recommendation_results(recommendation_run_id,eligibility_status,result_rank);
        CREATE INDEX IF NOT EXISTS idx_sc_rec_results_tenant_course ON recommendation_results(institute_id,course_id,recommendation_run_id);
    """)


def ensure_course_experience_schema(conn):
    """SQLite/test equivalent of the additive Phase 7 migration."""
    if not hasattr(conn, "executescript"):
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS counselling_course_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            counselling_session_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            recommendation_run_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            interest_level TEXT NOT NULL CHECK(interest_level IN ('INTERESTED','HIGHLY_INTERESTED','NOT_INTERESTED')),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
            created_by_user_id INTEGER NOT NULL,
            updated_by_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(counselling_session_id,course_id),
            FOREIGN KEY(counselling_session_id) REFERENCES counselling_sessions(id),
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(recommendation_run_id) REFERENCES recommendation_runs(id),
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(created_by_user_id) REFERENCES users(id),
            FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sc_course_interest_one_primary ON counselling_course_interests(counselling_session_id) WHERE is_primary=1;
        CREATE INDEX IF NOT EXISTS idx_sc_course_interest_tenant_session ON counselling_course_interests(institute_id,counselling_session_id,updated_at);
        CREATE INDEX IF NOT EXISTS idx_sc_course_interest_tenant_lead ON counselling_course_interests(institute_id,lead_id,updated_at);
    """)
