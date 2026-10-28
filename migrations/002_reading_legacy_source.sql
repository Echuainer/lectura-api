-- Migration: origin of imported rows, so the lectura_app (SQLite) import can be re-run without duplicates.
ALTER TABLE reading_texts       ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE reading_texts       ADD COLUMN IF NOT EXISTS source_id BIGINT;
ALTER TABLE reading_assessments ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE reading_assessments ADD COLUMN IF NOT EXISTS source_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_texts_source
    ON reading_texts (institution_id, source, source_id) WHERE source IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_assessments_source
    ON reading_assessments (institution_id, source, source_id) WHERE source IS NOT NULL;
