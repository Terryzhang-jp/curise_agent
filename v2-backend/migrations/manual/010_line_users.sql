CREATE TABLE IF NOT EXISTS v2_line_users (
    id              SERIAL PRIMARY KEY,
    line_user_id    VARCHAR(50) UNIQUE NOT NULL,
    user_id         INTEGER NOT NULL,
    display_name    VARCHAR(200),
    active_session_id VARCHAR(36),
    is_blocked      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
    last_active_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_v2_line_users_line_user_id ON v2_line_users(line_user_id);
