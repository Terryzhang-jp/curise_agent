CREATE TABLE IF NOT EXISTS v2_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    filename VARCHAR(500) NOT NULL,
    file_url VARCHAR(500),
    file_type VARCHAR(20) NOT NULL DEFAULT 'pdf',
    file_size_bytes INTEGER,
    doc_type VARCHAR(50),
    content_markdown TEXT,
    extracted_data JSONB,
    extraction_method VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    processing_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    extracted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_documents_user_id ON v2_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_documents_status ON v2_documents(status);
CREATE INDEX IF NOT EXISTS idx_v2_documents_created_at ON v2_documents(created_at DESC);
