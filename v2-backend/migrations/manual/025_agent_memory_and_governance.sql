-- Migration 025: Agent Memory System + Sub-Agent Task Governance
-- DeerFlow 2.0 standard alignment
-- Date: 2026-03-28

-- ============================================================
-- 1. Long-term Memory (DeerFlow MemoryMiddleware equivalent)
-- ============================================================

CREATE TABLE IF NOT EXISTS v2_agent_memories (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type     VARCHAR(30) NOT NULL,  -- 'user_preference', 'supplier_knowledge', 'workflow_pattern', 'fact'
    key             VARCHAR(200) NOT NULL,
    value           TEXT NOT NULL,
    source_session_id VARCHAR(36),          -- session that produced this memory
    access_count    INTEGER DEFAULT 0,      -- track how often this memory is used
    last_accessed_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_agent_memories_user_id ON v2_agent_memories(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_memories_type ON v2_agent_memories(user_id, memory_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memories_user_key ON v2_agent_memories(user_id, memory_type, key);

-- ============================================================
-- 2. Sub-Agent Task Tracking (DeerFlow SubagentExecutor equivalent)
-- ============================================================

CREATE TABLE IF NOT EXISTS v2_sub_agent_tasks (
    id                  SERIAL PRIMARY KEY,
    parent_session_id   VARCHAR(36) NOT NULL REFERENCES v2_agent_sessions(id) ON DELETE CASCADE,
    parent_turn         INTEGER,
    sub_agent_name      VARCHAR(100) NOT NULL,
    task_description    TEXT NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout')),
    result_preview      TEXT,               -- first 500 chars of result
    error_message       TEXT,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT NOW(),
    completed_at        TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_sub_agent_tasks_parent ON v2_sub_agent_tasks(parent_session_id);

-- ============================================================
-- 3. Agent Feedback (for memory quality improvement loop)
-- ============================================================

CREATE TABLE IF NOT EXISTS v2_agent_feedback (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(36) REFERENCES v2_agent_sessions(id) ON DELETE CASCADE,
    message_id      INTEGER,
    rating          INTEGER CHECK (rating >= 1 AND rating <= 5),
    feedback_text   TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_agent_feedback_session ON v2_agent_feedback(session_id);
