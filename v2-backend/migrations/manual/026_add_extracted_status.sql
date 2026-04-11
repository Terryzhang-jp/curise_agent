-- Add "extracted" to order status enum
-- Required for Agent-Centric flow: upload → extract → [Agent decides] → match → ready

ALTER TABLE v2_orders DROP CONSTRAINT IF EXISTS ck_v2_orders_status_enum;
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_status_enum
    CHECK (status IN ('uploading','pending_template','extracting','extracted','matching','ready','error'));
