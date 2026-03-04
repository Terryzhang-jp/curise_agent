-- 016: Bind supplier template to order format template for AI-guided field mapping
-- Adds order_format_template_id (which order template this inquiry template works with)
-- and field_mapping_metadata (provenance info from AI matching)

ALTER TABLE v2_supplier_templates
  ADD COLUMN IF NOT EXISTS order_format_template_id INTEGER;

ALTER TABLE v2_supplier_templates
  ADD COLUMN IF NOT EXISTS field_mapping_metadata JSON;
