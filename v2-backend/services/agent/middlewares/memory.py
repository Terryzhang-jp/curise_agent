"""
Memory Middleware — DeerFlow-aligned long-term memory system.

Lifecycle hooks:
  before_agent: Load relevant memories for this user, inject into context
  after_agent:  Extract new memories from conversation via LLM

Memory is per-user (not per-session), enabling cross-session knowledge retention.

Lifecycle management:
  - Per-user hard cap (MAX_MEMORIES_PER_USER)
  - Token budget for injection (MAX_MEMORY_TOKENS)
  - TTL-based auto-expiry (MEMORY_TTL_DAYS)
  - Minimum conversation length to trigger extraction
  - Existing memory dedup via LLM prompt
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

# Hard cap per user — LRU eviction when exceeded
MAX_MEMORIES_PER_USER = 100

# Token budget: approximate max chars for memory injection into system prompt
# ~4 chars per token, 500 tokens budget → 2000 chars
MAX_MEMORY_CHARS = 2000

# Auto-expiry: memories not accessed for this many days get cleaned up
MEMORY_TTL_DAYS = 90

# Minimum conversation length to trigger extraction (skip trivial chats)
MIN_CONVERSATION_LENGTH = 200

# Maximum conversation length to send for extraction
MAX_EXTRACT_CHARS = 8000


# ============================================================
# Extraction prompt
# ============================================================

MEMORY_EXTRACT_PROMPT = """从以下对话中提取值得长期记忆的信息。只提取跨会话有价值的知识，忽略一次性操作细节。

分类规则：
- user_preference: 用户的操作习惯、偏好设置（如"用户喜欢用表格展示数据"）
- supplier_knowledge: 供应商相关的持久知识（如"三祐的交货周期通常是7天"）
- workflow_pattern: 用户常用的工作流程模式（如"用户通常先查询订单再生成询价单"）
- fact: 业务事实（如"横滨港的默认仓库是XX"）

返回 JSON 数组，每项格式：
{{"type": "<类型>", "key": "<简短标识>", "value": "<具体内容>"}}

如果没有值得记忆的内容，返回空数组 []。

规则：
- 不要记忆上传的文件名、临时数据、一次性查询结果
- 不要记忆已经在数据库中可查到的信息（如产品价格）
- 重点记忆用户表达的偏好、习惯和反复出现的模式
- key 要简短唯一（5-15个字），相同含义的知识用相同的 key（实现去重）

{existing_memories}

对话内容：
{conversation}"""


# ============================================================
# Middleware
# ============================================================

class MemoryMiddleware(Middleware):
    """Long-term memory: load before agent, extract after agent.

    Requires ctx to have:
      - ctx.db: SQLAlchemy session
      - ctx.user_id: int (the current user)
      - ctx.session_id: str
      - ctx.memory_text: str (set by this middleware for prompt injection)
    """

    def __init__(self, provider_factory=None):
        """
        Args:
            provider_factory: Optional callable() -> LLMProvider for async extraction.
                If None, memory extraction is skipped (read-only mode).
        """
        self._provider_factory = provider_factory

    def before_agent(self, user_message: str, ctx: Any) -> str:
        """Load user's memories and attach to ctx for prompt injection."""
        db = getattr(ctx, 'db', None)
        user_id = getattr(ctx, 'user_id', None)
        if not db or not user_id:
            return user_message

        try:
            # Auto-cleanup expired memories first (lightweight, periodic)
            _cleanup_expired(db, user_id)

            memories = _load_memories(db, user_id)
            if memories:
                ctx.memory_text = _format_memories(memories)
                _touch_memories(db, [m['id'] for m in memories])
            else:
                ctx.memory_text = ""
        except Exception as e:
            logger.warning("MemoryMiddleware.before_agent failed: %s", e)
            ctx.memory_text = ""

        return user_message

    def after_agent(self, final_answer: str, ctx: Any) -> str:
        """Extract memories from conversation asynchronously (non-blocking)."""
        if self._provider_factory is None:
            return final_answer

        user_id = getattr(ctx, 'user_id', None)
        session_id = getattr(ctx, 'session_id', None)
        conversation_log = getattr(ctx, '_conversation_log', None)

        if not user_id or not conversation_log:
            return final_answer

        # Skip trivial conversations (e.g. "你好" → "你好！有什么可以帮你的？")
        if len(conversation_log) < MIN_CONVERSATION_LENGTH:
            logger.debug("MemoryMiddleware: conversation too short (%d chars), skipping extraction",
                         len(conversation_log))
            return final_answer

        # Fire-and-forget: extract in background thread (uses its own DB session)
        threading.Thread(
            target=_extract_and_save,
            args=(self._provider_factory, user_id, session_id, conversation_log),
            daemon=True,
        ).start()

        return final_answer


# ============================================================
# DB Operations
# ============================================================

def _load_memories(db, user_id: int, limit: int = 30) -> list[dict]:
    """Load most relevant memories for a user (recent + frequently accessed)."""
    from sqlalchemy import text
    result = db.execute(text("""
        SELECT id, memory_type, key, value
        FROM v2_agent_memories
        WHERE user_id = :uid
        ORDER BY
            COALESCE(last_accessed_at, created_at) DESC,
            access_count DESC
        LIMIT :lim
    """), {"uid": user_id, "lim": limit})
    return [dict(row._mapping) for row in result]


def _touch_memories(db, memory_ids: list[int]):
    """Update access_count and last_accessed_at for loaded memories.

    Uses a separate short-lived connection to avoid polluting the main
    agent db session's transaction state.
    """
    if not memory_ids:
        return
    try:
        from core.database import SessionLocal
        touch_db = SessionLocal()
        try:
            from sqlalchemy import text
            touch_db.execute(text("""
                UPDATE v2_agent_memories
                SET access_count = access_count + 1,
                    last_accessed_at = NOW()
                WHERE id = ANY(:ids)
            """), {"ids": memory_ids})
            touch_db.commit()
        finally:
            touch_db.close()
    except Exception as e:
        logger.debug("Failed to touch memories: %s", e)


def _cleanup_expired(db, user_id: int):
    """Remove memories that haven't been accessed for MEMORY_TTL_DAYS.

    Lightweight: uses the main db session but only runs a single DELETE.
    Called on every before_agent but the DELETE is fast (indexed).
    """
    try:
        from sqlalchemy import text
        from core.database import SessionLocal
        cleanup_db = SessionLocal()
        try:
            result = cleanup_db.execute(text("""
                DELETE FROM v2_agent_memories
                WHERE user_id = :uid
                  AND COALESCE(last_accessed_at, created_at) < NOW() - INTERVAL ':ttl days'
            """.replace(":ttl", str(MEMORY_TTL_DAYS))), {"uid": user_id})
            if result.rowcount > 0:
                logger.info("MemoryMiddleware: cleaned up %d expired memories for user %d",
                            result.rowcount, user_id)
            cleanup_db.commit()
        finally:
            cleanup_db.close()
    except Exception as e:
        logger.debug("Memory cleanup failed: %s", e)


def _format_memories(memories: list[dict]) -> str:
    """Format memories into prompt-injectable text, respecting token budget."""
    if not memories:
        return ""

    grouped: dict[str, list[str]] = {}
    type_labels = {
        "user_preference": "用户偏好",
        "supplier_knowledge": "供应商知识",
        "workflow_pattern": "工作流模式",
        "fact": "业务事实",
    }

    for m in memories:
        label = type_labels.get(m['memory_type'], m['memory_type'])
        grouped.setdefault(label, []).append(f"- {m['key']}: {m['value']}")

    lines = ["<memory>"]
    total_chars = 10  # <memory> + </memory> tags
    for label, items in grouped.items():
        header = f"### {label}"
        total_chars += len(header) + 1
        if total_chars > MAX_MEMORY_CHARS:
            break
        lines.append(header)
        for item in items:
            total_chars += len(item) + 1
            if total_chars > MAX_MEMORY_CHARS:
                lines.append(f"- ...({len(items) - items.index(item)} 条省略)")
                break
            lines.append(item)
    lines.append("</memory>")

    return "\n".join(lines)


def _save_memories(db, user_id: int, session_id: str | None, memories: list[dict]):
    """Upsert memories — update existing or insert new."""
    from sqlalchemy import text

    for mem in memories:
        mtype = mem.get("type", "fact")
        key = mem.get("key", "")
        value = mem.get("value", "")
        if not key or not value:
            continue
        # Enforce key length limit for dedup consistency
        key = key[:200]
        value = value[:2000]

        # Upsert: update if same (user_id, memory_type, key) exists
        db.execute(text("""
            INSERT INTO v2_agent_memories (user_id, memory_type, key, value, source_session_id)
            VALUES (:uid, :mtype, :key, :val, :sid)
            ON CONFLICT (user_id, memory_type, key)
            DO UPDATE SET
                value = EXCLUDED.value,
                source_session_id = EXCLUDED.source_session_id,
                updated_at = NOW()
        """), {"uid": user_id, "mtype": mtype, "key": key, "val": value, "sid": session_id})

    db.commit()

    # Enforce per-user memory cap — evict least-used oldest
    count_result = db.execute(text(
        "SELECT COUNT(*) FROM v2_agent_memories WHERE user_id = :uid"
    ), {"uid": user_id}).scalar()

    if count_result and count_result > MAX_MEMORIES_PER_USER:
        excess = count_result - MAX_MEMORIES_PER_USER
        db.execute(text("""
            DELETE FROM v2_agent_memories
            WHERE id IN (
                SELECT id FROM v2_agent_memories
                WHERE user_id = :uid
                ORDER BY access_count ASC, COALESCE(last_accessed_at, created_at) ASC
                LIMIT :excess
            )
        """), {"uid": user_id, "excess": excess})
        db.commit()


# ============================================================
# Async Memory Extraction
# ============================================================

def _extract_and_save(provider_factory, user_id: int,
                      session_id: str | None, conversation_log: str):
    """Background thread: use LLM to extract memories, then save to DB."""
    try:
        from core.database import SessionLocal
        thread_db = SessionLocal()

        try:
            # Truncate conversation if too long
            conv = conversation_log
            if len(conv) > MAX_EXTRACT_CHARS:
                conv = conv[:MAX_EXTRACT_CHARS] + "\n...(截断)"

            # Load existing memories so LLM can dedup
            existing = _load_memories(thread_db, user_id, limit=50)
            existing_hint = ""
            if existing:
                existing_keys = [f"  - [{m['memory_type']}] {m['key']}: {m['value'][:60]}"
                                 for m in existing[:20]]
                existing_hint = (
                    "用户已有以下记忆（请勿重复，如果新信息更新了旧记忆则用相同 key 覆盖）：\n"
                    + "\n".join(existing_keys)
                )

            prompt = MEMORY_EXTRACT_PROMPT.format(
                conversation=conv,
                existing_memories=existing_hint,
            )

            provider = provider_factory()
            history = [provider.build_user_message(prompt)]
            resp = provider.generate(history)

            text = "\n".join(resp.text_parts) if resp.text_parts else ""
            if not text.strip():
                return

            # Parse JSON from response (handle markdown code blocks)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            memories = json.loads(text)
            if not isinstance(memories, list):
                return

            # Filter: only allow known types
            valid_types = {"user_preference", "supplier_knowledge", "workflow_pattern", "fact"}
            memories = [m for m in memories if m.get("type") in valid_types]

            if memories:
                _save_memories(thread_db, user_id, session_id, memories)
                logger.info("MemoryMiddleware: extracted %d memories for user %d",
                            len(memories), user_id)

        finally:
            thread_db.close()

    except json.JSONDecodeError:
        logger.debug("MemoryMiddleware: LLM returned non-JSON, skipping extraction")
    except Exception as e:
        logger.warning("MemoryMiddleware: extraction failed: %s", e)
