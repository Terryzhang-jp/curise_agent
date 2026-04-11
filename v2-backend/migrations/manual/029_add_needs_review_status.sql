-- Migration 029: add 'needs_review' to v2_orders.status enum
--
-- Context: Before 2026-04-12, create_or_update_order_from_document(force=True)
-- silently bypassed the readiness check AND wrote status='ready' regardless of
-- blocking_missing_fields. Codex adversarial review flagged this as high severity.
--
-- The fix splits the force parameter into force (overwrite existing) vs
-- allow_incomplete (persist blocked docs), and introduces 'needs_review' as
-- the correct status for orders with missing required fields.
--
-- Rollback: DROP then re-add the original constraint without 'needs_review'.

ALTER TABLE v2_orders DROP CONSTRAINT IF EXISTS ck_v2_orders_status_enum;

ALTER TABLE v2_orders ADD CONSTRAINT ck_v2_orders_status_enum
    CHECK (status IN ('uploading','pending_template','extracting','extracted','matching','needs_review','ready','error'));
