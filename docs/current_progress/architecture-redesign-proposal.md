# 架构改版提案 — Agent-Centric 两层架构

> 状态: 待讨论
> 日期: 2026-04-09

---

## 目标

从 "Agent 是按钮" → "Agent 是大脑"。Agent 编排整个订单处理流程, 而非后台硬编码管道自动跑完。

## 两层架构

```
┌──────────────────────────────────────────────────┐
│  Layer 1: 文档标准化层                             │
│                                                    │
│  输入: PDF (暂时只支持 PDF)                         │
│  处理: Gemini 2.5 Flash 原生 PDF                   │
│  输出: { order_metadata, products[] }              │
│  特点: 一次调用, JSON 保证合法, 不理解业务           │
└───────────────────────┬──────────────────────────┘
                        │ 结构化数据
                        ▼
┌──────────────────────────────────────────────────┐
│  Layer 2: Agent + Tools                           │
│                                                    │
│  Agent 拿到 Layer 1 的输出后, 决定:                │
│  ├── 数据完整吗? → 缺什么, 问用户补充              │
│  ├── 需要匹配产品 → 调 match_products tool         │
│  ├── 匹配结果好吗? → 审核, 异常报告给用户          │
│  ├── 可以生成询价? → 调 generate_inquiry tool      │
│  └── 用户要改? → 调 modify_excel tool              │
│                                                    │
│  Tools 是独立的原子操作                             │
│  Skills 是工作流模板 (Agent 参考但不被绑定)         │
│  Agent 的决策基于上下文, 不是 if-elif-else          │
└──────────────────────────────────────────────────┘
```

---

## 具体改什么, 为什么

### 改动 1: 拆 order_processor.py 的硬编码管道

**现在**: `process_order()` 是一个 ~200 行的函数, 按顺序执行 提取→匹配→分析→询价预分析, 全部在后台线程自动跑完。

**改为**: 拆成独立 tools, Agent 编排。

| 现在的步骤 | 改为 Tool | 理由 |
|-----------|-----------|------|
| smart_extract() | `extract_order` tool | Agent 能看到提取结果, 判断是否需要重试 |
| run_agent_matching() | `match_products` tool | Agent 能在匹配后审核, 发现低置信度主动报告 |
| run_anomaly_check() | 合入 `match_products` 的后处理 | 异常检测不需要独立 tool |
| run_financial_analysis() | 合入 `manage_order(action="analyze")` | 按需调用, 不自动 |
| run_inquiry_pre_analysis() | 合入 `manage_inquiry(action="check")` | 已有, 不需要自动预分析 |

**关键变化**: 用户上传 PDF 后, 不再自动跑全流程。而是:
1. Layer 1 提取 (自动, ~90s) → 写入 Order.extraction_data + products
2. Agent 接管 → 审核提取结果 → 决定下一步

### 改动 2: 新增 `extract_order` tool

**参数**: `order_id` (从已上传的 Order 读取 file_bytes)
**内部逻辑**: 调用 `_gemini_native_pdf_extract()` (已有)
**输出**: 结构化的 metadata + products + 数值验证结果
**Agent 用途**: 看到提取结果后判断 — "94 个产品, PO 号 XYZ, 交货日期 4/23" → 继续; "0 个产品" → 报告问题

### 改动 3: 新增 `match_products` tool

**参数**: `order_id`
**内部逻辑**: 调用现有的 `run_agent_matching()` (不改)
**输出**: 匹配统计 + 低置信度产品列表
**Agent 用途**: "匹配率 92%, 8 个未匹配" → 用 `search_product_database` 补充; "匹配率 100%" → 直接进入询价

### 改动 4: 简化上传流程

**现在**: `POST /orders/upload` → 后台线程跑 `process_order()` 全流程
**改为**: `POST /orders/upload` → 只做 Layer 1 (提取) → status="extracted" → Agent 接管

```python
# 现在 (routes/orders.py)
background: process_order(order_id, file_bytes)  # 提取+匹配+分析 全部

# 改为
background: extract_order(order_id, file_bytes)  # 只做提取
# Agent 通过 chat 决定何时匹配, 何时生成询价
```

### 改动 5: 新增订单处理 Skill

```markdown
---
name: process-order
description: 处理新上传的订单 (提取→审核→匹配→询价)
---

# 订单处理流程

## Step 1: 检查提取结果
调用 manage_order(action="overview", order_id=N)
- 产品数 > 0? metadata 完整?
- 如果有问题 → 告知用户具体缺什么

## Step 2: 匹配产品
调用 match_products(order_id=N)
- 匹配率 > 90%? → 继续
- 有未匹配产品? → 展示列表, 问用户是否手动匹配

## Step 3: 生成询价
调用 manage_inquiry(action="check", order_id=N)
- 所有供应商 ready? → generate
- 有 blocking gap? → 列出缺失字段, 问用户
```

### 不改什么

| 组件 | 为什么不改 |
|------|-----------|
| ReActAgent engine (engine.py) | 已经稳定, 中间件链完善 |
| 14 个 tools 的 per-resource 设计 | 已经是最佳实践 |
| Skill 系统 | 已经工作, 只需加新 skill |
| 中间件链 | 不需要改 |
| 数据库 schema | Order 模型的 JSON 列足够灵活 |
| 前端 | 前端有订单页面和 chat, 都不需要改 |
| 询价生成逻辑 (inquiry_agent.py) | 内部逻辑不改, 只是从"后台自动触发"变为"Agent 触发" |

---

## 数据流变化

### 现在
```
上传 → [后台: 提取→匹配→分析] → ready → 用户审核(前端) → chat: "生成询价" → Agent 触发
```

### 改后
```
上传 → [后台: 提取] → extracted → Agent: "提取完成, 94 个产品, 要匹配吗?"
                                  → 用户: "匹配吧"
                                  → Agent: match_products → "匹配率 95%, 5 个未匹配"
                                  → 用户: "OK 生成询价"
                                  → Agent: generate_inquiry → "3 份询价单已生成"
```

**关键区别**: Agent 在每一步后都和用户对话, 用户始终知道发生了什么。不再是黑盒。

---

## 文件放置

| 文件 | 位置 | 变化 |
|------|------|------|
| `extract_order` tool | `services/tools/order_extraction.py` | **新文件** |
| `match_products` tool | `services/tools/product_matching.py` | 已有, 改为 tool 包装 |
| `process-order` skill | `skills/process-order/SKILL.md` | **新文件** |
| `order_processor.py` | 不变位置 | 内部函数保留, 只是不再被 routes 直接调用全流程 |
| `routes/orders.py` | 不变位置 | `POST /upload` 只做提取, 不跑匹配 |
| `services/tools/__init__.py` | 不变位置 | 注册新 tools |

---

## 风险和缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Agent 多轮对话比自动管道慢 | 用户等待时间从 90s 变为 ~3-5min (含人工确认) | Agent 可以自动推进 ("提取完成, 自动匹配中..."), 只在发现问题时暂停 |
| Agent 可能跳步或忘记步骤 | 产品没匹配就生成询价 | Skill 引导 + tool 内部校验 (generate_inquiry 前检查 match_results 非空) |
| 现有 API (前端调用) 依赖 status 流转 | 前端期望 uploading→extracting→matching→ready | 保持 status 流转, 但 matching 和 ready 由 Agent 触发, 不是自动 |

---

## 执行顺序

| 步骤 | 做什么 | 依赖 | 预计时间 |
|------|--------|------|---------|
| 1 | 新建 `extract_order` tool | 无 | 1h |
| 2 | 新建 `match_products` tool | 无 | 1h |
| 3 | 改 `routes/orders.py` — upload 后只做提取 | Step 1 | 30min |
| 4 | 新建 `process-order` skill | Step 1+2 | 30min |
| 5 | 注册新 tools 到 registry | Step 1+2 | 15min |
| 6 | 端到端测试: 上传 PDF → Agent 对话 → 匹配 → 生成询价 | Step 1-5 | 1h |

总计: ~4-5 小时

---

## 待讨论

1. **自动模式 vs 交互模式**: Agent 是每步都等用户确认, 还是可以自动推进 (只在异常时暂停)?
2. **前端适配**: 前端的订单详情页现在显示 status="matching"/"ready", 如果 Agent 控制流转, 前端需要感知吗?
3. **并发**: 多个用户同时上传多个订单, 每个都需要 Agent 对话吗? 还是支持批量?
