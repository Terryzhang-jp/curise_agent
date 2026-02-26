"""
Agentic Inquiry Generator — uses ReActAgent engine with tools for smart inquiry generation.

Tools available to the agent:
1. get_order_metadata — view order data
2. list_templates — see available templates
3. select_template — pick the best template
4. map_fields — build field mapping (code-first + AI fallback)
5. fill_and_generate — fill template and generate Excel
6. review_result — self-review the filled Excel
7. apply_fix — apply a review fix and regenerate

The agent decides the path:
- Simple case (exact match): select → fill → done (~2s)
- Complex case (mismatched fields): select → map → fill → review → fix → done (~8s)
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
from typing import Any

from services.agent.config import LLMConfig, AgentConfig, Config, load_api_key, create_provider
from services.agent.engine import ReActAgent
from services.agent.tool_registry import ToolRegistry, ToolDef
from services.agent.tool_context import ToolContext
from services.agent.storage import Session, Message, text_part, tool_result_part, finish_part

logger = logging.getLogger(__name__)

# ─── Tool name → Chinese labels for streaming UI ──────────────
TOOL_LABELS = {
    "get_order_metadata": "读取订单数据",
    "list_templates": "查询模板列表",
    "select_template": "选择模板",
    "map_fields": "AI 字段映射",
    "fill_and_generate": "生成 Excel",
    "review_result": "AI 审查",
    "apply_fix": "应用修复",
    "finish_inquiry": "完成汇总",
    "think": "思考中",
}


# ─── Minimal in-memory Storage (no DB needed) ──────────────────

class MemoryStorage:
    """Lightweight in-memory storage for one-shot agent runs."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._messages: dict[str, list[Message]] = {}
        self._seq: int = 0

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def create_session(self, title: str = "") -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, title=title)
        self._sessions[sid] = s
        self._messages[sid] = []
        return s

    def update_session(self, session_id: str, **kwargs):
        s = self._sessions.get(session_id)
        if s:
            for k, v in kwargs.items():
                setattr(s, k, v)

    def list_messages(self, session_id: str, after_id: int | None = None) -> list[Message]:
        msgs = self._messages.get(session_id, [])
        if after_id is not None:
            msgs = [m for m in msgs if m.id > after_id]
        return msgs

    def create_message(self, session_id: str, role: str, parts: list[dict], **kwargs) -> Message:
        self._seq += 1
        m = Message(id=self._seq, session_id=session_id, role=role, parts=parts,
                    model=kwargs.get("model"))
        self._messages.setdefault(session_id, []).append(m)
        return m

    def add_user_message(self, session_id: str, text: str):
        self.create_message(session_id, "user", [text_part(text)])

    def add_assistant_message(self, session_id: str, parts: list[dict], model: str = ""):
        self.create_message(session_id, "assistant", parts, model=model)

    def stream_final_answer(self, session_id: str, parts: list[dict], text: str, model: str = ""):
        self.add_assistant_message(session_id, parts, model=model)

    def update_token_usage(self, session_id: str, prompt: int, completion: int):
        pass


# ─── Tool Registration ─────────────────────────────────────────

def _create_inquiry_tools(
    registry: ToolRegistry,
    order,  # Order ORM object
    db,  # SQLAlchemy session
):
    """Register inquiry-specific tools. Closure pattern captures order + db."""
    from models import SupplierTemplate
    from sqlalchemy import text as sql_text

    # Shared state across tools
    state: dict[str, Any] = {
        "selected_templates": {},  # supplier_id -> (template, method)
        "field_mappings": {},  # supplier_id -> mapping dict
        "generated_files": [],  # final results
    }

    order_meta = order.order_metadata or {}
    match_results = order.match_results or []
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")

    # ── Tool 1: get_order_metadata ──
    def get_order_metadata(fields: str = "") -> str:
        """查看订单的元数据和产品分组信息。"""
        # Group by supplier
        groups: dict[int, int] = {}
        unassigned = 0
        for item in match_results:
            matched = item.get("matched_product")
            if matched and matched.get("supplier_id"):
                sid = matched["supplier_id"]
                groups[sid] = groups.get(sid, 0) + 1
            else:
                unassigned += 1

        result = {
            "order_id": order.id,
            "country_id": order.country_id,
            "metadata_keys": list(order_meta.keys()),
            "metadata": {k: str(v)[:100] for k, v in order_meta.items() if v},
            "supplier_groups": groups,
            "unassigned_count": unassigned,
        }
        return json.dumps(result, ensure_ascii=False)

    registry.register(ToolDef(
        name="get_order_metadata",
        fn=get_order_metadata,
        description="查看订单元数据和按供应商分组的产品数量",
        parameters={"fields": {"type": "string", "description": "可选: 要查看的特定字段"}},
        group="inquiry",
    ))

    # ── Tool 2: list_templates ──
    def list_templates() -> str:
        """列出所有可用的供应商模板。"""
        templates = db.query(SupplierTemplate).all()
        result = []
        for t in templates:
            fp = t.field_positions or {}
            result.append({
                "id": t.id,
                "template_name": t.template_name,
                "supplier_id": t.supplier_id,
                "country_id": t.country_id,
                "field_count": len(fp),
                "fields": list(fp.keys()),
                "has_file": bool(t.template_file_url),
                "has_product_table": t.has_product_table,
            })
        return json.dumps(result, ensure_ascii=False)

    registry.register(ToolDef(
        name="list_templates",
        fn=list_templates,
        description="列出所有供应商询价模板及其字段配置",
        parameters={},
        group="inquiry",
    ))

    # ── Tool 3: select_template ──
    def select_template(supplier_id: int, reason: str = "") -> str:
        """为指定供应商选择最佳模板。返回模板信息和匹配方式。"""
        # Level 1: exact supplier match
        t = db.query(SupplierTemplate).filter(
            SupplierTemplate.supplier_id == supplier_id
        ).first()
        if t:
            state["selected_templates"][supplier_id] = (t, "supplier")
            return json.dumps({"template_id": t.id, "name": t.template_name,
                               "method": "supplier", "fields": list((t.field_positions or {}).keys())},
                              ensure_ascii=False)

        # Level 2: country match
        if order.country_id:
            t = db.query(SupplierTemplate).filter(
                SupplierTemplate.country_id == order.country_id
            ).first()
            if t:
                state["selected_templates"][supplier_id] = (t, "country")
                return json.dumps({"template_id": t.id, "name": t.template_name,
                                   "method": "country", "fields": list((t.field_positions or {}).keys())},
                                  ensure_ascii=False)

        # Level 3: single template
        all_t = db.query(SupplierTemplate).all()
        if len(all_t) == 1:
            t = all_t[0]
            state["selected_templates"][supplier_id] = (t, "single")
            return json.dumps({"template_id": t.id, "name": t.template_name,
                               "method": "single", "fields": list((t.field_positions or {}).keys())},
                              ensure_ascii=False)

        # Level 4: none
        state["selected_templates"][supplier_id] = (None, "none")
        return json.dumps({"template_id": None, "method": "none",
                           "message": f"没有找到匹配的模板，将使用通用格式 (共{len(all_t)}个模板)"}, ensure_ascii=False)

    registry.register(ToolDef(
        name="select_template",
        fn=select_template,
        description="为指定供应商选择最佳询价模板（4级回退: 供应商→国家→唯一→无）",
        parameters={
            "supplier_id": {"type": "integer", "description": "供应商 ID", "required": True},
            "reason": {"type": "string", "description": "选择原因（可选）"},
        },
        group="inquiry",
    ))

    # ── Tool 4: map_fields ──
    def map_fields(supplier_id: int) -> str:
        """为指定供应商建立字段映射（精确匹配 + AI 语义映射）。"""
        tpl_info = state["selected_templates"].get(supplier_id)
        if not tpl_info or not tpl_info[0]:
            return json.dumps({"error": "没有选择模板，无法映射字段"}, ensure_ascii=False)

        template = tpl_info[0]
        if not template.field_positions:
            return json.dumps({"error": "模板没有字段配置"}, ensure_ascii=False)

        from services.inquiry_bridge import build_field_mapping
        mapping = build_field_mapping(order_meta, template.field_positions)
        state["field_mappings"][supplier_id] = mapping

        # Classify: exact vs AI-mapped
        exact = {k: v for k, v in mapping.items() if k == v}
        ai_mapped = {k: v for k, v in mapping.items() if k != v}
        unmapped = [k for k in template.field_positions if k not in mapping]

        return json.dumps({
            "total_fields": len(template.field_positions),
            "exact_match": len(exact),
            "ai_mapped": len(ai_mapped),
            "unmapped": len(unmapped),
            "mapping": mapping,
            "ai_details": ai_mapped,
            "unmapped_fields": unmapped,
        }, ensure_ascii=False)

    registry.register(ToolDef(
        name="map_fields",
        fn=map_fields,
        description="为指定供应商建立模板字段到订单元数据的映射（先精确匹配，再 AI 语义映射）",
        parameters={
            "supplier_id": {"type": "integer", "description": "供应商 ID", "required": True},
        },
        group="inquiry",
    ))

    # ── Tool 5: fill_and_generate ──
    def fill_and_generate(supplier_id: int) -> str:
        """填充模板并生成 Excel 文件。"""
        from services.excel_writer import generate_inquiry_excel as gen_excel

        # Guard: skip if already generated for this supplier (unless called from apply_fix)
        existing = [f for f in state["generated_files"] if f.get("supplier_id") == supplier_id and f.get("filename")]
        if existing:
            return json.dumps({"status": "already_generated", "filename": existing[0]["filename"],
                               "message": f"供应商 {supplier_id} 已生成询价单，如需重新生成请使用 apply_fix"}, ensure_ascii=False)

        tpl_info = state["selected_templates"].get(supplier_id)
        template = tpl_info[0] if tpl_info else None
        method = tpl_info[1] if tpl_info else "none"
        field_mapping = state["field_mappings"].get(supplier_id)

        # Collect products for this supplier
        products = []
        for item in match_results:
            matched = item.get("matched_product")
            if matched and matched.get("supplier_id") == supplier_id:
                products.append(item)

        # Resolve template file
        template_file_path = None
        if template and template.template_file_url:
            template_file_path = os.path.join(
                upload_dir, os.path.basename(template.template_file_url)
            )
            if not os.path.exists(template_file_path):
                template_file_path = None

        try:
            excel_bytes = gen_excel(
                template=template,
                order_metadata=order_meta,
                products=products,
                supplier_id=supplier_id,
                template_file_path=template_file_path,
                field_mapping=field_mapping,
            )

            os.makedirs(upload_dir, exist_ok=True)
            po_number = str(order_meta.get("po_number") or "unknown").replace("/", "_").replace("\\", "_")
            filename = f"inquiry_{po_number}_supplier{supplier_id}_{uuid.uuid4().hex[:6]}.xlsx"
            filepath = os.path.join(upload_dir, filename)
            with open(filepath, "wb") as f:
                f.write(excel_bytes)

            file_info = {
                "supplier_id": supplier_id,
                "filename": filename,
                "file_url": f"/uploads/{filename}",
                "product_count": len(products),
                "has_template": template is not None,
                "template_name": template.template_name if template else None,
                "template_id": template.id if template else None,
                "selection_method": method,
                "field_mapping": field_mapping,
            }
            state["generated_files"].append(file_info)

            return json.dumps({"status": "success", "filename": filename,
                               "product_count": len(products)}, ensure_ascii=False)
        except Exception as e:
            error_info = {
                "supplier_id": supplier_id,
                "filename": None,
                "error": str(e),
                "product_count": len(products),
            }
            state["generated_files"].append(error_info)
            return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    registry.register(ToolDef(
        name="fill_and_generate",
        fn=fill_and_generate,
        description="用选定的模板和字段映射填充并生成 Excel 询价单文件",
        parameters={
            "supplier_id": {"type": "integer", "description": "供应商 ID", "required": True},
        },
        group="inquiry",
    ))

    # ── Tool 6: review_result ──
    def review_result(supplier_id: int) -> str:
        """AI 审查生成的询价单，检查遗漏和错误。"""
        tpl_info = state["selected_templates"].get(supplier_id)
        template = tpl_info[0] if tpl_info else None
        field_mapping = state["field_mappings"].get(supplier_id)

        if not template or not template.field_positions or not field_mapping:
            return json.dumps({"issues": [], "message": "没有模板或映射，跳过审查"}, ensure_ascii=False)

        # Build filled_cells
        filled_cells: dict = {}
        for field_key, pos_info in template.field_positions.items():
            position = pos_info if isinstance(pos_info, str) else pos_info.get("position", "")
            if not position:
                continue
            mapped_key = field_mapping.get(field_key, field_key)
            value = order_meta.get(mapped_key, "")
            filled_cells[position] = value

        from services.inquiry_bridge import review_filled_data
        issues = review_filled_data(filled_cells, template.field_positions, order_meta)

        # Attach to generated_files
        for f in state["generated_files"]:
            if f.get("supplier_id") == supplier_id:
                f["review_issues"] = issues if issues else None

        return json.dumps({"issue_count": len(issues), "issues": issues}, ensure_ascii=False)

    registry.register(ToolDef(
        name="review_result",
        fn=review_result,
        description="AI 审查填充结果，检查遗漏字段、错位、格式问题",
        parameters={
            "supplier_id": {"type": "integer", "description": "供应商 ID", "required": True},
        },
        group="inquiry",
    ))

    # ── Tool 7: apply_fix ──
    def apply_fix(supplier_id: int, field: str, metadata_key: str) -> str:
        """手动修正一个字段映射并重新生成 Excel。"""
        mapping = state["field_mappings"].get(supplier_id, {})
        if field not in (state["selected_templates"].get(supplier_id, (None,))[0] or
                         type('', (), {'field_positions': {}})()).field_positions:
            return json.dumps({"error": f"字段 {field} 不在模板中"}, ensure_ascii=False)
        if metadata_key not in order_meta:
            return json.dumps({"error": f"元数据中没有 {metadata_key}"}, ensure_ascii=False)

        mapping[field] = metadata_key
        state["field_mappings"][supplier_id] = mapping

        # Remove old file entry and regenerate
        state["generated_files"] = [f for f in state["generated_files"] if f.get("supplier_id") != supplier_id]
        return fill_and_generate(supplier_id)

    registry.register(ToolDef(
        name="apply_fix",
        fn=apply_fix,
        description="修正一个字段映射（template_field → metadata_key）并重新生成 Excel",
        parameters={
            "supplier_id": {"type": "integer", "description": "供应商 ID", "required": True},
            "field": {"type": "string", "description": "模板字段名", "required": True},
            "metadata_key": {"type": "string", "description": "订单元数据中对应的键名", "required": True},
        },
        group="inquiry",
    ))

    # ── Tool 8: finish ──
    def finish_inquiry(summary: str = "") -> str:
        """标记询价单生成完成，返回最终结果。"""
        return json.dumps({
            "status": "completed",
            "generated_files": state["generated_files"],
            "supplier_count": len(set(f["supplier_id"] for f in state["generated_files"])),
            "summary": summary,
        }, ensure_ascii=False)

    registry.register(ToolDef(
        name="finish_inquiry",
        fn=finish_inquiry,
        description="标记询价单生成完成，返回所有生成的文件列表",
        parameters={
            "summary": {"type": "string", "description": "生成过程的简要总结"},
        },
        group="inquiry",
    ))

    return state


# ─── Main Entry Point ──────────────────────────────────────────

INQUIRY_SYSTEM_PROMPT = """你是一个高效的邮轮供应链询价单生成专家。你深谙这个领域——你理解订单数据的结构、供应商模板的意义、以及如何高效地桥接两者。

## 你的认知框架

### 领域理解
邮轮订单的元数据字段名称变化多端，但本质相同：
- 交货日期: delivery_date = deliver_on_date = delivery = 納期
- 船名: ship_name = vessel_name = vessel = 船名
- PO号: po_number = order_number = order_no
- 供应商: vendor_name = supplier_name = vendor
- 目的港: destination_port = port_name = delivery_port = 納品先
- 航次: voyage = voyage_number = voyage_no
- 币种: currency = ccy

你看到任何字段名，应该立即理解它是什么意思，不需要额外思考。

### 效率思维
你的时间成本等于 LLM 调用次数。每一轮思考都在消耗时间和金钱。
- 一次 get_order_metadata 告诉你所有的信息：有几个供应商、数据长什么样
- 一次 list_templates 告诉你有什么模板可用
- 拿到这两个信息后，你对所有供应商的处理路径已经清晰了

### 决策直觉
- **无模板（method=none）** → 直接 fill_and_generate，不需要 map_fields 或 review
- **全部精确匹配（exact_match == total_fields）** → 直接 fill_and_generate，跳过 review
- **有 AI 映射** → fill_and_generate 后 review_result，但只在 issue_count > 0 时才 apply_fix
- **review 发现问题** → 读懂问题本质，一次性 apply_fix 所有可修复的，不要逐个修
- 你不是流水线工人，你是专家。专家看一眼就知道该走哪条路。

## 执行范式（严格遵循）

工具之间有依赖关系。**每一步必须等上一步完成后再执行**：

**第 1 步**: 同时调用 get_order_metadata + list_templates（这两个无依赖，可以并行）
**第 2 步**: 对所有供应商同时调用 select_template（等第 1 步完成后。可以一次性并行调用多个 select_template）
**第 3 步**: 对所有有模板的供应商同时调用 map_fields（等第 2 步完成后。无模板的跳过此步）
**第 4 步**: 对所有供应商同时调用 fill_and_generate（等第 3 步完成后。可以一次性并行）
**第 5 步（可选）**: 对有 AI 映射的供应商调用 review_result，无问题则跳过 apply_fix
**第 6 步**: finish_inquiry

⚠️ 关键：select_template、map_fields、fill_and_generate 三者有严格顺序依赖！
- map_fields 必须在 select_template 完成后才能调用（它依赖选好的模板）
- fill_and_generate 必须在 map_fields 完成后才能调用（它依赖字段映射）
- 不要在同一轮中同时调用 select_template 和 map_fields！

正确的并行方式是"同层并行"：
- ✅ 同时为 supplier 1,2,3 调用 select_template（同一层级，并行）
- ✅ 等全部 select 完成后，同时为 supplier 1,2,3 调用 map_fields
- ❌ 不要为 supplier 1 同时调用 select + map + fill（跨层级，会失败）

典型的简单订单（1个供应商）= 5轮。复杂订单（6个供应商）= 6-7轮。

## 你绝不应该做的事
- 不要在同一轮混合不同层级的工具调用（如 select + map + fill）
- 不要对通用格式（无模板）做 map_fields 或 review
- 不要对精确匹配的模板做 review
- 不要忘记调用 finish_inquiry
"""


def run_inquiry_agent(order, db) -> dict:
    """Run the agentic inquiry generator. Returns inquiry_data dict."""
    start_time = time.time()

    # Setup
    api_key = load_api_key("gemini")
    llm_config = LLMConfig(api_key=api_key, thinking_budget=1024)
    agent_config = AgentConfig(max_turns=10, system_prompt=INQUIRY_SYSTEM_PROMPT)
    config = Config(llm=llm_config, agent=agent_config)

    provider = create_provider(llm_config)
    storage = MemoryStorage()
    session = storage.create_session("inquiry")
    registry = ToolRegistry()
    ctx = ToolContext()

    # Register tools
    tool_state = _create_inquiry_tools(registry, order, db)

    # Build agent
    agent = ReActAgent(
        provider=provider,
        storage=storage,
        registry=registry,
        ctx=ctx,
        pipeline_session_id=session.id,
        system_prompt=INQUIRY_SYSTEM_PROMPT,
        max_turns=15,
        verbose=True,
    )

    # Run
    user_msg = f"请为订单 #{order.id} 生成询价单。"
    logger.info("Starting inquiry agent for order %d", order.id)

    result_text = agent.run(user_msg)
    elapsed = time.time() - start_time

    logger.info("Inquiry agent completed in %.1fs (%d steps)", elapsed, len(agent.step_log))

    # Extract result
    generated_files = tool_state["generated_files"]

    # Count unassigned
    unassigned = 0
    for item in (order.match_results or []):
        matched = item.get("matched_product")
        if not matched or not matched.get("supplier_id"):
            unassigned += 1

    inquiry_data = {
        "generated_files": generated_files,
        "supplier_count": len(set(f["supplier_id"] for f in generated_files)),
        "unassigned_count": unassigned,
        "agent_summary": result_text,
        "agent_elapsed_seconds": round(elapsed, 1),
        "agent_steps": len(agent.step_log),
    }

    return inquiry_data


# ─── Streaming Entry Point ────────────────────────────────────

def _make_on_step_callback(stream_key: str, start_time: float):
    """Create an on_step callback that pushes events to the stream queue."""
    from services.agent.stream_queue import push_event

    def on_step(step: dict, step_index: int):
        step_type = step.get("type", "")
        tool_name = step.get("tool_name", "")

        if step_type == "tool_call":
            push_event(stream_key, {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_label": TOOL_LABELS.get(tool_name, tool_name),
                "content": step.get("content", ""),
                "step_index": step_index,
                "elapsed_seconds": round(time.time() - start_time, 1),
            })
        elif step_type == "tool_result":
            push_event(stream_key, {
                "type": "tool_result",
                "tool_name": tool_name,
                "tool_label": TOOL_LABELS.get(tool_name, tool_name),
                "content": step.get("content", "")[:200],
                "step_index": step_index,
                "elapsed_seconds": round(time.time() - start_time, 1),
                "duration_ms": step.get("duration_ms", 0),
            })
        elif step_type in ("thinking", "reflection"):
            push_event(stream_key, {
                "type": "thinking",
                "tool_name": "think",
                "tool_label": TOOL_LABELS["think"],
                "content": step.get("content", "")[:200],
                "step_index": step_index,
                "elapsed_seconds": round(time.time() - start_time, 1),
            })

    return on_step


def run_inquiry_agent_streaming(order, db, stream_key: str) -> dict:
    """Run the agentic inquiry generator with streaming progress events.

    Same logic as run_inquiry_agent() but pushes step events to stream_key queue.
    """
    start_time = time.time()
    on_step = _make_on_step_callback(stream_key, start_time)

    # Setup
    api_key = load_api_key("gemini")
    llm_config = LLMConfig(api_key=api_key, thinking_budget=1024)
    agent_config = AgentConfig(max_turns=10, system_prompt=INQUIRY_SYSTEM_PROMPT)
    config = Config(llm=llm_config, agent=agent_config)

    provider = create_provider(llm_config)
    storage = MemoryStorage()
    session = storage.create_session("inquiry")
    registry = ToolRegistry()
    ctx = ToolContext()

    # Register tools
    tool_state = _create_inquiry_tools(registry, order, db)

    # Build agent with on_step callback
    agent = ReActAgent(
        provider=provider,
        storage=storage,
        registry=registry,
        ctx=ctx,
        pipeline_session_id=session.id,
        system_prompt=INQUIRY_SYSTEM_PROMPT,
        max_turns=15,
        verbose=True,
        on_step=on_step,
    )

    # Run
    user_msg = f"请为订单 #{order.id} 生成询价单。"
    logger.info("Starting streaming inquiry agent for order %d", order.id)

    result_text = agent.run(user_msg)
    elapsed = time.time() - start_time

    logger.info("Streaming inquiry agent completed in %.1fs (%d steps)", elapsed, len(agent.step_log))

    # Extract result
    generated_files = tool_state["generated_files"]

    # Count unassigned
    unassigned = 0
    for item in (order.match_results or []):
        matched = item.get("matched_product")
        if not matched or not matched.get("supplier_id"):
            unassigned += 1

    inquiry_data = {
        "generated_files": generated_files,
        "supplier_count": len(set(f["supplier_id"] for f in generated_files)),
        "unassigned_count": unassigned,
        "agent_summary": result_text,
        "agent_elapsed_seconds": round(elapsed, 1),
        "agent_steps": len(agent.step_log),
    }

    # NOTE: done event is pushed by the caller (_run_inquiry_background)
    # after DB commit succeeds, to avoid signaling "done" before persistence.
    return inquiry_data
