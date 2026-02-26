-- 008: Add country_id to supplier templates for country-based template matching
ALTER TABLE v2_supplier_templates ADD COLUMN IF NOT EXISTS country_id INTEGER;
