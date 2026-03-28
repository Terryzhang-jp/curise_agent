-- 020_add_pending_template_status.sql
-- Add 'pending_template' to Order.status CHECK constraint
-- Date: 2026-03-06

ALTER TABLE v2_orders DROP CONSTRAINT IF EXISTS ck_v2_orders_status_enum;

ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_status_enum
  CHECK (status IN ('uploading','pending_template','extracting','matching','ready','error'));
