-- Financial analysis data for orders
ALTER TABLE v2_orders ADD COLUMN IF NOT EXISTS financial_data JSON;
