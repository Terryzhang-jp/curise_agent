# Agent-Centric 系统建设路线图

> 日期: 2026-04-07
> 前置: 基于《批判性强化方案》的 6 项立即做 + 用户的战略方向转变
> 新目标: 不只是"修 bug 保稳定", 而是"把系统打造成以 agent 为核心的智能供应链平台"

---

## 0. 方向转变意味着什么

之前的评估砍掉了很多项, 理由是"当前没用到"、"空框架"、"过度工程"。但如果目标是 **agent-centric**, 评估坐标系要变:

| 之前的坐标系 | 新的坐标系 |
|---|---|
| "子 agent 框架是空的, 不做" | "子 agent 是核心架构, 必须激活" |
| "tracer 持久化是 P2" | "多 agent 协作必须可追踪, 升 P1" |
| "tool 参数验证频率低" | "更多 agent 调工具 = 更多错误参数, 升 P1" |
| "4 天修 bug 就够了" | "4 天修 bug + 2 周建 agent 体系" |

**不变的原则**:
- 白名单安全、compact bug、LLM timeout — 这 3 个仍是 Day 1 必修
- 不加无用的抽象层 — 每个改动必须服务于一个具体的 agent 场景

---

## 1. 现状盘点: 你手上有什么

代码审计发现, agent 基础设施比预期**更完善**:

### 已经有的 (不需要从零建)

| 组件 | 状态 | 所在文件 |
|------|------|----------|
| ReActAgent 主循环 | ✅ 生产级 (911行) | `engine.py` |
| 6-hook 中间件链 | ✅ 9 个中间件已注册 | `hooks.py` + `middlewares/` |
| 子 agent 框架 | ✅ 框架完整, 隔离机制健全 | `sub_agent.py` (含 timeout, DB tracking, SSE events) |
| 子 agent 注册表 | ❌ **空的** — 0 个 agent 注册 | `sub_agents/__init__.py` |
| delegate 工具 | ✅ 已实现, 含递归保护 | `sub_agent.py:311-358` |
| 并行执行模式 | ✅ 已在 inquiry 中验证 | `inquiry_agent.py` (ThreadPoolExecutor) |
| Deferred tool 激活 | ✅ tool_search meta-tool | `engine.py:168-215` |
| 多 LLM provider | ✅ Gemini/Kimi/OpenAI/DeepSeek | `llm/` |
| Skill 系统 | ✅ SKILL.md 模板 + use_skill 工具 | `tools/skill.py` |
| HITL 暂停机制 | ✅ should_pause + 前端 review UI | `confirmation.py` |

### 需要建的

| 组件 | 优先级 | 原因 |
|------|--------|------|
| 注册真实的子 agent | **P0** | 框架没有灵魂, 注册 agent 才能用起来 |
| 子 agent 结构化返回 | **P0** | 当前返回 raw text, 父 agent 无法可靠解析 |
| 子 agent 安全继承 | **P0** | 子 agent 不继承父的 guardrail middleware — 安全漏洞 |
| 并行子 agent 执行器 | **P1** | 多供应商场景需要并行委派 |
| Agent trace 持久化 | **P1** | 多 agent 不可追踪 = 不可调试 = 不可上线 |
| Tool 参数校验 | **P2** | 更多 agent 调工具, 错误参数概率线性增长 |

---

## 2. 自然的 Agent 边界 (基于业务工作流)

代码审计识别出 **2 个强子 agent 候选** + **1 个潜在候选**:

### Sub-Agent 1: DataUploadAgent (数据上传 agent)

```
触发: 用户上传 Excel/CSV 文件 + "导入产品数据"
工具集: parse_file, analyze_columns, resolve_and_validate,
        create_references, preview_changes, execute_upload,
        rollback_batch, audit_data
超时: 180s
典型轮次: 5-8 轮 (解析 → 列映射 → 置信度匹配 → 预览 → 确认 → 执行)
```

**为什么适合做子 agent**:
- 7 步流水线, 完全自包含, 不依赖 inquiry/fulfillment 工具
- 需要 LLM 做模糊匹配 (supplier name → supplier_id), 不是简单 CRUD
- 失败时需要回滚 (rollback_batch), 隔离后不影响父 agent 状态
- 执行时间长 (可能 2-3 分钟), 父 agent 可以并行做别的事

### Sub-Agent 2: InquiryAgent (询价生成 agent)

```
触发: 订单已匹配, 用户说 "生成询价单"
工具集: check_inquiry_readiness, fill_inquiry_gaps, generate_inquiries,
        modify_excel, query_db
超时: 120s
典型轮次: 3-5 轮 (检查就绪 → 补齐缺失 → 生成文件)
```

**为什么适合做子 agent**:
- 前置条件明确 (match_results 必须存在), 入口清晰
- 可按供应商并行 (已有 `run_inquiry_orchestrator` 模式)
- 输出是文件 (Excel), 需要结构化返回 (文件路径 + 状态)

### Sub-Agent 3: ResearchAgent (分析研究 agent) — 新增

```
触发: 用户问 "分析一下这个供应商的历史报价" / "这个品类的价格趋势"
工具集: query_db, get_db_schema, calculate, think, web_search (可选)
超时: 90s
典型轮次: 5-10 轮 (多次查 DB → 计算 → 分析 → 总结)
```

**为什么需要**:
- Agent-centric 系统的核心价值是**让 agent 帮用户做分析**, 不只是执行流水线
- 分析任务需要多轮查询 + 推理, 适合独立 agent
- 可以用不同的 model (如 Gemini Pro 做深度分析, Flash 做日常对话)

---

## 3. 立即做的事 — 更新版

### 原有 6 项 (不变, Day 1-4)

| # | 任务 | 代码量 |
|---|------|--------|
| 1 | Bash 白名单 | ~40 行 |
| 2 | 修 compact 只执行一次 bug | ~30 行 |
| 3 | LLM 调用加 timeout | ~4 行 |
| 4 | SSE 心跳 | ~15 行 |
| 5 | Kimi compact 阈值调低 | 1 行 |
| 6 | 日期注入 system prompt | ~5 行 |

### 新增: Agent-Centric 基础 (Day 5-10)

#### 项 A: 注册 3 个真实子 agent 🟢

**做什么**: 在 `services/agent/sub_agents/__init__.py` 中注册 DataUploadAgent, InquiryAgent, ResearchAgent。

**具体代码**:

```python
# services/agent/sub_agents/__init__.py

from services.agent.sub_agent import register_sub_agent, SubAgentConfig

def register_all():
    register_sub_agent(SubAgentConfig(
        name="data_upload",
        description="处理产品数据文件上传: 解析Excel/CSV → 列映射 → 置信度匹配 → 预览 → 执行导入",
        system_prompt=(
            "你是数据上传专员。用户已经给你一份产品数据文件。\n"
            "严格按照流程执行: parse_file → analyze_columns → resolve_and_validate → "
            "preview_changes → (等用户确认) → execute_upload。\n"
            "遇到低置信度匹配时, 用 request_confirmation 让用户确认。"
        ),
        enabled_tools={
            "parse_file", "analyze_columns", "resolve_and_validate",
            "create_references", "preview_changes", "execute_upload",
            "rollback_batch", "query_db", "get_db_schema",
            "think", "request_confirmation",
        },
        max_turns=15,
        thinking_budget=2048,
        timeout_seconds=180,
    ))

    register_sub_agent(SubAgentConfig(
        name="inquiry",
        description="为已匹配的订单生成供应商询价单: 检查就绪状态 → 补齐缺失信息 → 生成Excel询价文件",
        system_prompt=(
            "你是询价单生成专员。用户需要为某个订单生成供应商询价单。\n"
            "流程: check_inquiry_readiness → (如有gap) fill_inquiry_gaps → generate_inquiries。\n"
            "注意: 必须先检查就绪状态, 有 blocking gap 时不能直接生成。"
        ),
        enabled_tools={
            "check_inquiry_readiness", "fill_inquiry_gaps", "generate_inquiries",
            "modify_excel", "query_db", "get_db_schema",
            "think", "request_confirmation",
        },
        max_turns=10,
        thinking_budget=1024,
        timeout_seconds=120,
    ))

    register_sub_agent(SubAgentConfig(
        name="researcher",
        description="执行数据分析和研究: 供应商历史报价分析、品类价格趋势、订单统计等",
        system_prompt=(
            "你是供应链数据分析师。用户需要你从数据库中查询数据, 进行分析, 给出洞察。\n"
            "使用 query_db 获取数据, 用 calculate 做计算, 用 think 组织分析思路。\n"
            "回答时给出具体数字和趋势, 不要泛泛而谈。"
        ),
        enabled_tools={
            "query_db", "get_db_schema", "calculate",
            "think", "get_current_time",
        },
        max_turns=15,
        thinking_budget=3072,
        timeout_seconds=90,
    ))
```

**工作量**: ~80 行配置, 半天。
**验证**: 在 chat 中输入 "帮我分析供应商 ABC 的历史报价" → 父 agent 应调用 `delegate("researcher", "分析供应商 ABC 的历史报价")`。

---

#### 项 B: 子 agent 结构化返回 🟢

**问题**: 当前 `run_sub_agent()` 返回 raw string (agent 的最终文本回答)。父 agent 无法可靠提取文件路径、状态码、错误信息。

**做什么**: 引入 `SubAgentResult` dataclass, 改造 `run_sub_agent()` 返回值。

```python
# services/agent/sub_agent.py 新增

@dataclass
class SubAgentResult:
    status: str          # "success" | "timeout" | "error"
    output: str          # Agent 的文本回答
    elapsed_ms: int      # 执行时长
    turns_used: int      # 使用了多少轮
    artifacts: list[str] # 产出的文件路径 (从 workspace 提取)
    errors: list[str]    # 错误/警告信息
```

改造 `run_sub_agent()`:
```python
def run_sub_agent(...) -> SubAgentResult:
    start = time.time()
    try:
        result_text = agent.run(prompt)
        elapsed = int((time.time() - start) * 1000)
        # 从 child_ctx.workspace_dir 提取产出文件
        artifacts = _collect_artifacts(child_ctx)
        return SubAgentResult(
            status="success", output=result_text,
            elapsed_ms=elapsed, turns_used=agent.turn_count,
            artifacts=artifacts, errors=[],
        )
    except FuturesTimeoutError:
        return SubAgentResult(status="timeout", output="", ...)
    except Exception as e:
        return SubAgentResult(status="error", output="", errors=[str(e)], ...)
```

改造 `delegate` 工具的返回格式:
```python
def delegate(agent_name: str, task: str) -> str:
    result = run_sub_agent(...)
    if result.status == "success":
        output = f"[子Agent '{agent_name}' 完成]\n{result.output}"
        if result.artifacts:
            output += f"\n\n产出文件: {', '.join(result.artifacts)}"
        return output
    elif result.status == "timeout":
        return f"Error: 子Agent '{agent_name}' 超时 ({result.elapsed_ms}ms)"
    else:
        return f"Error: 子Agent '{agent_name}' 失败: {'; '.join(result.errors)}"
```

**工作量**: ~60 行, 半天。

---

#### 项 C: 子 agent 安全继承 🟢

**问题**: 子 agent 不继承父的中间件链。如果 DataUploadAgent 调 `bash`, 没有 guardrail 拦截 — 白名单防线被绕过。

**做什么**: 在 `run_sub_agent()` 中, 将安全相关的中间件复制到子 agent:

```python
def run_sub_agent(...) -> SubAgentResult:
    ...
    # 安全中间件必须继承 (不是全部, 只有安全相关的)
    child_chain = MiddlewareChain()
    child_chain.add(GuardrailMiddleware(DefaultGuardrailProvider()))  # bash 安全
    child_chain.add(LoopDetectionMiddleware())  # 防止子 agent 死循环
    child_chain.add(ErrorRecoveryMiddleware())   # 错误提示

    agent = ReActAgent(
        ...
        config=Config(
            ...
            middlewares=child_chain,  # 注入安全中间件
        ),
    )
```

**关键**: 只继承安全类中间件 (Guardrail, LoopDetection, ErrorRecovery)。**不继承** Memory, Summarization, Clarification (这些是父 agent 的状态管理, 子 agent 不需要)。

**工作量**: ~20 行, 1 小时。

---

#### 项 D: 并行子 agent 执行器 🟡 (Week 2)

**场景**: "帮我同时分析供应商 A, B, C 的报价历史"

**做什么**: 在 `sub_agent.py` 中新增 `run_sub_agents_parallel()`:

```python
def run_sub_agents_parallel(
    tasks: list[tuple[str, str]],  # [(agent_name, prompt), ...]
    parent_ctx: ToolContext,
    max_workers: int = 3,
    **kwargs,
) -> list[SubAgentResult]:
    """并行运行多个子 agent, 复用 inquiry_orchestrator 的模式。"""
    results = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=min(len(tasks), max_workers)) as executor:
        futures = {
            executor.submit(run_sub_agent, name=name, prompt=prompt,
                          parent_ctx=parent_ctx, **kwargs): i
            for i, (name, prompt) in enumerate(tasks)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = SubAgentResult(
                    status="error", output="", errors=[str(e)],
                    elapsed_ms=0, turns_used=0, artifacts=[],
                )

    return results
```

在 `delegate` 工具中增加批量模式:
```python
@registry.tool(
    description="...",
    parameters={
        "agent_name": ...,
        "task": ...,
        "parallel_tasks": {
            "type": "ARRAY",
            "description": "批量并行任务 [{agent_name, task}, ...]",
            "required": False,
        },
    },
)
def delegate(agent_name: str = "", task: str = "", parallel_tasks: list = None) -> str:
    if parallel_tasks:
        tasks = [(t["agent_name"], t["task"]) for t in parallel_tasks]
        results = run_sub_agents_parallel(tasks, parent_ctx=ctx, ...)
        return _format_parallel_results(results)
    else:
        result = run_sub_agent(name=agent_name, prompt=task, ...)
        return _format_single_result(result)
```

**工作量**: ~80 行, 1 天。

---

#### 项 E: Agent trace 持久化 🟡 (Week 2)

**为什么升级到 P1**: 多 agent 系统中, 如果无法追踪"父 agent 在第 5 轮委派了 DataUploadAgent, 该 agent 在第 3 轮调了 execute_upload 失败了", 就无法调试任何复杂问题。

**做什么**: 不新建表 — 利用已有的 `v2_sub_agent_tasks` 表 + 扩展 `metadata` JSON 列:

```python
# 在 run_sub_agent 完成后, 写入 step_log
_record_task(db, {
    "parent_session_id": session_id,
    "sub_agent_name": name,
    "status": result.status,
    "duration_ms": result.elapsed_ms,
    "turns_used": result.turns_used,
    "metadata": json.dumps({
        "step_log": agent.step_log[:20],  # 最多 20 步
        "artifacts": result.artifacts,
        "errors": result.errors,
    }),
})
```

对于父 agent, 在 `after_agent` middleware 中追加 session-level 摘要:
```python
# 写入 v2_agent_sessions.metadata
session.metadata = {
    "total_turns": turn_count,
    "tools_used": list(tool_counter.keys()),
    "sub_agents_invoked": sub_agent_names,
    "total_elapsed_ms": elapsed,
}
```

**工作量**: ~40 行, 半天。

---

## 4. 完整时间线

### Week 1: 安全 + Bug 修复 + Agent 注册 (Day 1-5)

| 天 | 任务 | 类型 |
|----|------|------|
| Day 1 | Bash 白名单 + guardrail 增强 | 原有 #1 |
| Day 2 | 修 compact 一次性 bug + Kimi 阈值 | 原有 #2, #5 |
| Day 3 | LLM timeout + SSE 心跳 + 日期注入 | 原有 #3, #4, #6 |
| Day 4 | **注册 3 个子 agent** (配置 + 测试) | 新增 A |
| Day 5 | **SubAgentResult 结构化返回** + **安全中间件继承** | 新增 B, C |

### Week 2: Agent 体系补全 (Day 6-10)

| 天 | 任务 | 类型 |
|----|------|------|
| Day 6-7 | **并行子 agent 执行器** + delegate 工具增强 | 新增 D |
| Day 8 | **Agent trace 持久化** (利用已有表) | 新增 E |
| Day 9-10 | **端到端测试**: 父 agent → delegate → 子 agent → 结果回传 → 前端展示 | 集成测试 |

### Week 3-4: 迭代优化 (基于真实使用反馈)

| 任务 | 触发条件 |
|------|----------|
| 子 agent system prompt 调优 | 跑完 10 个真实订单, 根据成功率调整 |
| 添加更多子 agent (如 FulfillmentAgent) | 业务需要时 |
| Tool 参数校验 (Pydantic) | 错误参数导致 crash 超过 5 次 |
| 子 agent 多级委派 | 出现明确的三级场景 (目前没有) |
| Prompt-too-long 自动恢复 | 日志中出现 3+ 次 context overflow |

---

## 5. Agent-Centric 架构全景图

```
┌────────────────────────────────────────────────────┐
│                    用户 (采购人员)                     │
│                    ↕ SSE + REST                      │
├────────────────────────────────────────────────────┤
│               父 Agent (CruiseAgent)                 │
│  ┌──────────────────────────────────────────────┐  │
│  │ ReActAgent Engine (engine.py)                 │  │
│  │ ├─ 中间件链: Guardrail, Memory, Loop, ...     │  │
│  │ ├─ 核心工具: query_db, think, calculate       │  │
│  │ ├─ delegate 工具 ← 入口                       │  │
│  │ └─ tool_search ← 动态激活                     │  │
│  └──────────────────────────────────────────────┘  │
│         │                │               │          │
│    ┌────┴────┐    ┌──────┴─────┐   ┌─────┴─────┐  │
│    │ DataUp- │    │ Inquiry    │   │ Research  │  │
│    │ load    │    │ Agent      │   │ Agent     │  │
│    │ Agent   │    │            │   │           │  │
│    │ ─────── │    │ ────────── │   │ ───────── │  │
│    │ 9 tools │    │ 5 tools    │   │ 4 tools   │  │
│    │ 180s    │    │ 120s       │   │ 90s       │  │
│    │ 15 turns│    │ 10 turns   │   │ 15 turns  │  │
│    └─────────┘    └────────────┘   └───────────┘  │
│         │                │               │          │
│    ┌────┴────────────────┴───────────────┴────┐    │
│    │           共享层 (不隔离)                    │    │
│    │  PostgreSQL (Supabase) + Supabase Storage  │    │
│    │  安全中间件 (Guardrail, LoopDetection)       │    │
│    └────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────┤
│                   可观测层                            │
│  v2_sub_agent_tasks (执行记录)                       │
│  v2_agent_sessions.metadata (session 摘要)           │
│  stream_queue (SSE 实时事件)                         │
└────────────────────────────────────────────────────┘
```

---

## 6. 子 agent 设计原则 (从 Claude Code 学到的, 但适配后)

| Claude Code 的做法 | 我们采用的适配版 | 为什么 |
|---|---|---|
| 子 agent 完全独立 context (深拷贝 file state) | 子 agent 共享 DB session, 隔离 session_data | 我们的 agent 主要操作数据库, 不操作文件系统 |
| 子 agent 有独立 AbortController (子→父传播) | 子 agent 通过 ThreadPoolExecutor timeout 控制 | Python 没有 AbortController, timeout + cancel_event 等价 |
| 子 agent 结果通过 pendingNotification 注入父消息流 | 子 agent 结果通过 delegate 工具的 return 值同步返回 | 我们暂时只需要同步模式; 异步模式用 SSE events |
| 子 agent 可以有自己的 agent definition (.md 文件) | 子 agent 配置在 Python 代码中 (SubAgentConfig) | 我们的用户是业务人员, 不会写 .md agent 定义 |
| 子 agent 支持 worktree 隔离 (git 操作安全) | 不需要 | 我们不做 git 操作 |
| Prompt cache 共享 (父子共用 cacheSafeParams) | 不需要 | Gemini/Kimi 不支持 Anthropic 的 prompt caching |
| 子 agent 不继承父的 middleware | **改: 安全类中间件必须继承** | Claude Code 绑定 Anthropic (自带安全), 我们的安全靠中间件 |

---

## 7. 和原始路线图的对比

| 原批判版 (4 天) | Agent-Centric 版 (10 天) | 变化原因 |
|---|---|---|
| 6 项 bug 修复 | 6 项 bug 修复 (不变) | 安全和稳定性仍是前提 |
| — | +注册 3 个子 agent | 核心需求 |
| — | +结构化返回 | 子 agent 输出必须可靠解析 |
| — | +安全中间件继承 | 子 agent 不能绕过白名单 |
| — | +并行执行器 | 多供应商场景 |
| tracer 排期做 | tracer 升到 Week 2 | 多 agent 必须可追踪 |
| API retry 不做 | 仍然不做 | 各 provider 已有 retry |
| max_output_tokens 不做 | 仍然不做 | 65536 够用 |
| Skill 自动扫描不做 | 仍然不做 | CI/CD deploy 够快 |

**净增**: 从 4 天 → 10 天。多出的 6 天全部投在子 agent 体系上。这不是"过度工程", 而是**你明确要做的核心方向**。
