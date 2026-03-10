-- Add document_schema column to order format templates for schema-first PDF extraction
ALTER TABLE v2_order_format_templates ADD COLUMN IF NOT EXISTS document_schema JSONB;
