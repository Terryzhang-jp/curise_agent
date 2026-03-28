-- Session context data: stores referenced order IDs and other cross-turn context
ALTER TABLE v2_agent_sessions ADD COLUMN IF NOT EXISTS context_data JSON;
