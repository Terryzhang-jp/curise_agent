-- Pipeline tables for agentic order processing
-- Run against the shared Supabase PostgreSQL database

CREATE TABLE IF NOT EXISTS v2_pipeline_sessions (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    current_phase   VARCHAR(30),
    filename        VARCHAR(500) NOT NULL,
    file_url        VARCHAR(500),
    file_type       VARCHAR(10) NOT NULL DEFAULT 'pdf',
    phase_results   JSONB NOT NULL DEFAULT '{}',
    order_metadata  JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_sessions_user_id ON v2_pipeline_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_sessions_status ON v2_pipeline_sessions(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_sessions_created_at ON v2_pipeline_sessions(created_at DESC);

CREATE TABLE IF NOT EXISTS v2_pipeline_messages (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(36) NOT NULL REFERENCES v2_pipeline_sessions(id) ON DELETE CASCADE,
    sequence        INTEGER NOT NULL,
    role            VARCHAR(15) NOT NULL,
    phase           VARCHAR(30),
    msg_type        VARCHAR(20) NOT NULL DEFAULT 'text',
    content         TEXT NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_messages_session ON v2_pipeline_messages(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_pipeline_messages_phase ON v2_pipeline_messages(session_id, phase);
