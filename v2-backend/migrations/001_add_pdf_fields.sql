-- Migration: Add PDF support fields to v2_order_format_templates
-- Run this against your database to add the new columns.
-- If the table doesn't exist yet, create_all on startup will create it with these columns.

ALTER TABLE v2_order_format_templates
  ADD COLUMN IF NOT EXISTS file_type VARCHAR(10) DEFAULT 'excel',
  ADD COLUMN IF NOT EXISTS layout_prompt TEXT,
  ADD COLUMN IF NOT EXISTS extracted_fields JSON;
