-- v2_agent_traces: execution traces for LLM calls and tool calls
CREATE TABLE IF NOT EXISTS v2_agent_traces (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES v2_agent_sessions(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    event_type VARCHAR(20) NOT NULL,  -- 'llm_call' | 'tool_call'
    model_name VARCHAR(100),
    tool_name VARCHAR(100),
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    tool_duration_ms INTEGER,
    tool_success BOOLEAN,
    error_message TEXT,
    estimated_cost_usd NUMERIC(10,6),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_traces_session ON v2_agent_traces(session_id);
CREATE INDEX IF NOT EXISTS ix_agent_traces_created ON v2_agent_traces(created_at);

-- AgentSession: add token_usage summary column
ALTER TABLE v2_agent_sessions ADD COLUMN IF NOT EXISTS token_usage JSON;
