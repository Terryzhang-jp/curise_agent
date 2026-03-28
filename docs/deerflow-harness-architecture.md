# DeerFlow 2.0 Harness Architecture — 完整技术文档

> 来源：[bytedance/deer-flow](https://github.com/bytedance/deer-flow)（37k+ stars, MIT License）
> 版本：2.0（harness/app 拆分后）

---

## 1. 整体分层：Harness vs App

DeerFlow 强制执行**单向依赖边界**：

```
App（FastAPI 网关、Slack/Telegram/飞书）
  │
  ▼  import
Harness（可独立发包：deerflow-harness）
  ├── agents/        Agent 编排 + 状态
  ├── config/        16 个 Pydantic 配置模块
  ├── guardrails/    授权拦截
  ├── mcp/           MCP 客户端、缓存、OAuth
  ├── models/        模型工厂 + patch
  ├── sandbox/       本地沙箱
  ├── skills/        SKILL.md 解析、加载
  ├── subagents/     子 agent 执行器、注册、配置
  ├── tools/         工具聚合 + 内置工具
  ├── uploads/       文件上传管理
  ├── community/     Tavily, Firecrawl, Jina 等
  └── utils/         可读性、网络、文件转换
```

**CI 强制**：`tests/test_harness_boundary.py` 确保 Harness 代码不 import App 代码。违反则构建失败。

**包配置**：`pyproject.toml` — 名称 `deerflow-harness`，Python ≥3.12，核心依赖 `langchain>=1.2.3`、`langgraph`、`langchain-anthropic`、`langchain-openai`、`agent-client-protocol>=0.4.0`、`duckdb`、`markitdown`。

---

## 2. Agent 创建与执行循环

### 2.1 入口：DeerFlowClient

`client.py` 提供两个接口：
- `chat()` — 同步单次调用
- `stream()` — 生成器，yield SSE 事件

**懒初始化**：agent 在首次使用时创建，配置元组 `(model, thinking_mode, plan_mode, subagent_enabled)` 作为缓存 key，参数变化时自动重建。

### 2.2 make_lead_agent()

`agents/lead_agent/agent.py` — 核心工厂函数：

```python
def make_lead_agent(config, ...):
    # 1. 解析模型
    model_name = _resolve_model_name(config)

    # 2. 加载自定义 agent 配置（如有）
    agent_config = load_agent_config(agent_name)

    # 3. 创建 LLM
    model = create_chat_model(
        name=model_name,
        thinking_enabled=...,
        reasoning_effort=...
    )

    # 4. 组装工具（4 来源）
    tools = get_available_tools(
        model_name=model_name,
        groups=config.tool_groups,
        subagent_enabled=...
    )

    # 5. 构建中间件链（见第 3 节）
    middlewares = _build_middlewares(config, model_name, agent_name)

    # 6. 组装 system prompt
    system_prompt = apply_prompt_template(
        subagent_enabled=...,
        max_concurrent_subagents=...,
        agent_name=...
    )

    # 7. 创建 LangGraph agent
    return create_agent(
        model=model,
        tools=tools,
        middleware=middlewares,
        system_prompt=system_prompt,
        state_schema=ThreadState,
        checkpointer=checkpointer
    )
```

### 2.3 ThreadState（状态 Schema）

继承 LangGraph 的 `AgentState`（自带 `messages` + `add_messages` reducer），扩展字段：

| 字段 | 类型 | Reducer | 说明 |
|------|------|---------|------|
| `messages` | list[BaseMessage] | `add_messages` | 继承自 AgentState |
| `sandbox` | SandboxState \| None | — | 沙箱 ID |
| `thread_data` | ThreadDataState \| None | — | workspace/uploads/outputs 路径 |
| `title` | str \| None | — | 自动生成的对话标题 |
| `artifacts` | list[str] | `merge_artifacts` | 去重合并（dict.fromkeys） |
| `todos` | list[dict] \| None | — | plan 模式任务列表 |
| `uploaded_files` | list[str] \| None | — | 已上传文件句柄 |
| `viewed_images` | dict[str, ViewedImageData] | `merge_viewed_images` | `{}` = 清空信号 |

**关键设计**：使用 `Annotated` 类型提示定义自定义 reducer，实现智能合并而非简单替换。`viewed_images` 的 "空字典=清空" 模式特别值得注意。

### 2.4 工具组装

`tools/tools.py` — `get_available_tools()` 从 4 个来源聚合：

1. **配置定义的工具**：`app_config.tool_groups` 过滤后加载
2. **内置工具**：`present_file_tool`、`ask_clarification_tool`、视觉模型加 `view_image_tool`
3. **子 agent 工具**：`subagent_enabled=True` 时加入 `task_tool`
4. **MCP 工具**：`get_cached_mcp_tools()`
5. **ACP 工具**：Agent Coordination Protocol（如配置）
6. **tool_search 元工具**：`tool_search.enabled` 时加入运行时工具发现

Deferred tool registry 每次请求重置（`reset_deferred_registry()`），基于 `ContextVar` 隔离请求。

---

## 3. 中间件链（核心架构）

### 3.1 生命周期钩子

每个中间件可以 hook 以下 6 个点：

| 钩子 | 时机 | 典型用途 |
|------|------|----------|
| `before_agent` | 整个 agent 循环开始前 | 初始化资源（沙箱、目录） |
| `before_model` | 每次 LLM 调用前 | 修改消息、注入上下文 |
| `wrap_model_call` | 包裹 LLM 调用 | 修改请求参数（工具过滤） |
| `after_model` | 每次 LLM 响应后 | 检测循环、限制子 agent、生成标题 |
| `wrap_tool_call` | 包裹工具调用 | 授权、错误处理、中断 |
| `after_agent` | 整个 agent 循环结束后 | 清理资源、触发记忆保存 |

### 3.2 完整中间件链（16 个，按顺序）

#### #1 ThreadDataMiddleware
- **钩子**：`before_agent`
- **作用**：创建线程级目录结构
- **逻辑**：从 runtime context 或 LangGraph config 提取 `thread_id`，创建 `{base_dir}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`
- **必须第一**：所有其他中间件依赖 thread_id

#### #2 UploadsMiddleware
- **钩子**：`before_agent`
- **仅限 Lead Agent**
- **逻辑**：从 `additional_kwargs.files` 提取文件元数据，区分新/历史上传，向最后一条 HumanMessage 前置 `<uploaded_files>` 块（含文件大小、路径 `/mnt/user-data/uploads/{filename}`）
- **安全**：路径遍历验证

#### #3 SandboxMiddleware
- **钩子**：`before_agent`（eager）或延迟（lazy）
- **逻辑**：通过 `get_sandbox_provider().acquire(thread_id)` 获取沙箱，在 `after_agent` 释放
- **Lazy 模式**：延迟到第一次工具调用时才获取

#### #4 DanglingToolCallMiddleware ⭐
- **钩子**：`wrap_model_call` / `awrap_model_call`
- **仅限 Lead Agent**
- **问题**：如果 agent 在 tool_call 中间断开（断网、超时），消息历史中会留下没有对应 ToolMessage 的 AIMessage，导致 LLM 上下文损坏
- **逻辑**：
  1. 扫描所有 AIMessage 的 `tool_calls`
  2. 检查每个 tool_call 是否有对应的 ToolMessage
  3. 对孤立的 tool_call，插入合成的 `ToolMessage(content="[Tool call was interrupted...]", status="error")`
  4. 通过 `request.override(messages=patched)` 原地修改模型请求

#### #5 GuardrailMiddleware
- **钩子**：`wrap_tool_call` / `awrap_tool_call`
- **逻辑**：在工具执行前调用 `GuardrailProvider.evaluate(request)`
  - deny → 返回错误 ToolMessage + 原因码
  - provider 错误 → `fail_closed=True` 阻止调用；`fail_closed=False` 允许并警告
- **内置 Provider**：`AllowlistProvider`（`allowed_tools` / `denied_tools` 集合）
- **保留 `GraphBubbleUp`** 异常不拦截（LangGraph 控制流）

#### #6 ToolErrorHandlingMiddleware
- **钩子**：`wrap_tool_call` / `awrap_tool_call`
- **逻辑**：catch 所有异常（除 `GraphBubbleUp`），构建错误 ToolMessage：`"Error: Tool '{name}' failed with {ExcClass}: {detail[:500]}. Continue with available context..."`
- **截断**：错误详情最多 500 字符

#### #7 SummarizationMiddleware
- **来源**：LangChain 内置
- **条件**：`summarization.enabled` 时启用
- **逻辑**：token 超限时自动压缩历史消息为摘要

#### #8 TodoMiddleware（extends TodoListMiddleware）
- **钩子**：`before_model` / `abefore_model`
- **条件**：`is_plan_mode=True` 时启用
- **逻辑**：检测 `write_todos` tool call 是否被 SummarizationMiddleware 截断。如果 todos 存在于 state 但 `write_todos` 调用从消息历史消失，注入 `HumanMessage(name="todo_reminder")` 附带当前 todo 列表：`"- [status] content"`
- **Prompt**：plan 模式下注入约 100 行规划指令

#### #9 TokenUsageMiddleware
- **钩子**：`after_model` / `aafter_model`
- **条件**：`token_usage.enabled` 时启用
- **逻辑**：从最后一条消息的 `usage_metadata` 提取 input/output/total tokens，日志记录，fallback 显示 "?"

#### #10 TitleMiddleware
- **钩子**：`after_model` / `aafter_model`
- **逻辑**：
  1. 检查：启用了标题生成 + 尚无标题 + 至少 1 条用户消息 + 1 条助手消息
  2. 调用 LLM 生成标题
  3. 失败时 fallback：截取用户第一条消息前 50 字符 + "..."

#### #11 MemoryMiddleware
- **钩子**：`after_agent` / `aafter_agent`（后执行）
- **逻辑**：
  1. 过滤消息：只保留用户输入和最终助手响应（剔除 tool messages、中间步骤、上传文件块）
  2. 验证至少 1 条用户 + 1 条助手消息
  3. 入队 `MemoryUpdateQueue` 进行异步 LLM 提取
- **Per-agent 隔离**：如果提供 `agent_name`，单独存储记忆

#### #12 ViewImageMiddleware
- **钩子**：`before_model` / `abefore_model`
- **条件**：模型支持视觉时启用
- **逻辑**：检测已完成的 `view_image` tool call，创建 `HumanMessage` 附带 base64 编码图片数据块
- **去重**：防止同一图片重复注入

#### #13 DeferredToolFilterMiddleware ⭐
- **钩子**：`wrap_model_call` / `awrap_model_call`
- **条件**：`tool_search.enabled` 时启用
- **逻辑**：
  1. 从 `DeferredToolRegistry` 获取被延迟的工具名列表
  2. 从 `request.tools` 中移除这些工具的 schema（LLM 看不到）
  3. ToolNode 仍保留所有工具（执行不受影响）
  4. agent 通过 `tool_search` 元工具在运行时发现并激活
- **效果**：大幅减少 token 消耗和 LLM 混淆

#### #14 SubagentLimitMiddleware ⭐
- **钩子**：`after_model` / `aafter_model`
- **条件**：`subagent_enabled` 时启用
- **常量**：
  - `MIN_SUBAGENT_LIMIT = 2`
  - `MAX_SUBAGENT_LIMIT = 4`
  - 默认 `MAX_CONCURRENT_SUBAGENTS = 3`
- **逻辑**：
  1. 统计 AIMessage 中 `name == "task"` 的 tool call 数量
  2. 如果超过 `max_concurrent`，只保留前 N 个，丢弃剩余
  3. `_clamp_subagent_limit()` 强制范围 [2, 4]
- **关键设计**：**代码硬卡**，不依赖 prompt。prompt 中也有限制文字，但中间件是真正的执行者

#### #15 LoopDetectionMiddleware ⭐⭐⭐
- **钩子**：`after_model` / `aafter_model`
- **常量**：
  ```
  _DEFAULT_WARN_THRESHOLD = 3     # 3 次重复 → 注入警告
  _DEFAULT_HARD_LIMIT = 5         # 5 次重复 → 强制停止
  _DEFAULT_WINDOW_SIZE = 20       # 滑动窗口大小
  _DEFAULT_MAX_TRACKED_THREADS = 100  # LRU 线程上限
  ```

**哈希算法**：
```python
def _hash_tool_calls(tool_calls):
    # 1. 标准化每个 tool call 为 {name, args}
    normalized = [{"name": tc.name, "args": tc.args} for tc in tool_calls]
    # 2. 按 (name, json.dumps(args, sort_keys=True)) 排序 → 顺序无关
    normalized.sort(key=lambda x: (x["name"], json.dumps(x["args"], sort_keys=True, default=str)))
    # 3. 整体 JSON → MD5 → 取前 12 位
    return hashlib.md5(json.dumps(normalized).encode()).hexdigest()[:12]
```

**执行逻辑**：

| 重复次数 | 动作 |
|----------|------|
| < 3 | 无操作 |
| = 3（首次触发） | 注入 `HumanMessage("[LOOP DETECTED] You are repeating the same tool calls. Stop calling tools and produce your final answer now...")` — **单次警告，同一 hash 不再重复** |
| ≥ 5 | 从 AIMessage 中删除所有 `tool_calls=[]`，追加 `"[FORCED STOP] ..."` 到 content，强制文本输出 |

**线程管理**：
- `OrderedDict` 实现 LRU 淘汰（最多 100 线程）
- `_warned` dict 追踪每个线程中已警告的 hash（单次触发）
- `threading.Lock` 保证线程安全
- `reset(thread_id=None)` 清理追踪数据

**关键决策**：警告使用 `HumanMessage` 而非 `SystemMessage`，因为 **Anthropic 模型不支持对话中间出现非连续的 SystemMessage**（issue #1299 报告的崩溃问题）。

#### #16 ClarificationMiddleware（始终最后）
- **钩子**：`wrap_tool_call` / `awrap_tool_call`
- **逻辑**：拦截 `ask_clarification` 工具调用，格式化带类型图标的澄清请求，创建 ToolMessage，返回 `Command` 更新消息并跳转到 `END`（暂停等待用户输入）
- **必须最后**：确保其他中间件先处理完

---

## 4. 子 Agent 系统（Subagent）

### 4.1 SubagentConfig

```python
@dataclass
class SubagentConfig:
    name: str                                   # 如 "general-purpose"
    description: str                            # 能力描述
    system_prompt: str                          # 子 agent 系统提示
    tools: list[str] | None = None              # 工具白名单（None = 继承全部）
    disallowed_tools: list[str] | None = ["task"]  # 工具黑名单（防递归）
    model: str = "inherit"                      # "inherit" 或指定模型名
    max_turns: int = 50                         # 最大对话轮次
    timeout_seconds: int = 900                  # 15 分钟超时
```

### 4.2 双线程池执行

`subagents/executor.py` — `SubagentExecutor`：

```
Lead Agent
  │
  │ task() tool call
  ▼
┌──────────────────┐
│ Scheduler Pool   │  3 workers, prefix "subagent-scheduler-"
│ (调度层)         │
└────────┬─────────┘
         │ submit()
         ▼
┌──────────────────┐
│ Execution Pool   │  3 workers, prefix "subagent-exec-"
│ (执行层)         │
└────────┬─────────┘
         │ _aexecute()
         ▼
┌──────────────────┐
│ Sub-Agent        │  LangGraph agent with reduced middleware
│ (子 agent 实例)  │
└──────────────────┘
```

**执行流程**：
1. `_filter_tools()` — 应用白名单/黑名单过滤工具
2. `_create_agent()` — 创建子 agent，使用精简中间件（ThreadData + Sandbox + Guardrail + ToolErrorHandling，**不含** Uploads、DanglingToolCall 等）
3. `_build_initial_state()` — 传递父级的 sandbox/thread_data
4. `_aexecute()` — 通过 `agent.astream()` 以 `stream_mode="values"` 流式执行，收集 AI 消息（按 ID 去重），从最后一条 AIMessage 提取最终文本
5. `execute_async()` — 提交到 scheduler pool → execution pool + 超时

**状态生命周期**：

```
PENDING → RUNNING → COMPLETED / FAILED / TIMED_OUT
```

**结果追踪**：
- `SubagentResult` dataclass：`task_id`、`trace_id`、status enum、`ai_messages` list
- 全局 `_background_tasks` dict + Lock
- `cleanup_background_task()` 只清理终态任务

### 4.3 Task Tool

`tools/builtins/task_tool.py`：
- 委托给 `SubagentExecutor.execute_async()`
- **每 5 秒轮询**一次完成状态
- 安全超时 = 执行超时 + 60 秒
- 流式进度事件（start → running → completion）

### 4.4 内置子 Agent

| 名称 | 用途 | 禁用工具 | 轮次上限 | 模型 |
|------|------|----------|----------|------|
| general-purpose | 复杂多步任务 | task, ask_clarification, present_files | 50 | 继承父级 |
| bash | 命令执行专家 | — | 50 | 继承父级 |

**核心安全机制**：子 agent **不能派发子 agent**（`task` 在黑名单中），从根本上防止递归炸弹。

---

## 5. 记忆系统（Memory）

### 5.1 存储层

`agents/memory/storage.py`：

- **抽象接口**：`MemoryStorage` — `load()`, `reload()`, `save()`
- **文件实现**：`FileMemoryStorage`
  - Per-agent JSON 文件
  - mtime 缓存（避免不必要的磁盘读取）
  - 原子写入（通过临时文件）
  - 路径遍历验证

**记忆结构**：
```json
{
  "version": 1,
  "created_at": "...",
  "updated_at": "...",
  "user_context": {
    "work": "...",
    "personal": "...",
    "top_of_mind": "..."
  },
  "history": {
    "tier1_recent": [...],
    "tier2_important": [...]
  },
  "facts": [
    {
      "content": "用户是数据科学家",
      "confidence": 0.9,
      "source": "explicit_statement",
      "created_at": "..."
    }
  ]
}
```

### 5.2 LLM 提取器

`agents/memory/updater.py` — `MemoryUpdater`：

1. 格式化对话 → LLM prompt
2. LLM 返回结构化 JSON（新事实、更新的上下文摘要）
3. 应用到存储

**事实管理**：
- 置信度评分 0.0-1.0
- 去重：通过标准化比较
- 最大数量修剪
- 可配置的置信度阈值

**置信度层级**：
| 来源 | 置信度 |
|------|--------|
| 用户明确陈述 | 0.9+ |
| 强烈暗示 | 0.7-0.8 |
| 推断的模式 | 0.5-0.6 |

**清理**：`_strip_upload_mentions_from_memory()` — 移除临时文件引用，防止过时记忆

### 5.3 防抖队列

`agents/memory/queue.py` — `MemoryUpdateQueue`：

- `ConversationContext` dataclass：thread_id、messages、timestamp、agent_name
- 同一 thread_id 的新上下文**替换**旧的（不累积）
- **30 秒防抖**：避免频繁 LLM 调用
- 更新之间有速率限制延迟
- `flush()` 方法支持立即处理

### 5.4 Prompt 注入

`agents/memory/prompt.py`：

- 使用 tiktoken 进行 token 预算计算（有 fallback）
- `format_memory_for_injection()` 尊重 token 限制
- 优先注入高置信度事实
- 注入格式：`<memory>` 标签包裹

---

## 6. 技能系统（Skills）

### 6.1 数据结构

```python
@dataclass
class Skill:
    name: str
    description: str
    license: str
    file_paths: list[str]
    category: str          # "public" | "custom"
    enabled: bool

    def get_container_path(self):
        return f"/mnt/skills/{self.category}/{self.path}"
```

### 6.2 SKILL.md 解析

`skills/parser.py` — `parse_skill_file()`：
1. 读取 SKILL.md 文件
2. 通过正则提取 YAML front matter
3. 解析简单 key-value 对（不使用完整 YAML 解析器）
4. 返回 `Skill` 或 None

### 6.3 加载流程

`skills/loader.py` — `load_skills()`：
1. 递归扫描 `public/` 和 `custom/` 目录（确定性排序）
2. 逐个解析 SKILL.md
3. 从 `ExtensionsConfig.from_file()` 应用 enabled/disabled 配置（每次从磁盘读取最新）
4. 可选 filter：只返回 enabled 的

### 6.4 Prompt 注入

`lead_agent/prompt.py`：
- `get_skills_prompt_section()` — 列出可用技能及描述和容器路径
- **渐进式加载**：agent 只在需要时读取 SKILL.md 文件内容（节省 token）
- `get_deferred_tools_prompt_section()` — 生成 `<available-deferred-tools>` 注册表

---

## 7. 工具系统（Tools）

### 7.1 Deferred Tool Loading

`tools/builtins/tool_search.py`：

**DeferredToolRegistry**（基于 `ContextVar`，请求级隔离）：

```python
class DeferredToolRegistry:
    def register(tool):
        # 存储 DeferredToolEntry(name, description, tool)

    def search(query) -> list[DeferredToolEntry]:
        # 3 种查询形式：
        # 1. "select:name1,name2" → 精确名称匹配
        # 2. "+keyword rest"     → name 必须包含 keyword，按 rest 排序
        # 3. "keyword query"     → 正则匹配 name + description
        #    name 匹配得 2 分，description 匹配得 1 分
        # MAX_RESULTS = 5
```

**tool_search 工具**：
1. 调用 `registry.search(query)`
2. 对匹配的工具调用 `convert_to_openai_function()` 序列化为 JSON
3. 返回 JSON 数组

**工作流**：
```
初始状态：MCP 工具注册到 DeferredToolRegistry（LLM 看不到 schema）
     ↓
Agent 需要某工具：调用 tool_search("slack message")
     ↓
Registry 返回匹配工具的 schema
     ↓
下次 LLM 调用：DeferredToolFilterMiddleware 将已激活的工具加入 schema
     ↓
Agent 可以调用该工具
```

### 7.2 MCP 集成

`mcp/` 目录：

- **cache.py**：全局缓存 + 配置文件 mtime 失效。`get_cached_mcp_tools()` 处理 running/inactive/absent 事件循环（通过线程执行器）
- **tools.py**：`get_mcp_tools()` 初始化 `MultiServerMCPClient`，加载启用的服务器，注入 OAuth headers/拦截器。同步包装异步工具。10 worker 线程池 + shutdown hook
- **client.py**：MCP 客户端包装
- **oauth.py**：MCP 服务器 OAuth 集成

### 7.3 工具聚合流程

```
配置定义的工具
     +
内置工具（present_file, ask_clarification, view_image）
     +
task 工具（如果 subagent_enabled）
     +
MCP 工具：
  ├── tool_search 未启用 → 直接绑定到模型
  └── tool_search 启用   → 注册到 DeferredToolRegistry
     +                      DeferredToolFilterMiddleware 从模型 schema 中移除
ACP 工具                    ToolNode 仍保留所有工具用于执行
     +
tool_search 元工具（如果 enabled）
     ↓
最终工具列表 → create_agent()
```

---

## 8. 循环检测（Anti-Loop）— 完整实现

`agents/middlewares/loop_detection_middleware.py`

### 8.1 数据结构

```python
class LoopDetectionMiddleware:
    _lock: threading.Lock
    _thread_histories: OrderedDict[str, list[str]]  # thread_id → hash 列表
    _warned: dict[str, set[str]]                     # thread_id → 已警告的 hash 集合

    warn_threshold: int = 3
    hard_limit: int = 5
    window_size: int = 20
    max_tracked_threads: int = 100
```

### 8.2 哈希算法

```python
def _hash_tool_calls(tool_calls: list) -> str:
    """顺序无关的 tool call 指纹"""
    normalized = []
    for tc in tool_calls:
        normalized.append({
            "name": tc.name,
            "args": tc.args
        })

    # 排序使哈希与调用顺序无关
    normalized.sort(
        key=lambda x: (
            x["name"],
            json.dumps(x["args"], sort_keys=True, default=str)
        )
    )

    payload = json.dumps(normalized).encode()
    return hashlib.md5(payload).hexdigest()[:12]
```

### 8.3 检测逻辑

```python
def after_model(self, response, config):
    thread_id = get_thread_id(config)
    ai_message = response.messages[-1]

    if not ai_message.tool_calls:
        return response  # 无工具调用，跳过

    current_hash = _hash_tool_calls(ai_message.tool_calls)

    with self._lock:
        # LRU 淘汰
        if len(self._thread_histories) >= self.max_tracked_threads:
            self._thread_histories.popitem(last=False)

        history = self._thread_histories.setdefault(thread_id, [])
        history.append(current_hash)

        # 保持窗口大小
        if len(history) > self.window_size:
            history[:] = history[-self.window_size:]

        # 统计当前 hash 在窗口内出现次数
        count = history.count(current_hash)
        warned = self._warned.setdefault(thread_id, set())

    # 硬停止（优先级最高）
    if count >= self.hard_limit:
        ai_message.tool_calls = []  # 删除所有工具调用
        ai_message.content += "\n\n[FORCED STOP] Loop detected..."
        return response

    # 软警告（单次）
    if count >= self.warn_threshold and current_hash not in warned:
        warned.add(current_hash)
        # 注入 HumanMessage（不用 SystemMessage！Anthropic 兼容性）
        warning = HumanMessage(
            content="[LOOP DETECTED] You are repeating the same tool calls. "
                    "Stop calling tools and produce your final answer now. "
                    "If you cannot make progress, explain what you've tried."
        )
        response.messages.insert(-1, warning)  # 插在 AI 响应前

    return response
```

### 8.4 为什么用 HumanMessage

> Anthropic 模型（Claude）不支持对话中间出现非连续的 SystemMessage。如果在 user→assistant→system→assistant 的序列中插入 SystemMessage，API 会报错。使用 HumanMessage 避免这个问题。
> — GitHub Issue #1299

---

## 9. 架构总结

### 核心设计模式

| 模式 | 实现 | 价值 |
|------|------|------|
| **中间件链** | 16 个有序中间件，6 种钩子 | 关注点分离，可组合，可测试 |
| **代码强制 > Prompt 期望** | 循环检测、子 agent 限制 | Prompt 是建议，代码是法律 |
| **延迟加载** | DeferredToolRegistry + tool_search | 节省 token，减少 LLM 混淆 |
| **请求级隔离** | ContextVar for registry | 无跨请求污染 |
| **线程级隔离** | ThreadState + thread_id 作用域 | 文件、沙箱、记忆、状态互不影响 |
| **单向依赖** | Harness ← App，CI 强制 | 框架可独立发布、复用 |
| **防抖异步** | MemoryUpdateQueue 30s | 避免频繁 LLM 调用 |
| **原子修复** | DanglingToolCallMiddleware | 防止上下文损坏 |
| **渐进式技能** | SKILL.md + 运行时读取 | token 效率 |
| **LRU 追踪** | OrderedDict + max limit | 内存可控 |
