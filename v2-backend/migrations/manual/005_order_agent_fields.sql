-- 005: Add geographic and delivery fields to v2_orders for agent-based matching
ALTER TABLE v2_orders ADD COLUMN IF NOT EXISTS country_id INTEGER;
ALTER TABLE v2_orders ADD COLUMN IF NOT EXISTS port_id INTEGER;
ALTER TABLE v2_orders ADD COLUMN IF NOT EXISTS delivery_date VARCHAR(50);
