# 后端目录结构文档

> 更新日期：2026-04-11
> 对应 commit：Phase A/B/C 重构后的最终结构

---

## 顶层目录

```
v2-backend/
├── main.py
├── requirements.txt
├── Dockerfile
├── .dockerignore / .gcloudignore / .gitignore
├── env_vars.yaml
│
├── core/               # 应用基础设施（数据库、模型、鉴权）
├── routes/             # HTTP 接口层
├── services/           # 业务逻辑层（按领域分组）
│   ├── agent/          # Agent 引擎与 LLM 集成
│   ├── documents/      # 文档处理
│   ├── templates/      # 模板系统
│   ├── orders/         # 订单 + 询价
│   ├── excel/          # Excel 读写
│   ├── data/           # 数据抽取与标准化
│   ├── integrations/   # 外部系统集成
│   ├── common/         # 通用基础工具
│   ├── tools/          # Agent 可调用的业务工具
│   ├── extraction/     # PDF 提取管道
│   └── projection/     # 数据投影转换
├── migrations/         # 数据库 SQL 迁移文件
├── skills/             # （已移至 services/agent/skills/）
├── templates/          # Excel 模板静态文件
├── tests/              # 测试套件
└── uploads/            # 用户上传文件（运行时）
```

---

## 根文件

| 文件 | 说明 |
|------|------|
| `main.py` | FastAPI 应用入口，注册所有路由、CORS、限速中间件，初始化数据库连接 |
| `requirements.txt` | Python 依赖列表 |
| `Dockerfile` | Cloud Run 容器构建，基于 python:3.11-slim |
| `env_vars.yaml` | Google Cloud Run 环境变量配置 |

---

## `core/` — 应用基础设施

启动时必须加载的核心模块，被整个后端广泛引用。

| 文件 | 说明 |
|------|------|
| `core/config.py` | Settings 配置管理，读取 .env，包含数据库 URL、JWT 密钥、Gemini/Kimi/DeepSeek/OpenAI API 密钥、LINE Bot 配置 |
| `core/database.py` | SQLAlchemy 引擎和 Session 工厂，管理 PostgreSQL 连接池，提供 `get_db` 依赖注入 |
| `core/models.py` | 所有 SQLAlchemy ORM 模型定义（User、Order、SupplierTemplate、Document、AgentSession 等数十张表） |
| `core/schemas.py` | Pydantic 请求/响应 Schema（登录、Token、FieldDefinition 等），用于 FastAPI 接口的序列化和校验 |
| `core/security.py` | 密码 bcrypt 哈希、JWT 创建与校验、RefreshToken 管理、`require_role` 角色权限装饰器 |

---

## `routes/` — HTTP 接口层

每个文件对应一组业务接口，挂载到 FastAPI app。

| 文件 | 说明 |
|------|------|
| `routes/auth.py` | 登录、Token 刷新、修改密码、登出接口 |
| `routes/chat.py` | 通用 AI 对话接口，SSE 流式输出，支持文件上传，加载工具和 Skills，调用 Agent 引擎 |
| `routes/data.py` | 主数据 CRUD（国家、港口、分类、供应商、商品、汇率） |
| `routes/documents.py` | 文档上传与处理，自动触发 PDF 提取和订单投影 |
| `routes/excel.py` | Excel 文件解析和单元格位置探测，供模板分析使用 |
| `routes/line_webhook.py` | LINE Messaging Platform Webhook，验证签名并分发 Follow/Message 事件到 LINE Bot 服务 |
| `routes/orders.py` | 订单全生命周期接口：Excel 上传、提取、产品匹配、询价生成、履约跟踪 |
| `routes/settings.py` | 管理员设置：FieldSchema、供应商模板、公司配置、模板分析触发 |
| `routes/tool_settings.py` | AI 工具和 Skill 的启用/禁用管理，支持从 TOOL_META 自动发现工具列表 |
| `routes/users.py` | 超级管理员用户管理（创建、列表、更新、禁用、重置密码） |

---

## `services/agent/` — Agent 引擎

核心 AI 执行层，实现 ReAct 循环和多 LLM 提供商支持。

### 引擎核心

| 文件 | 说明 |
|------|------|
| `engine.py` | ReAct Agent 主循环：多轮推理、工具调用、循环检测、HITL 暂停，支持流式输出 |
| `config.py` | Agent 和 LLM 配置，支持 Gemini / OpenAI / DeepSeek / Kimi 多提供商切换 |
| `chat_storage.py` | 对话历史的 PostgreSQL 持久化，双写引擎消息和展示消息 |
| `memory_storage.py` | 无 DB 依赖的内存 Session 存储，用于一次性 Agent 任务 |
| `scenarios.py` | 场景化工具范围限定，减少 LLM 工具选择空间，提升准确率 |
| `sub_agent.py` | 子 Agent 委派框架，支持超时控制、递归保护和并发执行 |
| `tool_context.py` | Agent 和工具共享的可变状态容器，包含 Skill 系统支持 |
| `tool_registry.py` | 工具注册中心，支持延迟加载和权限规则 |
| `tracer.py` | LLM 调用 Token 用量与成本估算追踪 |
| `hooks.py` | 6 钩子中间件系统（before_agent / before_model / after_model / before_tool / after_tool / after_agent） |
| `stream_queue.py` | 线程安全的事件队列注册表，用于 Agent → SSE 流式推送 |
| `storage.py` | Agent 消息历史的 ORM 存储层（双写） |
| `error_utils.py` | 结构化错误识别，含中文翻译和恢复提示 |

### LLM 提供商 (`llm/`)

| 文件 | 说明 |
|------|------|
| `llm/base.py` | 抽象 LLMProvider 接口，定义 FunctionCall、ToolDeclaration 数据结构 |
| `llm/openai_provider.py` | OpenAI SDK 封装，支持工具调用和 Extended Thinking |
| `llm/gemini_provider.py` | Google Gemini SDK 封装，指数退避重试，原生 PDF 支持 |
| `llm/deepseek_provider.py` | DeepSeek OpenAI 兼容 API 封装，支持 Thinking 模式 |
| `llm/kimi_provider.py` | Moonshot Kimi K2.5 提供商，工具调用准确率约 93% |

### 中间件 (`middlewares/`)

| 文件 | 说明 |
|------|------|
| `middlewares/clarification.py` | 拦截 ask_clarification 工具调用，触发 HITL 暂停等待用户输入 |
| `middlewares/completion_verification.py` | 神经符号护栏，检测 Gemini 执行幻觉（声称完成但未实际调用工具） |
| `middlewares/error_recovery.py` | 追踪连续工具失败次数，注入针对性的恢复提示 |
| `middlewares/guardrail.py` | 可插拔安全策略系统，基于提供商的允许/拒绝决策 |
| `middlewares/loop_detection.py` | 检测并打破工具调用循环，使用顺序无关的批哈希算法 |
| `middlewares/memory.py` | 用户级长期记忆系统，支持 TTL 过期和 LRU 淘汰 |
| `middlewares/subagent_limit.py` | 子 Agent 治理（并发数、递归深度、超时限制） |
| `middlewares/summarization.py` | 监控 Token 用量，触发上下文自动压缩 |
| `middlewares/workspace_state.py` | 在 LLM 调用前注入工作区文件列表（DeerFlow 上传中间件模式） |

### Prompts (`prompts/`)

| 文件 | 说明 |
|------|------|
| `prompts/builder.py` | 从可组合层（身份、能力、约束）拼装最终 System Prompt |
| `prompts/layers.py` | 定义各提示层的纯函数（身份、能力、领域知识、约束规则） |

### Agent 工具 (`tools/`)

Agent 在推理循环中可直接调用的工具。

| 文件 | 说明 |
|------|------|
| `tools/clarification.py` | structured ask_clarification 工具，触发 HITL 暂停代替直接提问 |
| `tools/excel.py` | Excel 操作工具（read / write / format 三个 action） |
| `tools/filesystem.py` | 工作区文件操作（分页读取、写入、列表、编辑） |
| `tools/mcp_client.py` | MCP (Model Context Protocol) stdio 客户端，管理外部工具服务进程 |
| `tools/reasoning.py` | think 工具，结构化思考 + 质量复核的问题驱动模式 |
| `tools/search.py` | grep 和 glob_search 工具，基于 ripgrep 搜索文件内容 |
| `tools/shell.py` | Bash 命令执行，白名单安全控制（允许前缀 + 禁止元字符） |
| `tools/skill.py` | Skill 调用工具，展开可复用 Prompt 模板并注入执行指令 |
| `tools/todo.py` | 任务列表管理（add / update / clear / read），用于多步骤追踪 |
| `tools/utility.py` | 数学计算和当前时间获取工具 |
| `tools/web.py` | 网页抓取和搜索工具，HTML 转纯文本 |

### Skills (`skills/`)

纯 Markdown 的可复用 Prompt 模板，由 `use_skill` 工具加载执行。

| 目录 | 说明 |
|------|------|
| `skills/data-upload/` | 数据上传工作流指令（Excel → 暂存 → 校验 → 执行） |
| `skills/generate-inquiry/` | 询价单生成工作流 |
| `skills/modify-inquiry/` | 修改已有询价单 |
| `skills/process-document/` | 处理上传文档（提取 → 投影 → 关联订单） |
| `skills/process-order/` | 处理采购订单（提取 → 匹配 → 询价） |
| `skills/fulfillment/` | 订单履约跟踪工作流 |
| `skills/query-data/` | 数据查询工作流 |

---

## `services/documents/` — 文档处理

| 文件 | 说明 |
|------|------|
| `document_processor.py` | Stage 1 提取入口，将 PDF 转换为通用块 Schema（ExtractedDocument） |
| `document_workflow.py` | 原子性文档上传：Blob 存储 + DB 事务 + 补偿回滚 |
| `document_order_projection.py` | 将提取的文档数据投影为标准 PO 格式，含货币标准化 |
| `document_context_package.py` | 为聊天构建文档上下文信息（已检测字段、产品列表） |
| `pdf_analyzer.py` | 基于 Gemini Vision 的 PDF 结构分析，用于模板发现和创建 |

---

## `services/templates/` — 模板系统

| 文件 | 说明 |
|------|------|
| `template_engine.py` | Compose-from-scratch Excel 渲染器（从不修改原文件，创建新工作簿） |
| `template_engine_legacy.py` | 旧版行变异模板引擎（向后兼容保留） |
| `template_analyzer.py` | Gemini 分析 Excel 模板，发现字段位置和产品表布局 |
| `template_analysis_agent.py` | Agent 驱动的模板深度分析 |
| `template_matcher.py` | 多信号级联模板匹配（指纹 → 来源公司 → 关键词 IDF） |
| `template_contract.py` | 模板契约定义与校验 |
| `template_generator.py` | 模板生成工具 |
| `template_style_extractor.py` | 从现有模板提取样式（字体、颜色、边框）供新模板复用 |
| `zone_config_builder.py` | 从 AI 分析结果和 openpyxl 结构扫描自动生成 ZoneConfig |
| `zone_config_schema.py` | ZoneConfig Schema 定义与 Pydantic 校验 |

---

## `services/orders/` — 订单与询价

| 文件 | 说明 |
|------|------|
| `order_processor.py` | Vision 提取 + Agent 产品匹配，含元数据标准化和异常检测 |
| `inquiry_agent.py` | 单次 LLM 调用询价生成器，JSON 模式 + 确定性格式强制 |

---

## `services/excel/` — Excel 读写

| 文件 | 说明 |
|------|------|
| `excel_parser.py` | 解析 Excel 文件，提取表头、样本行、文件指纹，供 Settings Center 使用 |
| `excel_writer.py` | Excel 写入器，支持模板填充或通用布局生成 |

---

## `services/data/` — 数据抽取与标准化

| 文件 | 说明 |
|------|------|
| `schema_extraction.py` | Schema 驱动的大文档 PDF 批量提取 |
| `field_schema.py` | Schema 驱动的询价模板字段解析与缺口分析 |
| `product_normalizer.py` | 产品数据标准化（名称清洗、单位归一、格式统一） |

---

## `services/integrations/` — 外部集成

| 文件 | 说明 |
|------|------|
| `line_bot.py` | LINE Bot 服务，用户映射、Session 管理、Agent 调用 |
| `weather_service.py` | 基于 Open-Meteo（免费无需 Key）的天气和海洋预报，用于交货环境分析 |

---

## `services/common/` — 通用基础工具

| 文件 | 说明 |
|------|------|
| `file_storage.py` | Supabase Storage 封装，本地文件系统回退（向后兼容） |
| `workspace_manager.py` | 工作区文件跨 Session 持久化，含版本控制和恢复功能 |

---

## `services/tools/` — Agent 可调用业务工具

供 Agent 在执行任务时直接调用的领域工具，通过 ToolRegistry 注册。

| 文件 | 说明 |
|------|------|
| `registry_loader.py` | 从 TOOL_META 自动发现并注册工具元数据 |
| `_security.py` | 行级所有权范围限定，防止跨租户数据访问（安全审计修复） |
| `product_search.py` | 关键词产品数据库搜索 |
| `product_matching.py` | 两级产品匹配（精确编码匹配 → 模糊 LLM 匹配） |
| `order_query.py` | `get_db_schema` 和 `query_db` 工具，供 Agent SQL 查询使用 |
| `order_matching.py` | Agent 触发的产品匹配编排 |
| `order_extraction.py` | Agent 可调用的 Gemini 原生 PDF 提取 |
| `order_overview.py` | 合并 `manage_order` 工具（overview / products / update_match） |
| `inquiry_workflow.py` | 合并 `manage_inquiry` 工具（readiness / fill_gaps / generate） |
| `data_upload.py` | 数据上传管道：暂存 → 校验 → 缺口分析 → 原子执行 |
| `confirmation.py` | `request_confirmation` 工具，在高影响操作前触发 HITL 确认 |
| `document_order.py` | `manage_document_order` 工具，将文档投影为订单 |
| `fulfillment.py` | `manage_fulfillment` 工具，订单生命周期管理（已发询价 → 已报价 → 已确认 → 交付中） |

---

## `services/extraction/` — PDF 提取管道

| 文件 | 说明 |
|------|------|
| `base.py` | 抽象提取器接口（bytes → ExtractedDocument），明确定义失败类型 |
| `gemini_block.py` | Gemini 2.5 Flash 单次调用 PDF 提取器，最大支持 1M 输入 Token |
| `schema.py` | 通用块 Schema 和提取统计结构定义 |

---

## `services/projection/` — 数据投影

| 文件 | 说明 |
|------|------|
| `purchase_order.py` | 将通用 ExtractedDocument 投影为标准 PO 结构（向后兼容） |

---

## `migrations/` — 数据库迁移

手动 SQL 迁移文件，按编号顺序执行。

| 范围 | 文件编号 |
|------|----------|
| 基础设施（Agent、管道表） | 001–005 |
| 工具/Skill 配置 | 006 |
| 财务数据、模板、履约 | 007–009 |
| LINE 集成、索引、约束 | 010–012 |
| 订单模板集成、交货环境 | 013–014 |
| 供应商模板绑定、多供应商 | 016–017 |
| 订单备注、文档 Schema | 018–019 |
| 模板状态、港口日期、供应商扩展 | 020–022 |
| Agent 基础设施、Session 上下文、记忆 | 023–025 |
| 文档基础（提取状态、文档表、关联订单） | 026–030 |

---

## `templates/` — Excel 模板静态文件

| 文件 | 说明 |
|------|------|
| `purchase_order_template.xlsx` | 日文询价单 Excel 模板 |
| `purchase_order_template_en.xlsx` | 英文询价单 Excel 模板 |
| `purchase_order_template_analysis.json` | 日文模板的分析元数据（字段位置、ZoneConfig） |
| `purchase_order_template_en_analysis.json` | 英文模板的分析元数据 |

---

## `tests/` — 测试套件

415 个测试用例，覆盖 Agent 引擎、提取管道、模板系统、文档工作流、询价生成等核心路径。

---

*此文档由 Claude Code 在后端重构（Phase A/B/C）后自动生成，反映当前真实目录结构。*
