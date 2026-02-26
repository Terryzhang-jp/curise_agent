"""
In-memory storage for one-shot agent tasks (no DB persistence).

Compatible with the Storage interface used by ReActAgent,
but keeps everything in memory. Suitable for background tasks
like order matching where conversation history doesn't need
to be persisted.
"""

from __future__ import annotations

import time
from services.agent.storage import Session, Message, text_part, tool_result_part


class MemoryStorage:
    """In-memory storage — same interface as Storage, no database writes."""

    def __init__(self, session_id: str = "memory"):
        self._session = Session(
            id=session_id,
            title="order-matching",
            message_count=0,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._messages: list[Message] = []
        self._next_id = 1

    # ----------------------------------------------------------
    # Session operations
    # ----------------------------------------------------------

    def get_session(self, session_id: str) -> Session:
        return self._session

    def update_session(self, session_id: str, **fields):
        for key, value in fields.items():
            if hasattr(self._session, key):
                setattr(self._session, key, value)
        self._session.updated_at = time.time()

    # ----------------------------------------------------------
    # Message CRUD
    # ----------------------------------------------------------

    def create_message(
        self,
        session_id: str,
        role: str,
        parts: list[dict],
        model: str | None = None,
    ) -> Message:
        msg = Message(
            id=self._next_id,
            session_id=session_id,
            role=role,
            parts=parts,
            model=model,
            created_at=time.time(),
        )
        self._next_id += 1
        self._messages.append(msg)
        self._session.message_count = len(self._messages)
        return msg

    def list_messages(self, session_id: str, after_id: int | None = None) -> list[Message]:
        if after_id is not None:
            return [m for m in self._messages if m.id >= after_id]
        return list(self._messages)

    # ----------------------------------------------------------
    # Convenience methods
    # ----------------------------------------------------------

    def add_user_message(self, session_id: str, text_content: str) -> Message:
        return self.create_message(session_id, "user", [text_part(text_content)])

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
        self._session.prompt_tokens += prompt_tokens
        self._session.completion_tokens += completion_tokens
