-- Migration 004: Orders and Agent Sessions
-- Run manually: psql $DATABASE_URL < migrations/manual/004_orders_and_agent.sql

-- Orders table (independent business entity)
CREATE TABLE IF NOT EXISTS v2_orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    filename VARCHAR(500) NOT NULL,
    file_url VARCHAR(500),
    file_type VARCHAR(10) NOT NULL DEFAULT 'pdf',
    status VARCHAR(20) NOT NULL DEFAULT 'uploading',
    -- uploading | extracting | digitizing | matching | ready | error
    processing_error TEXT,
    extraction_data JSON,
    order_metadata JSON,
    products JSON,
    product_count INTEGER DEFAULT 0,
    total_amount NUMERIC(12,2),
    match_results JSON,
    match_statistics JSON,
    anomaly_data JSON,
    inquiry_data JSON,
    is_reviewed BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP,
    reviewed_by INTEGER,
    review_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_v2_orders_user ON v2_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_orders_status ON v2_orders(status);

-- Agent sessions (free-form chat, decoupled from orders)
CREATE TABLE IF NOT EXISTS v2_agent_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL DEFAULT '新对话',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    summary_message_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Agent messages (same dual-write pattern as pipeline)
CREATE TABLE IF NOT EXISTS v2_agent_messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES v2_agent_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    role VARCHAR(15) NOT NULL,
    msg_type VARCHAR(20) NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    metadata JSON,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_v2_agent_msgs ON v2_agent_messages(session_id, sequence);
