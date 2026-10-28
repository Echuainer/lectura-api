-- Migration: tables for the reading fluency service (lectura-api).
-- Lives in the same database and schema as api-colegio-smart. Tables use the reading_ prefix.

CREATE TABLE IF NOT EXISTS reading_texts (
    id           BIGSERIAL PRIMARY KEY,
    institution_id BIGINT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    level        SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 8),
    content      TEXT NOT NULL,
    word_count   INTEGER NOT NULL,
    created_by   BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reading_texts_institution_id ON reading_texts (institution_id);
CREATE INDEX IF NOT EXISTS idx_reading_texts_created_by     ON reading_texts (created_by);

CREATE TABLE IF NOT EXISTS reading_assessments (
    id                 BIGSERIAL PRIMARY KEY,
    institution_id     BIGINT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    -- Deleting a student in Colegio Smart deletes their readings (personal data). The audio objects in R2
    -- are not deleted by the database: see "Pendientes" in README.md.
    student_id         BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    course_id          BIGINT REFERENCES courses(id) ON DELETE SET NULL,
    text_id            BIGINT NOT NULL REFERENCES reading_texts(id),
    evaluator_user_id  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    course_name        TEXT NOT NULL,
    level              SMALLINT NOT NULL,
    assessed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    period             TEXT,
    audio_key          TEXT,
    audio_mime         TEXT,
    transcript         TEXT,
    result             JSONB,
    wcpm               DOUBLE PRECISION,
    wpm                DOUBLE PRECISION,
    accuracy_pct       DOUBLE PRECISION,
    errors             INTEGER,
    unexpected_pauses  INTEGER,
    category           TEXT,
    expression         SMALLINT,
    wcpm_adjusted      DOUBLE PRECISION,
    observation        TEXT,
    report             TEXT,
    evaluator_name     TEXT,
    framework          TEXT,
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'complete')),
    rasinski           JSONB,
    rasinski_2         JSONB,
    prosody_model      JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_institution_id    ON reading_assessments (institution_id);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_student_id        ON reading_assessments (student_id);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_course_id         ON reading_assessments (course_id);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_text_id           ON reading_assessments (text_id);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_evaluator_user_id ON reading_assessments (evaluator_user_id);
CREATE INDEX IF NOT EXISTS idx_reading_assessments_institution_status_period
    ON reading_assessments (institution_id, status, period);

CREATE TABLE IF NOT EXISTS reading_jobs (
    id             BIGSERIAL PRIMARY KEY,
    assessment_id  BIGINT NOT NULL REFERENCES reading_assessments(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('analyze', 'prosody')),
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'error')),
    error          TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_reading_jobs_assessment_id ON reading_jobs (assessment_id);
CREATE INDEX IF NOT EXISTS idx_reading_jobs_pending ON reading_jobs (created_at) WHERE status = 'pending';
