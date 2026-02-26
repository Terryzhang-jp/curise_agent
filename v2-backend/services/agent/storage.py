"""
PostgreSQL ORM storage layer for the ReAct Agent.

Replaces agent_design's SQLite storage with dual-write to PipelineMessage:
- agent_parts messages: canonical messages for engine history reconstruction
- display messages: thought/action/observation/text for frontend rendering

Uses the existing PipelineMessage ORM model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Data models (matching agent_design/storage.py interface)
# ============================================================

@dataclass
class Session:
    id: str
    title: str
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    summary_message_id: int | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class Message:
    id: int
    session_id: str
    role: str            # "user" | "assistant" | "tool"
    parts: list[dict]    # Parsed parts list
    model: str | None = None
    created_at: float = 0.0
    finished_at: float | None = None


# ============================================================
# Parts helper functions
# ============================================================

def text_part(text: str) -> dict:
    return {"type": "text", "data": {"text": text}}


def thinking_part(thinking: str) -> dict:
    return {"type": "thinking", "data": {"thinking": thinking}}


def tool_call_part(name: str, args: dict) -> dict:
    return {"type": "tool_call", "data": {"name": name, "args": args}}


def tool_result_part(name: str, result: str, duration_ms: int = 0) -> dict:
    return {"type": "tool_result", "data": {"name": name, "result": result, "duration_ms": duration_ms}}


def finish_part(reason: str = "stop") -> dict:
    return {"type": "finish", "data": {"reason": reason}}


# ============================================================
# Storage class — PostgreSQL ORM backed
# ============================================================

class Storage:
    """PostgreSQL-backed storage using PipelineMessage ORM model.

    Dual-write strategy:
    - Each agent message writes one canonical 'agent_parts' row (for engine history)
    - Plus display rows (thought/action/observation/text) for frontend rendering
    """

    def __init__(self, db):
        """Initialize with a SQLAlchemy session.

        Args:
            db: SQLAlchemy Session instance (not a factory)
        """
        self._db = db

    def _next_sequence(self, session_id: str) -> int:
        """Get the next sequence number for a session."""
        from models import PipelineMessage
        result = self._db.query(PipelineMessage.sequence).filter(
            PipelineMessage.session_id == session_id,
        ).order_by(PipelineMessage.sequence.desc()).first()
        return (result[0] + 1) if result else 1

    def _write_display_message(
        self,
        session_id: str,
        role: str,
        msg_type: str,
        content: str,
        phase: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Write a single display message for frontend rendering. Returns the message ID."""
        from models import PipelineMessage
        seq = self._next_sequence(session_id)
        msg = PipelineMessage(
            session_id=session_id,
            sequence=seq,
            role=role,
            phase=phase,
            msg_type=msg_type,
            content=content,
            meta=metadata,
        )
        self._db.add(msg)
        self._db.flush()  # Get the ID without committing
        return msg.id

    # ----------------------------------------------------------
    # Session operations (delegate to PipelineSession ORM)
    # ----------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        from models import PipelineSession
        ps = self._db.query(PipelineSession).filter(PipelineSession.id == session_id).first()
        if ps is None:
            return None
        return Session(
            id=ps.id,
            title=ps.filename,
            message_count=len(ps.messages) if ps.messages else 0,
            summary_message_id=ps.summary_message_id,
            created_at=ps.created_at.timestamp() if ps.created_at else 0.0,
            updated_at=ps.updated_at.timestamp() if ps.updated_at else 0.0,
        )

    def update_session(self, session_id: str, **fields):
        from models import PipelineSession
        ps = self._db.query(PipelineSession).filter(PipelineSession.id == session_id).first()
        if not ps:
            return
        for key, value in fields.items():
            if key == "title":
                # Map title to filename (we use filename as title)
                pass
            elif key == "summary_message_id":
                ps.summary_message_id = value
            elif hasattr(ps, key):
                setattr(ps, key, value)
        ps.updated_at = datetime.utcnow()
        self._db.flush()

    # ----------------------------------------------------------
    # Message CRUD — dual-write
    # ----------------------------------------------------------

    def create_message(
        self,
        session_id: str,
        role: str,
        parts: list[dict],
        model: str | None = None,
    ) -> Message:
        """Write a canonical agent_parts message + display messages.

        This is the core dual-write method.
        """
        from models import PipelineMessage

        now = datetime.utcnow()

        # 1. Write canonical agent_parts message (for engine history reconstruction)
        seq = self._next_sequence(session_id)
        canonical = PipelineMessage(
            session_id=session_id,
            sequence=seq,
            role=self._map_role(role),
            msg_type="agent_parts",
            content="",  # Not used for agent_parts
            meta={"parts": parts, "model": model},
        )
        self._db.add(canonical)
        self._db.flush()

        # 2. Write display messages for frontend
        current_phase = None
        # Try to get current_phase from the session
        from models import PipelineSession
        ps = self._db.query(PipelineSession).filter(PipelineSession.id == session_id).first()
        if ps:
            current_phase = ps.current_phase

        for part in parts:
            ptype = part.get("type", "")
            data = part.get("data", {})

            if ptype == "thinking":
                self._write_display_message(
                    session_id, self._map_role(role), "thought",
                    data.get("thinking", ""),
                    phase=current_phase,
                )
            elif ptype == "text":
                text = data.get("text", "")
                if text:
                    self._write_display_message(
                        session_id, self._map_role(role), "text",
                        text,
                        phase=current_phase,
                    )
            elif ptype == "tool_call":
                tool_name = data.get("name", "")
                tool_args = data.get("args", {})
                content = f"调用工具: {tool_name}"
                self._write_display_message(
                    session_id, "agent", "action",
                    content,
                    phase=current_phase,
                    metadata={"tool_name": tool_name, "tool_args": tool_args},
                )
            elif ptype == "tool_result":
                tool_name = data.get("name", "")
                result_text = data.get("result", "")
                # Truncate very long results for display
                display_text = result_text[:2000] if len(result_text) > 2000 else result_text
                self._write_display_message(
                    session_id, "tool", "observation",
                    display_text,
                    phase=current_phase,
                    metadata={"tool_name": tool_name, "duration_ms": data.get("duration_ms", 0)},
                )
            elif ptype == "finish":
                pass  # No display message for finish part

        self._db.commit()

        return Message(
            id=canonical.id,
            session_id=session_id,
            role=role,
            parts=parts,
            model=model,
            created_at=now.timestamp(),
        )

    def list_messages(self, session_id: str, after_id: int | None = None) -> list[Message]:
        """List canonical agent_parts messages (for engine history reconstruction).

        If after_id is given, returns messages with id >= after_id.
        """
        from models import PipelineMessage

        query = self._db.query(PipelineMessage).filter(
            PipelineMessage.session_id == session_id,
            PipelineMessage.msg_type == "agent_parts",
        )

        if after_id is not None:
            query = query.filter(PipelineMessage.id >= after_id)

        rows = query.order_by(PipelineMessage.sequence).all()

        messages = []
        for row in rows:
            meta = row.meta or {}
            parts = meta.get("parts", [])
            messages.append(Message(
                id=row.id,
                session_id=row.session_id,
                role=self._unmap_role(row.role),
                parts=parts,
                model=meta.get("model"),
                created_at=row.created_at.timestamp() if row.created_at else 0.0,
            ))
        return messages

    # ----------------------------------------------------------
    # Convenience methods (match agent_design/storage.py interface)
    # ----------------------------------------------------------

    def add_user_message(self, session_id: str, text: str) -> Message:
        """Write a user message (canonical + display)."""
        # Also write a user_input display message
        from models import PipelineSession
        ps = self._db.query(PipelineSession).filter(PipelineSession.id == session_id).first()
        phase = ps.current_phase if ps else None
        self._write_display_message(session_id, "user", "user_input", text, phase=phase)
        return self.create_message(session_id, "user", [text_part(text)])

    def add_assistant_message(
        self, session_id: str, parts_list: list[dict], model: str | None = None
    ) -> Message:
        return self.create_message(session_id, "assistant", parts_list, model=model)

    def add_tool_message(
        self, session_id: str, tool_name: str, result: str, duration_ms: int = 0
    ) -> Message:
        return self.create_message(
            session_id, "tool", [tool_result_part(tool_name, result, duration_ms)]
        )

    def update_token_usage(self, session_id: str, prompt_tokens: int, completion_tokens: int):
        """Update token usage — stored in PipelineSession.phase_results for now."""
        from models import PipelineSession
        ps = self._db.query(PipelineSession).filter(PipelineSession.id == session_id).first()
        if ps:
            results = dict(ps.phase_results or {})
            token_usage = results.get("_token_usage", {"prompt": 0, "completion": 0})
            token_usage["prompt"] = token_usage.get("prompt", 0) + prompt_tokens
            token_usage["completion"] = token_usage.get("completion", 0) + completion_tokens
            results["_token_usage"] = token_usage
            ps.phase_results = results
            ps.updated_at = datetime.utcnow()
            self._db.flush()

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _map_role(agent_role: str) -> str:
        """Map agent_design roles to PipelineMessage roles."""
        return {
            "user": "user",
            "assistant": "agent",
            "tool": "tool",
        }.get(agent_role, agent_role)

    @staticmethod
    def _unmap_role(db_role: str) -> str:
        """Map PipelineMessage roles back to agent_design roles."""
        return {
            "user": "user",
            "agent": "assistant",
            "tool": "tool",
            "system": "user",  # System messages treated as user context
        }.get(db_role, db_role)
