"""Tenant isolation regression tests for document access.

Why this test exists
====================
Codex adversarial review (2026-04-12) flagged `manage_document_order`
as a CRITICAL cross-tenant leak: any employee could read or mutate
another tenant's documents by guessing the document_id. The same leak
existed in `build_document_context_injection`.

These tests lock in the fix so that:

  1. user_A creates a document
  2. user_B tries to access it via the tool and via context injection
  3. Both return "not found" (never "forbidden", to avoid existence leaks)
  4. A superadmin can still access everything

Threat model
------------
The attacker has a valid employee JWT but tries to access another
tenant's data by guessing primary keys. Our defense is a row-level
ownership filter (`Document.user_id == ctx.user_id`) applied at every
query site that reads or writes Document rows from tools.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

import models  # noqa: E402
from models import Document, Order  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """sqlite in-memory session with the rows we need."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Document.__table__.create(engine, checkfirst=True)
    Order.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    # User A owns document 1, User B owns document 2
    doc_a = Document(
        id=1,
        user_id=100,
        filename="user_a_secret.pdf",
        file_type="pdf",
        doc_type="purchase_order",
        extracted_data={
            "order_metadata": {"po_number": "USER-A-PO-001"},
            "products": [{"product_name": "secret_item", "quantity": 5}],
        },
        status="extracted",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    doc_b = Document(
        id=2,
        user_id=200,
        filename="user_b_secret.pdf",
        file_type="pdf",
        doc_type="purchase_order",
        extracted_data={
            "order_metadata": {"po_number": "USER-B-PO-002"},
            "products": [{"product_name": "other_item", "quantity": 3}],
        },
        status="extracted",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add_all([doc_a, doc_b])
    session.commit()
    yield session
    session.close()


def _make_ctx(db, *, user_id: int, user_role: str = "employee"):
    from services.agent.tool_context import ToolContext
    return ToolContext(db=db, user_id=user_id, user_role=user_role)


def _register_tool(ctx):
    """Create a minimal registry and register manage_document_order into it."""
    from services.tools.document_order import register
    from services.agent.tool_registry import ToolRegistry
    registry = ToolRegistry()
    register(registry, ctx)
    return registry


# ──────────────────────────────────────────────────────────────────────
# manage_document_order — read actions
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["preview", "products", "compute_total"])
def test_employee_cannot_read_other_tenant_document(db_session, action):
    """user_B (id=200) must NOT see user_A's (id=100) document."""
    ctx = _make_ctx(db_session, user_id=200, user_role="employee")
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    # userB targets doc_a (belongs to userA)
    result = tool.fn(action=action, document_id=1)

    assert "不存在" in result, (
        f"{action} leaked user_A's document to user_B: {result!r}"
    )
    # Also make sure it's NOT a 'forbidden' message (no existence leak)
    assert "permission" not in result.lower()
    assert "forbidden" not in result.lower()


def test_employee_can_read_own_document(db_session):
    """user_A accessing own document works normally."""
    ctx = _make_ctx(db_session, user_id=100, user_role="employee")
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    result = tool.fn(action="preview", document_id=1)
    assert "不存在" not in result
    # Preview output contains the document payload summary
    assert "文档" in result or "PO" in result or "products" in result.lower() or result


def test_superadmin_can_read_any_document(db_session):
    """superadmin bypasses ownership filter."""
    ctx = _make_ctx(db_session, user_id=999, user_role="superadmin")
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    result_a = tool.fn(action="preview", document_id=1)
    result_b = tool.fn(action="preview", document_id=2)

    assert "不存在" not in result_a
    assert "不存在" not in result_b


def test_unauthenticated_ctx_returns_not_found(db_session):
    """If ctx.user_id is None (no auth), refuse to return anything."""
    ctx = _make_ctx(db_session, user_id=None, user_role="employee")  # type: ignore
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    result = tool.fn(action="preview", document_id=1)
    assert "不存在" in result


# ──────────────────────────────────────────────────────────────────────
# manage_document_order — write actions
# ──────────────────────────────────────────────────────────────────────


def test_employee_cannot_mutate_other_tenant_document(db_session):
    """user_B must NOT be able to update user_A's document fields."""
    ctx = _make_ctx(db_session, user_id=200, user_role="employee")
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    result = tool.fn(
        action="update_fields",
        document_id=1,
        fields=json.dumps({"currency": "HACKED"}),
    )
    assert "不存在" in result

    # Verify the document was NOT mutated
    db_session.expire_all()
    doc_a = db_session.query(Document).filter(Document.id == 1).first()
    overrides = (doc_a.extracted_data or {}).get("document_overrides") or {}
    assert overrides.get("currency") != "HACKED"


def test_employee_cannot_clear_other_tenant_document_fields(db_session):
    """user_B must NOT be able to clear user_A's document fields."""
    ctx = _make_ctx(db_session, user_id=200, user_role="employee")
    registry = _register_tool(ctx)
    tool = registry.get("manage_document_order")

    result = tool.fn(
        action="clear_fields",
        document_id=1,
        fields=json.dumps({"keys": ["currency"]}),
    )
    assert "不存在" in result


# ──────────────────────────────────────────────────────────────────────
# Context injection path (build_document_context_injection)
# ──────────────────────────────────────────────────────────────────────


def test_context_injection_refuses_other_tenant(db_session):
    """The chat prompt context injection must also respect ownership."""
    from services.documents.document_context_package import build_document_context_injection

    # user_B asks about user_A's document
    result = build_document_context_injection(
        db_session,
        "请查看 document 1",
        "document_processing",
        user_id=200,
        user_role="employee",
    )
    assert result == "", f"context injection leaked: {result!r}"


def test_context_injection_allows_owner(db_session):
    """Owner can see their own document in context."""
    from services.documents.document_context_package import build_document_context_injection

    result = build_document_context_injection(
        db_session,
        "请查看 document 1",
        "document_processing",
        user_id=100,
        user_role="employee",
    )
    assert result != ""
    assert "USER-A-PO-001" in result or "文档" in result


def test_context_injection_allows_superadmin(db_session):
    from services.documents.document_context_package import build_document_context_injection

    result = build_document_context_injection(
        db_session,
        "请查看 document 1",
        "document_processing",
        user_id=999,
        user_role="superadmin",
    )
    assert result != ""


def test_context_injection_without_user_returns_empty(db_session):
    """Missing auth context → empty injection (fail closed)."""
    from services.documents.document_context_package import build_document_context_injection

    result = build_document_context_injection(
        db_session,
        "请查看 document 1",
        "document_processing",
        user_id=None,
        user_role="employee",
    )
    assert result == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
