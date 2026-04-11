# Agent 架构 — 当前状态 (2026-04-09)

## 系统定位

邮轮供应链 B2B 内部系统。用户是采购/业务人员。核心价值: 把供应商发来的订单 PDF 变成可发出去的询价 Excel。

## Agent 在系统中的角色

```
┌──────────────────────────────────────────────┐
│                   用户                        │
│            (采购人员, 非开发者)                 │
│                ↕ Chat (SSE)                   │
├──────────────────────────────────────────────┤
│              CruiseAgent (主 Agent)            │
│                                              │
│  ┌─ 14 个 Tools ─────────────────────────┐   │
│  │ manage_order    (订单查看/匹配修改)    │   │
│  │ manage_inquiry  (询价检查/补齐/生成)   │   │
│  │ manage_fulfillment (履约管理)          │   │
│  │ manage_upload   (数据上传)             │   │
│  │ query_db        (SQL 查询)             │   │
│  │ get_db_schema   (表结构)               │   │
│  │ modify_excel    (Excel 编辑)           │   │
│  │ think / calculate / use_skill / ...    │   │
│  └───────────────────────────────────────┘   │
│                                              │
│  ┌─ 5 个 Skills ─────────────────────────┐   │
│  │ query-data      (SQL 查询指南)         │   │
│  │ generate-inquiry (询价生成流程)         │   │
│  │ data-upload     (数据上传流程)          │   │
│  │ fulfillment     (履约管理流程)          │   │
│  │ modify-inquiry  (询价修改流程)          │   │
│  └───────────────────────────────────────┘   │
│                                              │
│  Engine: ReActAgent (engine.py, 900+ 行)     │
│  LLM: Kimi K2.5 (chat) / Gemini 2.5 (提取)  │
│  Middleware: 9 个 (安全/记忆/压缩/循环检测等)  │
├──────────────────────────────────────────────┤
│              后端服务 (非 Agent)               │
│                                              │
│  order_processor.py  — 订单提取+匹配          │
│  inquiry_agent.py    — 询价 Excel 生成        │
│  template_engine.py  — 确定性模板填充          │
│  excel_writer.py     — Excel 底层操作         │
│                                              │
│  这些服务 Agent 可以触发 (通过 tools)          │
│  但内部逻辑不走 Agent 循环                     │
└──────────────────────────────────────────────┘
```

## 核心矛盾

**Agent 只是入口, 核心业务逻辑在 Agent 之外。**

| 功能 | Agent 参与度 | 实际执行者 |
|------|-----------|-----------|
| 订单提取 | 0% (后台自动) | order_processor.py → Gemini 原生 PDF |
| 产品匹配 | 0% (后台自动) | order_processor.py → 代码+LLM |
| 匹配审核 | 10% (可查看/修改) | manage_order 工具 |
| 询价生成 | 5% (触发) | inquiry_agent.py → template_engine |
| 询价修改 | 80% (Agent 主导) | modify_excel 工具 |
| 数据查询 | 100% (Agent 主导) | query_db 工具 |
| 数据上传 | 60% (Agent 引导) | manage_upload → data_upload.py |
| 履约管理 | 90% (Agent 主导) | manage_fulfillment 工具 |

**订单提取和询价生成 — 系统最核心的两个功能 — Agent 几乎不参与。**

用户上传 PDF → 后台自动处理 → 结果出来 → 用户在前端审核 → 在 chat 里说"生成询价" → Agent 调一个工具 → 工具内部跑完所有逻辑。

Agent 在这里是一个**按钮**, 不是一个**大脑**。

## 如果要让 Agent 成为核心 (harness agent)

需要回答的问题:

1. **提取阶段**: Agent 应该能观察提取过程、发现问题、自主修正吗? 还是继续让后台服务自动跑?

2. **匹配阶段**: Agent 应该主动审核匹配结果 (不等用户来问) 吗? 发现低置信度匹配时主动提醒?

3. **询价阶段**: Agent 应该理解模板、决定填什么、验证填得对不对吗? 还是继续当一个触发按钮?

4. **整体**: 用户的理想体验是什么? "上传一个 PDF, Agent 从头到尾处理, 我只需要最后审批"? 还是"每一步都要我确认"?

## 文件清单

| 目录 | 核心文件 | 行数 | 职责 |
|------|---------|------|------|
| `services/` | `order_processor.py` | ~1350 | 提取+匹配 (Gemini native PDF + 代码匹配) |
| `services/` | `inquiry_agent.py` | ~1518 | 询价 Excel 生成 (per-supplier 并行) |
| `services/` | `template_engine.py` | ~602 | 确定性模板填充 |
| `services/` | `excel_writer.py` | ~300 | Excel 底层操作 |
| `services/agent/` | `engine.py` | ~920 | ReActAgent 主循环 |
| `services/agent/` | `tool_registry.py` | ~278 | Tool 注册+执行 |
| `services/agent/` | `hooks.py` | ~176 | 中间件链 |
| `services/tools/` | `__init__.py` | ~160 | Tool 注册编排 |
| `services/tools/` | `order_overview.py` | ~200 | manage_order 工具 |
| `services/tools/` | `inquiry_workflow.py` | ~445 | manage_inquiry 工具 |
| `services/tools/` | `fulfillment.py` | ~200 | manage_fulfillment 工具 |
| `services/tools/` | `data_upload.py` | ~2755 | manage_upload (最大文件) |
| `routes/` | `chat.py` | ~1100 | Chat API + SSE |
| `routes/` | `orders.py` | ~500 | 订单 REST API |
