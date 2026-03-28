-- 021: Add port and effective date columns to v2_upload_batches
-- Enables port-aware and date-aware product upload pipeline

ALTER TABLE v2_upload_batches ADD COLUMN IF NOT EXISTS port_id INTEGER;
ALTER TABLE v2_upload_batches ADD COLUMN IF NOT EXISTS port_name VARCHAR(200);
ALTER TABLE v2_upload_batches ADD COLUMN IF NOT EXISTS effective_from DATE;
ALTER TABLE v2_upload_batches ADD COLUMN IF NOT EXISTS effective_to DATE;
