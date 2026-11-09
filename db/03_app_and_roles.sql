-- App tables (never readable by learners) + the read-only learner role.
-- Run as the database owner (Supabase: the `postgres` user in the SQL editor).
-- BEFORE RUNNING: replace CHANGE_ME_STRONG_PASSWORD below.

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS shop;   -- so the GRANTs below work before reset_db.sh builds the tables

CREATE TABLE IF NOT EXISTS app.learners (
    learner_id    SERIAL PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,          -- login code handed out on paper
    display_name  TEXT NOT NULL,
    is_pilot      BOOLEAN NOT NULL DEFAULT FALSE, -- pilot excluded from all results
    excluded      BOOLEAN NOT NULL DEFAULT FALSE, -- no-show / dropout / duplicate (logged in events)
    arm           TEXT CHECK (arm IN ('tutor','baseline')),
    pair_no       INT,
    phase         TEXT NOT NULL DEFAULT 'waiting'
                  CHECK (phase IN ('waiting','pretest','practice','break','heldout','done')),
    phase_started_at TIMESTAMPTZ,                -- the phase clock starts here
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.attempts (
    attempt_id    BIGSERIAL PRIMARY KEY,
    learner_id    INT NOT NULL REFERENCES app.learners(learner_id),
    question_id   TEXT NOT NULL,
    phase         TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('run','submit')),
    sql_text      TEXT NOT NULL,
    error         TEXT,
    correct       BOOLEAN,
    got_rows      INT,
    diff          JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.question_views (
    learner_id    INT NOT NULL REFERENCES app.learners(learner_id),
    question_id   TEXT NOT NULL,
    phase         TEXT NOT NULL,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    final_correct BOOLEAN,
    PRIMARY KEY (learner_id, question_id)
);

CREATE TABLE IF NOT EXISTS app.hints (
    hint_id         BIGSERIAL PRIMARY KEY,
    learner_id      INT NOT NULL REFERENCES app.learners(learner_id),
    question_id     TEXT NOT NULL,
    arm             TEXT NOT NULL,
    level           INT NOT NULL,      -- 0 gate, 1-4 tutor ladder, 9 baseline full answer
    attempts_before INT NOT NULL,
    mastered        BOOLEAN,
    text            TEXT NOT NULL,
    source          TEXT NOT NULL,     -- llm | llm_retry | fallback | repeat | gate
    guard_blocked   INT NOT NULL DEFAULT 0,
    model           TEXT,
    latency_ms      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.survey (
    learner_id    INT NOT NULL REFERENCES app.learners(learner_id),
    item          TEXT NOT NULL,
    value         INT NOT NULL CHECK (value BETWEEN 1 AND 5),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, item)
);

CREATE TABLE IF NOT EXISTS app.events (
    event_id      BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE app.learners ADD COLUMN IF NOT EXISTS excluded BOOLEAN NOT NULL DEFAULT FALSE;
-- migrations for databases created by an earlier version of this file (safe to re-run)
ALTER TABLE app.learners ADD COLUMN IF NOT EXISTS phase_started_at TIMESTAMPTZ;
ALTER TABLE app.learners DROP CONSTRAINT IF EXISTS learners_phase_check;
ALTER TABLE app.learners ADD CONSTRAINT learners_phase_check
  CHECK (phase IN ('waiting','pretest','practice','break','heldout','done'));
ALTER TABLE app.learners ALTER COLUMN phase SET DEFAULT 'waiting';

-- ---------- read-only learner role ----------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'learner_ro') THEN
    CREATE ROLE learner_ro LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
  END IF;
END $$;

ALTER ROLE learner_ro SET statement_timeout = '3s';
ALTER ROLE learner_ro SET default_transaction_read_only = on;
ALTER ROLE learner_ro SET search_path = shop;
ALTER ROLE learner_ro CONNECTION LIMIT 20;

REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM learner_ro;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM learner_ro;
GRANT USAGE ON SCHEMA shop TO learner_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO learner_ro;
