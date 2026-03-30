"""
Chat endpoints — general-purpose AI assistant conversations.

Uses the ReAct agent engine with query_db + get_db_schema tools.
SSE streaming for real-time message delivery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime
from queue import Empty

from fastapi import APIRouter, Depends, HTTPException, Query, Form, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from config import settings
from database import get_db, SessionLocal
from models import AgentSession, AgentMessage, User
from routes.auth import get_current_user
from security import require_role
from services.agent.stream_queue import (
    get_or_create_queue, get_queue, remove_queue, push_event,
    get_or_create_cancel_event, set_cancelled, remove_cancel_event,
)

require_chat_user = require_role("superadmin", "admin", "employee")

UPLOAD_DIR = settings.UPLOAD_DIR
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".pdf", ".csv", ".jpg", ".jpeg", ".png", ".webp"}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])





# ─── Schemas ──────────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    content: str


class ChatSessionCreate(BaseModel):
    title: str = "新对话"


# ─── ReAct Agent Factory ─────────────────────────────────────

def _load_enabled_tools(db: DBSession) -> set[str] | None:
    """Load enabled tool names from DB. Returns None if no config rows exist (backward compat)."""
    from models import ToolConfig
    count = db.query(ToolConfig).count()
    if count == 0:
        return None  # No config yet — register all defaults
    rows = db.query(ToolConfig.tool_name).filter(ToolConfig.is_enabled == True).all()
    return {r[0] for r in rows}


def _load_skills_into_ctx(db: DBSession, ctx):
    """Load skills: filesystem first (base), then DB overlay (user wins).

    Order matters: scan_skills() calls skills.clear(), so we must call it
    BEFORE loading DB skills. DB skills have higher priority and can override
    filesystem skills of the same name.

    Finally, remove any filesystem skill that has a DB entry with is_enabled=False.
    """
    import os
    from models import SkillConfig
    from services.agent.tool_context import SkillDef

    # 1. Filesystem skills first (scan_skills clears then populates)
    # Check two possible locations: inside app dir (for Cloud Run) and parent dir (legacy)
    app_dir = os.path.dirname(os.path.dirname(__file__))  # v2-backend/
    skills_candidates = [
        os.path.join(app_dir, "skills"),            # v2-backend/skills/ (Cloud Run)
        os.path.join(app_dir, "..", "skills"),       # curise_agent/skills/ (legacy)
    ]
    extra = [d for d in skills_candidates if os.path.isdir(d)]
    ctx.scan_skills(extra_paths=extra or None)

    # 2. DB skills — enabled ones override filesystem, disabled ones remove filesystem entries
    all_db_skills = db.query(SkillConfig).all()
    for s in all_db_skills:
        if s.is_enabled and s.content:
            # Override or add
            ctx.skills[s.name] = SkillDef(
                name=s.name,
                description=s.description or "",
                body=s.content,
                source_path=f"db:skill:{s.id}",
                references_dir=None,
            )
        elif not s.is_enabled:
            # Explicitly disabled in DB — remove from ctx even if from filesystem
            ctx.skills.pop(s.name, None)


def _build_system_prompt(enabled_tools: set[str] | None, ctx,
                         scenario: str | None = None,
                         registered_tool_names: set[str] | None = None) -> str:
    """Build the chat system prompt using layered prompt assembly."""
    from services.agent.prompts import build_chat_prompt, PromptContext

    prompt_ctx = PromptContext(
        enabled_tools=enabled_tools,
        skill_summary=ctx.get_skill_list_summary(),
        scenario=scenario,
        registered_tool_names=registered_tool_names,
        memory_text=getattr(ctx, 'memory_text', ''),  # DeerFlow: memory injection
    )
    return build_chat_prompt(prompt_ctx)


def _create_chat_agent(session_id: str, db: DBSession, file_bytes: bytes | None = None,
                       scenario: str | None = None, user_role: str = "employee",
                       user_id: int | None = None):
    """Create a ReAct agent configured for chat with general-purpose + query tools.

    DeerFlow 2.0 aligned middleware chain (16 middlewares → 10 for our use case):
      1. MemoryMiddleware       — before_agent: load memories; after_agent: extract
      2. SqlReadOnlyHook        — before_tool: block write SQL
      3. GuardrailMiddleware    — before_tool: enhanced bash + indirect exec blocking
      4. SubagentLimitMiddleware— after_model: cap concurrent delegates; before_tool: block recursion
      5. ClarificationMiddleware— after_tool: intercept ask_clarification → HITL pause
      6. ErrorRecoveryMiddleware— after_tool: consecutive error tracking
      7. OutputSanitizationHook — after_tool: redact PII
      8. SummarizationMiddleware— after_model/before_model: flag for context compact
      9. LoopDetectionMiddleware— after_model: detect and break loops (LAST model hook)
    """
    from services.agent.config import LLMConfig
    from services.agent.chat_storage import ChatStorage
    from services.agent.tool_context import ToolContext
    from services.agent.engine import ReActAgent
    from services.tools import create_chat_registry
    from config import settings

    # Provider — Kimi K2.5 (93% tool calling accuracy, OpenAI-compatible)
    # Fallback to Gemini if no MOONSHOT_API_KEY configured
    moonshot_key = getattr(settings, 'MOONSHOT_API_KEY', '') or os.getenv('MOONSHOT_API_KEY', '')
    if moonshot_key:
        from services.agent.llm.kimi_provider import KimiProvider
        llm_config = LLMConfig(provider="kimi", model_name="kimi-k2.5", api_key=moonshot_key)
        provider = KimiProvider(llm_config)
    else:
        from services.agent.llm.gemini_provider import GeminiProvider
        llm_config = LLMConfig(api_key=settings.GOOGLE_API_KEY)
        provider = GeminiProvider(llm_config)

    # Storage (uses AgentSession/AgentMessage)
    storage = ChatStorage(db)

    # Load enabled tools from DB
    enabled_tools = _load_enabled_tools(db)

    # Workspace for generated files (bash tool defaults cwd here)
    workspace_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
    os.makedirs(workspace_dir, exist_ok=True)

    # Restore persisted files from Supabase (e.g., after server restart)
    try:
        from services.workspace_manager import restore_workspace
        restored = restore_workspace(session_id, workspace_dir)
        if restored:
            logger.info("Restored %d file(s) for session %s: %s",
                         len(restored), session_id, restored)
    except Exception as e:
        logger.debug("Workspace restore skipped: %s", e)

    # Tools — general-purpose + business query tools
    ctx = ToolContext(db=db, file_bytes=file_bytes, pipeline_session_id=session_id,
                      workspace_dir=workspace_dir,
                      user_id=user_id, session_id=session_id)

    # Tracer: token + tool performance tracking
    from services.agent.tracer import AgentTracer
    ctx.tracer = AgentTracer(db, session_id)

    # Load skills from DB + filesystem
    _load_skills_into_ctx(db, ctx)

    # DeerFlow-aligned: ALL tools always registered, scenario only affects prompt
    # No more tool whitelist filtering — tools never "disappear"
    registry = create_chat_registry(ctx)

    # Role-based permissions
    if user_role == "employee":
        registry.set_permissions([
            {"tool": "bash", "permission": "deny"},
            {"tool": "execute_upload", "permission": "deny"},
            {"tool": "*", "permission": "allow"},
        ])
    elif user_role == "admin":
        registry.set_permissions([
            {"tool": "bash", "permission": "deny"},
            {"tool": "*", "permission": "allow"},
        ])
    # superadmin: default all allow

    # ─── Middleware chain (DeerFlow 2.0 aligned, order-dependent) ───
    from services.agent.hooks import MiddlewareChain, SqlReadOnlyHook, OutputSanitizationHook
    from services.agent.middlewares.memory import MemoryMiddleware
    from services.agent.middlewares.guardrail import GuardrailMiddleware, DefaultGuardrailProvider
    from services.agent.middlewares.subagent_limit import SubagentLimitMiddleware
    from services.agent.middlewares.clarification import ClarificationMiddleware
    from services.agent.middlewares.error_recovery import ErrorRecoveryMiddleware
    from services.agent.middlewares.summarization import SummarizationMiddleware
    from services.agent.middlewares.loop_detection import LoopDetectionMiddleware
    from services.agent.middlewares.completion_verification import CompletionVerificationMiddleware
    from services.agent.middlewares.workspace_state import WorkspaceStateMiddleware

    # Memory provider factory — uses same provider as main agent (lightweight call)
    def _memory_provider_factory():
        from services.agent.config import LLMConfig as _LC, create_provider as _cp
        _moonshot = getattr(settings, 'MOONSHOT_API_KEY', '') or os.getenv('MOONSHOT_API_KEY', '')
        if _moonshot:
            _cfg = _LC(provider="kimi", model_name="kimi-k2.5", api_key=_moonshot,
                        thinking_budget=0)
        else:
            _cfg = _LC(model_name="gemini-2.0-flash", api_key=settings.GOOGLE_API_KEY,
                        thinking_budget=0)
        p = _cp(_cfg)
        # Must configure with a non-empty system prompt (Kimi rejects empty system messages)
        p.configure("Extract memories from conversation.", [], 0)
        return p

    hooks = MiddlewareChain([
        # 0. Workspace state: inject file listing before every LLM call
        #    (DeerFlow UploadsMiddleware pattern — filesystem as ground truth)
        WorkspaceStateMiddleware(),
        # 1. Memory: load before agent, extract after agent
        MemoryMiddleware(provider_factory=_memory_provider_factory),
        # 2. SQL safety
        SqlReadOnlyHook(),
        # 3. Enhanced guardrails (replaces BashGuardrailHook with indirect exec detection)
        GuardrailMiddleware(DefaultGuardrailProvider()),
        # 4. Sub-agent governance: concurrency cap + recursion block
        SubagentLimitMiddleware(max_concurrent=3),
        # 5. Clarification: intercept ask_clarification → HITL pause
        ClarificationMiddleware(),
        # 6. Error recovery
        ErrorRecoveryMiddleware(),
        # 7. PII sanitization
        OutputSanitizationHook(),
        # 8. Summarization: flag for context compact
        SummarizationMiddleware(token_threshold=80000, message_threshold=40),
        # 9. Loop detection (must see final response state)
        LoopDetectionMiddleware(),
        # 10. Completion verification (LAST — checks final answer for fabrication)
        CompletionVerificationMiddleware(),
    ])
    registry.set_hooks(hooks)
    registry.set_ctx(ctx)

    # Build dynamic system prompt AFTER registry (knows registered_tool_names)
    # DeerFlow: inject memory into prompt context
    system_prompt = _build_system_prompt(
        None, ctx, scenario=scenario,
        registered_tool_names=set(registry.names()),
    )

    # Compact threshold: adapt to model's context window
    # Anthropic: compact at ~80% capacity, not a fixed number
    # Kimi K2.5: 128K context → 100K threshold (78%)
    # Gemini:    1M context   → 80K threshold (8%, conservative)
    compact_threshold = 100_000 if moonshot_key else 80_000

    # Agent
    agent = ReActAgent(
        provider=provider,
        storage=storage,
        registry=registry,
        ctx=ctx,
        pipeline_session_id=session_id,
        system_prompt=system_prompt,
        max_turns=25,
        thinking_budget=2048,
        verbose=True,
    )
    agent._compact_threshold = compact_threshold

    return agent


# ─── Session CRUD ─────────────────────────────────────────────

@router.post("/sessions")
def create_session(
    body: ChatSessionCreate,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Create a new chat session."""
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=body.title,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.get("/sessions")
def list_sessions(
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """List all chat sessions for current user."""
    sessions = (
        db.query(AgentSession)
        .filter(AgentSession.user_id == current_user.id)
        .order_by(AgentSession.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Get a chat session."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Delete a chat session."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")
    db.delete(session)
    db.commit()
    return {"detail": "已删除"}


# ─── Messages ─────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages")
def get_messages(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Get all display messages in a chat session."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    messages = (
        db.query(AgentMessage)
        .filter(
            AgentMessage.session_id == session_id,
            AgentMessage.msg_type != "agent_parts",  # Skip canonical engine messages
        )
        .order_by(AgentMessage.sequence)
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "msg_type": m.msg_type,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            **({"metadata": m.meta} if m.meta and m.msg_type in ("error_observation", "error", "action", "observation", "thinking") else {}),
        }
        for m in messages
    ]


# ─── Send + SSE Stream ───────────────────────────────────────

@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str,
    content: str = Form(...),
    file: UploadFile | None = File(None),
    scenario: str = Form(""),
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Send a message — starts ReAct agent in background, returns immediately.

    Accepts multipart form data with optional file attachment.
    """
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    # Handle optional file upload
    file_bytes = None
    file_url = None
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"不支持的文件类型: {ext}。支持: {', '.join(ALLOWED_EXTENSIONS)}")
        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(400, "文件大小不能超过 20 MB")
        # Save to Supabase Storage
        from services.file_storage import storage
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        file_url = storage.upload("chat", safe_name, file_content)
        file_bytes = file_content

        # Bridge: save uploaded file to workspace so Agent's bash can access it
        from config import settings
        ws_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
        os.makedirs(ws_dir, exist_ok=True)
        ws_path = os.path.join(ws_dir, file.filename)
        with open(ws_path, "wb") as wf:
            wf.write(file_content)
        logger.info("Uploaded file saved to workspace: %s", ws_path)

    # Record the current max display message ID (baseline for SSE)
    from sqlalchemy import func
    last_id = db.query(func.max(AgentMessage.id)).filter(
        AgentMessage.session_id == session_id,
        AgentMessage.msg_type != "agent_parts",
    ).scalar() or 0

    # Mark session as processing
    session.status = "processing"
    session.updated_at = datetime.utcnow()

    # Auto-update title from first user message
    existing_count = db.query(AgentMessage).filter(
        AgentMessage.session_id == session_id,
        AgentMessage.role == "user",
    ).count()
    if existing_count == 0:
        title = content[:50]
        if len(content) > 50:
            title += "..."
        session.title = title

    db.commit()

    # Create queue and cancel event BEFORE launching thread
    get_or_create_queue(session_id)
    cancel_event = get_or_create_cancel_event(session_id)
    cancel_event.clear()  # Reset in case previous run left it set

    # Inject uploaded file context into user message so Agent knows about it
    agent_message = content
    if file and file.filename:
        agent_message = f"[用户上传了文件: {file.filename}，已保存到工作目录]\n\n{content}"

    # Extract user role for permission control
    user_role = getattr(current_user, "role", "employee") or "employee"

    # Auto-detect intent — with session-level persistence
    # Anthropic pattern: scenario context survives HITL pause/resume
    resolved_scenario = scenario.strip() or None
    if not resolved_scenario:
        from services.agent.scenarios import detect_intent
        resolved_scenario = detect_intent(content, has_file=bool(file_bytes))

    # If no scenario detected, inherit from session (HITL resume, follow-up messages)
    if not resolved_scenario:
        prev_ctx = session.context_data or {}
        resolved_scenario = prev_ctx.get("last_scenario")

    # Persist scenario to session for future messages
    if resolved_scenario:
        from sqlalchemy.orm.attributes import flag_modified
        ctx_data = session.context_data or {}
        ctx_data["last_scenario"] = resolved_scenario
        session.context_data = ctx_data
        flag_modified(session, "context_data")
        db.commit()

    # Launch agent in background thread (pass user_id for memory system)
    threading.Thread(
        target=_run_chat_agent,
        args=(session_id, agent_message),
        kwargs={"file_bytes": file_bytes, "scenario": resolved_scenario,
                "cancel_event": cancel_event, "user_role": user_role,
                "user_id": current_user.id},
        daemon=True,
    ).start()

    return {"status": "processing", "session_id": session_id, "last_msg_id": last_id}


@router.get("/sessions/{session_id}/stream")
async def stream_messages(
    session_id: str,
    after_id: int = Query(0, description="Only return messages after this ID"),
    current_user: User = Depends(require_chat_user),
):
    """SSE stream — pushes new display messages in real-time while agent processes.

    Phase 1: Flush any missed messages from DB (id > after_id).
    Phase 2: Read events from the in-memory queue until done.
    """

    async def event_generator():
        loop = asyncio.get_event_loop()
        seen_ids: set[int] = set()  # Track message IDs sent in Phase 1

        # Phase 1: catch-up — flush missed messages from DB
        poll_db = SessionLocal()
        try:
            new_msgs = (
                poll_db.query(AgentMessage)
                .filter(
                    AgentMessage.session_id == session_id,
                    AgentMessage.msg_type != "agent_parts",
                    AgentMessage.id > after_id,
                )
                .order_by(AgentMessage.sequence)
                .all()
            )
            for msg in new_msgs:
                seen_ids.add(msg.id)
                msg_data = {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "msg_type": msg.msg_type,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                if msg.meta and msg.msg_type in ("error_observation", "error", "action", "observation", "thinking"):
                    msg_data["metadata"] = msg.meta
                data = {"type": "message", "data": msg_data}
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            poll_db.close()

        # Phase 2: read from queue
        q = get_queue(session_id)
        if q is None:
            # No queue means agent already finished or never started — check status
            check_db = SessionLocal()
            try:
                session = check_db.query(AgentSession).filter(
                    AgentSession.id == session_id
                ).first()
                if not session or session.status != "processing":
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return
            finally:
                check_db.close()
            # Session is processing but no queue — fallback to done
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        max_idle = 240  # 240 consecutive empty reads * 0.5s = 120s inactivity timeout
        idle_count = 0
        while idle_count < max_idle:
            try:
                event = await loop.run_in_executor(None, lambda: q.get(True, 0.5))
            except Empty:
                idle_count += 1
                continue

            idle_count = 0  # Reset on successful read

            event_type = event.get("type", "")

            if event_type == "done":
                # Forward done event and clean up
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                remove_queue(session_id)
                return

            # Skip duplicate messages already sent in Phase 1
            if event_type == "message":
                msg_id = event.get("data", {}).get("id")
                if msg_id and msg_id in seen_ids:
                    continue

            # Forward event as-is (message, token, token_done)
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # Inactivity timeout — clean up
        remove_queue(session_id)
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _run_chat_agent(session_id: str, user_message: str, file_bytes: bytes | None = None,
                    scenario: str | None = None, cancel_event=None,
                    user_role: str = "employee", user_id: int | None = None):
    """Background thread: run ReAct agent with independent DB session."""
    db = SessionLocal()
    try:
        agent = _create_chat_agent(session_id, db, file_bytes=file_bytes,
                                   scenario=scenario, user_role=user_role,
                                   user_id=user_id)
        if cancel_event:
            agent.ctx.cancel_event = cancel_event

        # DeerFlow skill auto-loading: scenario → inject skill as system context
        # Skill content is injected as a transient system message (not in user message)
        # so the user's message stays clean in the UI
        _SCENARIO_SKILL_MAP = {
            "inquiry": "generate-inquiry",
            "data_upload": "data-upload",
            "fulfillment": "fulfillment",
            "query": "query-data",
        }
        if scenario and scenario in _SCENARIO_SKILL_MAP:
            skill_name = _SCENARIO_SKILL_MAP[scenario]
            if hasattr(agent.ctx, 'skills') and skill_name in agent.ctx.skills:
                from services.agent.tool_context import _expand_template
                skill = agent.ctx.skills[skill_name]
                agent.ctx._skill_injection = _expand_template(skill.body, user_message)

        # Handle explicit /slash-command from user (still modifies message)
        if user_message.strip().startswith("/") and hasattr(agent.ctx, 'resolve_slash_command'):
            was_skill, expanded = agent.ctx.resolve_slash_command(user_message)
            if was_skill:
                user_message = expanded

        agent.run(user_message)
    except Exception as e:
        logger.error("Chat agent error: %s", str(e), exc_info=True)
        db.rollback()  # Clear any dirty state left by agent.run()
        # Save error as display message with error msg_type
        try:
            msg_count = db.query(AgentMessage).filter(
                AgentMessage.session_id == session_id
            ).count()
            error_content = f"抱歉，处理您的消息时出错了: {str(e)}"
            error_meta = {"severity": "critical", "category": "agent_crash"}
            error_msg = AgentMessage(
                session_id=session_id,
                sequence=msg_count + 1,
                role="assistant",
                msg_type="error",
                content=error_content,
                meta=error_meta,
            )
            db.add(error_msg)
            db.flush()
            # Push error to SSE queue for real-time delivery
            push_event(session_id, {
                "type": "message",
                "data": {
                    "id": error_msg.id,
                    "role": "assistant",
                    "content": error_content,
                    "msg_type": "error",
                    "created_at": error_msg.created_at.isoformat() if error_msg.created_at else datetime.utcnow().isoformat(),
                    "metadata": error_meta,
                },
            })
            db.commit()
        except Exception:
            db.rollback()
    finally:
        # Sync workspace files to Supabase Storage (best-effort)
        workspace_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
        try:
            from services.workspace_manager import sync_workspace
            synced = sync_workspace(session_id, workspace_dir)
            if synced:
                logger.info("Synced %d workspace file(s) for session %s", len(synced), session_id)
        except Exception as e:
            logger.debug("Workspace sync skipped: %s", e)

        # Save referenced order IDs to session context (for artifact panel)
        try:
            if agent.ctx.referenced_order_ids:
                _session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
                if _session:
                    ctx_data = dict(_session.context_data or {})
                    existing = set(ctx_data.get("referenced_order_ids", []))
                    existing.update(agent.ctx.referenced_order_ids)
                    ctx_data["referenced_order_ids"] = sorted(existing)
                    _session.context_data = ctx_data
                    db.commit()
        except Exception as e:
            logger.debug("Save referenced orders skipped: %s", e)
            try:
                db.rollback()
            except Exception:
                pass

        # Mark session as active (done processing)
        try:
            session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
            title = session.title if session else None
            if session:
                session.status = "active"
                session.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
            title = None
        db.close()

        # Clean up cancel event
        remove_cancel_event(session_id)

        # Push done event to queue
        push_event(session_id, {
            "type": "done",
            "data": {"title": title},
        })


# ─── Cancel ──────────────────────────────────────────────────

@router.post("/sessions/{session_id}/cancel")
def cancel_agent(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Cancel a running agent for the given session."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    set_cancelled(session_id)
    return {"status": "cancelled"}


# ─── File Download ────────────────────────────────────────────

@router.get("/sessions/{session_id}/files/{filename}")
def download_file(
    session_id: str,
    filename: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Download a generated file from the session workspace."""
    # Security: reject path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "无效的文件名")

    # Verify session ownership
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    filepath = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id, filename)

    # Determine media type
    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    from urllib.parse import quote
    encoded = quote(filename)

    # Try local workspace first
    if os.path.isfile(filepath):
        return FileResponse(
            filepath,
            media_type=media_type,
            filename=filename,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            },
        )

    # Fallback: download from Supabase Storage (inquiry files are stored there)
    try:
        from services.file_storage import storage
        # Try common storage paths where inquiry files are uploaded
        for prefix in ("inquiries", "chat"):
            try:
                content = storage.download(f"{prefix}/{filename}")
                from fastapi.responses import Response
                return Response(
                    content=content,
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
                    },
                )
            except (FileNotFoundError, Exception):
                continue
    except Exception:
        pass

    raise HTTPException(404, "文件不存在")


# ─── Workspace Files ─────────────────────────────────────────

@router.get("/sessions/{session_id}/files")
def list_workspace_files(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """List all files in the session workspace."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    workspace_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
    try:
        from services.workspace_manager import list_workspace_files as _list_files
        return _list_files(session_id, workspace_dir)
    except Exception:
        return []


# ─── Unified Artifacts ────────────────────────────────────────

@router.get("/sessions/{session_id}/artifacts")
def list_session_artifacts(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """List all artifacts for a session — workspace files + order inquiry files.

    Returns a unified list with source-aware download URLs.
    """
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    artifacts = []

    # 1. Workspace files (local + synced)
    workspace_dir = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id)
    try:
        from services.workspace_manager import list_workspace_files as _list_files
        ws_files = _list_files(session_id, workspace_dir)
        for f in ws_files:
            if f.get("is_output"):
                artifacts.append({
                    "id": f"ws:{f['filename']}",
                    "filename": f["filename"],
                    "source": "workspace",
                    "size": f.get("size", 0),
                    "modified_at": f.get("modified_at", 0),
                    "order_id": None,
                    "supplier_name": None,
                    "product_count": None,
                })
    except Exception:
        pass

    # 2. Order inquiry files from referenced orders
    ctx_data = session.context_data or {}
    order_ids = ctx_data.get("referenced_order_ids", [])

    if order_ids:
        from models import Order
        orders = db.query(Order).filter(Order.id.in_(order_ids)).all()

        # Load supplier names in bulk
        supplier_ids = set()
        for order in orders:
            for f in (order.inquiry_data or {}).get("generated_files", []):
                sid = f.get("supplier_id")
                if sid:
                    supplier_ids.add(sid)

        supplier_names = {}
        if supplier_ids:
            import sqlalchemy
            rows = db.execute(
                sqlalchemy.text("SELECT id, name FROM suppliers WHERE id = ANY(:ids)"),
                {"ids": list(supplier_ids)},
            ).fetchall()
            supplier_names = {r[0]: r[1] for r in rows}

        for order in orders:
            inquiry = order.inquiry_data or {}
            for f in inquiry.get("generated_files", []):
                filename = f.get("filename")
                if not filename:
                    continue
                sid = f.get("supplier_id")
                artifacts.append({
                    "id": f"order:{order.id}:{filename}",
                    "filename": filename,
                    "source": "order_inquiry",
                    "size": 0,
                    "modified_at": 0,
                    "order_id": order.id,
                    "supplier_name": supplier_names.get(sid, f"供应商 #{sid}" if sid else None),
                    "product_count": f.get("product_count"),
                })

    return artifacts


@router.get("/sessions/{session_id}/artifacts/download")
def download_artifact(
    session_id: str,
    artifact_id: str = Query(..., description="Artifact ID: ws:filename or order:id:filename"),
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Download an artifact by ID — unified proxy for workspace and order files."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    parts = artifact_id.split(":", 2)
    source = parts[0]

    if source == "ws" and len(parts) >= 2:
        # Workspace file — serve from local filesystem
        filename = parts[1]
        safe = os.path.basename(filename)
        filepath = os.path.join(settings.AGENT_WORKSPACE_ROOT, session_id, safe)
        if not os.path.isfile(filepath):
            raise HTTPException(404, "文件不存在")
        ext = os.path.splitext(safe)[1].lower()
        media_types = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
            ".pdf": "application/pdf",
        }
        from urllib.parse import quote
        return FileResponse(
            filepath,
            media_type=media_types.get(ext, "application/octet-stream"),
            filename=safe,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe)}"},
        )

    elif source == "order" and len(parts) >= 3:
        # Order inquiry file — serve from Supabase storage
        try:
            order_id = int(parts[1])
        except ValueError:
            raise HTTPException(400, "无效的 artifact_id")
        filename = parts[2]

        # Verify order is referenced by this session
        ctx_data = session.context_data or {}
        if order_id not in (ctx_data.get("referenced_order_ids") or []):
            raise HTTPException(403, "该订单未在此会话中引用")

        from models import Order
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(404, "订单不存在")

        inquiry = order.inquiry_data or {}
        files = inquiry.get("generated_files", [])
        file_entry = next((f for f in files if f.get("filename") == filename), None)
        if not file_entry:
            raise HTTPException(404, "文件不存在")

        file_url = file_entry.get("file_url", filename)
        try:
            from services.file_storage import storage
            content = storage.download(file_url)
        except FileNotFoundError:
            raise HTTPException(404, "文件已丢失")

        from fastapi.responses import Response
        safe = os.path.basename(filename)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe}"'},
        )

    raise HTTPException(400, "无效的 artifact_id 格式")


# ─── Context Compaction ──────────────────────────────────────

@router.post("/sessions/{session_id}/compact")
def compact_session(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Compact a chat session's context to reduce token usage.

    Calls agent.compact() which summarizes the conversation history,
    replacing older turns with a condensed summary.
    """
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    if session.status == "processing":
        raise HTTPException(409, "会话正在处理中，无法压缩")

    try:
        agent = _create_chat_agent(session_id, db)
        agent.compact()
        return {"detail": "会话上下文已压缩", "session_id": session_id}
    except Exception as e:
        logger.error("Compact error for session %s: %s", session_id, str(e), exc_info=True)
        raise HTTPException(500, f"压缩失败: {str(e)}")


# ─── Session Stats ────────────────────────────────────────────

@router.get("/sessions/{session_id}/stats")
def get_session_stats(
    session_id: str,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Get token usage and tool performance stats for a session."""
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    from services.agent.tracer import AgentTracer
    tracer = AgentTracer(db, session_id)
    stats = tracer.get_session_stats()
    # Also include the accumulated token_usage from session record
    stats["session_token_usage"] = session.token_usage or {}
    return stats


# ─── Memory Management ──────────────────────────────────────

class MemoryUpdate(BaseModel):
    memory_type: str | None = None
    key: str | None = None
    value: str | None = None


class MemoryCreate(BaseModel):
    memory_type: str = "fact"
    key: str
    value: str


@router.get("/memories")
def list_memories(
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """List all memories for the current user."""
    from models import AgentMemory
    memories = (
        db.query(AgentMemory)
        .filter(AgentMemory.user_id == current_user.id)
        .order_by(AgentMemory.updated_at.desc())
        .all()
    )
    return [
        {
            "id": m.id,
            "memory_type": m.memory_type,
            "key": m.key,
            "value": m.value,
            "source_session_id": m.source_session_id,
            "access_count": m.access_count,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        }
        for m in memories
    ]


@router.post("/memories")
def create_memory(
    body: MemoryCreate,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Manually create a memory entry."""
    from models import AgentMemory

    valid_types = {"user_preference", "supplier_knowledge", "workflow_pattern", "fact"}
    if body.memory_type not in valid_types:
        raise HTTPException(400, f"无效的记忆类型。可选: {', '.join(valid_types)}")

    # Upsert: if same type+key exists, update value
    existing = db.query(AgentMemory).filter(
        AgentMemory.user_id == current_user.id,
        AgentMemory.memory_type == body.memory_type,
        AgentMemory.key == body.key,
    ).first()

    if existing:
        existing.value = body.value
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return {"id": existing.id, "action": "updated"}

    mem = AgentMemory(
        user_id=current_user.id,
        memory_type=body.memory_type,
        key=body.key,
        value=body.value,
    )
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return {"id": mem.id, "action": "created"}


@router.put("/memories/{memory_id}")
def update_memory(
    memory_id: int,
    body: MemoryUpdate,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Update an existing memory entry."""
    from models import AgentMemory
    mem = db.query(AgentMemory).filter(
        AgentMemory.id == memory_id,
        AgentMemory.user_id == current_user.id,
    ).first()
    if not mem:
        raise HTTPException(404, "记忆不存在")

    if body.memory_type is not None:
        valid_types = {"user_preference", "supplier_knowledge", "workflow_pattern", "fact"}
        if body.memory_type not in valid_types:
            raise HTTPException(400, f"无效的记忆类型。可选: {', '.join(valid_types)}")
        mem.memory_type = body.memory_type
    if body.key is not None:
        mem.key = body.key
    if body.value is not None:
        mem.value = body.value

    mem.updated_at = datetime.utcnow()
    db.commit()
    return {"detail": "已更新"}


@router.delete("/memories/{memory_id}")
def delete_memory(
    memory_id: int,
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Delete a memory entry."""
    from models import AgentMemory
    mem = db.query(AgentMemory).filter(
        AgentMemory.id == memory_id,
        AgentMemory.user_id == current_user.id,
    ).first()
    if not mem:
        raise HTTPException(404, "记忆不存在")
    db.delete(mem)
    db.commit()
    return {"detail": "已删除"}


@router.delete("/memories")
def clear_all_memories(
    current_user: User = Depends(require_chat_user),
    db: DBSession = Depends(get_db),
):
    """Clear all memories for the current user."""
    from models import AgentMemory
    count = db.query(AgentMemory).filter(
        AgentMemory.user_id == current_user.id
    ).delete()
    db.commit()
    return {"detail": f"已清除 {count} 条记忆"}


# ─── Skills ──────────────────────────────────────────────────

@router.get("/skills")
def list_skills(
    current_user: User = Depends(require_chat_user),
):
    """List available skills for the slash command menu."""
    from services.agent.tool_context import ToolContext
    import os

    ctx = ToolContext()
    app_dir = os.path.dirname(os.path.dirname(__file__))
    skills_dir = os.path.join(app_dir, "skills")
    ctx.scan_skills([skills_dir] if os.path.isdir(skills_dir) else None)

    return [
        {"name": s.name, "description": s.description}
        for s in ctx.skills.values()
    ]
