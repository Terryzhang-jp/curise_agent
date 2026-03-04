-- Add notes column to order format templates
ALTER TABLE v2_order_format_templates ADD COLUMN IF NOT EXISTS notes TEXT;
