-- 011: Add missing indexes for frequently queried columns
-- Run this on production after deploying the updated models.py

CREATE INDEX IF NOT EXISTS ix_v2_orders_user_id ON v2_orders (user_id);
CREATE INDEX IF NOT EXISTS ix_v2_agent_sessions_user_id ON v2_agent_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_v2_agent_messages_session_id ON v2_agent_messages (session_id);
CREATE INDEX IF NOT EXISTS ix_v2_pipeline_sessions_user_id ON v2_pipeline_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_v2_pipeline_messages_session_id ON v2_pipeline_messages (session_id);
CREATE INDEX IF NOT EXISTS ix_v2_refresh_tokens_user_id ON v2_refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_v2_line_users_user_id ON v2_line_users (user_id);

-- Numeric field constraints
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_total_amount_nonneg CHECK (total_amount >= 0);
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_payment_amount_nonneg CHECK (payment_amount >= 0);
ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_invoice_amount_nonneg CHECK (invoice_amount >= 0);
ALTER TABLE products ADD CONSTRAINT ck_products_price_nonneg CHECK (price >= 0);
