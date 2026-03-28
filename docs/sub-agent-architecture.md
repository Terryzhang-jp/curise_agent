# Sub-Agent 架构设计文档

> 编写日期: 2026-03-24
> 作者: 老K (Claude Agent)

---

## 目录

1. [问题背景：为什么需要 Sub-Agent](#1-问题背景)
2. [行业调研：SOTA Multi-Agent 模式](#2-行业调研)
3. [Claude Code Sub-Agent 深度分析](#3-claude-code-sub-agent-深度分析)
4. [Google ADK Multi-Agent 对比](#4-google-adk-multi-agent-对比)
5. [我们的现状](#5-我们的现状)
6. [目标架构设计](#6-目标架构设计)
7. [Gemini 模型选型](#7-gemini-模型选型)
8. [实施路线图](#8-实施路线图)

---

## 1. 问题背景

### 当前痛点

我们的 Chat Agent 是单一 Agent 架构 — 一个 Agent 承担所有职责（对话、查询、代码生成、Excel 生成、验证）。随着功能增加，暴露出三个核心问题：

**1.1 Context 污染**

当 Agent 执行 Excel 生成任务时，模板分析（~2000 tokens）、数据探索（~1500 tokens）、Python 代码（~3000 tokens）、bash 输出（~1000 tokens）、验证脚本（~1500 tokens）全部堆积在同一个 context 窗口中，总计 ~8000+ tokens。这些信息在任务完成后对用户对话毫无价值，但会一直占据 context，导致：

- 后续对话质量下降（模型需要在更多无关信息中找重点）
- 更快触发 context 压缩，可能丢失重要的对话上下文
- token 成本增加（每轮 LLM 调用都要重新读取这些历史）

**1.2 模型能力受限**

所有任务被迫使用同一个模型（`gemini-3-flash-preview`）。但不同任务对模型能力的需求差异很大：

| 任务 | 需要的能力 | 理想模型 |
|---|---|---|
| 日常对话 / 路由 | 快速响应，理解意图 | Flash（便宜快速） |
| Excel 代码生成 | 精确的代码逻辑，模板理解 | Pro（代码能力强） |
| 数据搜索 / 探索 | 大量文件阅读，信息提取 | Flash（快速遍历） |
| 质量验证 | 深度推理，发现逻辑缺陷 | Pro（推理能力强） |

**1.3 Prompt 注入的脆弱性**

当前通过 `use_skill` 工具在运行时将 SKILL.md 注入 context。这意味着：
- Agent 可能不调用 use_skill（之前测试中确实发生过）
- SKILL.md 作为工具返回值进入历史，与其他工具结果混在一起
- Agent 可能只部分遵循 SKILL.md 的步骤（之前测试中跳过了 CRITIC 验证）

### 核心目标

引入 Sub-Agent 模式，实现：
1. **Context 隔离** — Sub-Agent 在独立的 context 中工作，只返回摘要给主 Agent
2. **模型差异化** — 不同 Sub-Agent 使用最适合的模型
3. **指令内置** — Sub-Agent 的 system prompt 直接包含完整的操作流程，不依赖运行时注入

---

## 2. 行业调研：SOTA Multi-Agent 模式

### 2.1 五种主流模式

| 模式 | 描述 | 适用场景 |
|---|---|---|
| **Sequential Pipeline** | Agent A → Agent B → Agent C 串行 | 任务有严格先后依赖 |
| **Orchestrator + Workers** | 中央 Agent 路由到专业 Worker | 多种异质任务的分发 |
| **AgentTool Wrapping** | Sub-Agent 被包装成工具 | 最自然的集成方式 |
| **Parallel Fan-Out** | 多个 Agent 并行，结果汇总 | 多供应商同时生成 |
| **Generator + Critic** | 一个生成，一个验证 | 质量要求高的输出 |

**我们的目标架构是 Orchestrator + AgentTool Wrapping 的组合** — 主 Agent 作为路由器，Sub-Agent 被包装成工具按需调用。

### 2.2 主流框架对比

| 框架 | 提供方 | Sub-Agent 机制 | Context 模型 | 特点 |
|---|---|---|---|---|
| **Claude Code** | Anthropic | Agent 工具 | 完全隔离 | 消息传递，最简洁 |
| **Google ADK** | Google | AgentTool / sub_agents | 共享 session.state | 白板模型，适合 Gemini |
| **LangGraph** | LangChain | create_supervisor + handoff | 可配置 | 图结构，最灵活 |
| **AutoGen** | Microsoft | SelectorGroupChat | 对话共享 | 多方对话，适合讨论 |
| **CrewAI** | CrewAI | Process.hierarchical | 角色隔离 | 角色明确，上手快 |
| **OpenAI Agents SDK** | OpenAI | agent.handoff() | 传递控制权 | 简单线性链 |

---

## 3. Claude Code Sub-Agent 深度分析

Claude Code 的实现是所有框架中**最简洁且最符合我们需求**的参考。

### 3.1 架构原理

```
Parent Agent (主对话)
  │
  │  tool_use: Agent(prompt="任务描述...")
  │  ← 这是父→子的唯一数据通道
  │
  ▼
Sub-Agent (完全独立)
  ├─ 全新的 context window（200K tokens）
  ├─ 自己的 system prompt
  ├─ 自己的工具集（可限制子集）
  ├─ 不继承父的对话历史
  ├─ 不继承父的 system prompt
  └─ 干完活 → 最终回复文本作为工具返回值传回父
       │
       ▼
Parent 收到返回文本（~50-200 tokens 的摘要）
继续对话，context 几乎没有增长
```

### 3.2 关键设计决策

**决策 1：完全 Context 隔离**

Sub-Agent 不看父的对话历史，父也不看 Sub-Agent 的中间过程。

- Sub-Agent 读了 20 个文件、跑了 10 次 bash — 这些 token 消耗在 Sub-Agent 自己的 context 里
- 父的 context 只增加了返回的摘要文本
- 这是最核心的价值：**保护主 Agent 的 context 不被探索性工作污染**

**决策 2：单向消息传递**

```
父 → 子: 一个 prompt 字符串（任务描述 + 必要参数）
子 → 父: 一个结果字符串（最终回复文本）
```

没有共享内存、没有共享状态、没有流式回传。设计极简，不容易出错。

**决策 3：父负责组装 prompt**

父 Agent 必须将子 Agent 需要的所有信息编码进 prompt 字符串：
- 文件路径
- 具体参数（order_id, supplier_id）
- 约束条件
- 输出格式要求

子 Agent 不能"回头问"父 Agent — 它只能用自己的工具去获取信息。

**决策 4：子不能再生子**

Claude Code 硬性禁止嵌套。如果需要多级委派，由父依次调度多个子 Agent。这避免了递归调用带来的复杂性和不可控的 token 消耗。

### 3.3 何时 spawn Sub-Agent vs 自己做

Claude Code 的决策逻辑（我们应采纳）：

**应该委派给 Sub-Agent：**
- 任务会产生大量中间输出（>1000 tokens），但最终只需要一个摘要
- 任务是自包含的（给定输入，产出输出，不需要和用户交互）
- 任务需要不同的专业工具集
- 任务可以并行执行

**应该自己做：**
- 需要频繁与用户交互的任务
- 很快就能完成的小任务（委派的开销不值得）
- 需要前序步骤 context 的任务（不值得重传）

### 3.4 失败处理

Sub-Agent 失败时，父收到错误信息作为工具返回值。父可以：
- 重试（传相同或修改过的 prompt）
- 换策略（如切换到手动执行）
- 告知用户

没有框架级的自动重试 — 重试逻辑由父 Agent 的推理决定。

### 3.5 Token 成本

Anthropic 的研究数据：
- Multi-Agent 系统比单 Agent 使用 **3-10x** 更多 tokens
- 但 Opus + Sonnet 组合比单 Opus 在研究任务上好 **90.2%**
- Token 使用量占性能差异的 80% — 更多 token 通常 = 更好结果

**核心认知：Sub-Agent 的价值不是省 token，而是保护主 Agent 的 context 质量，以及让专业任务用专业模型。**

---

## 4. Google ADK Multi-Agent 对比

因为我们使用 Gemini 模型，Google ADK 是另一个重要参考。

### 4.1 ADK 的 AgentTool 模式

```python
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool

excel_agent = LlmAgent(
    name="ExcelGenerator",
    model="gemini-3.1-pro-preview",
    instruction="生成询价单 Excel...",
    tools=[bash_tool, workspace_tool]
)

chat_agent = LlmAgent(
    name="ChatRouter",
    model="gemini-3-flash-preview",
    tools=[AgentTool(agent=excel_agent), query_db, think],
    instruction="处理用户请求，将 Excel 生成任务委派给 ExcelGenerator"
)
```

### 4.2 ADK vs Claude Code 关键区别

| 维度 | Claude Code | Google ADK |
|---|---|---|
| Context 隔离 | **完全隔离**（子拿不到父的历史） | **共享 session.state**（键值白板） |
| 父→子通道 | prompt 字符串（唯一） | session.state + 函数参数 |
| 子→父通道 | 最终回复文本 | session.state 修改 + 回复文本 + artifacts |
| 状态共享 | 无 | 所有 Agent 共享一个 state 字典 |
| 竞态条件 | 不存在 | 并行 Agent 需要用不同 output key |

**我们的选择**：采用 Claude Code 的完全隔离模型。原因：
1. 更简单，更不容易出 bug
2. 我们已有 ReActAgent + MemoryStorage 基础设施，天然支持独立实例
3. 不需要共享状态 — 文件系统（workspace）已经是共享的持久层

---

## 5. 我们的现状

### 5.1 当前架构

```
┌─────────────────────────────────────────────────┐
│  Chat Agent (单一 ReAct Agent)                    │
│  模型: gemini-3-flash-preview                     │
│  引擎: services/agent/engine.py                   │
│                                                   │
│  System Prompt: services/agent/prompts/layers.py  │
│  ┌─────────────────────────────────────────────┐  │
│  │ ToolRegistry (所有工具平铺注册)               │  │
│  │                                             │  │
│  │ 业务工具:                                    │  │
│  │   query_db, get_db_schema                   │  │
│  │   get_order_overview                        │  │
│  │   prepare_inquiry_workspace                 │  │
│  │   get_order_fulfillment, update_fulfillment │  │
│  │                                             │  │
│  │ 通用工具:                                    │  │
│  │   bash (执行代码)                            │  │
│  │   think (质量检查)                           │  │
│  │   use_skill (读取技能文档)                    │  │
│  │   calculate, get_current_time               │  │
│  │   todo_write, todo_read                     │  │
│  │   web_fetch, web_search (可选)              │  │
│  │                                             │  │
│  │ 上传工具 (条件注册):                          │  │
│  │   resolve_and_validate, preview_changes     │  │
│  │   execute_upload                            │  │
│  └─────────────────────────────────────────────┘  │
│                                                   │
│  Skills (SKILL.md 文本，运行时通过 use_skill 注入):  │
│   - generate-inquiry                              │
│   - data-upload                                   │
│   - query-data                                    │
│   - fulfillment                                   │
└─────────────────────────────────────────────────────┘
```

### 5.2 信息流（以询价单生成为例）

```
用户: "帮我生成订单60供应商2的询价单"
  │
  ▼ [turn 1] LLM 判断 → 调用 use_skill("generate-inquiry")
  │  ← SKILL.md 全文 (~3000 tokens) 注入 context
  │
  ▼ [turn 2] LLM 读 SKILL.md → 调用 prepare_inquiry_workspace
  │  ← 工具返回摘要 (~200 tokens) 注入 context
  │
  ▼ [turn 3] LLM → 调用 bash (探索 order_data.json)
  │  ← bash 输出 (~500 tokens) 注入 context
  │
  ▼ [turn 4] LLM → 调用 bash (读取模板结构)
  │  ← bash 输出 (~800 tokens) 注入 context
  │
  ▼ [turn 5] LLM → 调用 bash (生成 Excel 的 Python 代码)
  │  ← bash 输出 (~200 tokens) 注入 context
  │  （但 LLM 输出的代码本身 ~2000 tokens 也在 context）
  │
  ▼ [turn 6] LLM → 调用 think (质量检查)
  │  ← think 返回 (~100 tokens) 注入 context
  │
  ▼ [turn 7] LLM → 调用 bash (CRITIC 验证脚本)
  │  ← bash 输出 (~300 tokens) 注入 context
  │
  ▼ [turn 8] LLM → 最终回复给用户

总计新增 context: ~7100+ tokens（全部留在主对话历史中）
```

### 5.3 已有的 Multi-Agent 基础（v5 Inquiry Generator）

在订单处理流程（非 chat）中，`services/inquiry_generator.py` 已经实现了 orchestrator + worker 模式：

```python
# run_inquiry_orchestrator() 中
for supplier_id in supplier_ids:
    agent = ReActAgent(
        model=model,
        system_prompt=PER_SUPPLIER_PROMPT,
        tools=per_supplier_tools,
        storage=MemoryStorage(),  # 独立的 storage
        max_turns=10,
    )
    result = agent.run(f"为供应商 {supplier_id} 生成询价单")
```

这证明我们的基础设施（ReActAgent + MemoryStorage + ToolRegistry）**已经支持创建独立的 Agent 实例**。缺少的只是：
1. 在 chat agent 的工具集中暴露一个 `delegate` 工具
2. 定义 Sub-Agent 的配置（模型、prompt、工具集）
3. 把执行结果传回主 agent

---

## 6. 目标架构设计

### 6.1 整体架构

```
┌─────────────────────────────────────────────┐
│  Chat Agent (路由 + 对话)                     │
│  模型: gemini-3-flash-preview                │
│  职责: 理解用户意图，路由到合适的 Sub-Agent     │
│                                             │
│  工具箱:                                     │
│  ┌─────────────────────────────────────────┐│
│  │ 直接工具 (轻量，不污染 context):          ││
│  │   query_db, get_order_overview           ││
│  │   think, calculate, get_current_time     ││
│  │                                         ││
│  │ Sub-Agent 工具 (重任务委派):              ││
│  │   delegate("excel_generator", {...})     ││
│  │   delegate("data_researcher", {...})     ││
│  │   delegate("data_uploader", {...})       ││
│  └─────────────────────────────────────────┘│
└──────────┬──────────┬──────────┬────────────┘
           │          │          │
     ┌─────▼─────┐ ┌──▼────────┐ ┌▼───────────┐
     │ Excel      │ │ Research  │ │ Upload     │
     │ Generator  │ │ Agent     │ │ Agent      │
     │            │ │           │ │            │
     │ Model:     │ │ Model:    │ │ Model:     │
     │ 3.1-pro    │ │ 3-flash   │ │ 3-flash    │
     │            │ │           │ │            │
     │ Tools:     │ │ Tools:    │ │ Tools:     │
     │ bash       │ │ web_search│ │ bash       │
     │ think      │ │ web_fetch │ │ query_db   │
     │ prepare_   │ │ query_db  │ │ resolve_   │
     │ inquiry_ws │ │ bash      │ │ validate   │
     │            │ │           │ │ preview    │
     │ Prompt:    │ │ Prompt:   │ │ execute    │
     │ SKILL.md   │ │ 搜索指引   │ │            │
     │ 内置       │ │ 内置      │ │ Prompt:    │
     └───────────┘ └───────────┘ │ SKILL.md   │
                                  │ 内置       │
                                  └────────────┘
```

### 6.2 delegate 工具设计

```python
SUB_AGENT_CONFIGS = {
    "excel_generator": SubAgentConfig(
        model="gemini-3.1-pro-preview",
        system_prompt=EXCEL_SKILL_PROMPT,    # SKILL.md 内容内置
        tools=["bash", "think", "prepare_inquiry_workspace"],
        max_turns=15,
        description="生成 Excel 询价单、报表等文件。"
                    "需要传入: order_id, supplier_id, 模板信息（如有）。"
                    "返回: 文件名、产品数、验证结果摘要。",
    ),
    "data_researcher": SubAgentConfig(
        model="gemini-3-flash-preview",
        tools=["web_search", "web_fetch", "query_db", "bash"],
        max_turns=10,
        description="搜索和整理资料。"
                    "需要传入: 搜索主题和具体问题。"
                    "返回: 结构化的调研结果摘要。",
    ),
    "data_uploader": SubAgentConfig(
        model="gemini-3-flash-preview",
        system_prompt=UPLOAD_SKILL_PROMPT,
        tools=["bash", "query_db", "resolve_and_validate",
               "preview_changes", "execute_upload"],
        max_turns=12,
        description="处理数据上传到数据库。"
                    "需要传入: 文件路径、目标表、映射规则。"
                    "返回: 上传结果（成功数、失败数、变更摘要）。",
    ),
}
```

### 6.3 父→子通信协议

父 Agent 调用 delegate 时，必须在 task_prompt 中包含：

```
## 任务
为订单 60 供应商 2 生成询价单 Excel。

## 参数
- order_id: 60
- supplier_id: 2
- workspace_dir: /tmp/workspace/xxx-xxx-xxx

## 模板
用户上传了模板文件: 询价单_template.xlsx（已在工作目录中）

## 输出要求
完成后返回:
1. 生成的文件名
2. 产品数量
3. 验证结果（PASS/FAIL + 详情）
4. 任何数据异常或缺失的说明
```

### 6.4 子→父返回格式

Sub-Agent 的最终回复作为 delegate 工具的返回值传回父 Agent：

```
已完成。

文件: inquiry_PO112240CCI_supplier2.xlsx
产品数: 50/50 (全部写入)
验证: ✓ ALL CHECKS PASSED
备注: currency 字段为空，Excel 中标注为 TBD
```

父 Agent 读到这段文本，直接转化为用户可读的回复。

### 6.5 Workspace 共享

Sub-Agent 不共享 context，但**共享文件系统**。

```
/tmp/workspace/{session_id}/
  ├── order_data.json      ← prepare_inquiry_workspace 生成
  ├── 询価単_template.xlsx   ← 用户上传（由 chat.py bridge 保存）
  └── inquiry_XXX.xlsx      ← Sub-Agent 生成的输出文件
```

- 父 Agent 的 `ctx.workspace_dir` 和 Sub-Agent 的 bash cwd 指向同一个目录
- 这是父子之间除了 prompt/result 文本之外的**唯一共享通道**
- 文件是持久化的（同步到 Supabase Storage），比 context 更可靠

### 6.6 SSE 实时推送

Sub-Agent 执行期间，前端需要看到进度。两种方案：

**方案 A（简单）：静默执行**
- Sub-Agent 静默运行，完成后父 Agent 一次性推送结果
- 前端只看到一个 "正在生成询价单..." loading 状态
- 实现最简单，但用户体验一般

**方案 B（推荐）：中间事件透传**
- Sub-Agent 的 ChatStorage 写入同一个 session_id 的 display messages
- SSE 队列共享，前端实时看到 Sub-Agent 的 action/observation
- 前端体验不变（仍然看到工具调用的展开/收起卡片）
- 实现方式：Sub-Agent 使用主 session 的 ChatStorage 实例

```python
def delegate(agent_type: str, task_prompt: str) -> str:
    config = SUB_AGENT_CONFIGS[agent_type]

    # 使用主 session 的 ChatStorage（SSE 事件共享）
    sub_storage = ctx.storage  # 或 ChatStorage(ctx.db)

    sub_agent = ReActAgent(
        model=config.model,
        system_prompt=config.system_prompt,
        tools=build_sub_tools(config, ctx),
        storage=sub_storage,  # 共享 display 输出
        max_turns=config.max_turns,
    )

    result = sub_agent.run(task_prompt)
    return result
```

---

## 7. Gemini 模型选型

### 7.1 当前可用模型（2026-03）

| 模型 | Model ID | 代码能力 (SWE-Bench) | 工具编排 | 价格 (input/output per 1M) | 状态 |
|---|---|---|---|---|---|
| Gemini 2.5 Flash | `gemini-2.5-flash` | ~50% | 中等 | $0.30 / $2.50 | **GA 稳定** |
| Gemini 2.5 Pro | `gemini-2.5-pro` | ~65% | 好 | $1.25 / $10.00 | **GA 稳定** |
| Gemini 3 Flash | `gemini-3-flash-preview` | 78% | 好 | $0.50 / $3.00 | Preview |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite-preview` | - | - | $0.25 / $1.50 | Preview |
| **Gemini 3.1 Pro** | `gemini-3.1-pro-preview` | **80.6%** | **最强 (69.2%)** | $2.00 / $12.00 | Preview |

### 7.2 推荐配置

| 角色 | 模型 | 原因 |
|---|---|---|
| **Chat Agent (路由)** | `gemini-3-flash-preview` | 快速、便宜，路由不需要强推理 |
| **Excel Generator** | `gemini-3.1-pro-preview` | 代码生成 80.6%，工具编排 69.2%，值得多花钱 |
| **Data Researcher** | `gemini-3-flash-preview` | 搜索遍历为主，不需要强代码能力 |
| **Data Uploader** | `gemini-3-flash-preview` | 流程固定，Flash 够用 |
| **Fallback (稳定)** | `gemini-2.5-pro` | Preview 不可用时的后备，GA 稳定 |

### 7.3 成本估算

单次询价单生成（1 个供应商，50 个产品）：

| 场景 | 模型 | 预估 tokens | 成本 |
|---|---|---|---|
| Chat Agent 路由 | 3-flash | ~2000 in + ~500 out | ¥0.01 |
| Excel Sub-Agent | 3.1-pro | ~8000 in + ~4000 out | ¥0.45 |
| **合计** | | | **¥0.46** |
| 对比：当前单 Agent | 3-flash | ~10000 in + ~4500 out | ¥0.10 |

**成本增加约 4-5 倍，但质量提升显著**（代码能力 50% → 80.6%，验证更可靠）。
对于 B2B 询价单场景，每单多花 ¥0.4 完全可接受。

---

## 8. 实施路线图

### Phase 1: 基础框架（delegate 工具 + SubAgentConfig）

**目标**: 搭建 Sub-Agent 的基础设施，不改变现有功能，只增加新路径。

**改动范围**:
- 新建 `services/agent/sub_agent.py` — SubAgentConfig 定义 + delegate 执行逻辑
- 修改 `services/tools/__init__.py` — 注册 delegate 工具
- 修改 `services/agent/prompts/layers.py` — 主 Agent 的 prompt 增加委派指引

**关键设计**:
```python
# services/agent/sub_agent.py

@dataclass
class SubAgentConfig:
    model: str
    system_prompt: str
    tools: list[str]
    max_turns: int = 15
    description: str = ""

SUB_AGENT_REGISTRY: dict[str, SubAgentConfig] = {}

def register_sub_agent(name: str, config: SubAgentConfig):
    SUB_AGENT_REGISTRY[name] = config

def run_sub_agent(name: str, task_prompt: str, ctx: ToolContext) -> str:
    """在独立 context 中执行 Sub-Agent，返回最终回复"""
    config = SUB_AGENT_REGISTRY[name]

    # 构建独立的工具集
    sub_registry = build_tools_for_sub_agent(config.tools, ctx)

    # 构建独立的 LLM Provider
    from services.agent.llm.gemini_provider import GeminiProvider
    provider = GeminiProvider(model=config.model)

    # 使用主 session 的 storage（SSE 共享）
    from services.agent.engine import ReActAgent
    agent = ReActAgent(
        provider=provider,
        system_prompt=config.system_prompt,
        registry=sub_registry,
        storage=ctx.storage,         # 共享 display 输出
        session_id=ctx.session_id,   # 同一个 session
        max_turns=config.max_turns,
        ctx=ToolContext(              # 独立的 ctx，共享 workspace
            workspace_dir=ctx.workspace_dir,
            db=ctx.db,
            session_id=ctx.session_id,
        ),
    )

    return agent.run(task_prompt)
```

### Phase 2: Excel Generator Sub-Agent

**目标**: 将询价单生成从 use_skill 模式迁移到 Sub-Agent 模式。

**改动**:
- 将 `skills/generate-inquiry/SKILL.md` 的核心内容转化为 Sub-Agent 的 system_prompt
- 注册 `excel_generator` Sub-Agent（模型: `gemini-3.1-pro-preview`）
- 主 Agent 的 prompt 中增加: "生成 Excel 任务，使用 delegate('excel_generator', ...)"

**验证**:
- 同一订单+供应商，对比单 Agent vs Sub-Agent 的生成质量
- 确认 SSE 推送正常（前端实时可见进度）
- 确认文件卡片正确显示（structured_card）

### Phase 3: 更多 Sub-Agent

- `data_researcher` — 搜索和整理资料
- `data_uploader` — 数据上传流程
- 根据需要增加新的 Sub-Agent 类型

### Phase 4: 模型动态选择

- 环境变量控制各 Sub-Agent 的模型选择
- Preview 模型不可用时自动降级到 GA 模型
- 监控各 Sub-Agent 的 token 使用和成功率

---

## 附录 A: 参考资料

### Claude Code Sub-Agent
- [Claude Code: Create custom subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Agent SDK: Subagents](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [Anthropic Engineering: Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: When to use multi-agent systems](https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)

### Google ADK
- [ADK: Multi-agent systems](https://google.github.io/adk-docs/agents/multi-agents/)
- [Google Developers Blog: Multi-agent patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)

### Gemini 模型
- [Gemini API Models](https://ai.google.dev/gemini-api/docs/models)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini 3.1 Pro Model Card](https://deepmind.google/models/model-cards/gemini-3-1-pro/)

### 框架对比
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [langgraph-supervisor (GitHub)](https://github.com/langchain-ai/langgraph-supervisor-py)
- [OpenAI Agents SDK: Multi-Agent Orchestration](https://openai.github.io/openai-agents-python/multi_agent/)

## 附录 B: 与现有 v5 Inquiry Generator 的关系

v5 Inquiry Generator（`services/inquiry_generator.py`）已经实现了 orchestrator + per-supplier agent 的模式，但它是从订单处理流程直接调用的，不经过 chat agent。

Sub-Agent 框架建成后，v5 的模式可以统一到 delegate 工具中：
- 主 Agent 调用 `delegate("excel_generator", ...)` 为每个供应商生成
- 复用相同的 Sub-Agent 配置和模型
- 统一 SSE 推送和文件管理

这样 chat 路径和订单处理路径最终共用同一套 Sub-Agent 基础设施。
