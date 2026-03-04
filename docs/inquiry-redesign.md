# 询价单生成系统 — 重新设计方案

> 作者: 老K | 日期: 2026-03-01

---

## 一、当前系统的问题

### 1.1 用户体验层面

| 问题 | 现状 | 影响 |
|------|------|------|
| 多供应商串行处理 | 1 个 Agent 按顺序处理所有供应商 | 10 个供应商 = 10 倍耗时，用户干等 |
| 进度不可区分 | 扁平步骤列表，不分供应商 | "加载模板"出现 5 次，用户看不懂 |
| 预览生命周期断裂 | 生成中有实时预览，完成后消失 | 最需要看预览时反而看不到 |
| 不能单独重做 | 只能"全部重新生成" | 1 个供应商不对，全部重跑 |
| 不能手动修改 | 生成后只有下载按钮 | 发现错误只能重新生成 |

### 1.2 Agent 架构层面

| 问题 | 现状 | 影响 |
|------|------|------|
| 模板选择用 if-else 猜测 | 4 级 fallback (supplier→country→single→none) | country fallback 会误配（日本模板给澳洲供应商） |
| check_annotations 无实际校验 | 只返回值+注解文本，Agent 自判 | self-evaluation bias，错误无法自纠 |
| 产品表映射做无效搬运 | Agent 读 product_table_config 后原样传回 | 浪费 token，有出错风险 |
| DB session 无隔离 | tool 中的 DB 异常污染整个 session | 一个 DB 错误导致后续全部失败 |
| workbook 无 None 保护 | render_html/save_bytes 不检查 _wb | 未初始化时 crash |
| 两个入口函数 90% 重复 | run_inquiry_agent / run_inquiry_agent_streaming | 维护负担 |

### 1.3 引擎层面

| 能力 | 现状 | 差距 |
|------|------|------|
| 上下文管理 | history 全量传入 LLM，无裁剪 | 多供应商时 context 快速增长 |
| 记忆 | MemoryStorage（纯内存，会话结束即丢） | 无跨订单学习能力 |
| 压缩 | engine.compact() 存在但 inquiry 未调用 | 没有利用已有能力 |
| 并行 | tool 级别支持并行（ThreadPoolExecutor） | 但供应商级别仍是串行 |

---

## 二、设计原则

1. **以供应商为单位** — 数据模型、UI、Agent 执行都按供应商分离
2. **确定的事情代码做，不确定的事情 Agent 做** — 显式绑定走快路，模糊场景靠推理
3. **Agent 全程决策** — 保持 Agent 在 loop 中做所有决定，但给它更好的工具和反馈
4. **可中断、可恢复、可单独重做** — 每个供应商独立，不互相影响
5. **预览贯穿全生命周期** — 生成中看到实时预览，完成后依然可查看

---

## 三、架构重新设计

### 3.1 总体流程

> **架构模式**: Orchestrator + Per-Supplier Agent = **Map-Reduce** 模式 ([Azure AI Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns))。Orchestrator 做 fan-out（分发供应商任务）和 fan-in（收集结果合并 inquiry_data）。每个 per-supplier agent 是独立执行单元，遵循 [Anthropic Sub-Agent](https://claudefa.st/blog/guide/agents/sub-agent-best-practices) 的 context 隔离原则。

```
用户点击"生成询价单"
        │
        ▼
┌─ Orchestrator (代码层，非 Agent) ─────────────────────┐
│                                                        │
│  1. 按 supplier_id 分组 match_results                   │
│  2. 对每个供应商，启动独立的 inquiry task                 │
│  3. 每个 task 有独立的:                                  │
│     - Agent 实例（独立 context）                         │
│     - InquiryWorkbook 实例                              │
│     - SSE stream (带 supplier_id 前缀)                  │
│  4. 收集所有 task 结果，合并为 inquiry_data              │
│                                                        │
└────────────────────────────────────────────────────────┘
        │
        ▼ (每个供应商独立)
┌─ Per-Supplier Agent Task ─────────────────────────────┐
│                                                        │
│  Tool 1: read_template()                               │
│    → 确定性匹配 or Agent 选择模板                       │
│                                                        │
│  Tool 2: read_order_data()                             │
│    → 返回 metadata + products                          │
│                                                        │
│  Tool 3: write_cells(cells_json)                       │
│    → Agent 决定值和格式                                 │
│                                                        │
│  Tool 4: write_product_rows()                          │
│    → 默认使用 product_table_config，Agent 可覆盖        │
│                                                        │
│  Tool 5: verify()                                      │
│    → 代码级校验 + 返回 pass/fail                        │
│                                                        │
│  Tool 6: save()                                        │
│    → 保存文件 + 持久化 preview HTML                     │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 3.2 模板选择逻辑重新设计

**旧逻辑**: 4 级 if-else (容易误配)

**新逻辑**: 两步走

```python
def resolve_template(supplier_id, all_templates):
    """Step 1: 确定性匹配"""
    # 精确绑定
    for t in all_templates:
        if t.supplier_ids and supplier_id in t.supplier_ids:
            return t, "exact_binding"
        if t.supplier_id == supplier_id:
            return t, "exact_binding"

    # 没有精确绑定 → 返回 None，让 Agent 选
    return None, "agent_choice"
```

当 `resolve_template` 返回 None 时，`read_template` tool 返回可用模板列表，Agent 在 thinking 中推理后调用 `select_template(template_id)`:

```
Agent 收到:
  "供应商 #102 (XYZ Trading, Australia) 没有精确绑定的模板。
   可用模板:
   - id=1: 日本標準見積書 (绑定: Japan)
   - id=2: AU Inquiry Form (绑定: Australia)
   - id=3: 通用格式 (无模板文件)
   选择 template_id，或选择 0 使用通用格式。"

Agent thinking: "XYZ Trading 是澳洲公司，id=2 是澳洲模板"
Agent 调用: select_template(template_id=2)
```

### 3.3 Tool 重新设计

> **前沿背景**: 工具设计的两个核心原则:
> - **Anthropic "Building Effective Agents"**: "Start with simple, composable patterns." 工具粒度的 sweet spot 是——常见路径用粗粒度（减少 LLM 调用），关键控制点用细粒度（保持可观察性）。
> - **STRATUS Rollback 模式** (IBM Research): 每个 action 对应一个 undo operator，拒绝不可逆操作。对我们的场景: `write_cells` 天然可逆（覆写即可），`save` 是唯一不可逆操作。
> - **Microsoft Agent Mode for Excel**: Validation-first — Agent 生成轻量测试来验证预期结果，每一步可审计可复现。对应我们的 `verify()` tool 设计。
> - **Error Classification**: 所有 tool 错误分为 retriable（重试可解决）和 non-retriable（需要换策略），防止 Agent 在不可恢复的错误上反复重试。

#### Tool 1: `read_template()` — 智能模板加载

参数: 无（当前供应商已由 orchestrator 设定）

行为:
1. 确定性匹配 → 直接加载
2. 无匹配 → 返回候选列表，等 Agent 选择
3. 加载模板后返回: field_positions + annotations + product_table_config
4. 推送初始 preview

#### Tool 2: `select_template(template_id)` — Agent 选模板

只在 `read_template` 返回候选列表时使用。template_id=0 表示通用格式。

#### Tool 3: `read_order_data()` — 读取订单数据

参数: 无（当前供应商已确定）

返回: metadata 全部 kv + 该供应商的 products

#### Tool 4: `write_cells(cells_json)` — Agent 写单元格

不变。Agent 全权决定值和格式。

#### Tool 5: `write_product_rows(column_overrides?, formula_columns?)` — 写产品行

关键改变: **默认使用 product_table_config 里存储的列映射**，Agent 只需传覆盖项。

```python
# 旧: Agent 必须传完整映射
write_product_rows(start_row=12, columns_json='{"A":"line_number","C":"product_code",...}')

# 新: 默认使用模板配置，Agent 可选覆盖
write_product_rows()                                    # 使用模板默认配置
write_product_rows(column_overrides='{"F":"pack_size"}') # 覆盖某些列
write_product_rows(start_row=15)                         # 覆盖起始行
```

#### Tool 6: `verify()` — 代码级校验（替代 check_annotations）

关键改变: **tool 用代码做实际校验**，返回明确的 pass/fail。

```python
def verify():
    checks = []
    for cell_ref, annotation in annotations.items():
        value = ws[cell_ref].value
        result = _code_check(value, annotation)  # 代码级检查
        checks.append({
            "cell": cell_ref,
            "value": str(value),
            "annotation": annotation,
            "result": result["status"],     # "pass" | "fail"
            "reason": result.get("reason"), # 失败原因
            "suggestion": result.get("suggestion"),  # 修正建议
        })
    return checks
```

代码级检查规则:
```python
def _code_check(value, annotation):
    ann = annotation.lower()

    # 日期格式检查
    if "yyyy/mm/dd" in ann:
        try:
            datetime.strptime(str(value), "%Y/%m/%d")
            return {"status": "pass"}
        except:
            return {"status": "fail", "reason": f"'{value}' 不符合 YYYY/MM/DD",
                    "suggestion": _try_reformat_date(value, "%Y/%m/%d")}

    # 小数位检查
    m = re.search(r'小数点?(\d+)位', ann)
    if m:
        decimals = int(m.group(1))
        if '.' not in str(value) or len(str(value).split('.')[1]) != decimals:
            return {"status": "fail", "reason": f"需要 {decimals} 位小数",
                    "suggestion": f"{float(value):.{decimals}f}"}
        return {"status": "pass"}

    # 无法用代码检查的 → 返回 "unchecked"，Agent 自行判断
    return {"status": "unchecked", "reason": "需要 Agent 判断"}
```

Agent 收到 fail 后自行决定如何修正（保持全程决策权），但反馈信号从"自己判自己"变成了"代码给出客观结论"。

> **设计依据 (Microsoft Agent Mode for Excel)**: Agent Mode 的核心模式是 "validation-first"——在执行计算前先生成轻量测试来建立预期结果，每一步都可检查和复现。我们的 verify() tool 正是这个模式: Agent 执行 write_cells/write_product_rows 后，verify 充当自动化测试。区别在于 Agent Mode 是 Agent 自己生成测试，我们是 annotations 作为测试用例——但效果一致: **可审计的中间结果**。

#### Tool 错误分类

所有 tool 统一返回错误分类，帮助 Agent 决定下一步:

```python
# Tool 返回格式
{"status": "ok", "data": ...}
{"status": "error", "retriable": True, "error": "DB connection timeout"}
{"status": "error", "retriable": False, "error": "Template file not found"}
```

- **retriable**: Agent 可以直接重试（DB 超时、文件锁）
- **non-retriable**: Agent 需要换策略（模板不存在 → 用通用格式）

#### Tool 7: `save()` — 保存文件 + 持久化预览

新增: **保存 preview HTML 到文件**，通过 API 端点提供。

```python
def save():
    # 保存 .xlsx
    xlsx_bytes = workbook.save_bytes()
    write_file(xlsx_bytes)

    # 保存 preview HTML
    html = workbook.render_html()
    write_file(html, suffix=".html")

    return {filename, file_url, preview_url, product_count}
```

### 3.4 上下文管理

#### 问题
当前 Agent 处理多个供应商时，history 不断增长。前一个供应商的 read_template 结果（大量 JSON）对后一个供应商没用，但仍占用 context window。

#### 方案: Per-Supplier Context 隔离

> **前沿背景**: Anthropic 的 [Sub-Agent Best Practices](https://claudefa.st/blog/guide/agents/sub-agent-best-practices) 报告，sub-agent 由于 context 隔离，相比共享 context 的 Skills 模式 **减少 67% 的 token 消耗**。Google ADK 的 Parallel Agents 模式也采用独立 sub-agent、不自动共享 history 的设计。

每个供应商使用独立的 Agent 实例（独立的 MemoryStorage、history）。好处:

1. **Context 干净** — 每个 Agent 只看到当前供应商的信息（~3K tokens vs 多供应商累积 ~15K tokens）
2. **无串扰** — 供应商 A 的 tool 结果不会干扰供应商 B 的推理
3. **可并行** — 独立 Agent 可以用 ThreadPoolExecutor 并发执行
4. **可单独重做** — 失败的供应商不影响已完成的
5. **无 Reasoning Drift** — 每个 Agent 从干净的 context 开始推理，不会被前一个供应商的残留信息误导

```python
# Orchestrator
results = {}
for supplier_id, products in grouped.items():
    agent = create_per_supplier_agent(order, supplier_id, products, db, stream_key)
    result = agent.run(f"为供应商 #{supplier_id} 生成询价单。")
    results[supplier_id] = result
```

#### 供应商间共享信息

如果 Agent 在处理供应商 B 时需要知道供应商 A 的情况（极少见），通过 system prompt 注入摘要:

```
你正在为供应商 #102 生成询价单。
其他供应商的处理状态: #101 已完成 (12 个产品, 使用 JP 模板)。
```

#### Context Window 预算

典型单供应商 Agent 的 context 消耗估算:
- System prompt: ~800 tokens
- read_template 返回: ~1.5K tokens (field_positions + annotations)
- read_order_data 返回: ~1.5K tokens (metadata + 20 products)
- Tool 调用/结果: ~200 tokens × 5 轮 = ~1K tokens
- Agent thinking: ~500 tokens × 5 轮 = ~2.5K tokens
- **总计**: ~7.3K tokens（远低于 Gemini 2.5 Flash 的 1M context window）

结论: 对于单供应商场景，context 不是瓶颈。但多轮修正（verify 失败 → fix → verify 循环）时需要 compact 兜底。

### 3.5 Agent 记忆

> **前沿背景**: 业界三种主流记忆架构: LangGraph 的 **State-Driven Memory**（TypedDict + Reducer + Checkpointer）、CrewAI 的 **Unified Memory with Adaptive Scoring**（语义相似度+时间衰减+重要性评分）、MemGPT 的 **Two-Tier Virtual Context**（in-context core + out-of-context searchable store）。对于我们的场景——短生命周期、单任务 Agent——不需要复杂的记忆架构，但跨订单学习有价值。

#### 短期记忆（当前会话内）

- **MemoryStorage** — 保持不变，每个 Agent 实例独立
- **Compact** — 对于单供应商场景不需要（通常 5-8 轮就结束）
- **State 持久化** — 每个 tool 调用的结果存入 `state` dict，Agent 崩溃后 orchestrator 可以用已保存的 state 重试

#### 跨订单记忆（长期 — P2）

目前没有跨订单学习能力。未来可加:

- **模板选择记忆**: "上次供应商 #102 选了澳洲模板，这次也用"
- **格式偏好记忆**: "这个用户喜欢日期用 YYYY/MM/DD 格式"
- **字段映射缓存**: "deliver_on_date → delivery_date 的映射已验证"

实现方式参考 **CrewAI 的 Adaptive Scoring 模式**:
1. Agent 完成填写后，自动从 verify 结果中提取"已验证的映射"
2. 存入 `field_mapping_metadata.verified_mappings[]`
3. 下次生成时，将已验证映射作为 few-shot 注入 system prompt
4. 用 **importance + recency 加权** 选择最相关的 few-shot（最近5次同供应商的映射优先）

```python
# 存储格式
verified_mappings = [
    {
        "order_field": "deliver_on_date",
        "template_cell": "H8",
        "annotation": "格式 YYYY/MM/DD",
        "agent_value": "2025/12/13",
        "verify_result": "pass",
        "timestamp": "2026-03-01",
    }
]
```

这比完整的 RAG 记忆系统简单得多，但能解决 90% 的"Agent 每次都要重新推理同样映射"的问题。

### 3.6 Compact 策略

> **前沿背景**: 三种压缩方案对比:
> - **Claude Code Compaction**: 自动摘要 → 创建 compaction block → 58.6% token 削减（204K → 82K tokens）。保留架构决策、未解决的 bug、实现细节。
> - **Factory.ai Structured Summarization**: 按类别分节（session intent / file modifications / decisions / next steps），在 36K+ 生产消息上测得 **4.04 准确度**，比 OpenAI 高 0.61，技术细节保留率最佳。
> - **Microsoft LLMLingua**: 基于 perplexity 的 token 排序，小模型（GPT2-small）计算每个 token 的信息密度 → 20x 压缩，仅 1.5% 准确度损失。
>
> 我们的引擎已有 `engine.compact()` 能力（Claude Code 模式），inquiry agent 只需在合适时机触发。

对于 inquiry agent 的场景，compact 的核心价值是在 **单供应商多轮修正** 时防止 context 溢出:

```
Turn 1: read_template → 大量 JSON (2K tokens)
Turn 2: read_order_data → 大量 JSON (3K tokens)
Turn 3: write_cells → 确认
Turn 4: write_product_rows → 确认
Turn 5: verify → 发现 3 个问题
Turn 6: write_cells 修正 → 确认
Turn 7: verify → 还有 1 个问题
Turn 8: write_cells 修正 → 确认
Turn 9: verify → 全部通过
Turn 10: save
```

当到 Turn 7 时，Turn 1-2 的大量 JSON 已经不再有用。

#### Compact 触发策略

```python
# 自动触发条件 (两种任一满足):
# 1. verify 失败且轮次超过阈值
if verify_result has failures and turn > 6:
    agent.compact()

# 2. 估算 token 接近预算 (安全网)
if estimated_tokens > max_tokens * 0.7:
    agent.compact()
```

#### Compact 摘要模板 (参考 Factory.ai Structured Summarization)

```python
COMPACT_PROMPT = """请压缩以上对话历史为结构化摘要:

## 当前任务状态
- 供应商: #xxx, 模板: yyy
- 已完成: [列出已完成的步骤]
- 未完成: [列出剩余步骤]

## 关键数据 (必须保留)
- 模板字段位置: {保留 field_positions 摘要}
- 未通过校验的 annotations: {只保留失败项}
- 产品表配置: start_row=xx, columns={...}

## 上一轮 verify 结果
{只保留 fail 和 unchecked 项}

## 不需要保留
- 已成功写入的 cell 值 (workbook 已保存)
- 已通过的 verify 检查项
- 中间 thinking 过程
"""
```

关键洞察: **workbook 本身是 state**——已写入的值不需要在 history 中重复保留，Agent 可以通过 verify() 重新读取当前状态。这使得压缩可以更激进。

但对于典型场景（5-8 轮），context 不会溢出，所以 compact 作为安全网存在，不是常规路径。

---

## 四、数据模型变更

### 4.1 inquiry_data 重构为 per-supplier

```python
# 旧结构
inquiry_data = {
    "generated_files": [file1, file2],   # flat list
    "supplier_count": 2,
    "unassigned_count": 0,
    "agent_summary": "...",
    "agent_elapsed_seconds": 47.3,
    "agent_steps": 28,
}

# 新结构
inquiry_data = {
    "suppliers": {
        "101": {
            "status": "completed",          # pending | generating | completed | error
            "file": {
                "filename": "inquiry_...xlsx",
                "file_url": "/uploads/...",
                "preview_url": "/uploads/..._preview.html",
                "product_count": 12,
            },
            "template": {
                "id": 1,
                "name": "JP 模板",
                "selection_method": "exact_binding",  # exact_binding | agent_choice | none
            },
            "verify_results": [
                {"cell": "H8", "annotation": "格式 YYYY/MM/DD", "result": "pass"},
            ],
            "elapsed_seconds": 15.2,
            "steps": 8,
        },
        "102": { ... },
    },
    # 向后兼容的 flat list (从 suppliers 生成)
    "generated_files": [file1, file2],
    "supplier_count": 2,
    "unassigned_count": 0,
    "total_elapsed_seconds": 30.4,
}
```

### 4.2 新增 API 端点

```
POST /orders/{id}/generate-inquiry                    # 全部供应商生成
POST /orders/{id}/generate-inquiry/{supplier_id}      # 单供应商重做
GET  /orders/{id}/inquiry-preview/{supplier_id}        # 获取预览 HTML
```

---

## 五、前端重新设计

### 5.1 InquiryTab — 供应商卡片网格

替换现有的文件列表为 **供应商卡片网格**:

```
┌─────────────────────────────────────────────────────┐
│ 询价单                                    [全部生成] │
│ 3 个供应商 · 22 个产品                   [下载全部]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────┐  ┌─────────────────┐           │
│  │ ABC Foods       │  │ XYZ Trading     │           │
│  │ 供应商 #101     │  │ 供应商 #102     │           │
│  │ 12 产品 · JP模板│  │ 10 产品 · 通用  │           │
│  │                 │  │                 │           │
│  │ ┌─────────────┐ │  │ ┌─────────────┐ │           │
│  │ │ [Excel 缩略]│ │  │ │ [Excel 缩略]│ │           │
│  │ └─────────────┘ │  │ └─────────────┘ │           │
│  │                 │  │                 │           │
│  │ ✅ 15.2s       │  │ ✅ 0.3s        │           │
│  │ [预览][下载][↻] │  │ [预览][下载][↻] │           │
│  └─────────────────┘  └─────────────────┘           │
└─────────────────────────────────────────────────────┘
```

### 5.2 卡片状态机

```
pending (灰色) ─── 点击"生成" ──→ generating (蓝色脉冲)
                                       │
                                       ├── 成功 → completed (绿色)
                                       └── 失败 → error (红色)

completed ─── 点击"重做" ──→ generating
error     ─── 点击"重试" ──→ generating
```

### 5.3 生成进度集成到卡片

不再使用独立的 `InquiryProgress` banner。每张卡片内部显示该供应商的进度:

```
┌─────────────────┐
│ ABC Foods       │
│ 供应商 #101     │
│                 │
│ ⏳ 8.3s         │
│ ├ ✓ 加载模板    │
│ ├ ✓ 读取数据    │
│ ├ ✓ 填写单元格  │
│ └ ⟳ 写入产品表  │
│                 │
│ ┌─────────────┐ │
│ │ [实时预览]  │ │
│ └─────────────┘ │
└─────────────────┘
```

SSE 事件带 `supplier_id`，前端按 supplier_id 路由到对应卡片。

### 5.4 全屏预览 Dialog

点击 [预览] 按钮打开全屏 Dialog:

```
┌──────────────────────────────────────────────────────┐
│ ABC Foods · JP模板                     [下载] [重做]  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │                                              │    │
│  │         完整 Excel HTML 预览                  │    │
│  │         (从持久化的 preview HTML 加载)         │    │
│  │                                              │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  校验结果:                                            │
│  ✅ H8: "2025/12/13" — 格式 YYYY/MM/DD              │
│  ✅ B5: "KOBE" — 大写英文                            │
│  ❌ G12: "45" — 小数点2位 → 应为 "45.00"            │
│                                                      │
└──────────────────────────────────────────────────────┘
```

预览 HTML 来自 `GET /orders/{id}/inquiry-preview/{supplier_id}`，不需要重新生成。

---

## 六、SSE 事件协议

### 6.1 新增 supplier_id 字段

所有事件必须携带 `supplier_id`:

```json
{"type": "tool_call", "supplier_id": 101, "tool_name": "write_cells", ...}
{"type": "tool_result", "supplier_id": 101, "tool_name": "write_cells", ...}
{"type": "preview", "supplier_id": 101, "html": "<table>...", ...}
{"type": "thinking", "supplier_id": 101, "content": "...", ...}

// 全局事件
{"type": "supplier_started", "supplier_id": 101}
{"type": "supplier_completed", "supplier_id": 101, "file": {...}}
{"type": "supplier_error", "supplier_id": 101, "error": "..."}
{"type": "done", "data": inquiry_data}
```

### 6.2 前端路由

```typescript
onStep(step) {
    if (step.supplier_id) {
        // 路由到对应供应商卡片
        updateSupplierCard(step.supplier_id, step);
    }
    // 全局事件
    if (step.type === "supplier_completed") {
        markSupplierDone(step.supplier_id, step.file);
    }
}
```

---

## 七、实现优先级

### P0 — 核心架构 (必须做)

| # | 改动 | 文件 | 预计 |
|---|------|------|------|
| 1 | inquiry_agent 拆为 orchestrator + per-supplier agent | `inquiry_agent.py` | 重写 |
| 2 | 模板选择: 精确匹配 + Agent 选择 | `inquiry_agent.py` | 新 tool |
| 3 | verify 替代 check_annotations (代码级校验) | `inquiry_agent.py` | 重写 tool |
| 4 | write_product_rows 默认使用 product_table_config | `inquiry_agent.py` | 改 tool |
| 5 | inquiry_data 重构为 per-supplier | `inquiry_agent.py`, `orders-api.ts` | 改数据结构 |
| 6 | save 时持久化 preview HTML | `inquiry_agent.py`, `excel_writer.py` | 改 tool |
| 7 | Bug: DB session 隔离 | `inquiry_agent.py` | 加 try/except |
| 8 | Bug: _wb None guard | `excel_writer.py` | 加检查 |
| 9 | 合并两个入口函数 | `inquiry_agent.py` | 重构 |

### P1 — 前端重新设计 (体验提升)

| # | 改动 | 文件 |
|---|------|------|
| 10 | InquiryTab 改为供应商卡片网格 | `page.tsx` |
| 11 | 生成进度移入卡片 (per-supplier SSE 路由) | `page.tsx`, `orders-api.ts` |
| 12 | 全屏预览 Dialog | `page.tsx` (新组件) |
| 13 | 单供应商重做按钮 + API | `page.tsx`, `orders.py` |
| 14 | preview API 端点 | `orders.py` |

### P2 — 增强 (未来)

| # | 改动 |
|---|------|
| 15 | 供应商并行生成 (ThreadPoolExecutor) |
| 16 | 下载全部 (.zip) |
| 17 | 跨订单记忆 (模板选择 / 格式偏好缓存) |
| 18 | Compact 自动触发 (多轮修正场景) |

---

## 八、前沿技术参考与实施建议

> 以下内容基于 2025-2026 年生产系统和学术研究的系统调研，每项技术都标注了与我们系统的 **适用性** 和 **实施优先级**。

### 8.1 Context Management

| 模式 | 来源 | 核心思路 | 适用性 |
|------|------|----------|--------|
| Multi-Session Architecture | [Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | Initializer agent + Coding agent，任务间用 artifact 传递状态 | ⭐⭐ 我们的 orchestrator + per-supplier agent 就是这个模式 |
| Progressive Disclosure | [Claude Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) | 只展示必要的 tools，按需动态加载 | ⭐ 我们只有 7 个 tool，不需要渐进式 |
| Sliding Window | [Strands Agents](https://strandsagents.com/0.1.x/documentation/docs/user-guide/concepts/agents/context-management/) | 维持固定窗口大小，裁剪最早消息 | ⭐ 兜底方案，per-supplier 隔离已解决主要问题 |
| Thought Signatures | [Google Gemini 3](https://ai.google.dev/gemini-api/docs/thought-signatures) | 加密的推理状态，tool call 之间保留 reasoning context | ⭐⭐⭐ **如果升级到 Gemini 3，必须支持** |

**Thought Signatures 关键点**: Gemini 3 引入了加密的 "Thought Signature"——模型在调用 tool 前生成推理状态密文，tool 返回后需要把密文传回。如果不传回会导致 "Reasoning Drift"（模型忘了为什么调用这个 tool）。Google SDK 自动处理此逻辑，但我们的 `gemini_provider.py` 如果手动管理 history 需要注意。

**实施建议**: 当前 Gemini 2.5 Flash 不需要 Thought Signatures，但在 `_parse_response()` 中预留 thought_signature 字段的传递逻辑，以便未来升级。

### 8.2 Tool Design

| 模式 | 来源 | 核心思路 | 适用性 |
|------|------|----------|--------|
| Coarse/Fine Hybrid | [Composio](https://composio.dev/blog/how-to-build-tools-for-ai-agents-a-field-guide) | 常见路径粗粒度，关键控制点细粒度 | ⭐⭐⭐ 我们的 write_product_rows（粗）+ write_cells（细）就是这个模式 |
| Error Classification | [Retry Best Practices 2025](https://sparkco.ai/blog/mastering-retry-logic-agents-a-deep-dive-into-2025-best-practices) | retriable vs non-retriable，指数退避+jitter | ⭐⭐⭐ 已加入 tool 返回格式设计 |
| STRATUS Rollback | [IBM Research](https://research.ibm.com/blog/undo-agent-for-cloud) | 每个 action 有 undo operator，拒绝不可逆操作 | ⭐⭐ write_cells 天然可逆，save 是唯一不可逆点 |
| Validation-First | [Microsoft Agent Mode for Excel](https://techcommunity.microsoft.com/blog/excelblog/building-agent-mode-in-excel/4457320) | 先生成测试/验证标准，再执行操作 | ⭐⭐⭐ verify() tool 的设计基础 |
| Progressive Disclosure of Params | [Anthropic](https://www.anthropic.com/research/building-effective-agents) | 必要参数最小化，复杂参数用默认值 | ⭐⭐⭐ write_product_rows 的默认配置设计 |

**实施建议**:
- write_cells/write_product_rows 天然可逆（覆写），无需 undo operator
- save() 前 Agent 必须先 verify()，类似 STRATUS 的"拒绝不可逆操作前的校验"
- Tool 返回统一 `{status, retriable, data/error}` 格式

### 8.3 Memory Systems

| 模式 | 来源 | 核心思路 | 适用性 |
|------|------|----------|--------|
| State-Driven Memory | [LangGraph](https://docs.langchain.com/oss/python/langgraph/persistence) | TypedDict + Reducer + Checkpointer | ⭐ 对短生命周期 Agent 过重 |
| Unified Adaptive Scoring | [CrewAI](https://docs.crewai.com/en/concepts/memory) | 语义相似度 + 时间衰减 + 重要性评分 | ⭐⭐ 跨订单记忆的参考模式 |
| Two-Tier Virtual Context | [MemGPT/Letta](https://github.com/cpacker/MemGPT) | in-context core + out-of-context searchable store | ⭐ 架构太重，不适合我们的场景 |
| Verified Mappings Cache | 我们自己的设计 | verify pass 的映射存入 metadata，下次作为 few-shot | ⭐⭐⭐ **P2 优先实现** |

**实施建议**: 跨订单记忆用最轻的方案——verified_mappings 写入 `field_mapping_metadata`，按 importance×recency 加权选择。不引入 RAG、向量数据库、ChromaDB 等重型依赖。

### 8.4 History Compaction

| 模式 | 来源 | 压缩率 | 技术细节保留 | 适用性 |
|------|------|--------|-------------|--------|
| Automatic Compaction | [Claude Code](https://platform.claude.com/docs/en/build-with-claude/compaction) | 58.6% | ⭐⭐⭐ | ⭐⭐⭐ 我们已有此能力 |
| Structured Summarization | [Factory.ai](https://factory.ai/news/compressing-context) | ~60% | ⭐⭐⭐⭐ (4.04/5.0) | ⭐⭐⭐ **compact 摘要模板的参考** |
| Perplexity-Based Compression | [LLMLingua](https://github.com/microsoft/LLMLingua) | 95% (20x) | ⭐⭐ | ⭐ 需要额外小模型，对我们过重 |
| Sliding Window | 通用模式 | 可变 | ⭐ | ⭐ 简单但丢失所有历史 |

**关键发现 (Factory.ai)**: 结构化摘要比自由摘要好得多——按"session intent / file modifications / decisions / next steps"分节，每个节强制保留信息，防止 LLM 在摘要时"静默丢失"技术细节。

**实施建议**: Section 3.6 的 compact 摘要模板已参考 Factory.ai 的分节模式。额外的关键洞察: **workbook 本身就是 state checkpoint**——已写入的值不需要在 history 中重复，这使得我们的压缩可以比通用方案更激进。

### 8.5 Multi-Agent Orchestration

| 模式 | 来源 | 核心思路 | 适用性 |
|------|------|----------|--------|
| Parallel Agents | [Google ADK](https://google.github.io/adk-docs/) | 独立 sub-agent 并发执行，不共享 history | ⭐⭐⭐ per-supplier 并行的参考 |
| M1-Parallel | 2025 研究 | 同任务 3 个方案并行，取最快完成的 | ⭐ 我们的场景不需要多方案竞争 |
| Map-Reduce | [Azure AI](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) | fan-out → 独立执行 → fan-in 合并 | ⭐⭐⭐ Orchestrator 的 gather 阶段就是 reduce |
| ARISE Rubric-Guided | [ICLR 2025](https://arxiv.org/html/2511.17689) | 评分标准驱动的迭代改进循环 | ⭐⭐ verify → fix → verify 循环的理论基础 |

**最佳实践: 3-5 个并行 Agent 是 sweet spot**（超过后合并复杂度吃掉收益）。我们的典型订单 2-5 个供应商，正好在这个范围。

**实施建议**: P0 先串行（简单可靠），P2 再加并行。并行时每个 Agent 用独立 `SessionLocal()` 和独立 `InquiryWorkbook`，共享 `stream_key` 但 SSE 事件带 `supplier_id` 区分。

### 8.6 Agent Observability

| 模式 | 来源 | 核心思路 | 适用性 |
|------|------|----------|--------|
| OpenTelemetry AI Spans | [OpenTelemetry](https://opentelemetry.io/blog/2025/ai-agent-observability/) | 标准化 trace: prompts, tool calls, latency, cost | ⭐⭐ P2 可考虑 |
| Langfuse | [Langfuse](https://langfuse.com/) | 开源自托管，严格数据治理 | ⭐⭐ P2 可选 |
| AgentOps | [AgentOps](https://www.agentops.ai/) | Session replays, 400+ framework 集成 | ⭐ 对我们过重 |

**实施建议**: 当前 `on_step` callback + SSE 已提供基本 observability。P2 可在 `on_step` 中添加 token usage 统计，写入 `inquiry_data.suppliers[sid].token_usage`。

### 8.7 Workflow vs Agent 决策框架

> **Anthropic 2026 Guidance**: Workflows（预定义代码路径）适合可预测任务；Agents（LLM 动态决策）适合开放式问题。趋势是 "Digital Assembly Lines" — 人类引导的多步骤工作流，多 Agent 端到端执行。

我们的设计落在二者之间:
- **Orchestrator**: Workflow（确定性的供应商分组、模板匹配、文件保存）
- **Per-Supplier Agent**: Agent（语义映射、格式转换、质量检查）

这符合 Anthropic 的建议: "确定的事情用 workflow，不确定的事情用 agent。"

---

## 九、参考资料

1. [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — Multi-session architecture
2. [Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — Tool design principles
3. [Claude Agent Skills Documentation](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) — Progressive disclosure
4. [Claude Code Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction) — Automatic context compression
5. [Google Gemini Thought Signatures](https://ai.google.dev/gemini-api/docs/thought-signatures) — Reasoning state preservation
6. [Factory.ai: Compressing Context](https://factory.ai/news/compressing-context) — Structured summarization (4.04 accuracy)
7. [Microsoft LLMLingua](https://github.com/microsoft/LLMLingua) — 20x compression with 1.5% loss
8. [Microsoft Agent Mode for Excel](https://techcommunity.microsoft.com/blog/excelblog/building-agent-mode-in-excel/4457320) — Validation-first pattern
9. [IBM STRATUS Rollback](https://research.ibm.com/blog/undo-agent-for-cloud) — Undo operators for agent actions
10. [LangGraph Memory System](https://docs.langchain.com/oss/python/langgraph/persistence) — State-driven memory with checkpointers
11. [CrewAI Memory Architecture](https://docs.crewai.com/en/concepts/memory) — Unified memory with adaptive scoring
12. [ARISE: Rubric-Guided Document Generation](https://arxiv.org/html/2511.17689) — Multi-agent refinement loop
13. [Azure AI Agent Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) — Orchestration patterns
14. [OpenTelemetry AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/) — Distributed tracing standards
15. [Tool Design Best Practices](https://composio.dev/blog/how-to-build-tools-for-ai-agents-a-field-guide) — Parameter design, error handling
16. [Retry Patterns 2025](https://sparkco.ai/blog/mastering-retry-logic-agents-a-deep-dive-into-2025-best-practices) — Exponential backoff + jitter
17. [Claude Sub-Agent Best Practices](https://claudefa.st/blog/guide/agents/sub-agent-best-practices) — 67% token reduction via isolation

---

## 十、风险与缓解

| 风险 | 缓解策略 | 参考 |
|------|----------|------|
| Agent 选模板选错 | Agent 选择后立即推送 preview，用户可看到并选择重做 | STRATUS: 不可逆操作前校验 |
| per-supplier 并行时 DB 竞争 | 每个 agent 用独立 SessionLocal()（已有此模式） | ADK Parallel: 状态隔离 |
| verify 代码检查规则不全 | 无法代码检查的注解标记为 "unchecked"，Agent 自行判断 | ARISE: rubric 驱动验证 |
| inquiry_data 结构变更影响前端 | 保留 generated_files flat list 向后兼容 | — |
| 新旧 SSE 事件格式不兼容 | 前端 onStep 已有 else 分支，新事件类型自然兼容 | — |
| Agent 在修正循环中卡死 | engine 的 loop_threshold=3 + max_turns=20 自动终止 | Retry Best Practices: circuit breaker |
| Gemini 升级到 3.0 后 Thought Signatures 必须传回 | `_parse_response()` 预留 thought_signature 字段 | Google Thought Signatures |
| compact 摘要丢失关键信息 | 用结构化模板（分节强制保留），workbook 本身作为 state checkpoint | Factory.ai: structured summarization |
| 单供应商超时 (>60s) | Orchestrator 设 per-supplier timeout，超时标记 error 不阻塞其他供应商 | Durable execution pattern |
