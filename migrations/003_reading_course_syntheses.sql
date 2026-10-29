-- Migration: saved AI course synthesis, one per course and measurement (period). Regenerating replaces it.
CREATE TABLE IF NOT EXISTS reading_course_syntheses (
    id               BIGSERIAL PRIMARY KEY,
    institution_id   BIGINT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    course_id        BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    period           TEXT NOT NULL,
    content          TEXT NOT NULL,
    created_by       BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_by_email TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (institution_id, course_id, period)
);
CREATE INDEX IF NOT EXISTS idx_reading_course_syntheses_course_id  ON reading_course_syntheses (course_id);
CREATE INDEX IF NOT EXISTS idx_reading_course_syntheses_created_by ON reading_course_syntheses (created_by);
