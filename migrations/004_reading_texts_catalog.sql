-- Migration: shared catalog of reading texts. institution_id NULL = visible to every institution, read-only for them.
-- Each institution's own texts keep its institution_id.
ALTER TABLE reading_texts ALTER COLUMN institution_id DROP NOT NULL;

-- NULLs are distinct in the unique index from 002, so catalog rows need their own: it makes the seed re-runnable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_texts_catalog_source
    ON reading_texts (source, source_id) WHERE institution_id IS NULL AND source IS NOT NULL;
