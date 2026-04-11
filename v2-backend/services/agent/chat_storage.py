"""
ChatStorage — Storage adapter for AgentSession/AgentMessage models.

Same interface as Storage (for pipeline), but backed by v2_agent_sessions
and v2_agent_messages tables instead of v2_pipeline_sessions/messages.

Dual-write strategy (same as pipeline Storage):
- agent_parts messages: canonical messages for engine history reconstruction
- display messages: user_input / text / action / observation for frontend
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Callable

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


def _extract_bash_summary(result: str) -> str:
    """Generate a concise summary for bash tool results."""
    if not result:
        return "执行命令"
    if "Error" in result:
        return "执行出错"
    if ".xlsx" in result:
        return "生成 Excel 文件"
    if ".csv" in result:
        return "生成 CSV 文件"
    if ".pdf" in result:
        return "生成 PDF 文件"
    # Truncate to first meaningful line
    first_line = result.split("\n")[0].strip()
    return "执行命令" + (f": {first_line[:50]}" if first_line else "")


def _build_tool_summary_map() -> dict[str, str | Callable[[str], str]]:
    """Build tool summary map from auto-discovered TOOL_META.

    Falls back to display_name if no summary is specified.
    Special case: bash uses _extract_bash_summary callable for richer summaries.
    """
    try:
        from services.tools.registry_loader import get_tool_summaries
        summaries = get_tool_summaries()
    except Exception:
        summaries = {}

    # Override bash with callable for richer summaries
    summaries["bash"] = _extract_bash_summary

    return summaries


_TOOL_SUMMARY_MAP: dict[str, str | Callable[[str], str]] = _build_tool_summary_map()


_STRUCTURED_MARKER = "\n__STRUCTURED__\n"


def _extract_structured_data(text: str) -> tuple[str, dict | None]:
    """Extract structured JSON from tool result text.

    Returns (clean_text, parsed_dict_or_None).
    Always strips the __STRUCTURED__ marker from clean_text even on parse failure.
    """
    idx = text.find(_STRUCTURED_MARKER)
    if idx < 0:
        return text, None
    clean = text[:idx]
    json_str = text[idx + len(_STRUCTURED_MARKER):]
    try:
        return clean, json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return clean, None


def _detect_xlsx_in_workspace(tool_name: str, output_text: str, session_id: str) -> str | None:
    """Detect a generated/modified xlsx file from tool output.

    Strategy:
    1. If output mentions a .xlsx filename AND that file exists in workspace → use it
    2. For bash: if output doesn't mention .xlsx but indicates success (exit 0, no error),
       scan workspace for the most recently modified .xlsx file
    Returns filename or None.
    """
    import os
    from core.config import settings

    ws_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
    if not os.path.isdir(ws_dir):
        return None

    # Strategy 1: filename mentioned in output
    fn_match = re.search(r"[\w\u4e00-\u9fff\u3040-\u30ff\-]+\.xlsx", output_text)
    if fn_match:
        _fn = fn_match.group(0)
        if os.path.isfile(os.path.join(ws_dir, _fn)):
            return _fn

    # Strategy 2 (bash only): scan workspace for recently modified xlsx
    # Only trigger when bash succeeded and output hints at file operations
    if tool_name == "bash" and "Exit code: 0" in output_text:
        _HINTS = ("save", "wrote", "生成", "updated", "created", "output", "formula",
                  "tax", "修改", "完成", ".xlsx")
        if any(h in output_text.lower() for h in _HINTS):
            xlsx_files = []
            for f in os.listdir(ws_dir):
                if f.endswith(".xlsx") and not f.startswith("template") and not f.startswith("~"):
                    fpath = os.path.join(ws_dir, f)
                    xlsx_files.append((os.path.getmtime(fpath), f))
            if xlsx_files:
                xlsx_files.sort(reverse=True)
                # Return the most recently modified file
                return xlsx_files[0][1]

    return None


class ChatStorage:
    """AgentSession/AgentMessage-backed storage for the ReAct engine."""

    def __init__(self, db):
        self._db = db

    def _next_sequence(self, session_id: str) -> int:
        from core.models import AgentMessage
        result = self._db.query(AgentMessage.sequence).filter(
            AgentMessage.session_id == session_id,
        ).order_by(AgentMessage.sequence.desc()).first()
        return (result[0] + 1) if result else 1

    def _write_display_message(
        self, session_id: str, role: str, msg_type: str, content: str,
        metadata: dict | None = None,
    ) -> int:
        """Write a display message for frontend rendering and push to SSE queue."""
        from core.models import AgentMessage
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
        from core.models import AgentSession
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
        from core.models import AgentSession
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
        from core.models import AgentMessage

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
                    # Strip internal file-context prefix from display (user shouldn't see it)
                    display_text = text
                    if role == "user" and display_text.startswith("[用户上传了文件:"):
                        # Remove the injected prefix, keep only the user's original message
                        nl_idx = display_text.find("\n\n")
                        if nl_idx > 0:
                            display_text = display_text[nl_idx + 2:]
                    self._write_display_message(
                        session_id, self._map_role(role), display_type, display_text,
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
                    summary_val = _TOOL_SUMMARY_MAP.get(tool_name, f"调用 {tool_name}")
                    # Static string or callable (for bash etc.)
                    summary = summary_val if isinstance(summary_val, str) else summary_val("")
                    self._write_display_message(
                        session_id, "assistant", "action",
                        f"调用工具: {tool_name}",
                        metadata={
                            "tool_name": tool_name,
                            "tool_args": data.get("args", {}),
                            "summary": summary,
                        },
                    )
            elif ptype == "tool_result":
                tool_name = data.get("name", "")
                if tool_name == "think":
                    continue  # Skip think tool result ("[Thought recorded]")
                result_text = data.get("result", "")

                # Extract structured data (upload cards, confirmation, etc.)
                clean_text, upload_data = _extract_structured_data(result_text)

                # P1-2: Don't truncate query_db results — frontend needs full JSON for DataTable
                if tool_name != "query_db" and len(clean_text) > 2000:
                    clean_text = clean_text[:2000] + "..."

                if clean_text.startswith("Error:"):
                    from services.agent.error_utils import parse_tool_error, log_tool_error
                    error_meta = parse_tool_error(clean_text, tool_name)
                    error_meta["duration_ms"] = data.get("duration_ms", 0)
                    log_tool_error(session_id, tool_name, error_meta)
                    self._write_display_message(
                        session_id, "tool", "error_observation",
                        error_meta["user_message"],
                        metadata=error_meta,
                    )
                else:
                    meta = {"tool_name": tool_name, "duration_ms": data.get("duration_ms", 0)}
                    # Dynamic summary for tools with callable summaries (e.g. bash)
                    summary_val = _TOOL_SUMMARY_MAP.get(tool_name)
                    if callable(summary_val):
                        meta["summary"] = summary_val(clean_text)
                    if upload_data:
                        # Ensure card_type for backward compat
                        if "card_type" not in upload_data:
                            _LEGACY = {
                                "resolve_and_validate": "upload_validation",
                                "preview_changes": "upload_preview",
                                "execute_upload": "upload_result",
                            }
                            upload_data["card_type"] = _LEGACY.get(upload_data.get("tool", ""), "unknown")
                        meta["structured_card"] = upload_data
                    elif tool_name in ("bash", "generate_inquiries"):
                        # Detect generated/modified Excel file
                        _detected_file = _detect_xlsx_in_workspace(
                            tool_name, clean_text, session_id
                        )
                        if _detected_file:
                            meta["structured_card"] = {
                                "card_type": "generated_file",
                                "filename": _detected_file,
                                "session_id": session_id,
                            }
                    elif tool_name == "query_db":
                        # Auto-wrap query_db JSON as structured card
                        try:
                            parsed = json.loads(clean_text)
                            if isinstance(parsed.get("columns"), list) and isinstance(parsed.get("rows"), list):
                                meta["structured_card"] = {"card_type": "query_table", **parsed}
                        except (json.JSONDecodeError, ValueError):
                            pass
                    self._write_display_message(
                        session_id, "tool", "observation",
                        clean_text,
                        metadata=meta,
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
        from core.models import AgentMessage

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
        from core.models import AgentMessage

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
        """Accumulate token usage on the session record."""
        try:
            from core.models import AgentSession
            s = self._db.query(AgentSession).filter(AgentSession.id == session_id).first()
            if s:
                usage = dict(s.token_usage or {})
                usage["prompt"] = usage.get("prompt", 0) + prompt_tokens
                usage["completion"] = usage.get("completion", 0) + completion_tokens
                s.token_usage = usage
                self._db.flush()
        except Exception as e:
            logger.debug("update_token_usage failed: %s", e)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _map_role(agent_role: str) -> str:
        return {"user": "user", "assistant": "assistant", "tool": "tool"}.get(agent_role, agent_role)

    @staticmethod
    def _unmap_role(db_role: str) -> str:
        return {"user": "user", "assistant": "assistant", "tool": "tool"}.get(db_role, db_role)
