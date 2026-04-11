# Tool 与 Skill 设计原则

> 日期: 2026-04-09
> 目的: 统一团队对 Tool 和 Skill 的理解, 指导未来设计

---

## Tool 是什么

**Tool 是 Agent 操作世界的手。** 每个 Tool 是一个原子操作 — 做一件事, 做完返回结果。

### 设计原则

1. **Per-Resource, Not Per-Operation**
   - 好: `manage_order(action="overview"|"products"|"update_match")`
   - 坏: `get_order_overview()` + `get_order_products()` + `update_match_result()`
   - 原因: Anthropic 研究表明 30+ tools 准确率显著下降; per-resource 减少 tool 数量

2. **一个 Tool 做一件事, 但可以有多个 action**
   - action 参数路由到内部 helper 函数
   - 对外是 1 个 tool, 对内是多个函数
   - description 中包含示例调用 (准确率 72% → 90%)

3. **Tool 不决定流程, Agent 决定流程**
   - Tool 不应该内部调用其他 tool
   - Tool 不应该硬编码 "下一步做什么"
   - Tool 只做被要求做的事, 返回结果, Agent 决定下一步

4. **Tool 结果必须 informative**
   - 返回足够信息让 Agent 做判断
   - 不只是 "成功", 而是 "成功: 94 个产品提取, 匹配率 92%, 5 个未匹配"
   - Agent 基于这些信息决定是否继续

5. **Tool 内部做校验, 但不做决策**
   - 好: `generate_inquiry` 内部检查 match_results 非空, 空则返回错误
   - 坏: `generate_inquiry` 内部自动调用 match_products (这是 Agent 的决策)

6. **Fields JSON 参数用于扩展**
   - 固定参数: `action`, `order_id` (LLM 必须填)
   - 可变参数: `fields` (JSON string, 按 action 不同内容不同)
   - 加新字段不改 tool 签名

### 当前 Tool 清单

| Tool | 资源 | 核心 action | 状态 |
|------|------|------------|------|
| `manage_order` | Order | overview, products, update_match | Core |
| `manage_inquiry` | Order.inquiry | check, fill_gaps, generate | Deferred |
| `manage_fulfillment` | Order.fulfillment | get, update, record_delivery, attach | Deferred |
| `manage_upload` | UploadBatch | prepare, execute, rollback | Deferred |
| `parse_upload` | File → UploadBatch | (单一操作) | Deferred |
| `query_db` | 任意表 | (单一操作: SELECT) | Core |
| `get_db_schema` | information_schema | (单一操作) | Core |
| `modify_excel` | workspace 文件 | read, write, format, list | Core |
| `think` | 无 | (单一操作) | Core |
| `calculate` | 无 | (单一操作) | Core |
| `ask_clarification` | 无 | (HITL 暂停) | Core |
| `request_confirmation` | 无 | (HITL 暂停) | Core |
| `use_skill` | Skills | (单一操作) | Core |
| `manage_todo` | 内存 | add, update, clear, read | Deferred |
| `bash` | 文件系统 | (单一操作) | Deferred |
| `search_product_database` | products 表 | (单一操作) | Deferred |

### 即将新增的 Tool

| Tool | 资源 | 做什么 | 为什么需要 |
|------|------|--------|-----------|
| `extract_order` | Order + PDF file | Gemini 原生 PDF 提取 | Agent 需要能触发和观察提取过程 |
| `match_products` | Order.products → match_results | 产品匹配 (代码+LLM) | Agent 需要能触发匹配并审核结果 |

---

## Skill 是什么

**Skill 是 Agent 知道该怎么干活的工作流模板。** Skill 不执行代码, 只注入指令到 Agent 的上下文。

### Skill vs Tool 的区别

| | Tool | Skill |
|---|---|---|
| **本质** | 操作 (做事) | 知识 (知道怎么做) |
| **执行** | 代码执行, 有副作用 | 注入 prompt, 无副作用 |
| **调用方** | Agent 通过 function_call | Agent 通过场景匹配自动注入, 或 use_skill 手动调用 |
| **输出** | 数据 (JSON, 文本, 文件) | 无输出 (只改变 Agent 的行为) |
| **类比** | 手 (操作世界) | 大脑中的 SOP (标准操作流程) |

### 设计原则

1. **Skill 是建议, 不是命令**
   - Agent 参考 Skill 的步骤, 但可以根据上下文调整
   - Skill 写 "Step 1: 检查提取结果", Agent 看到结果没问题可以跳过

2. **Skill 包含异常处理指引**
   - 不只是 happy path
   - "如果产品数=0 → 告知用户提取失败, 建议重新上传"
   - "如果匹配率 < 80% → 列出未匹配产品, 问用户是否手动处理"

3. **Skill 引用 Tool, 不重新实现**
   - 好: "调用 manage_order(action='products', order_id=N)"
   - 坏: "用 SQL 查询 v2_orders 表的 products 字段" (这是 Tool 的事)

4. **一个 Skill 对应一个用户意图**
   - `process-order`: "处理这个订单" (端到端)
   - `generate-inquiry`: "生成询价单" (单步)
   - `modify-inquiry`: "改一下询价单" (迭代)

5. **Skill 包含 "自动推进 + 异常暂停" 指引**
   - 正常情况: Agent 自动推进到下一步, 不等用户确认
   - 异常情况: Agent 暂停, 报告问题, 等用户决策
   - 这避免了 "每步都问用户" 的低效模式

6. **Skill 的加载是 lazy 的**
   - Level 1: 只有 name + description 在 system prompt (~100 tokens)
   - Level 2: 完整内容在场景匹配时注入 (~1000 tokens)
   - Level 3: 引用文件在需要时加载 (0 idle cost)

### 当前 + 计划中的 Skill 清单

| Skill | 意图 | 自动推进规则 | 暂停条件 |
|-------|------|------------|---------|
| `process-order` | **新** — 处理新订单 | 提取OK→自动匹配→自动检查询价就绪 | 产品数=0; 匹配率<80%; 缺必填字段 |
| `query-data` | 查询数据 | N/A (交互式) | N/A |
| `generate-inquiry` | 生成询价单 | check OK→自动generate | blocking gap; 无模板 |
| `data-upload` | 上传产品数据 | parse→prepare (自动) | 低置信度匹配; execute 前必须确认 |
| `modify-inquiry` | 修改询价单 | N/A (交互式) | N/A |
| `fulfillment` | 履约管理 | N/A (交互式) | N/A |

---

## 未来使用指南

### 加新 Tool 的 checklist
1. 它操作什么资源? → 看能否合入现有的 manage_* tool (加 action)
2. 如果不能合入 → 新建 tool, 遵循 per-resource 模式
3. 写 description + 示例调用 (准确率差 18%)
4. 标记是否 concurrency-safe
5. 注册到 `__init__.py`, 决定 core 还是 deferred
6. 更新 TOOL_META (display_name, group, prompt_description)

### 加新 Skill 的 checklist
1. 对应什么用户意图? → 一个意图一个 Skill
2. 写清楚 happy path 步骤 (引用 Tool 名, 不写 SQL)
3. 写清楚异常处理 (什么情况暂停, 暂停时告知用户什么)
4. 写清楚自动推进规则 (什么情况不等用户)
5. 放在 `skills/{name}/SKILL.md`
6. 如果有 scenario 关键词匹配, 更新 `scenarios.py`

### Tool + Skill 协作模式
```
用户: "处理这个订单"
  ↓
Scenario 检测 → "process-order"
  ↓
Skill 注入 → Agent 知道流程: extract → match → inquiry
  ↓
Agent 调 Tool: extract_order(order_id=123)
  ↓
Tool 返回: "94 个产品, PO=XYZ, 交货日期=4/23"
  ↓
Agent 判断: 产品数 > 0, metadata 完整 → 自动推进
  ↓
Agent 调 Tool: match_products(order_id=123)
  ↓
Tool 返回: "匹配率 92%, 8 个未匹配"
  ↓
Agent 判断: 匹配率 > 80% → 自动推进, 但报告未匹配列表
  ↓
Agent: "匹配完成, 8 个产品未匹配 [列表]. 要生成询价吗?"
  ↓
用户: "生成吧"
  ↓
Agent 调 Tool: manage_inquiry(action="generate", order_id=123)
```
