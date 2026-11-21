-- SMART ENGLISH AI — initial schema (PostgreSQL 15+)
-- Validated against PostgreSQL 16. UUID primary keys, FKs, indexes, timestamps.
-- Audio is NOT stored permanently: only transcripts, summaries and scores.
-- No BEGIN/COMMIT here: app/db/migrate.py wraps each file in a transaction.


CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email

-- ---------- Enums ----------
CREATE TYPE user_role          AS ENUM ('parent', 'student', 'admin');
CREATE TYPE cefr_level         AS ENUM ('A0', 'A1', 'A2', 'B1', 'B2');
CREATE TYPE ui_language        AS ENUM ('ar', 'en');
CREATE TYPE session_status     AS ENUM ('active', 'completed', 'abandoned');
CREATE TYPE conversation_mode  AS ENUM ('beginner', 'guided', 'free', 'role_play');
CREATE TYPE message_speaker    AS ENUM ('teacher', 'student', 'system');
CREATE TYPE assessment_kind    AS ENUM ('lesson_quiz', 'unit_test', 'placement', 'game');
CREATE TYPE subscription_plan  AS ENUM ('free', 'standard', 'premium');
CREATE TYPE subscription_state AS ENUM ('active', 'grace_period', 'expired', 'revoked', 'trial');

-- Shared trigger to maintain updated_at
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- ---------- Identity ----------
CREATE TABLE users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role            user_role   NOT NULL,
    email           citext      UNIQUE,                 -- parents/admins only
    password_hash   text,                               -- scrypt/argon2 hash, never plaintext
    is_active       boolean     NOT NULL DEFAULT true,
    last_login_at   timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT parent_needs_credentials CHECK (
        role <> 'parent' OR (email IS NOT NULL AND password_hash IS NOT NULL))
);

CREATE TABLE parents (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    display_name         text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 80),
    preferred_language   ui_language NOT NULL DEFAULT 'ar',
    country_code         char(2),
    parent_pin_hash      text,                          -- protects the parent area on a shared device
    consent_accepted_at  timestamptz,                   -- verifiable parental consent
    consent_version      text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE teachers (                                 -- virtual teacher personas
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,               -- 'emma' | 'daniel' | 'alex'
    display_name    text NOT NULL,
    description_en  text NOT NULL,
    description_ar  text NOT NULL,
    min_level       cefr_level NOT NULL DEFAULT 'A0',
    voice_id        text NOT NULL,                      -- provider-specific TTS voice
    avatar_asset    text NOT NULL,
    persona_prompt  text NOT NULL,                      -- server-side only, never sent to client
    is_enabled      boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE students (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    parent_id            uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    nickname             text NOT NULL CHECK (char_length(nickname) BETWEEN 1 AND 40),  -- no full legal name
    birth_year           smallint CHECK (birth_year BETWEEN 2000 AND 2030),            -- year only (data minimisation)
    avatar_code          text NOT NULL DEFAULT 'default',
    current_level        cefr_level NOT NULL DEFAULT 'A0',
    preferred_teacher_id uuid REFERENCES teachers(id) ON DELETE SET NULL,
    show_arabic          boolean NOT NULL DEFAULT true,
    daily_goal_minutes   smallint NOT NULL DEFAULT 15 CHECK (daily_goal_minutes BETWEEN 5 AND 120),
    total_points         integer  NOT NULL DEFAULT 0 CHECK (total_points >= 0),
    streak_days          integer  NOT NULL DEFAULT 0 CHECK (streak_days >= 0),
    last_active_on       date,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    deleted_at           timestamptz
);
CREATE INDEX ix_students_parent ON students(parent_id) WHERE deleted_at IS NULL;

CREATE TABLE parent_settings (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id                 uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    student_id                uuid REFERENCES students(id) ON DELETE CASCADE,  -- NULL = default for all children
    daily_limit_minutes       smallint CHECK (daily_limit_minutes BETWEEN 5 AND 240),
    allowed_start_time        time,
    allowed_end_time          time,
    free_conversation_enabled boolean NOT NULL DEFAULT true,
    role_play_enabled         boolean NOT NULL DEFAULT true,
    store_transcripts         boolean NOT NULL DEFAULT true,   -- parent may disable transcript retention
    transcript_retention_days smallint NOT NULL DEFAULT 90 CHECK (transcript_retention_days BETWEEN 0 AND 365),
    weekly_report_email       boolean NOT NULL DEFAULT true,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);
-- One default row per parent, one row per (parent, student)
CREATE UNIQUE INDEX ux_parent_settings_default ON parent_settings(parent_id) WHERE student_id IS NULL;
CREATE UNIQUE INDEX ux_parent_settings_student ON parent_settings(parent_id, student_id) WHERE student_id IS NOT NULL;

CREATE TABLE refresh_tokens (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   text NOT NULL UNIQUE,                  -- SHA-256 of the opaque token
    device_label text,
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_tokens_user ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

-- ---------- Curriculum ----------
CREATE TABLE curriculum_units (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text NOT NULL UNIQUE,               -- 'U01-alphabet'
    position       smallint NOT NULL UNIQUE,
    level          cefr_level NOT NULL,
    title_en       text NOT NULL,
    title_ar       text NOT NULL,
    description_ar text NOT NULL,
    is_published   boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE lessons (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id            uuid NOT NULL REFERENCES curriculum_units(id) ON DELETE RESTRICT,
    code               text NOT NULL UNIQUE,           -- 'U02-L03-animals'
    position           smallint NOT NULL,
    title_en           text NOT NULL,
    title_ar           text NOT NULL,
    explanation_ar     text NOT NULL,
    objectives         jsonb NOT NULL DEFAULT '[]',
    steps              jsonb NOT NULL DEFAULT '[]',    -- ordered lesson-sequence definition
    estimated_minutes  smallint NOT NULL DEFAULT 20 CHECK (estimated_minutes BETWEEN 5 AND 60),
    pass_score         smallint NOT NULL DEFAULT 70 CHECK (pass_score BETWEEN 0 AND 100),
    min_plan           subscription_plan NOT NULL DEFAULT 'free',
    is_published       boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (unit_id, position)
);

CREATE TABLE vocabulary (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    word_en             text NOT NULL,
    meaning_ar          text NOT NULL,
    phonetic_ar         text NOT NULL,                 -- approximate pronunciation in Arabic letters (aid only)
    ipa                 text,
    part_of_speech      text,
    example_en          text NOT NULL,
    example_ar          text NOT NULL,
    audio_word_key      text,                          -- object-storage key of reviewed native audio
    audio_example_key   text,
    image_key           text,
    topic               text NOT NULL,                 -- 'colors', 'animals', ...
    level               cefr_level NOT NULL DEFAULT 'A0',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (word_en, part_of_speech)
);
CREATE INDEX ix_vocabulary_topic_level ON vocabulary(topic, level);

CREATE TABLE lesson_vocabulary (
    lesson_id     uuid NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    vocabulary_id uuid NOT NULL REFERENCES vocabulary(id) ON DELETE RESTRICT,
    position      smallint NOT NULL,
    PRIMARY KEY (lesson_id, vocabulary_id)
);

CREATE TABLE student_vocabulary (                     -- spaced-repetition state per word
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id       uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    vocabulary_id    uuid NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    mastery          smallint NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 5),
    times_seen       integer  NOT NULL DEFAULT 0,
    times_correct    integer  NOT NULL DEFAULT 0,
    first_learned_at timestamptz NOT NULL DEFAULT now(),
    last_reviewed_at timestamptz,
    next_review_at   timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (student_id, vocabulary_id)
);
CREATE INDEX ix_student_vocab_review ON student_vocabulary(student_id, next_review_at);

-- ---------- Learning activity ----------
CREATE TABLE lesson_sessions (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id        uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    lesson_id         uuid NOT NULL REFERENCES lessons(id) ON DELETE RESTRICT,
    teacher_id        uuid REFERENCES teachers(id) ON DELETE SET NULL,
    status            session_status NOT NULL DEFAULT 'active',
    current_step      smallint NOT NULL DEFAULT 0,
    score             smallint CHECK (score BETWEEN 0 AND 100),
    stars             smallint CHECK (stars BETWEEN 0 AND 3),
    passed            boolean,
    duration_seconds  integer NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
    summary           jsonb,                           -- educational summary for parent report
    started_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_lesson_sessions_student ON lesson_sessions(student_id, started_at DESC);
CREATE INDEX ix_lesson_sessions_lesson  ON lesson_sessions(lesson_id);

CREATE TABLE conversation_sessions (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id            uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    teacher_id            uuid NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    lesson_session_id     uuid REFERENCES lesson_sessions(id) ON DELETE SET NULL,
    mode                  conversation_mode NOT NULL,
    scenario_code         text,                        -- role-play: 'restaurant', 'airport', ...
    status                session_status NOT NULL DEFAULT 'active',
    student_speech_seconds integer NOT NULL DEFAULT 0,
    teacher_speech_seconds integer NOT NULL DEFAULT 0,
    turn_count            integer NOT NULL DEFAULT 0,
    avg_latency_ms        integer,
    summary               jsonb,                       -- mistakes, new words, highlights
    provider_info         jsonb,                       -- which STT/TTS/LLM handled it (for QA)
    started_at            timestamptz NOT NULL DEFAULT now(),
    ended_at              timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_conv_sessions_student ON conversation_sessions(student_id, started_at DESC);

CREATE TABLE conversation_messages (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id         uuid NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    seq                integer NOT NULL,
    speaker            message_speaker NOT NULL,
    text_en            text NOT NULL,
    text_ar            text,
    correction         jsonb,                          -- {original, corrected, explanation_ar}
    was_interrupted    boolean NOT NULL DEFAULT false,
    stt_confidence     real CHECK (stt_confidence BETWEEN 0 AND 1),
    safety_flags       text[] NOT NULL DEFAULT '{}',
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz,                    -- set from parent_settings.transcript_retention_days
    UNIQUE (session_id, seq)
);
CREATE INDEX ix_conv_messages_expiry ON conversation_messages(expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE pronunciation_results (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id             uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    conversation_session_id uuid REFERENCES conversation_sessions(id) ON DELETE SET NULL,
    lesson_session_id      uuid REFERENCES lesson_sessions(id) ON DELETE SET NULL,
    vocabulary_id          uuid REFERENCES vocabulary(id) ON DELETE SET NULL,
    target_text            text NOT NULL,
    recognized_text        text NOT NULL,
    method                 text NOT NULL CHECK (method IN ('phoneme_assessment', 'transcript_match')),
    accuracy_score         real CHECK (accuracy_score BETWEEN 0 AND 100),  -- only for phoneme_assessment
    fluency_score          real CHECK (fluency_score  BETWEEN 0 AND 100),
    completeness_score     real CHECK (completeness_score BETWEEN 0 AND 100),
    word_details           jsonb NOT NULL DEFAULT '[]',  -- per-word / per-phoneme errors
    missing_words          text[] NOT NULL DEFAULT '{}',
    provider               text NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT accuracy_requires_phoneme CHECK (method = 'phoneme_assessment' OR accuracy_score IS NULL)
);
CREATE INDEX ix_pron_results_student ON pronunciation_results(student_id, created_at DESC);

CREATE TABLE assessments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id   uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    lesson_id    uuid REFERENCES lessons(id) ON DELETE SET NULL,
    unit_id      uuid REFERENCES curriculum_units(id) ON DELETE SET NULL,
    kind         assessment_kind NOT NULL,
    game_code    text,                                 -- 'word_matching', 'listen_choose', ...
    score        smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
    max_points   smallint NOT NULL DEFAULT 100,
    points       smallint NOT NULL DEFAULT 0,
    answers      jsonb NOT NULL DEFAULT '[]',          -- [{item_id, given, correct, ms}]
    duration_seconds integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_assessments_student ON assessments(student_id, created_at DESC);

CREATE TABLE achievements (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text NOT NULL UNIQUE,               -- 'first_conversation', 'words_50'
    title_en       text NOT NULL,
    title_ar       text NOT NULL,
    description_ar text NOT NULL,
    icon_asset     text NOT NULL,
    points         smallint NOT NULL DEFAULT 0,
    rule           jsonb NOT NULL,                     -- evaluated server-side
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE student_achievements (
    student_id     uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    achievement_id uuid NOT NULL REFERENCES achievements(id) ON DELETE CASCADE,
    earned_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, achievement_id)
);

CREATE TABLE daily_activity (                          -- pre-aggregated for dashboards & limits
    student_id            uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    activity_date         date NOT NULL,
    learning_seconds      integer NOT NULL DEFAULT 0,
    conversation_seconds  integer NOT NULL DEFAULT 0,
    lessons_completed     smallint NOT NULL DEFAULT 0,
    words_learned         smallint NOT NULL DEFAULT 0,
    points_earned         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, activity_date)
);

-- ---------- Billing (prepared, disabled until MVP is tested) ----------
CREATE TABLE subscriptions (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id                uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    plan                     subscription_plan NOT NULL DEFAULT 'free',
    state                    subscription_state NOT NULL DEFAULT 'active',
    apple_original_transaction_id text UNIQUE,
    apple_product_id         text,
    environment              text CHECK (environment IN ('Sandbox', 'Production')),
    current_period_end       timestamptz,
    auto_renew               boolean,
    last_verified_at         timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_subscriptions_parent ON subscriptions(parent_id);

-- ---------- Audit (parent-visible privacy actions) ----------
CREATE TABLE audit_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    action      text NOT NULL,                         -- 'student.created', 'data.deleted', ...
    target_type text,
    target_id   uuid,
    metadata    jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_actor ON audit_events(actor_user_id, created_at DESC);

-- updated_at triggers
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['users','parents','teachers','students','parent_settings',
    'curriculum_units','lessons','vocabulary','student_vocabulary','lesson_sessions',
    'conversation_sessions','achievements','subscriptions']
  LOOP
    EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
  END LOOP;
END $$;

-- Seed the three teacher personas (prompts are filled in Phase 3)
INSERT INTO teachers (code, display_name, description_en, description_ar, min_level, voice_id, avatar_asset, persona_prompt) VALUES
 ('emma',   'Emma',   'Friendly teacher for beginners',        'معلمة ودودة للمبتدئين',          'A0', 'TBD', 'teacher_emma',   'PHASE3'),
 ('daniel', 'Daniel', 'Friendly teacher for conversation',     'معلم ودود لممارسة المحادثة',     'A1', 'TBD', 'teacher_daniel', 'PHASE3'),
 ('alex',   'Alex',   'Advanced teacher for intermediate levels','معلم متقدم للمستويات المتوسطة', 'A2', 'TBD', 'teacher_alex',   'PHASE3');


