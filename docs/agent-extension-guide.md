# CruiseAgent 能力扩展指南

> 编写日期: 2026-03-23
> 基于: v2-backend 重构后的架构（工具自发现 + Prompt 分层 + Skills 体系 + Auto-Compact）

本文档面向开发者，说明如何在现有架构上扩展 Agent 的能力。
涵盖 5 种扩展场景，每种都给出具体步骤和示例代码。

---

## 目录

1. [添加新工具（Tool）](#1-添加新工具)
2. [添加新业务技能（Skill）](#2-添加新业务技能)
3. [添加新领域知识（Prompt Layer）](#3-添加新领域知识)
4. [添加新编排器（Agent-as-Tool）](#4-添加新编排器)
5. [接入新 LLM Provider](#5-接入新-llm-provider)
6. [架构速查图](#6-架构速查图)
7. [常见问题](#7-常见问题)

---

## 1. 添加新工具

### 场景
你需要 Agent 拥有一个新的能力——比如发送邮件、调用外部 API、操作文件系统等。

### 只需改 1 个文件

在 `services/tools/` 或 `services/agent/tools/` 下创建一个 Python 文件，包含两样东西：

1. **`TOOL_META`** 字典 — 工具的元数据（单一数据源）
2. **`register()`** 函数 — 将工具注册到 ToolRegistry

### 完整示例：创建一个"发送邮件"工具

```python
# services/tools/email_sender.py

from services.tools.registry_loader import ToolMetaInfo

# ── 元数据（唯一数据源）──────────────────────────────
TOOL_META = {
    "send_email": ToolMetaInfo(
        display_name="发送邮件",
        group="communication",
        description="发送邮件给指定收件人",
        prompt_description="发送邮件（支持 HTML 正文和附件）",
        summary="发送邮件",
        is_enabled_default=False,   # 默认关闭，管理员可在设置中启用
        auto_register=False,        # 不自动注册，需在 enabled_tools 中显式包含
    ),
}


# ── 注册函数 ─────────────────────────────────────────
def register(registry, ctx=None):
    @registry.tool(
        description=(
            "Send an email to specified recipients. "
            "Supports plain text and HTML body. "
            "Use this when the user asks to send inquiry emails, reports, etc."
        ),
        parameters={
            "to": {
                "type": "STRING",
                "description": "收件人邮箱，多个用逗号分隔",
            },
            "subject": {
                "type": "STRING",
                "description": "邮件主题",
            },
            "body": {
                "type": "STRING",
                "description": "邮件正文（支持 HTML）",
            },
        },
        group="communication",
    )
    def send_email(to: str, subject: str, body: str) -> str:
        # 实现邮件发送逻辑
        # ctx.db 可以访问数据库
        # ctx.pipeline_session_id 是当前会话 ID
        try:
            # ... 实际发送逻辑 ...
            return f"邮件已发送给 {to}"
        except Exception as e:
            return f"Error: 发送失败: {e}"
```

### 就这样。不需要改任何其他文件。

自发现机制会自动完成：

| 原来需要手动同步的地方 | 现在怎么处理 |
|----------------------|------------|
| `tool_settings.py` BUILTIN_TOOLS 列表 | 自动从 TOOL_META 读取 |
| `chat.py` tool_descs 描述字典 | 自动从 TOOL_META.prompt_description 读取 |
| `chat_storage.py` _TOOL_SUMMARY_MAP | 自动从 TOOL_META.summary 读取 |
| `__init__.py` 注册分支 | `_auto_register_module()` 或自动扫描 |

### 可选：注册到 `__init__.py`

如果工具需要特殊的注册条件（如只在有文件上传时注册），在 `services/tools/__init__.py` 中加一行：

```python
_auto_register_module("services.tools.email_sender", registry, ctx, _should_register,
                      ["send_email"])
```

如果 `auto_register=True`，自发现机制会自动处理，不需要这一步。

### ToolMetaInfo 字段说明

| 字段 | 作用 | 消费者 |
|------|------|--------|
| `display_name` | 前端展示名 | tool_settings.py DB seed |
| `group` | 工具分组 | tool_settings.py DB seed |
| `description` | 完整描述 | tool_settings.py DB seed |
| `prompt_description` | 系统 prompt 中的简短描述 | chat.py 动态 prompt |
| `summary` | 工具执行后的前端摘要 (str 或 callable) | chat_storage.py 展示消息 |
| `is_enabled_default` | DB seed 时的默认启用状态 | tool_settings.py |
| `auto_register` | 是否自动注册（False = 需显式启用） | __init__.py 过滤 |

---

## 2. 添加新业务技能

### 场景
你有一个复杂的多步骤业务流程（如"做月度报表"、"价格对比分析"），想让 Agent 按照固定步骤执行。

### Skill vs Tool 的区别

| | Tool | Skill |
|---|------|-------|
| 本质 | Python 函数 | Prompt 模板 (Markdown) |
| 加载时机 | Agent 创建时注册 | Agent 按需调用 use_skill 时加载 |
| 上下文消耗 | 始终占用工具声明 token | 仅调用时占用，不用不消耗 |
| 适合 | 原子操作（查询、执行命令） | 多步骤流程、工作指引 |

### 创建步骤

**Step 1**: 在 `v2-backend/skills/` 下创建目录和 `SKILL.md`

```
skills/
├── data-upload/SKILL.md       ← 已有
├── generate-inquiry/SKILL.md  ← 已有
├── query-data/SKILL.md        ← 已有
├── fulfillment/SKILL.md       ← 已有
└── monthly-report/SKILL.md    ← 你要创建的
```

**Step 2**: 编写 SKILL.md

```markdown
---
name: monthly-report
description: 生成月度采购报表（按供应商/品类汇总，含同比环比）
---

## 月度采购报表生成流程

### Step 1: 确认报告范围
用 `query_db` 查询数据范围：
- 确认目标月份（如 2026-03）
- 确认是否包含所有国家/港口

### Step 2: 数据采集
执行以下 SQL 查询：
1. 按供应商汇总采购金额
2. 按品类汇总采购数量
3. 同比数据（去年同月）
4. 环比数据（上月）

### Step 3: 生成 Excel
用 `bash` + openpyxl 生成报表：
- Sheet 1: 供应商汇总表
- Sheet 2: 品类汇总表
- Sheet 3: 趋势图数据

### Step 4: 验证
读回文件检查数据完整性。

$ARGUMENTS
```

**就这样**。不需要重启服务。Agent 可以立即通过 `use_skill(name="monthly-report")` 调用。

### SKILL.md 格式规范

```markdown
---
name: skill-name          # 唯一标识，用于 use_skill(name="...")
description: 一句话描述    # 显示在技能列表中
---

## 标题

（Markdown 正文 — Agent 调用 use_skill 时会收到这段内容作为工作指引）

$ARGUMENTS                 # 占位符，use_skill 传入的参数会替换这里
```

### Skill 加载优先级

```
文件系统 skills/xxx/SKILL.md  ← 基础层（代码库自带）
          ↓ 被覆盖
数据库 SkillConfig 表          ← 用户自定义层（管理员在前端编辑）
          ↓ 禁用
DB 中 is_enabled=False        ← 即使文件系统有，也会被移除
```

### 当 Skill 需要引用文件

如果 Skill 需要引用模板文件或示例数据，放在同目录下：

```
skills/monthly-report/
├── SKILL.md
├── report_template.xlsx    ← Skill 可以引用的文件
└── example_output.png      ← 示例输出
```

`SkillDef.references_dir` 会指向该目录，Skill 中可以引用这些文件。

---

## 3. 添加新领域知识

### 场景
Agent 需要了解新的业务领域——比如新增了"仓库管理"模块，需要让 Agent 知道相关数据表和业务规则。

### Prompt 分层架构

系统 prompt 由 4 层组装而成：

```
┌─────────────────────────────────┐
│ Layer 1: Identity               │  "你是 CruiseAgent，邮轮供应链管理助手"
├─────────────────────────────────┤
│ Layer 2: Capabilities           │  可用工具列表 + 技能摘要
├─────────────────────────────────┤
│ Layer 3: Domain Knowledge       │  数据表、业务规则、工作流指引
├─────────────────────────────────┤
│ Layer 4: Constraints            │  元认知规则、安全规则
└─────────────────────────────────┘
```

### 添加新领域知识

编辑 `services/agent/prompts/layers.py`：

**方式 A — 全局知识（所有场景都需要）**

在 `domain_knowledge()` 函数的 "Full generic" 分支中添加：

```python
# layers.py 中

_WAREHOUSE_RULES = """## 仓库管理
- v2_warehouses: 仓库表（name, location, capacity）
- v2_inventory: 库存表（warehouse_id, product_id, quantity, last_updated）
- 库存查询优先使用 v2_inventory 视图
- 库存不足时自动提醒用户"""

def domain_knowledge(ctx: PromptContext) -> str:
    # ...
    # 在 Full generic 分支中添加：
    parts.append(_WAREHOUSE_RULES)
```

**方式 B — 场景特定知识（只在特定场景使用）**

```python
def domain_knowledge(ctx: PromptContext) -> str:
    if ctx.scenario == "warehouse":
        parts.append(_WAREHOUSE_RULES)
        return "\n\n".join(parts)
    # ...
```

**方式 C — 推荐：封装为 Skill（按需加载，不占常驻 token）**

对于详细的操作步骤，建议写成 Skill 而不是放进 prompt：

```
# skills/warehouse-management/SKILL.md
把详细的入库、出库、盘点步骤写在这里
```

然后在 layers.py 中只加一行引用：

```python
parts.append('- 仓库管理：`use_skill(name="warehouse-management")`')
```

### 添加新的 Scenario

如果需要一个全新的场景（前端通过 `scenario` 参数触发）：

1. 在 `layers.py` 的 `identity()` 中加一个分支
2. 在 `domain_knowledge()` 中加对应的领域知识
3. 前端发消息时传 `scenario: "warehouse"`

```python
# layers.py

def identity(ctx: PromptContext) -> str:
    if ctx.scenario == "warehouse":
        return "你是 CruiseAgent，正在帮助用户管理仓库库存。"
    # ...
```

---

## 4. 添加新编排器

### 场景
你有一个复杂的后台流程（多个 Agent 协作、耗时较长），想让 Chat Agent 通过一次工具调用触发它。

### Agent-as-Tool 模式

核心思想：把编排器（orchestrator）包装成一个普通工具函数。

### 完整示例：包装"自动对账"编排器

假设你有一个 `run_reconciliation(order_id, db)` 函数需要 30 秒执行。

```python
# services/tools/orchestration.py（在已有文件中追加）

TOOL_META = {
    # ... 已有的 generate_inquiry_for_order ...
    "run_reconciliation": ToolMetaInfo(
        display_name="自动对账",
        group="business",
        description="对比订单与发票，自动识别差异并生成对账报告",
        prompt_description="自动对账（对比订单与发票差异）",
        summary="执行对账",
        is_enabled_default=False,
        auto_register=False,
    ),
}


def register(registry, ctx=None):
    # ... 已有的 generate_inquiry_for_order 注册 ...

    @registry.tool(
        description="Run automated reconciliation ...",
        parameters={
            "order_id": {"type": "NUMBER", "description": "订单 ID"},
        },
        group="business",
    )
    def run_reconciliation(order_id: int) -> str:
        try:
            from services.reconciliation import reconcile_order
            result = reconcile_order(int(order_id), ctx.db)
            return f"对账完成: {result['summary']}"
        except Exception as e:
            return f"Error: 对账失败: {e}"
```

### 关键设计原则

1. **工具函数只做转发**：不含业务逻辑，只调用编排器并格式化结果
2. **返回摘要而非全量数据**：Agent 只需要知道"成功/失败+关键指标"
3. **错误必须返回字符串**：不能抛异常（Agent 需要 Error: 前缀来识别错误）
4. **默认关闭**：`is_enabled_default=False`，因为这类工具通常有副作用

---

## 5. 接入新 LLM Provider

### 场景
你想让 Agent 使用 Claude、GPT-4o 或 DeepSeek 作为大脑。

### LLMProvider 接口

所有 Provider 必须实现 `services/agent/llm/base.py` 中的抽象接口：

```python
class LLMProvider(ABC):
    @abstractmethod
    def configure(self, system_prompt: str, tools: list, thinking_budget: int): ...

    @abstractmethod
    def generate(self, history: list) -> LLMResponse: ...

    @abstractmethod
    def build_user_message(self, text: str) -> Any: ...

    @abstractmethod
    def build_model_message(self, text_parts: list, function_calls: list) -> Any: ...

    @abstractmethod
    def build_tool_results(self, responses: list[FunctionResponse]) -> Any: ...

    @abstractmethod
    def build_system_injection(self, text: str) -> Any: ...

    @abstractmethod
    def build_empty_model_message(self) -> Any: ...
```

### 关键数据结构

```python
@dataclass
class LLMResponse:
    text_parts: list[str]           # 文本回复
    thinking_parts: list[str]       # 思考过程（如果 provider 支持）
    function_calls: list[FunctionCall]  # 工具调用
    raw: Any                        # provider 原始响应（用于 history）
    prompt_tokens: int
    completion_tokens: int

@dataclass
class FunctionCall:
    name: str       # 工具名
    args: dict      # 参数
    id: str = ""    # 调用 ID（部分 provider 需要）

@dataclass
class FunctionResponse:
    name: str       # 工具名
    result: str     # 执行结果
    id: str = ""    # 对应的调用 ID
```

### 添加新 Provider 的步骤

**Step 1**: 创建 Provider 文件

```python
# services/agent/llm/claude_provider.py

from services.agent.llm.base import LLMProvider, LLMResponse, FunctionCall, FunctionResponse

class ClaudeProvider(LLMProvider):
    def __init__(self, config):
        self.config = config
        self.client = None
        # ...

    def configure(self, system_prompt, tools, thinking_budget):
        # 将 tools (list[ToolDeclaration]) 转换为 Claude 格式
        # 保存 system_prompt
        ...

    def generate(self, history) -> LLMResponse:
        # 调用 Claude API
        # 将响应转换为 LLMResponse
        ...

    def build_user_message(self, text):
        # 返回 Claude SDK 的用户消息格式
        ...

    # ... 其他方法 ...
```

**Step 2**: 注册到工厂函数

```python
# services/agent/config.py → create_provider()

def create_provider(llm_config: LLMConfig):
    if provider_name == "claude":
        from services.agent.llm.claude_provider import ClaudeProvider
        return ClaudeProvider(llm_config)
    # ...
```

**Step 3**: 使用

```python
# 在 chat.py 或任何需要的地方
llm_config = LLMConfig(provider="claude", api_key="sk-...")
provider = create_provider(llm_config)
```

### 注意事项

- `build_tool_results()` 的返回值格式因 provider 而异：Gemini 返回单个对象，OpenAI 返回列表
- `raw` 字段必须是 provider 原生格式，因为它会被直接追加到 history 中
- `build_system_injection()` 用于在对话中间插入系统提示（如循环检测警告），某些 provider 可能不支持
- `function_calls` 的 `id` 字段：Gemini 不需要，OpenAI/Claude 需要（用于匹配 tool_result）

---

## 6. 架构速查图

### 文件结构

```
v2-backend/
├── services/
│   ├── agent/
│   │   ├── engine.py              # ReAct 循环引擎（不需要改）
│   │   ├── config.py              # LLMConfig, AgentConfig
│   │   ├── tool_registry.py       # ToolRegistry（不需要改）
│   │   ├── tool_context.py        # ToolContext + SkillDef
│   │   ├── chat_storage.py        # 双写存储（自动读 TOOL_META）
│   │   ├── prompts/               # ★ Prompt 分层组装
│   │   │   ├── builder.py         #   PromptContext + build_chat_prompt()
│   │   │   └── layers.py          #   identity/capabilities/domain/constraints
│   │   ├── llm/
│   │   │   ├── base.py            #   LLMProvider 抽象接口
│   │   │   └── gemini_provider.py #   Gemini 实现
│   │   └── tools/                 # 通用工具（reasoning, shell, web...）
│   │       └── *.py               #   每个文件: TOOL_META + register()
│   └── tools/                     # 业务工具（order_query, fulfillment...）
│       ├── registry_loader.py     # ★ 自发现引擎
│       ├── orchestration.py       # ★ Agent-as-Tool 包装器
│       └── *.py                   #   每个文件: TOOL_META + register()
├── skills/                        # ★ 业务技能（Markdown 模板）
│   ├── data-upload/SKILL.md
│   ├── generate-inquiry/SKILL.md
│   ├── query-data/SKILL.md
│   └── fulfillment/SKILL.md
├── routes/
│   ├── chat.py                    # Chat API（委托 prompt builder）
│   └── tool_settings.py           # 工具设置 API（自动 seed）
└── config.py                      # AGENT_WORKSPACE_ROOT 等配置
```

### 数据流

```
用户消息
    ↓
routes/chat.py
    ├── _build_system_prompt()
    │       ↓
    │   prompts/builder.py → layers.py    ← Prompt 分层组装
    │       ↓
    ├── create_chat_registry()
    │       ↓
    │   registry_loader.py                ← 工具自发现
    │   tools/__init__.py                 ← 条件注册
    │       ↓
    └── ReActAgent.run()
            ↓
        engine.py 循环:
            LLM ← system_prompt + history + tool declarations
             ↓
            function_calls? → 执行工具 → auto-compact? → 继续循环
             ↓
            final text → chat_storage.py 双写 → SSE 推送到前端
```

### 扩展点速查

| 我想... | 改什么 | 参考章节 |
|---------|--------|---------|
| 加一个新工具 | 新建 `services/tools/xxx.py`（TOOL_META + register） | §1 |
| 加一个业务流程 | 新建 `skills/xxx/SKILL.md` | §2 |
| 加领域知识到 prompt | 编辑 `services/agent/prompts/layers.py` | §3 |
| 包装一个后台编排器 | 编辑 `services/tools/orchestration.py` | §4 |
| 接入 Claude/GPT-4o | 新建 `services/agent/llm/xxx_provider.py` | §5 |
| 改工具的前端摘要 | 改对应文件的 `TOOL_META.summary` | §1 |
| 改工具的默认启用状态 | 改对应文件的 `TOOL_META.is_enabled_default` | §1 |
| 调整 auto-compact 阈值 | `AgentConfig.compact_threshold` 或创建 agent 时传参 | engine.py |
| 改 workspace 存储位置 | 设环境变量 `AGENT_WORKSPACE_ROOT` | config.py |

---

## 7. 常见问题

### Q: 新增工具后，前端看不到？

工具需要在数据库 `v2_tool_configs` 表中有记录。两种方式：
1. 调用 `POST /settings/tools/seed` 接口手动同步
2. 访问工具设置页面时会自动 seed（首次访问 count==0 时）

如果表里已有旧数据，seed 不会覆盖已有记录的 `is_enabled` 状态。只会插入新发现的工具。

### Q: TOOL_META 里的 description 和 @registry.tool 的 description 有什么区别？

| | TOOL_META.description | @registry.tool description |
|---|---|---|
| 消费者 | 人类（DB seed → 前端设置页面展示） | LLM（工具声明，LLM 据此决定是否调用） |
| 语言 | 中文 | 英文（LLM 理解更好） |
| 长度 | 简短一句话 | 可以较长，包含使用场景和示例 |

### Q: Skill 和系统 prompt 中的领域知识重复了怎么办？

设计原则：**系统 prompt 只放"什么时候用"，Skill 放"怎么用"**。

- 系统 prompt (layers.py): `"生成询价单：use_skill(name='generate-inquiry')"`
- Skill (SKILL.md): 详细的 4 步操作流程

这样 Agent 在不需要生成询价单时不会浪费 token 加载详细步骤。

### Q: auto-compact 什么时候触发？会丢数据吗？

- 触发条件：单次 `run()` 中累计 `prompt_tokens >= 80000`（可配置）
- 触发后：调用 `compact()` 生成对话摘要 → 替代旧历史消息
- 每次 `run()` 最多触发一次
- 不会丢数据：旧消息仍在数据库中（`agent_parts` 类型），只是 LLM 不再看到它们，而是看到摘要
- 失败安全：compact 失败后标记 `_compact_done=True`，不会反复重试

### Q: 如何测试新工具？

```python
# 最简单的方式：直接调用 register() + execute()
from services.agent.tool_registry import ToolRegistry
from services.agent.tool_context import ToolContext

registry = ToolRegistry()
ctx = ToolContext(db=your_db_session)

# 注册工具
from services.tools.your_module import register
register(registry, ctx)

# 执行
result = registry.execute("your_tool_name", {"param1": "value1"})
print(result)
```

### Q: 如何让工具只在特定条件下注册？

参考 `data_upload` 的模式——在 `services/tools/__init__.py` 的 `create_chat_registry()` 末尾：

```python
# 只在有文件上传时注册
if some_condition(ctx):
    from services.tools.your_module import register
    register(registry, ctx)
```

同时设置 `TOOL_META` 中 `auto_register=False`，防止自动注册。
