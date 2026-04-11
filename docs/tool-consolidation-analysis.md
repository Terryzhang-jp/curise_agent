# Tool 合并分析 — v2-backend 从 ~40 个到 ~18 个

> 日期: 2026-04-08
> 输入: Anthropic 官方指南 + 学术研究 + 行业案例 + Decision 001 参考 + v2-backend 实际工具审计
> 目标: 确定是否合并、怎么合并、合并后的具体形态

---

## 1. 关键证据

| 来源 | 核心数据点 |
|------|----------|
| **Anthropic 官方** ("Writing Tools for Agents") | "Instead of get_customer_by_id + list_transactions, implement get_customer_context" — 按 workflow 合并, 不按 operation 拆 |
| **Anthropic Tool Search 文档** | "Claude 的工具选择准确率在超过 **30-50 个工具**时显著下降" |
| **Anthropic Advanced Tool Use** | Tool Search 使 Opus 4 准确率从 **49% → 74%**; Tool Use Examples 使准确率从 **72% → 90%** |
| **Vercel d0** (文本→SQL agent) | 16 tools → ~3 tools: 成功率 **80% → 100%**, 延迟 274s → 77s (3.5x), token **-37%**, 步骤 **-42%** |
| **Letta V1** (MemGPT 重构) | 废弃 `send_message` 和 `request_heartbeat` 控制流工具 — "staying in-distribution relative to LLM training data" |
| **Claude Code** | ~12 核心工具常驻 + 其余全部 deferred, MCP 工具超过 context 10% 时自动启用 tool search |

**核心结论**: 30 个以上工具准确率下降是 Anthropic 的官方声明, 不是观点。我们有 ~40 个注册工具, 虽然 deferred loading 缓解了部分问题, 但合并仍有明确收益。

---

## 2. v2-backend 当前状态

### 2.1 工具分布

**业务工具 (21 个):**

| 领域 | 当前工具 | 数量 |
|------|---------|------|
| 订单 | get_order_overview, get_order_products, update_match_result | 3 |
| 询价 | check_inquiry_readiness, fill_inquiry_gaps, generate_inquiries | 3 |
| 数据上传 | parse_file, analyze_columns, resolve_and_validate, create_references, preview_changes, execute_upload, prepare_upload, rollback_batch, audit_data | **9** |
| 履约 | get_order_fulfillment, update_order_fulfillment, record_delivery_receipt, attach_order_file | 4 |
| 查询 | query_db, get_db_schema | 2 |

**通用工具 (19 个):**

| 领域 | 当前工具 | 数量 |
|------|---------|------|
| 推理 | think | 1 |
| Shell | bash | 1 |
| 文件 | read_file, write_file, list_files, edit_file | 4 |
| Web | web_fetch, web_search | 2 |
| 搜索 | grep, glob_search | 2 |
| 工具 | calculate, get_current_time | 2 |
| 任务 | todo_write, todo_read | 2 |
| 交互 | ask_clarification, request_confirmation | 2 |
| 技能 | use_skill | 1 |
| Excel | modify_excel | 1 |
| 产品 | search_product_database | 1 |

**总计: ~40 个注册工具**

### 2.2 当前缓解措施

我们已经有 deferred loading + scenario scoping:
- **核心工具 (9 个常驻)**: think, query_db, get_db_schema, get_order_overview, calculate, get_current_time, ask_clarification, request_confirmation, modify_excel
- **其余 ~31 个**: deferred, 需要 `tool_search` 激活

所以 LLM 在任一时刻通常只看到 9-15 个工具 (核心 + 场景激活的)。**准确率问题部分已被缓解**, 但不完全:
- 用户说"帮我处理这个订单", agent 需要激活 inquiry + order 工具 = 12-15 个可见
- 数据上传场景: 9 个上传工具全部激活 = 18+ 个可见 → **超过准确率甜点**

### 2.3 合并的真实动机

不只是准确率。更重要的是:

1. **加字段不改 tool**: 当前 `update_match_result` 的参数是固定的 (`order_id, product_index, new_product_code`)。如果未来要加"匹配置信度"字段, 需要改 tool 签名。用 `fields` JSON 参数则不需要。
2. **场景裁剪更简单**: 当前每个场景需要列出 8-12 个允许的工具名。合并后只需 4-5 个。
3. **数据上传最痛**: 9 个工具, LLM 必须串联 5-7 步, 经常出错。合并成 1 个带 action 参数的工具, 错误面更小。

---

## 3. 合并方案

### 3.1 按资源合并的 4 个业务工具

#### `manage_order` (3→1)

```
之前: get_order_overview + get_order_products + update_match_result
之后: manage_order(action="overview"|"products"|"update_match", order_id=123, fields='{"product_index": 3, "new_code": "ABC"}')
```

**为什么合并**: 三个工具都操作同一个资源 (v2_orders), 共享 order_id 参数, 逻辑内聚。
**action 枚举**: `overview` | `products` | `update_match`
**fields JSON 参数**: update_match 时使用, 未来加 `update_metadata` 无需改签名。

#### `manage_inquiry` (3→1)

```
之前: check_inquiry_readiness + fill_inquiry_gaps + generate_inquiries
之后: manage_inquiry(action="check"|"fill_gaps"|"generate", order_id=123, fields='{"supplier_id": 5, "field_values": {"H8": "2026/04/15"}}')
```

**为什么合并**: 三步是一个连贯 workflow, 总是 check → fill → generate。
**额外收益**: agent 更容易理解这是一个流程 (一个工具的三个 action) 而非三个独立工具。

#### `manage_upload` (9→2)

```
之前: parse_file + analyze_columns + resolve_and_validate + create_references + preview_changes + execute_upload + prepare_upload + rollback_batch + audit_data
之后:
  - parse_upload(file_bytes, column_mapping) — 解析入口 (保持独立, 因为需要 file_bytes 二进制参数)
  - manage_upload(action="prepare"|"execute"|"rollback"|"preview"|"analyze"|"audit"|"create_refs", batch_id=123)
```

**为什么拆成 2 而非 1**: `parse_file` 接收二进制文件, 和其余操作参数类型不同。强行塞进一个 action 会导致参数混乱。
**最大收益**: 从 9 个工具降到 2 个, 减少 7 个工具的选择负担。

#### `manage_fulfillment` (4→1)

```
之前: get_order_fulfillment + update_order_fulfillment + record_delivery_receipt + attach_order_file
之后: manage_fulfillment(action="get"|"update"|"record_delivery"|"attach_file", order_id=123, fields='{"status": "delivered", "items": [...]}')
```

**为什么合并**: 四个操作都是同一个 v2_orders 的履约生命周期。

### 3.2 通用工具合并

#### `manage_files` (4→1)

```
之前: read_file + write_file + list_files + edit_file
之后: manage_files(action="read"|"write"|"list"|"edit", path="...", content="...", old_string="...", new_string="...")
```

**为什么合并**: Claude Code 虽然分开了 (Read, Write, Edit), 但那是因为 CLI 需要不同的 permission check。我们的 B2B 后端不需要逐个审批, 合并更简洁。

#### `manage_todo` (2→1)

```
之前: todo_write + todo_read
之后: manage_todo(action="add"|"update"|"clear"|"read", task="...", task_id=1, status="done")
```

#### 保持不变的工具 (已经是 atomic/distinct)

| 工具 | 为什么不合并 |
|------|-----------|
| query_db | 已经是 per-resource (任意 SQL), 不能再泛化 |
| get_db_schema | 与 query_db 互补但职责不同 |
| bash | 已经是 atomic |
| modify_excel | 已经是 4-action 合一模式, 就是 Decision 001 推荐的模式 |
| web_fetch / web_search | 两个的参数和返回完全不同, 合并反而混淆 |
| grep / glob_search | 同上 |
| calculate | atomic |
| use_skill | atomic |
| ask_clarification / request_confirmation | 两个的 HITL 行为不同 (ask=暂停等回答, confirm=暂停等按钮), 不合并 |
| search_product_database | 独立搜索, 不属于任何资源 CRUD |
| delegate | 子 agent 委派, 独立 |
| think | 见下方讨论 |

### 3.3 `think` 工具的去留

**Letta 的建议**: 废弃控制流工具, "staying in-distribution relative to LLM training data"。

**我们的 `think` 不是纯控制流** — 它是一个**质量检查门禁** (检测 issues 后强制修复)。但说实话:
- Gemini/Kimi 自带 extended thinking (thinking_budget=2048)
- `think` 工具的 issue 检测逻辑 (正则匹配 "- 问题:", "缺失") 很粗糙
- 强制调 think 会增加 1 轮 tool call, 浪费 token

**决策**: 保留 `think`, 但从"强制每 4 轮调用"降级为"agent 自主决定何时调用"。去掉 engine.py 中的 think enforcement 注入。

---

## 4. 合并后的工具清单

| # | 工具名 | 类型 | 合并来源 | 核心/Deferred |
|---|--------|------|---------|-------------|
| 1 | **manage_order** | 业务 | overview + products + update_match | 核心 (替代 get_order_overview) |
| 2 | **manage_inquiry** | 业务 | check + fill + generate | Deferred |
| 3 | **parse_upload** | 业务 | parse_file (二进制入口) | Deferred (文件上传时激活) |
| 4 | **manage_upload** | 业务 | prepare + execute + rollback + 5个子步骤 | Deferred |
| 5 | **manage_fulfillment** | 业务 | get + update + delivery + attach | Deferred |
| 6 | query_db | 查询 | 不变 | 核心 |
| 7 | get_db_schema | 查询 | 不变 | 核心 |
| 8 | search_product_database | 搜索 | 不变 | Deferred |
| 9 | think | 推理 | 不变 (降级为可选) | 核心 |
| 10 | bash | Shell | 不变 | Deferred |
| 11 | **manage_files** | 文件 | read + write + list + edit | Deferred |
| 12 | modify_excel | Excel | 不变 | 核心 |
| 13 | web_fetch | Web | 不变 | Deferred |
| 14 | web_search | Web | 不变 | Deferred |
| 15 | grep | 搜索 | 不变 | Deferred |
| 16 | glob_search | 搜索 | 不变 | Deferred |
| 17 | calculate | 工具 | 不变 | 核心 |
| 18 | **manage_todo** | 任务 | write + read | Deferred |
| 19 | use_skill | 技能 | 不变 | 核心 |
| 20 | ask_clarification | 交互 | 不变 | 核心 |
| 21 | request_confirmation | 交互 | 不变 | 核心 |
| 22 | delegate | 子Agent | 不变 | 核心 (有注册的子agent时) |

**核心 (常驻): 10 个** — manage_order, query_db, get_db_schema, think, modify_excel, calculate, use_skill, ask_clarification, request_confirmation, delegate
**Deferred: 12 个** — manage_inquiry, parse_upload, manage_upload, manage_fulfillment, search_product_database, bash, manage_files, web_fetch, web_search, grep, glob_search, manage_todo

**总计: 22 个 (从 ~40 个)**, 其中核心 10 个 (从 9 个, 变化不大)。

---

## 5. 与 Decision 001 的对比

| 维度 | Decision 001 (生活助手) | v2-backend (供应链) |
|------|----------------------|-------------------|
| 初始工具数 | 30 | ~40 |
| 合并后 | ~14 | ~22 |
| 最大合并 | task 4→1 | upload 9→2 |
| `fields` JSON | 所有 manage_* | 仅 update 类 action 使用 |
| 控制流工具 | 保留 | think 降级为可选 |
| Deferred loading | 无 (30 个都常驻) | 有 (12 个 deferred) |

**关键差异**: Decision 001 的系统没有 deferred loading, 所以 30 个工具全部常驻 = 准确率问题严重。我们有 deferred loading, 准确率问题已部分缓解。因此我们的合并动机更多是**维护性**和**可扩展性**, 不仅仅是准确率。

---

## 6. 实施优先级

| 优先级 | 合并项 | 收益 | 工作量 |
|--------|--------|------|--------|
| **P0** | upload 9→2 (parse_upload + manage_upload) | 最大收益: 减少 7 个工具, 数据上传场景从 18+ 可见降到 12 | 大 — 需要重写 data_upload.py 的 register() |
| **P1** | fulfillment 4→1 | 减少 3 个工具 | 中 — 参数合并, 逻辑不变 |
| **P1** | order 3→1 | 减少 2 个工具 | 中 |
| **P2** | inquiry 3→1 | 减少 2 个工具, 但这 3 个已经是清晰 workflow | 中 |
| **P2** | files 4→1, todo 2→1 | 减少 5 个工具 | 小 |

**建议**: 先做 P0 (upload 合并), 跑两周观察, 再做 P1。不要一次性改所有。

---

## 7. 不应该做的

| 看起来该做 | 为什么不做 |
|-----------|----------|
| 把 query_db + get_db_schema 合并为一个 | query_db 接受 SQL 字符串, get_db_schema 接受表名 — 参数类型完全不同, 合并反而混淆 |
| 把 ask_clarification + request_confirmation 合成 `manage_interaction` | 两者的 HITL 行为完全不同: ask 暂停等文字回复, confirm 暂停等按钮点击。合并后 LLM 不知道该用哪个 action |
| 把 web_fetch + web_search 合成 `manage_web` | 一个接 URL 返回内容, 一个接关键词返回列表 — 完全不同的输入输出 |
| 做 1 个超级 `execute_tool` 路由所有操作 | Anthropic 明确反对: "If a human engineer cannot definitively say which tool should be used, an agent cannot be expected to do better" — generic routing 会让 LLM 迷失 |
| 完全删除 think | 我们的 think 有质量检查功能 (issue 检测), 不只是 reasoning |

---

## 8. `fields` JSON 参数设计

参考 Decision 001 的核心设计:

```python
manage_order(
    action="update_match",
    order_id=123,
    fields='{"product_index": 3, "new_product_code": "ABC123", "confidence": "high"}'
)
```

**规则**:
- `action` 和 `order_id` 是固定参数 (LLM 必须填)
- `fields` 是 JSON 字符串, 内容按 action 不同而变化
- 工具 description 中列出每个 action 的 fields schema
- 加新字段只改: migration + Pydantic model + 工具内部路由 — **不改 tool 签名**

**风险**: Anthropic 研究指出 "JSON schemas define what's structurally valid, but can't express usage patterns"。`fields` JSON 的内部结构对 LLM 来说是黑盒, 可能导致参数填错。

**缓解**: 在 tool description 中用 **Tool Use Examples** 展示典型调用 (Anthropic 数据: 准确率从 72% → 90%)。
