"""
ChatStorage — Storage adapter for AgentSession/AgentMessage models.

Same interface as Storage (for pipeline), but backed by v2_agent_sessions
and v2_agent_messages tables instead of v2_pipeline_sessions/messages.

Dual-write strategy (same as pipeline Storage):
- agent_parts messages: canonical messages for engine history reconstruction
- display messages: user_input / text / action / observation for frontend
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import time

from services.agent.storage import Session, Message, text_part, tool_result_part
from services.agent.stream_queue import push_event

logger = logging.getLogger(__name__)


# ─── Summary helpers ─────────────────────────────────────────

def _generate_summary(text: str, max_len: int = 60) -> str:
    """Extract first sentence of thinking text as a summary (no LLM call)."""
    if not text:
        return "推理过程"
    # Try splitting by sentence-ending punctuation or newline
    for sep in ("。", ".\n", "\n"):
        idx = text.find(sep)
        if 0 < idx <= max_len:
            return text[:idx].strip()
    # Fallback: truncate
    if len(text) <= max_len:
        return text.strip()
    return text[:50].strip() + "..."


_TOOL_SUMMARY_MAP: dict[str, str] = {
    "query_db": "查询数据库",
    "get_db_schema": "获取表结构",
    "think": "思考",
    "calculate": "数学计算",
    "get_current_time": "获取当前时间",
    "todo_write": "更新任务清单",
    "todo_read": "读取任务清单",
    "use_skill": "调用技能",
    "web_fetch": "获取网页内容",
    "search_product_database": "搜索产品数据库",
    "get_order_overview": "查看订单概览",
    "generate_order_inquiry": "生成询价Excel",
    "parse_price_list": "解析价格表",
    "resolve_references": "查找ID引用",
    "check_existing_products": "比对现有产品",
    "execute_product_upload": "执行产品导入",
    "get_order_fulfillment": "查看履约状态",
    "update_order_fulfillment": "更新履约状态",
    "record_delivery_receipt": "记录交货验收",
    "attach_order_file": "附加订单文件",
}


class ChatStorage:
    """AgentSession/AgentMessage-backed storage for the ReAct engine."""

    def __init__(self, db):
        self._db = db

    def _next_sequence(self, session_id: str) -> int:
        from models import AgentMessage
        result = self._db.query(AgentMessage.sequence).filter(
            AgentMessage.session_id == session_id,
        ).order_by(AgentMessage.sequence.desc()).first()
        return (result[0] + 1) if result else 1

    def _write_display_message(
        self, session_id: str, role: str, msg_type: str, content: str,
        metadata: dict | None = None,
    ) -> int:
        """Write a display message for frontend rendering and push to SSE queue."""
        from models import AgentMessage
        seq = self._next_sequence(session_id)
        msg = AgentMessage(
            session_id=session_id,
            sequence=seq,
            role=role,
            msg_type=msg_type,
            content=content,
            meta=metadata,
        )
        self._db.add(msg)
        self._db.flush()

        # Push to SSE queue for real-time delivery
        event_data = {
            "id": msg.id,
            "role": role,
            "content": content,
            "msg_type": msg_type,
            "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat(),
        }
        if metadata:
            event_data["metadata"] = metadata
        push_event(session_id, {"type": "message", "data": event_data})

        return msg.id

    # ----------------------------------------------------------
    # Session operations
    # ----------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        from models import AgentSession
        s = self._db.query(AgentSession).filter(AgentSession.id == session_id).first()
        if s is None:
            return None
        return Session(
            id=s.id,
            title=s.title or "",
            summary_message_id=s.summary_message_id,
            created_at=s.created_at.timestamp() if s.created_at else 0.0,
            updated_at=s.updated_at.timestamp() if s.updated_at else 0.0,
        )

    def update_session(self, session_id: str, **fields):
        from models import AgentSession
        s = self._db.query(AgentSession).filter(AgentSession.id == session_id).first()
        if not s:
            return
        if "summary_message_id" in fields:
            s.summary_message_id = fields["summary_message_id"]
        if "title" in fields:
            s.title = fields["title"]
        s.updated_at = datetime.utcnow()
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
        from models import AgentMessage

        now = datetime.utcnow()

        # 1. Write canonical agent_parts message (for engine history)
        seq = self._next_sequence(session_id)
        canonical = AgentMessage(
            session_id=session_id,
            sequence=seq,
            role=self._map_role(role),
            msg_type="agent_parts",
            content="",
            meta={"parts": parts, "model": model},
        )
        self._db.add(canonical)
        self._db.flush()

        # 2. Write display messages for frontend
        for part in parts:
            ptype = part.get("type", "")
            data = part.get("data", {})

            if ptype == "text":
                text = data.get("text", "")
                if text:
                    # Fix 1: user text parts use "user_input" msg_type
                    display_type = "user_input" if role == "user" else "text"
                    self._write_display_message(
                        session_id, self._map_role(role), display_type, text,
                    )
            elif ptype == "tool_call":
                tool_name = data.get("name", "")
                if tool_name == "think":
                    # Show think tool content as a thinking message
                    thought = data.get("args", {}).get("thought", "")
                    if thought:
                        self._write_display_message(
                            session_id, "assistant", "thinking", thought,
                            metadata={"summary": _generate_summary(thought)},
                        )
                else:
                    self._write_display_message(
                        session_id, "assistant", "action",
                        f"调用工具: {tool_name}",
                        metadata={
                            "tool_name": tool_name,
                            "tool_args": data.get("args", {}),
                            "summary": _TOOL_SUMMARY_MAP.get(tool_name, f"调用 {tool_name}"),
                        },
                    )
            elif ptype == "tool_result":
                tool_name = data.get("name", "")
                if tool_name == "think":
                    continue  # Skip think tool result ("[Thought recorded]")
                result_text = data.get("result", "")
                # P1-2: Don't truncate query_db results — frontend needs full JSON for DataTable
                if tool_name != "query_db" and len(result_text) > 2000:
                    result_text = result_text[:2000] + "..."

                if result_text.startswith("Error:"):
                    from services.agent.error_utils import parse_tool_error, log_tool_error
                    error_meta = parse_tool_error(result_text, tool_name)
                    error_meta["duration_ms"] = data.get("duration_ms", 0)
                    log_tool_error(session_id, tool_name, error_meta)
                    self._write_display_message(
                        session_id, "tool", "error_observation",
                        error_meta["user_message"],
                        metadata=error_meta,
                    )
                else:
                    self._write_display_message(
                        session_id, "tool", "observation",
                        result_text,
                        metadata={"tool_name": tool_name, "duration_ms": data.get("duration_ms", 0)},
                    )
            elif ptype == "thinking":
                # Gemini native thinking output
                # Fix 4: thinking_part() stores {"thinking": text}, not {"text": text}
                thought_text = data.get("thinking", "") or data.get("text", "")
                if thought_text:
                    self._write_display_message(
                        session_id, "assistant", "thinking", thought_text,
                        metadata={"summary": _generate_summary(thought_text)},
                    )

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
        """List canonical agent_parts messages (for engine history)."""
        from models import AgentMessage

        query = self._db.query(AgentMessage).filter(
            AgentMessage.session_id == session_id,
            AgentMessage.msg_type == "agent_parts",
        )

        if after_id is not None:
            query = query.filter(AgentMessage.id >= after_id)

        rows = query.order_by(AgentMessage.sequence).all()

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
    # Convenience methods (match Storage interface)
    # ----------------------------------------------------------

    def add_user_message(self, session_id: str, text: str) -> Message:
        # Fix 1: removed separate _write_display_message call here.
        # create_message() now writes user_input display message via the
        # text part handler (role=="user" → msg_type="user_input").
        return self.create_message(session_id, "user", [text_part(text)])

    def add_assistant_message(
        self, session_id: str, parts_list: list[dict], model: str | None = None
    ) -> Message:
        return self.create_message(session_id, "assistant", parts_list, model=model)

    def stream_final_answer(
        self,
        session_id: str,
        parts_list: list[dict],
        final_text: str,
        model: str | None = None,
    ) -> Message:
        """Write final answer to DB and stream tokens via queue.

        - Writes canonical agent_parts to DB (persistence)
        - Writes full text display message to DB (persistence)
        - Pushes token events through SSE queue (streaming)
        - Pushes token_done event (finality)
        """
        from models import AgentMessage

        now = datetime.utcnow()

        # 1. Write canonical agent_parts message
        seq = self._next_sequence(session_id)
        canonical = AgentMessage(
            session_id=session_id,
            sequence=seq,
            role="assistant",
            msg_type="agent_parts",
            content="",
            meta={"parts": parts_list, "model": model},
        )
        self._db.add(canonical)
        self._db.flush()

        # 2. Write thinking display messages (non-text parts)
        for part in parts_list:
            ptype = part.get("type", "")
            data = part.get("data", {})
            if ptype == "thinking":
                thought_text = data.get("thinking", "") or data.get("text", "")
                if thought_text:
                    self._write_display_message(
                        session_id, "assistant", "thinking", thought_text,
                        metadata={"summary": _generate_summary(thought_text)},
                    )

        # 3. Write full text display message to DB (for persistence / page reload)
        seq2 = self._next_sequence(session_id)
        text_msg = AgentMessage(
            session_id=session_id,
            sequence=seq2,
            role="assistant",
            msg_type="text",
            content=final_text,
        )
        self._db.add(text_msg)
        self._db.flush()
        msg_id = text_msg.id
        created_at = text_msg.created_at.isoformat() if text_msg.created_at else now.isoformat()

        self._db.commit()

        # 4. Stream tokens via queue (no DB write per token — just SSE events)
        #    Sleep between pushes so browser receives separate TCP chunks.
        chunk_size = 4
        for i in range(0, len(final_text), chunk_size):
            chunk = final_text[i : i + chunk_size]
            push_event(session_id, {
                "type": "token",
                "data": {
                    "content": chunk,
                    "msg_id": msg_id,
                    "role": "assistant",
                    "msg_type": "text",
                },
            })
            time.sleep(0.02)  # 20ms → ~200 chars/sec, visually smooth

        # 5. Token stream done
        push_event(session_id, {
            "type": "token_done",
            "data": {
                "msg_id": msg_id,
                "full_content": final_text,
                "created_at": created_at,
            },
        })

        return Message(
            id=canonical.id,
            session_id=session_id,
            role="assistant",
            parts=parts_list,
            model=model,
            created_at=now.timestamp(),
        )

    def update_token_usage(self, session_id: str, prompt_tokens: int, completion_tokens: int):
        pass  # No-op for chat sessions

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _map_role(agent_role: str) -> str:
        return {"user": "user", "assistant": "assistant", "tool": "tool"}.get(agent_role, agent_role)

    @staticmethod
    def _unmap_role(db_role: str) -> str:
        return {"user": "user", "assistant": "assistant", "tool": "tool"}.get(db_role, db_role)
