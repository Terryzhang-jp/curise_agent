-- Migration 030: Partial unique index on v2_orders.document_id
--
-- Guarantees at most one order per document, while still allowing
-- document_id = NULL (set when a document is deleted / de-linked).
-- A plain UNIQUE constraint would reject multiple NULL rows because
-- NULL != NULL in SQL but PostgreSQL unique indexes treat each NULL
-- as distinct — either way we need a partial index for clarity.
--
-- Idempotent: IF NOT EXISTS guard means safe to re-run.

CREATE UNIQUE INDEX IF NOT EXISTS uq_v2_orders_document_id
    ON v2_orders (document_id)
    WHERE document_id IS NOT NULL;
