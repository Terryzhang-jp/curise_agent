-- Migration 003: Add summary_message_id for agent context compression
-- Run against existing database if v2_pipeline_sessions table already exists

ALTER TABLE v2_pipeline_sessions ADD COLUMN IF NOT EXISTS summary_message_id INTEGER;
