-- 009: Fulfillment lifecycle management
-- Adds fulfillment tracking columns to v2_orders and seeds tool configs

ALTER TABLE v2_orders
  ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(30) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS delivery_data JSON,
  ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(100),
  ADD COLUMN IF NOT EXISTS invoice_amount NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS invoice_date VARCHAR(50),
  ADD COLUMN IF NOT EXISTS payment_amount NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS payment_date VARCHAR(50),
  ADD COLUMN IF NOT EXISTS payment_reference VARCHAR(200),
  ADD COLUMN IF NOT EXISTS attachments JSON DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS fulfillment_notes TEXT;

CREATE INDEX IF NOT EXISTS ix_v2_orders_fulfillment_status ON v2_orders(fulfillment_status);

-- Seed fulfillment tool configs
INSERT INTO v2_tool_configs (tool_name, group_name, display_name, description, is_enabled, is_builtin)
VALUES
  ('get_order_fulfillment', 'business', '查看订单履约', '查看订单履约状态', true, true),
  ('update_order_fulfillment', 'business', '更新订单履约', '更新订单履约状态', true, true),
  ('record_delivery_receipt', 'business', '记录交货验收', '记录港口交货验收', true, true),
  ('attach_order_file', 'business', '附加文件', '附加文件到订单', true, true)
ON CONFLICT (tool_name) DO NOTHING;
