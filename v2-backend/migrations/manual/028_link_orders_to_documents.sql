ALTER TABLE v2_orders
ADD COLUMN IF NOT EXISTS document_id INTEGER REFERENCES v2_documents(id);

CREATE INDEX IF NOT EXISTS idx_v2_orders_document_id ON v2_orders(document_id);
