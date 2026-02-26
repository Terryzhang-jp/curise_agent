-- 014: Add delivery_environment column to v2_orders
ALTER TABLE v2_orders
  ADD COLUMN IF NOT EXISTS delivery_environment JSON;
