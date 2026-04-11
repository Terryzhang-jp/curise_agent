"""Atomicity regression tests for document-first upload.

Why this test exists
====================
Codex adversarial review (2026-04-12) flagged:

  create_document_record() uploads the blob and commits the Document row.
  create_pending_order_for_document() then performs a SECOND independent commit
  for the Order. There is no transaction spanning both steps and no
  compensating delete if the later step fails.

This meant any transient DB failure between the two commits would leave an
orphaned Document row + blob, and the upload endpoint would return 500
without cleaning up.

The fix introduces `create_document_and_pending_order` which:

  1. Uploads the blob
  2. Creates Document + Order in a single DB transaction
  3. On DB failure, deletes the blob (compensation) and rolls back

These tests lock in the fix via failure injection.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

import models  # noqa: E402
from models import Document, Order  # noqa: E402


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Document.__table__.create(engine, checkfirst=True)
    Order.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def fake_storage():
    """Mock storage.upload + delete, track all calls."""
    from services import document_workflow

    class FakeStorage:
        def __init__(self):
            self.uploaded: list[str] = []
            self.deleted: list[str] = []
            self.upload_should_fail = False

        def upload(self, folder, filename, content, content_type):
            if self.upload_should_fail:
                raise RuntimeError("simulated storage upload failure")
            path = f"{folder}/{filename}"
            self.uploaded.append(path)
            return path

        def delete(self, path):
            self.deleted.append(path)

    fake = FakeStorage()
    with mock.patch.object(document_workflow, "storage", fake):
        yield fake


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_atomic_upload_happy_path(db_session, fake_storage):
    from services.document_workflow import create_document_and_pending_order

    document, order = create_document_and_pending_order(
        db_session,
        user_id=100,
        filename="test.pdf",
        content=b"pdf-bytes",
        file_type="pdf",
        content_type="application/pdf",
    )

    assert document.id is not None
    assert order.id is not None
    assert order.document_id == document.id
    assert order.status == "uploading"
    assert len(fake_storage.uploaded) == 1
    assert len(fake_storage.deleted) == 0


# ──────────────────────────────────────────────────────────────────────
# Failure injection
# ──────────────────────────────────────────────────────────────────────


def test_atomic_upload_db_failure_compensates_blob(db_session, fake_storage):
    """If the DB transaction fails mid-way, the blob must be deleted and
    no Document/Order rows should remain."""
    from services.document_workflow import create_document_and_pending_order

    # Patch Order.__init__ to raise after Document is flushed
    original_order_init = Order.__init__

    def failing_order_init(self, *args, **kwargs):
        raise RuntimeError("simulated DB failure during Order creation")

    with mock.patch.object(Order, "__init__", failing_order_init):
        with pytest.raises(RuntimeError, match="simulated DB failure"):
            create_document_and_pending_order(
                db_session,
                user_id=100,
                filename="test.pdf",
                content=b"pdf-bytes",
                file_type="pdf",
                content_type="application/pdf",
            )

    # Compensation fired: blob was deleted
    assert len(fake_storage.uploaded) == 1
    assert len(fake_storage.deleted) == 1
    assert fake_storage.uploaded[0] == fake_storage.deleted[0]

    # No Document rows left (rollback worked)
    Order.__init__ = original_order_init  # restore
    assert db_session.query(Document).count() == 0
    assert db_session.query(Order).count() == 0


def test_atomic_upload_storage_failure_no_db_rows(db_session, fake_storage):
    """If the blob upload itself fails, no DB rows should be created and
    no compensating delete is needed."""
    from services.document_workflow import create_document_and_pending_order

    fake_storage.upload_should_fail = True

    with pytest.raises(RuntimeError, match="simulated storage upload failure"):
        create_document_and_pending_order(
            db_session,
            user_id=100,
            filename="test.pdf",
            content=b"pdf-bytes",
            file_type="pdf",
            content_type="application/pdf",
        )

    assert len(fake_storage.uploaded) == 0
    assert len(fake_storage.deleted) == 0
    assert db_session.query(Document).count() == 0
    assert db_session.query(Order).count() == 0


def test_compensation_tolerates_delete_failure(db_session, fake_storage):
    """If the compensating blob delete itself fails, the original DB error
    must still propagate (not be masked)."""
    from services.document_workflow import create_document_and_pending_order

    # Make delete raise
    def failing_delete(path):
        raise RuntimeError("simulated delete failure")
    fake_storage.delete = failing_delete

    # Make Order creation fail too
    def failing_order_init(self, *args, **kwargs):
        raise RuntimeError("simulated DB failure")

    with mock.patch.object(Order, "__init__", failing_order_init):
        with pytest.raises(RuntimeError, match="simulated DB failure"):
            create_document_and_pending_order(
                db_session,
                user_id=100,
                filename="test.pdf",
                content=b"pdf-bytes",
                file_type="pdf",
                content_type="application/pdf",
            )

    # Even though delete failed, the original error propagated
    # and no DB rows remain
    assert db_session.query(Document).count() == 0
    assert db_session.query(Order).count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
