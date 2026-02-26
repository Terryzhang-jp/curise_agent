-- 012_db_constraints.sql
-- Database constraint fixes: FK, Unique, Check, Index
-- Date: 2026-02-25

-- ─── 1. FK: RefreshToken.user_id → users.id ─────────────────
ALTER TABLE v2_refresh_tokens
  ADD CONSTRAINT fk_v2_refresh_tokens_user_id
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- ─── 2. Unique: FieldDefinition(schema_id, field_key) ───────
-- Clean up possible duplicate data first
DELETE FROM v2_field_definitions a
USING v2_field_definitions b
WHERE a.id > b.id
  AND a.schema_id = b.schema_id
  AND a.field_key = b.field_key;

ALTER TABLE v2_field_definitions
  ADD CONSTRAINT uq_field_def_schema_key UNIQUE (schema_id, field_key);

-- ─── 3. Check: Order.status enum ────────────────────────────
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_status_enum
  CHECK (status IN ('uploading','extracting','matching','ready','error'));

-- ─── 4. Check: Order.fulfillment_status enum ────────────────
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_fulfillment_status_enum
  CHECK (fulfillment_status IN ('pending','inquiry_sent','quoted','confirmed','delivering','delivered','invoiced','paid'));

-- ─── 5. Index: RefreshToken.is_revoked ──────────────────────
CREATE INDEX IF NOT EXISTS ix_v2_refresh_tokens_is_revoked ON v2_refresh_tokens (is_revoked);

-- ─── 6. Index: Order.created_at ─────────────────────────────
CREATE INDEX IF NOT EXISTS ix_v2_orders_created_at ON v2_orders (created_at);
