-- Migration: an assessment can be excluded ("no considerar esta grabación"): it stays stored but leaves every report.
-- Run by hand in production (migrations are not applied automatically).
ALTER TABLE reading_assessments DROP CONSTRAINT IF EXISTS reading_assessments_status_check;
ALTER TABLE reading_assessments ADD CONSTRAINT reading_assessments_status_check
    CHECK (status IN ('draft', 'complete', 'excluded'));
