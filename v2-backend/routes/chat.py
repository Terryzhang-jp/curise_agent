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
from fastapi.responses import StreamingResponse
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


_SCENARIO_PROMPTS = {
    "data_upload": """你是 CruiseAgent，正在帮助用户上传产品数据（报价单/价格表）。

## 上传模板
如果用户询问模板或格式要求，告知可以下载模板文件：
- 下载地址：/uploads/product_upload_template.xlsx
- 模板包含 16 列（product_name、country_id、category_id 等），第二个 sheet 有参考表可查 ID
- 必填字段：product_name、country_id、category_id、effective_from

## 流程
1. parse_file 解析文件
2. analyze_columns 分析未映射列（检测 supplier_id/country_id 等引用列）
3. 确认国家、港口、供应商、生效日期
4. prepare_upload 一键验证+审计+预览（传入所有参数）
5. 用户确认后 execute_upload
6. 如有错误可用 rollback_batch 回滚

## 规则
- parse_file 后必须立即调用 analyze_columns
- 必须在 prepare_upload 之前确认国家、港口、生效日期
- prepare_upload 返回卡片后等待用户确认，不要主动执行
- 如有缺失供应商/国家，用 create_references 创建后再调用 prepare_upload
- 简短回复，不要重复卡片已展示的信息""",

    "query": """你是 CruiseAgent，正在帮助用户查询数据。

## 能力
你可以查询数据库获取产品、供应商、订单、国家、港口等信息。

## 重要数据表
- products: 产品主数据库（品名、价格、供应商、国家、港口等）
- v2_orders: 上传的订单（含产品列表、匹配结果）
- countries / ports: 国家和港口
- suppliers: 供应商
- categories: 产品分类

## 规则
- 先用 get_db_schema 了解表结构，再用 query_db 查询
- 只允许 SELECT 查询
- 查询结果用 markdown 表格格式展示
- 数值字段保留合理精度，价格保留2位小数
- 「按X统计」意味着 GROUP BY，不是 ORDER BY + LIMIT
- 结果太多只展示关键信息并说明总数""",

    "order_management": """你是 CruiseAgent，正在帮助用户管理订单。

## 能力
- 查看订单概览：get_order_overview
- 查询订单详情：query_db
- 为订单生成询价单：generate_order_inquiry

## 重要数据表
- v2_orders: 订单表（order_metadata, products, match_results 是 JSON 字段）
- products: 产品匹配参考

## 规则
- v2_orders 中 JSON 字段使用 PostgreSQL JSON 操作符查询
- 查询结果用 markdown 表格展示
- 生成询价单前先确认订单ID""",

    "fulfillment": """你是 CruiseAgent，正在帮助用户管理订单履约。

## 履约周期
pending → inquiry_sent → quoted → confirmed → delivering → delivered → invoiced → paid

## 可用工具
- get_order_fulfillment: 查看履约状态
- update_order_fulfillment: 更新状态和财务信息
- record_delivery_receipt: 记录交货验收（逐产品接收/拒收）
- attach_order_file: 上传交货照片/发票扫描件

## 规则
- 理解自然语言意图（如"订单已交货"→update状态为delivered）
- 执行重要操作前调用 request_confirmation""",
}


def _build_system_prompt(enabled_tools: set[str] | None, ctx,
                         scenario: str | None = None) -> str:
    """Build the chat system prompt with dynamic tool list.

    If *scenario* is given and matches a key in _SCENARIO_PROMPTS, use the
    lightweight scenario-specific prompt instead of the full generic prompt.
    """
    # Determine which tools to list
    if enabled_tools is None:
        tool_section = """## 可用工具
- get_db_schema: 获取数据库表结构
- query_db(sql): 执行只读 SQL 查询
- think(thought): 内部思考和规划
- calculate(expression): 数学计算
- get_current_time(): 获取当前时间
- todo_write/todo_read: 任务清单管理
- use_skill(skill_name): 调用技能模板"""
    else:
        tool_lines = []
        tool_descs = {
            "get_db_schema": "获取数据库表结构",
            "query_db": "执行只读 SQL 查询",
            "think": "内部思考和规划",
            "calculate": "数学计算",
            "get_current_time": "获取当前时间",
            "todo_write": "创建/更新任务清单",
            "todo_read": "读取任务清单",
            "use_skill": "调用技能模板",
            "web_fetch": "获取网页内容",
            "web_search": "搜索网络获取最新信息（天气、新闻、实时数据等）",
            "search_product_database": "按关键词搜索产品数据库",
            "get_order_overview": "查看订单概览（基本信息、匹配、询价状态）",
            "generate_order_inquiry": "为指定订单生成询价 Excel 文件",
            "parse_file": "解析上传的 Excel/CSV 文件，创建暂存数据",
            "analyze_columns": "分析未映射列（交叉比对 DB 参考表，检测 supplier_id/country_id 等）",
            "resolve_and_validate": "验证暂存数据（代码匹配+LLM模糊匹配+置信度分级）",
            "create_references": "自动创建缺失的供应商/国家等引用数据",
            "preview_changes": "生成变更预览报告（新增/更新/异常/无变化）",
            "execute_upload": "确认后原子执行产品导入，写入变更日志",
            "audit_data": "数据质量审计（检查列缺失、格式错误、重复数据、单位/价格合理性等）",
            "prepare_upload": "一键准备上传（验证匹配+数据审计+变更预览，返回统一审查卡片）",
            "rollback_batch": "回滚已完成的批次导入（删除新增、恢复更新产品原值）",
            "get_order_fulfillment": "查看订单履约状态（交货、发票、付款）",
            "update_order_fulfillment": "更新订单履约状态和财务信息",
            "record_delivery_receipt": "记录港口交货验收（逐产品接收/拒收）",
            "attach_order_file": "将上传的图片/文件附加到订单",
            "request_confirmation": "请求用户确认（重要操作前必须调用）",
        }
        for name in sorted(enabled_tools):
            desc = tool_descs.get(name, name)
            tool_lines.append(f"- {name}: {desc}")
        tool_section = "## 可用工具\n" + "\n".join(tool_lines)

    # Skills section
    skill_summary = ctx.get_skill_list_summary()

    # Scenario-specific prompt — lightweight, focused on one task
    if scenario and scenario in _SCENARIO_PROMPTS:
        base = _SCENARIO_PROMPTS[scenario]
        return f"""{base}

{tool_section}

## 记忆
你拥有完整的对话记忆。

{skill_summary}"""

    # No scenario → full generic prompt
    return f"""你是 CruiseAgent，邮轮供应链管理助手。

## 能力
你可以查询数据库获取产品、供应商、订单、国家、港口等信息，回答业务相关问题。
你还可以执行数学计算、获取当前时间、管理任务清单。

## 记忆
你拥有完整的对话记忆。你可以回忆本次会话中用户之前说过的所有内容。如果用户问你是否记得之前的对话，请确认你记得，并引用具体内容。

{tool_section}

## 重要数据表
- v2_orders: 上传的订单（含产品列表、匹配结果、元数据等 JSON 字段）
- products: 产品主数据库（品名、价格、供应商、国家、港口等）
- countries / ports: 国家和港口
- suppliers: 供应商
- categories: 产品分类
- v2_upload_batches: 产品数据上传批次（file_name, status, supplier_name, summary 等）
- v2_staging_products: 暂存产品行（batch_id, product_name, price, match_result 等）
- v2_product_changelog: 产品变更日志（product_id, batch_id, change_type, field_changes）

## 规则
- 需要数据时，先用 get_db_schema 了解表结构，再用 query_db 查询
- 只允许 SELECT 查询，不能修改数据
- 用中文简洁回答
- 如果查询结果太多，只展示关键信息并说明总数
- v2_orders 中 products/match_results/order_metadata 是 JSON 字段，使用 PostgreSQL JSON 操作符查询
- 复杂任务可以用 todo_write 拆分步骤，逐步完成
- 查询结果务必用 markdown 表格格式展示，不要用列表或纯文字罗列
- 编写 SQL 时仔细分析用户意图：「按X统计」「不同X的Y」意味着需要 GROUP BY 或窗口函数（如 ROW_NUMBER() OVER (PARTITION BY ...)），而非简单 ORDER BY + LIMIT
- 表格中数值字段保留合理精度，价格保留2位小数
- 执行重要操作（删除数据、批量更新、不可逆变更）前，先调用 request_confirmation 获取用户授权
- 调用 request_confirmation 后必须停止当前回合，等待用户确认或取消

## 履约管理
你可以管理订单的完整履约周期：
- 查看/更新履约状态: pending → inquiry_sent → quoted → confirmed → delivering → delivered → invoiced → paid
- 记录交货验收: 逐产品记录接收数量、拒收数量和原因
- 附加文件: 上传交货照片、发票扫描件等到订单
- 记录发票和付款信息

用户可能用自然语言描述状态更新（如"订单已交货"、"土豆只收了500kg"），你需要理解意图并调用相应工具。

## 产品上传模板
如果用户询问上传模板或格式要求，告知可以下载模板：/uploads/product_upload_template.xlsx
模板包含 16 列，必填：product_name、country_id、category_id、effective_from。第二个 sheet 有 ID 参考表。

## 产品上传流程
如果用户上传了 Excel 文件（报价单/价格表），你应该：
1. 用 parse_file 解析文件（自动映射列、创建暂存数据）
2. 用 analyze_columns 分析未映射列（检测是否有 supplier_id/country_id 等引用列）
3. 根据分析结果和用户输入，确认国家、港口、供应商、生效日期
4. 用 prepare_upload 一键验证+审计+预览（传入 supplier_name、country_name、port_name、effective_from、effective_to）
5. 用户确认后 execute_upload（支持排除指定行号）
6. 如有错误，可用 rollback_batch 回滚（传入 batch_id）
注意：parse_file 后必须立即调用 analyze_columns。
prepare_upload 返回卡片后等待用户确认。
简短回复，不要重复卡片已展示的信息。
{skill_summary}"""


def _create_chat_agent(session_id: str, db: DBSession, file_bytes: bytes | None = None,
                       scenario: str | None = None):
    """Create a ReAct agent configured for chat with general-purpose + query tools."""
    from services.agent.config import LLMConfig
    from services.agent.llm.gemini_provider import GeminiProvider
    from services.agent.chat_storage import ChatStorage
    from services.agent.tool_context import ToolContext
    from services.agent.engine import ReActAgent
    from services.tools import create_chat_registry
    from config import settings

    # Provider
    llm_config = LLMConfig(api_key=settings.GOOGLE_API_KEY)
    provider = GeminiProvider(llm_config)

    # Storage (uses AgentSession/AgentMessage)
    storage = ChatStorage(db)

    # Load enabled tools from DB
    enabled_tools = _load_enabled_tools(db)

    # Tools — general-purpose + business query tools
    ctx = ToolContext(db=db, file_bytes=file_bytes, pipeline_session_id=session_id)

    # Load skills from DB + filesystem
    _load_skills_into_ctx(db, ctx)

    registry = create_chat_registry(ctx, enabled_tools=enabled_tools)

    # Build dynamic system prompt
    system_prompt = _build_system_prompt(enabled_tools, ctx, scenario=scenario)

    # Agent
    agent = ReActAgent(
        provider=provider,
        storage=storage,
        registry=registry,
        ctx=ctx,
        pipeline_session_id=session_id,
        system_prompt=system_prompt,
        max_turns=10,
        thinking_budget=2048,
        verbose=True,
    )

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

    # Launch agent in background thread
    threading.Thread(
        target=_run_chat_agent,
        args=(session_id, content),
        kwargs={"file_bytes": file_bytes, "scenario": scenario.strip() or None,
                "cancel_event": cancel_event},
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
                    scenario: str | None = None, cancel_event=None):
    """Background thread: run ReAct agent with independent DB session."""
    db = SessionLocal()
    try:
        agent = _create_chat_agent(session_id, db, file_bytes=file_bytes, scenario=scenario)
        if cancel_event:
            agent.ctx.cancel_event = cancel_event
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
