# Sub-Agent 与 Skill 优化分析

> 日期: 2026-04-08
> 核心发现: 子 agent 是死代码, skills 和 system prompt 存在大量重复, 需要减法而非加法

---

## 1. 审计发现的两个硬伤

### 硬伤 1: 子 agent 完全没有接通

代码审计发现:
- `register_all()` **从未被调用** — 在生产代码中 0 处 import (参见: grep 结果)
- `create_delegate_tool()` **从未被注册** — 不在 `create_chat_registry()` 中
- 结果: `SUB_AGENT_REGISTRY` 在运行时始终为空, 父 agent 没有 `delegate` 工具

**三个子 agent (data_upload, inquiry, researcher) 虽然定义了配置, 但用户无法以任何方式触发它们。**

### 硬伤 2: Skills 和 System Prompt 大量重复

`layers.py:domain_knowledge()` 中已经硬编码了:
- 数据上传流程 (parse → prepare → execute) — 和 `data-upload` skill 重复
- 询价流程 (check → fill → generate) — 和 `generate-inquiry` skill 重复
- 履约状态流 (pending → ... → paid) — 和 `fulfillment` skill 重复
- SQL 查询指南 (JSON 语法, LIMIT, 错误恢复) — 和 `query-data` skill 重复

这意味着: 每次对话, agent 的 system prompt 已经包含了这些工作流知识 (~2000 tokens), 然后 skill 又注入一遍 (~1000 tokens) — **同样的信息出现两次, 浪费 token, 且两处不一致时 LLM 会困惑**。

---

## 2. 证据驱动的判断

### 子 agent 该不该要?

| 证据来源 | 结论 |
|---------|------|
| **Anthropic 官方** ("Building Effective Agents") | "Start with simple prompts... add multi-agent only when simpler solutions fall short" |
| **临床研究** (npj Health Systems, 348 试验) | 单 agent vs 多 agent 在 **<10 个并发任务**时无显著差异; 超过 10 个才有意义 (p<0.01) |
| **Anthropic 多 agent 研究系统** | 多 agent 消耗 **15x 更多 token**; 用于"10+ subagents with clearly divided responsibilities"的复杂研究 |
| **Claude Code** | 子 agent 用于**代码修改隔离** (worktree) 和**并行文件搜索** — 是 context 隔离需求, 不是 workflow 编排 |
| **我们的场景** | 典型对话 10-20 轮, 5-15 次工具调用。**远低于需要多 agent 的阈值**。当前 14 个工具 + skill 引导已经足够。 |

**判断: 子 agent 现在不需要。** 原因:
1. 我们的三个"子 agent"做的事 (数据上传, 询价生成, 数据分析) **和 skill 完全重复** — 只是多了 context 隔离
2. Context 隔离对我们没有价值 — 对话不会长到需要隔离 (Kimi 128K, compact 已修)
3. 子 agent 每次调用 = 新建 LLM provider + 新建 registry + 新的 API 调用 — 延迟和成本翻倍
4. 当前只有 1-2 个用户, 没有并发任务压力

**什么时候需要子 agent**: 当出现以下信号时再启用:
- 单次对话超过 50 轮 (context 压力)
- 需要同时处理 3+ 个订单 (并发需求)
- Skill 引导不够, agent 仍然频繁跳步出错 (质量需求)

### Skill 该怎么优化?

| 证据来源 | 结论 |
|---------|------|
| **SKILL.md 模式** (Medium, First Principles Deep Dive) | 三级加载: Level 1 元数据 (~100 token) → Level 2 完整内容 (<5K) → Level 3 引用文件 (按需) |
| **Anthropic** ("Effective Context Engineering") | 区分"always-on"知识和"just-in-time"知识; always-on 放 system prompt, just-in-time 放 skill |
| **Token 经济学** | Skill ~2000 tokens vs Tool schema ~50K tokens — skill 远更便宜, 但**不该重复** |
| **安全研究** (arxiv 2510.26328) | Skill 文件每一行都被当作指令, 恶意内容可以无混淆注入 — 说明 skill 内容应精简、不包含 shell 命令 |

**判断: 消除重复, 精简 skill, 让 system prompt 和 skill 各管各的。**

---

## 3. 具体优化方案

### 3.1 子 agent: 不激活, 保留框架, 清理死代码

**做什么:**
- 不调用 `register_all()`
- 不注册 `delegate` 工具
- `sub_agents/__init__.py` 恢复为空 (删除三个 SubAgentConfig 注册)
- `sub_agent.py` 框架保留 (SubAgentResult, run_sub_agent 等) — 未来需要时能用
- 删除之前加的安全中间件继承代码 (因为没用)

**不做什么:**
- 不删 `sub_agent.py` — 框架有价值, 等信号再启用
- 不删 `v2_sub_agent_tasks` 表 — 零成本

### 3.2 Skills: 消除与 system prompt 的重复

**当前状态:**

```
system prompt (layers.py:domain_knowledge)    skills/ 目录
─────────────────────────────────────────    ─────────────
上传流程 (parse→prepare→execute)              data-upload/SKILL.md (同样的流程)
询价流程 (check→fill→generate)                generate-inquiry/SKILL.md (同样的流程)
履约状态流                                    fulfillment/SKILL.md (同样的流程)
SQL 查询指南                                  query-data/SKILL.md (同样的指南)
                                              modify-inquiry/SKILL.md (独有, 无重复)
```

**优化后:**

```
system prompt (精简版)                        skills/ 目录 (详细版)
────────────────────                         ─────────────
核心表结构 (保留)                              data-upload/SKILL.md (详细步骤, 保留)
JSON 查询语法 (保留, 高频出错)                 generate-inquiry/SKILL.md (详细步骤, 保留)
宪法规则 C1-C4 (保留)                         fulfillment/SKILL.md (详细步骤, 保留)
                                              query-data/SKILL.md (详细指南, 保留)
删除: 上传流程步骤                             modify-inquiry/SKILL.md (保留)
删除: 询价流程步骤
删除: 履约状态流
删除: 上传模板列说明
```

**原则: System prompt 放"是什么" (表结构, 语法), Skills 放"怎么做" (流程步骤)。不重复。**

预计减少 system prompt ~800 tokens (layers.py domain_knowledge 中的流程描述部分)。

### 3.3 Skill 精简: 删除冗余内容

5 个 skill 全部保留, 但每个精简:
- 去掉和 system prompt 重复的表结构/语法信息 (skill 不需要重复"v2_orders 的 JSON 列用 json_array_elements")
- 每个 skill 控制在 **1000 tokens 以内** (当前 query-data skill 最长, 约 1500 tokens)
- 加 `when-to-use` 描述 (提高 scenario 匹配准确率)

---

## 4. 不该做的

| 看起来该做 | 为什么不做 |
|-----------|----------|
| 激活子 agent | 当前 14 个工具 + skill 已覆盖所有路径; 子 agent 增加延迟和成本, 无额外收益 |
| 加更多 skill | 5 个已覆盖 4 条路径 + 1 个迭代场景; 更多 skill 增加选择负担 |
| Skill 内嵌 tool 调用代码 | 安全风险 (arxiv 2510.26328: skill 每行都是指令); skill 只做指导, 不做执行 |
| 用 skill 替代 tool | Anthropic: "Tools are hands, skills are training" — 不可混淆 |
| 给每个 manage_* 工具配一个 skill | manage_order 等工具的 description 里已有示例调用, 不需要额外 skill |
