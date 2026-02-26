-- 013: Order template integration — add template matching fields
-- v2_order_format_templates: source_company, match_keywords, is_active
-- v2_orders: template_id, template_match_method

ALTER TABLE v2_order_format_templates
  ADD COLUMN IF NOT EXISTS source_company VARCHAR(200),
  ADD COLUMN IF NOT EXISTS match_keywords JSON,
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE v2_orders
  ADD COLUMN IF NOT EXISTS template_id INTEGER,
  ADD COLUMN IF NOT EXISTS template_match_method VARCHAR(30);
