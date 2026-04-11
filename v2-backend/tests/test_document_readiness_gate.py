"""Readiness-gate regression tests.

Why this test exists
====================
Codex adversarial review (2026-04-12) flagged a High issue:
`create_or_update_order_from_document(force=True)` silently bypassed
`_ensure_order_creation_allowed()` AND still wrote `order.status="ready"`
via `_resolve_order_status` (which only checked whether products existed).

The net effect: a document with products but missing `delivery_date` /
`po_number` / `ship_name` would become a ready order in the main upload
pipeline, breaking the fail-fast contract.

These tests lock in the fix:

  1. Incomplete document → status "needs_review", not "ready"
  2. Document without products → status "error"
  3. Complete document → status "ready"
  4. `force=True` alone only controls overwrite semantics, NOT validation
  5. `allow_incomplete=True` allows persisting blocked docs (as needs_review)
  6. `admin_override=True` is the ONLY path that can force "ready" on
     incomplete docs, and it leaves an audit log entry
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

import models  # noqa: E402
from models import Document, Order  # noqa: E402
from services.documents.document_order_projection import create_or_update_order_from_document  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Document.__table__.create(engine, checkfirst=True)
    Order.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_document(
    session,
    *,
    doc_id: int = 1,
    products: list | None = None,
    metadata: dict | None = None,
    doc_type: str = "purchase_order",
) -> Document:
    extracted = {
        "metadata": metadata or {},
        "products": products if products is not None else [],
    }
    doc = Document(
        id=doc_id,
        user_id=100,
        filename=f"doc_{doc_id}.pdf",
        file_type="pdf",
        doc_type=doc_type,
        extracted_data=extracted,
        status="extracted",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(doc)
    session.commit()
    return doc


# ──────────────────────────────────────────────────────────────────────
# Status resolution
# ──────────────────────────────────────────────────────────────────────


def test_complete_document_becomes_ready(db_session):
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    order = create_or_update_order_from_document(doc, db_session)
    assert order.status == "ready"


def test_incomplete_document_raises_by_default(db_session):
    """Missing delivery_date → default call raises ValueError."""
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            # no delivery_date
        },
    )
    with pytest.raises(ValueError, match="缺少关键字段"):
        create_or_update_order_from_document(doc, db_session)

    # Order must NOT have been created
    assert db_session.query(Order).filter(Order.document_id == doc.id).first() is None


def test_incomplete_document_with_allow_incomplete_becomes_needs_review(db_session):
    """allow_incomplete=True persists the order but status is needs_review, not ready.

    This is the regression: before the fix, this would produce status='ready'
    because force=True skipped both the validation AND the status computation.
    """
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            # no delivery_date
        },
    )
    order = create_or_update_order_from_document(
        doc, db_session, force=True, allow_incomplete=True,
    )
    assert order.status == "needs_review", (
        f"Incomplete doc became ready instead of needs_review: status={order.status}"
    )
    # Order was persisted (ingestion pipeline needs this)
    assert db_session.query(Order).filter(Order.document_id == doc.id).first() is not None


def test_no_products_becomes_error_status(db_session):
    """Document with metadata but zero products → status error."""
    doc = _make_document(
        db_session,
        products=[],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    order = create_or_update_order_from_document(
        doc, db_session, force=True, allow_incomplete=True,
    )
    assert order.status == "error"


def test_force_alone_does_not_bypass_validation(db_session):
    """force=True (without allow_incomplete) must still validate missing fields.

    Before the fix, force=True silently implied allow_incomplete=True. This
    test ensures the semantics are now split.
    """
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            # missing ship_name + delivery_date
        },
    )
    with pytest.raises(ValueError):
        create_or_update_order_from_document(doc, db_session, force=True)


def test_force_on_existing_order_overwrites(db_session):
    """force=True still controls the 'overwrite existing' semantic."""
    doc = _make_document(
        db_session,
        products=[{"product_name": "item_v1", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    # First call creates order
    order1 = create_or_update_order_from_document(doc, db_session)
    assert order1.status == "ready"
    original_product_name = order1.products[0]["product_name"]

    # Mutate document products
    doc.extracted_data["products"] = [{"product_name": "item_v2", "quantity": 2}]
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(doc, "extracted_data")
    db_session.commit()

    # Without force → returns existing unchanged
    order2 = create_or_update_order_from_document(doc, db_session, force=False)
    assert order2.id == order1.id
    assert order2.products[0]["product_name"] == original_product_name  # unchanged

    # With force → overwrites
    order3 = create_or_update_order_from_document(doc, db_session, force=True)
    assert order3.id == order1.id
    assert order3.products[0]["product_name"] == "item_v2"


# ──────────────────────────────────────────────────────────────────────
# admin_override
# ──────────────────────────────────────────────────────────────────────


def test_admin_override_forces_ready_on_incomplete(db_session, caplog):
    """admin_override=True is the ONLY way to force 'ready' on incomplete docs,
    and every use MUST emit a WARNING-level audit log."""
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            # missing delivery_date
        },
    )
    with caplog.at_level(logging.WARNING, logger="services.document_order_projection"):
        order = create_or_update_order_from_document(
            doc, db_session, force=True, admin_override=True,
        )

    assert order.status == "ready"
    # Audit log must have been emitted
    assert any(
        "ADMIN_OVERRIDE" in rec.message for rec in caplog.records
    ), "admin_override must emit a WARNING audit log"


# ──────────────────────────────────────────────────────────────────────
# Background ingestion path (simulates document_workflow)
# ──────────────────────────────────────────────────────────────────────


def test_background_ingestion_persists_blocked_as_needs_review(db_session):
    """Simulates the document_workflow.py ingestion call pattern:
    force=True, allow_incomplete=True, admin_override=False.

    This is the critical path Codex flagged. A blocked document MUST become
    a persisted order with status='needs_review', NOT lost AND NOT ready.
    """
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            # no delivery_date → blocked
        },
    )
    order = create_or_update_order_from_document(
        doc, db_session, force=True, allow_incomplete=True,
    )
    assert order.status == "needs_review"
    assert order.processing_error  # has a human-readable hint
    assert "delivery_date" in order.processing_error


# ──────────────────────────────────────────────────────────────────────
# Phase gate + stale-state clearing (P0.6.3, 2026-04-12)
# ──────────────────────────────────────────────────────────────────────


def test_reproject_blocked_when_fulfillment_started(db_session):
    """force=True must raise ValueError if fulfillment_status != 'pending'.

    Once fulfillment has started (inquiry_sent, confirmed, delivered …)
    the order carries financial/logistics records that must not be clobbered
    by re-reading the source document.
    """
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    order = create_or_update_order_from_document(doc, db_session)
    order.fulfillment_status = "inquiry_sent"
    db_session.commit()

    with pytest.raises(ValueError, match="fulfillment has already started"):
        create_or_update_order_from_document(doc, db_session, force=True)


def test_admin_override_bypasses_phase_gate(db_session):
    """admin_override=True can still reproject even after fulfillment starts."""
    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    order = create_or_update_order_from_document(doc, db_session)
    order.fulfillment_status = "confirmed"
    db_session.commit()

    # Should NOT raise
    result = create_or_update_order_from_document(
        doc, db_session, force=True, admin_override=True,
    )
    assert result.id == order.id


def test_reproject_clears_derived_state(db_session):
    """force=True (reproject) must clear match_results, match_statistics,
    anomaly_data, financial_data, and inquiry_data so downstream tools don't
    operate on stale data from the old document version.
    """
    from sqlalchemy.orm.attributes import flag_modified

    doc = _make_document(
        db_session,
        products=[{"product_name": "item", "quantity": 1}],
        metadata={
            "po_number": "PO-001",
            "ship_name": "MS Test",
            "delivery_date": "2026-05-01",
        },
    )
    order = create_or_update_order_from_document(doc, db_session)

    # Inject stale derived state
    order.match_results = [{"matched": True}]
    order.match_statistics = {"score": 0.9}
    order.anomaly_data = {"anomalies": []}
    order.financial_data = {"total": 100.0}
    order.inquiry_data = {"suppliers": {"1": {"status": "completed"}}}
    for field in ("match_results", "match_statistics", "anomaly_data", "financial_data", "inquiry_data"):
        flag_modified(order, field)
    db_session.commit()

    # Reproject
    create_or_update_order_from_document(doc, db_session, force=True)
    db_session.refresh(order)

    assert order.match_results is None
    assert order.match_statistics is None
    assert order.anomaly_data is None
    assert order.financial_data is None
    assert order.inquiry_data is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
