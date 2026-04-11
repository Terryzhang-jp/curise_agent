# Process Document Skill 落实进度

> 起始日期: 2026-04-10
> 范围: 当前阶段只覆盖 `purchase_order` 类型文档，其他类型后续扩展
> 维护方式: 每完成一次真实验证或状态变更后追加一节，不删旧节
> 相关文档:
> - `process-document-skill-research-2026-04-10.md` — 研究与设计原则
> - `v2-backend/skills/process-document/SKILL.md` — Skill 本体
> - `v2-backend/tests/_e2e_process_document_real.py` — 真实端到端脚本

---

## 当前里程碑

- [x] M1 — Skill 文本与底层 Tool 行为对齐（mock 数据）
- [x] M2 — 真实 PDF + 真实 Gemini + 真实 Supabase 全链路跑通一次（脚本编排）
- [x] **M3 — 全部 4 个分支覆盖：happy / 缺字段 / 非 PO / 产品数=0 ✅**
- [x] **M4 — 真实 ReActAgent 自主执行 skill，且 skill→skill 链式调用打通 ✅**
- [x] **M5 — currency 符号归一化为 ISO 三位代码（不可识别返回 None） ✅**
- [x] **M5b — Gemini 重试加固：智能错误分类 + 指数退避 + jitter ✅**
- [x] **M5c — preview 与 create 阻断字段一致化 ✅**
- [ ] **下一步: 清理脏数据（详见下方「下一步：脏数据清理」一节）**
- [ ] M6 — 进入扩展阶段（开始支持非 purchase_order 文档类型）

---

## 范围声明（重要）

当前阶段，本 Skill 仅处理 `doc_type == "purchase_order"` 的文档。

- 其他文档类型（报价单、发票、运单、库存表等）**不在本阶段范围**
- 后续扩展时必须同步更新:
  - `SKILL.md` 的 Step 2.1 文档类型检查规则
  - `_classify_document()` 的分类逻辑
  - 本进度文档的「范围声明」一节

---

## 2026-04-10 — M1 完成（mock 数据回归）

### 做了什么

- 重写 `v2-backend/skills/process-document/SKILL.md`，引入 validation gate / 字段契约 / 暂停规则 / examples
- 编写 `tests/_evaluate_process_document_skill_flow.py`，使用 sqlite in-memory + mock `process_document` 验证两个核心 case

### 验证结果

| Case | preview | create | 数据库订单状态 |
|------|---------|--------|----------------|
| 字段完整 | `可直接建单: 是` | `已生成订单 #1, status=ready` | ready ✅ |
| 缺 `delivery_date` | `可直接建单: 否, 缺失字段: delivery_date` | `Error: 当前缺少关键字段，不能创建订单: delivery_date` | 订单未建 ✅ |

### 关键发现

底层硬门禁已经存在于 `services/document_order_projection.py:158 _ensure_order_creation_allowed`，缺关键字段时 raise ValueError，不会落库。

这意味着 Skill 不再只是「prompt 层建议」，而是有真实的 tool/projection 层强制约束：即使有调用方绕过 Skill 直接调 `manage_document_order(action="create")`，缺字段时也建不出脏订单。

---

## 2026-04-10 — M2 完成（真实 PDF + 真实 Gemini + 真实 Supabase）

### 测试目标

用真实 PDF (`/Users/yichuanzhang/Desktop/curise_system_2/68358749.pdf`)，**不 mock 任何东西**，跑一次完整链路：
- 真实 `create_document_record` 写入 Supabase
- 真实 `run_document_pipeline` 调用 Gemini Native PDF 抽取
- 真实 `manage_document_order(preview/create)` 经 projection 层建单
- 真实 `manage_order(overview)` 复核
- 真实 `use_skill(process-document)` 加载 skill 文本

### 执行

```bash
cd v2-backend
PYTHONPATH=. ./venv/bin/python tests/_e2e_process_document_real.py
```

### 真实结果

| 指标 | 值 |
|------|---|
| Document ID（Supabase 真数据） | 3 |
| Order ID（Supabase 真数据） | 70 |
| Gemini 抽取耗时 | 100.1 秒 |
| 抽取方法 | `gemini_native_pdf` |
| doc_type | `purchase_order` ✅ |
| po_number | `68358749` ✅ |
| ship_name | `CELEBRITY EDGE` ✅ |
| delivery_date | `2026-01-05` ✅ |
| vendor_name | `AJX Global Trading Pty Ltd` ✅ |
| destination_port | `SYD` |
| total_amount | `55203.08` |
| currency | `$` ⚠️ 符号未归一化 |
| 产品数 | **73** |
| Skill gate | `可直接建单: 是` |
| 建单结果 | `order #70, status=ready, processing_error=None` |
| Overview | 正常返回，PO/船名/日期/币种/产品列表都对 |

### 加载到的 Skills

`['data-upload', 'fulfillment', 'generate-inquiry', 'modify-inquiry', 'process-document', 'process-order', 'query-data']`

`process-document` 已被 ToolContext 正确加载，skill 文本长度 3543 字符。

### 这次验证的边界（必读）

**这次验证的是「skill 描述的流程在底层是可执行的」，不是「真实 LLM 会按 skill 执行」**。

- 脚本里的 step 顺序（preview → create → overview）是脚本作者按 SKILL.md 手动编排的
- 没有真的把 LLM 接进来让它读 skill 文本后自主决定调哪些 tool
- 因此本里程碑只能证明：底层 tool 链 + projection + DB 在 happy path 下表现正确，与 SKILL.md 的描述一致

真实 LLM 自主执行的验证留给 M4。

### 真实暴露的问题

**问题 1: 币种字段未归一化**
- Gemini 抽取出 `currency = "$"`（原始符号）
- `_build_order_payload` / projection 没有做符号 → ISO 代码的转换
- 直接落库到 `order.currency = "$"`
- SKILL.md 第 7.3 节明确要求 3 位大写代码（USD/EUR/JPY/CNY）
- 当前系统没有任何位置做这件事
- **影响**: 不阻断建单（currency 是「重要但不阻断」字段），但下游询价单生成、汇率匹配、财务对账时都会变成隐性 bug
- **行动项**: M5 要补归一化层，建议位置在 `services/document_order_projection.py` 的 metadata 整理阶段，或 `services/document_processor.py` 的后处理阶段

**问题 2: Gemini 抽取耗时 100 秒**
- 73 行产品的 PDF，Gemini native PDF mode 用了 100.1 秒
- 这不是 bug，是真实成本
- **影响**: 前端 loading UI、超时配置、用户预期管理都要按这个量级设计
- **行动项**: 后续如果加上「实时进度提示」需求，要在 `run_document_pipeline` 里加 stage hook

### 这次验证没覆盖到的分支（M3 待办）

| 分支 | SKILL.md 里的位置 | 状态 |
|------|------------------|------|
| 文档类型 ≠ purchase_order 时暂停 | Step 2.1 | 未测 |
| 产品数 = 0 时暂停 | Step 2.2 | 未测 |
| 重复触发 create 时复用已有订单 | Step 3 | 未测 |
| 调用 `use_skill(process-order)` 衔接 | Step 5 | 未测 |
| 真实 LLM 按 skill 自主执行 | 全文 | 未测 |

---

## Skill 设计与现状的对照表

下表用于在每次扩展或修复后快速定位「文档说了什么 vs 系统真的做了什么」。

| 字段 / 规则 | SKILL.md 期望 | 当前真实状态 | 差距 |
|------------|--------------|-------------|------|
| `po_number` | 保留原文 | ✅ Gemini 直接返回 | 无 |
| `ship_name` | 保留主船名 | ✅ Gemini 直接返回 | 无 |
| `delivery_date` | `YYYY-MM-DD` | ✅ Gemini 已返回该格式 | 无 |
| `order_date` | `YYYY-MM-DD`，可空 | ✅ | 无 |
| `currency` | 3 位大写 ISO 代码 | ⚠️ 原始符号 `$` | **需要 M5 补归一化** |
| `destination_port` | 文档原文港口 | ✅ `SYD` | 无（DB 主键解析在 process-order 阶段） |
| `total_amount` | 数字或空 | ✅ `55203.08` | 无 |
| `products` 非空才能建单 | 是 | ✅ projection 层硬阻断 | 无 |
| 关键字段缺失阻断 | po/ship/delivery 任一缺 | ✅ projection 层硬阻断 | 无 |
| 文档类型 ≠ purchase_order 暂停 | 是 | ⚠️ 未测 | M3 剩余 |
| 复用已有订单 | 区分新建 vs 复用 | ✅ tool 文案 + LLM 行为已验证 | 无（M4 修复） |
| Step 5 衔接 process-order skill | use_skill | ✅ M4 修复后 LLM 真的会调 | 无（依赖 use_skill 在 CORE_TOOLS） |

---

## 下一步行动（按优先级）

### P0 — 完成 M3 的剩余 case

写一个补充脚本（或扩展 `_e2e_process_document_real.py`），覆盖：
1. 用一份明显非 PO 的文档跑 preview（或临时把 doc_type 改掉），验证 skill 阻断逻辑
2. 用一份能解析但产品列表为空的文档跑，验证产品数=0 阻断
3. 对同一个 document 连续调两次 `manage_document_order(action="create")`，验证第二次复用 order_id 而不是重复建单
4. 在已建单的情况下调 `use_skill(process-order)`，验证它能被 ToolContext 正确加载、skill 文本能正确返回

### P1 — 启动 M4

设计一个最小 LLM agent harness：
- 输入：document_id
- system prompt 注入 SKILL.md 内容
- 让 LLM 自主调 manage_document_order / manage_order / use_skill
- 全程记录 tool call 序列
- 检查 tool call 序列是否与 SKILL.md 描述的 5 个 step 一致

这一步是「skill 是否真的在驱动 LLM 行为」的唯一证明方式。

### P2 — 补 M5 currency 归一化

在 `services/document_order_projection.py` 增加一个 `_normalize_currency()`：
- `$` → `USD`
- `¥` / `￥` → `JPY`（注意 CNY 也用 ¥，需要根据 vendor 国家辅助判断或留 unknown）
- `€` → `EUR`
- `£` → `GBP`
- 三位 ISO 代码 → 直接保留
- 不能确定 → 设为 `null`，**不要猜**（与 skill 原则一致）

---

## 2026-04-10 — M4 完成（真实 ReActAgent 自主执行 + skill→skill 链式调用打通）

### 这次回答的问题

上一次 M2 的局限是：脚本作者按 SKILL.md 手动编排了 step 顺序去调 tool，没有真的把 LLM 接进来让它自己读 skill 自己决定。M4 必须证明：**把真实 ReActAgent 接进来，给它 skill，它会按 skill 跑**。

### 测试入口

- `tests/_e2e_process_document_agent.py`
- 用真实 `ReActAgent` + `GeminiProvider` + 真实 `create_chat_registry` + 真实 Supabase
- 通过 slash command `/process-document document_id=3` 触发
- 全程通过 `on_step` hook 抓取每一次 tool call

### 第一次跑（修复前）的发现

| 现象 | 根因 |
|------|------|
| Step 1/3/4 完全按 SKILL.md 顺序执行 ✅ | skill 描述清楚的部分 LLM 会服从 |
| Step 5 走错路径 ❌ | LLM 调了 `tool_search(query="process-order")` 而不是 `use_skill(skill_name="process-order")` |
| 调 create 时 LLM 看不出是「复用」 | tool 返回文案没有区分 new vs reuse |
| 流程末尾 Gemini API 500 INTERNAL | 外部不可控错误 |

### 修复（按根因分别处理）

| # | 文件 | 改动 | 影响范围 |
|---|------|------|---------|
| 1 | `services/tools/__init__.py` | `use_skill` 加入 `CORE_TOOLS` | **全系统所有 skill→skill 编排** |
| 2 | `services/tools/document_order.py` | create 分支显式区分「已新建订单 / 已复用已有订单」 | manage_document_order 调用方 |
| 3 | `skills/process-document/SKILL.md` | Step 5 加硬约束：禁止把 process-order 当 tool 去 search | 本 skill |

#### 修复 1 的重要性（必读）

`use_skill` 原本是 deferred tool，意味着 LLM 在 schema 里**根本看不到它存在**。要使用必须先 `tool_search`。但 LLM 在「我要进入下一个 skill」的语境里，自然会去 search 那个 skill 的名字（process-order），结果搜不到（因为 process-order 是 skill 不是 tool），陷入死路。

这不是 process-document 一个 skill 的问题，**这是整个系统所有 skill 编排能力的硬伤**。任何 skill 想调另一个 skill 都做不到。修复后 `use_skill` 始终在 LLM 的 tool schema 里可见。

### 第二次跑（修复后）的真实结果

Tool call 序列（10 次调用，document_id=3）：

```
[01] tool_search(manage_document_order)            # 激活 deferred tool
[02] manage_document_order(preview, doc=3)         # SKILL.md Step 1 ✅
[03] manage_document_order(create, doc=3)          # SKILL.md Step 3 → 复用 #70 ✅
[04] manage_order(overview, order=70)              # SKILL.md Step 4 ✅
[05] use_skill(skill=process-order, order=70)      # SKILL.md Step 5 ✅✅✅
[06] tool_search(match_products)                   # process-order 自己驱动
[07] match_products(order=70)                      # 0.7s, 100% 匹配 73/73
[08] tool_search(manage_inquiry)
[09] manage_inquiry(check, order=70)               # 2 供应商 ready
[10] manage_inquiry(generate, order=70)            # 9.4s, 生成 2 份询价 xlsx
```

### 这次实际证明了什么

1. **process-document skill 真的驱动 LLM 行为** — 顺序、门禁、复用判断、衔接全部按 SKILL.md
2. **skill 之间能真的链式调用** — process-document 在 Step 5 调 use_skill，process-order 接管后又驱动 LLM 完成匹配 + 询价
3. **整个 v2 文档→订单→匹配→询价的核心业务链路在真实环境下端到端跑通** — PDF + Gemini + Supabase + Excel 询价单生成
4. **询价单真实生成** — `inquiry_68358749_supplier17_39e14c.xlsx` 和 `inquiry_68358749_supplier20_82a901.xlsx`

### 仍未解决的真实缺口

| # | 问题 | 状态 |
|---|------|------|
| 1 | currency 字段 `$` 未归一化为 ISO 代码 | M5 待办 |
| 2 | 非 purchase_order 文档分支未测 | M3 剩余待办 |
| 3 | 产品数=0 分支未测 | M3 剩余待办 |
| 4 | Gemini 偶发 500 INTERNAL（第一次跑遇到） | 外部，需要 agent 层重试策略 |

### 这次真正的「副产品」

发现 `use_skill` 不在 `CORE_TOOLS` 是一个**全局影响所有 skill 编排能力的隐藏 bug**。修复后整个系统的 skill 链路才真正可用。这件事如果不是用真实 agent 跑过，永远不会被发现——脚本编排的 M2 测不出来，因为脚本压根不需要 use_skill 工具，它直接调底层 tool。

---

## 2026-04-10 — UI「创建订单」按钮改造为 Agent 触发器

### 这次回答的问题

**用户的真问题**：你们设计了 agent 来处理「文档 → 订单」，结果 UI 上有一个按钮**绕过 agent，直接调底层 REST**。这就违背了 agent-first 的设计意图。如果 UI 不经过 agent，那 agent 系统就不是真理，而是平行存在的另一套实现，所有 skill 改进都只对 chat 用户生效，UI 用户绕过去。

### 修改前的现状

`v2-frontend/src/app/dashboard/documents/[id]/page.tsx` 上的「创建订单」按钮：

- 直接调 `createOrderFromDocument(documentId, force)`
- 走 `POST /api/documents/{id}/create-order`
- 后端直接调 `create_or_update_order_from_document()` 落库
- **完全绕过 ReActAgent**
- 还有一个「强制建单」按钮，缺关键字段时显示，传 `force=True` 绕过 projection 层 gate
- 这个 force=True 路径与 SKILL.md 第 51-58 行「缺关键字段必须暂停」直接矛盾

### 修改后的设计

「让 Agent 处理」按钮（取代原「创建订单」+ 删除原「强制建单」）：

```
用户在文档详情页点「让 Agent 处理」
   ↓
前端调 createChatSession(`处理文档 #N`)
   ↓
前端 router.push(`/dashboard/workspace?session=X&prompt=ENCODED`)
   ↓
工作台页面读 ?session 和 ?prompt URL 参数
   ↓
两阶段处理:
   Stage 1: 等 sessionsLoading=false, 调 handleSelectSession(X)
   Stage 2: 等 activeSessionId === X, 调 doSendRef.current("/process-document document_id=N")
   ↓
ReActAgent 接管, SSE 流式显示 thinking + tool call + 询价单生成
```

**两阶段的必要性**：`doSend` 通过闭包捕获 `activeSessionId`。如果不等 React 状态更新就直接 dispatch，会捕获到旧值（null）然后 early return。两个独立 effect + 两个 ref（`autoSelectedRef` / `promptDispatchedRef`）解决了这个竞态。

### 为什么不在前端直接 sendChatMessage？

诱人但错误。如果文档页面调 `createChatSession + sendChatMessage` 然后再 navigate，**SSE 流不会被前端听到**——`streamChatMessages` 只在 workspace 的 `doSend` 内部启动。结果：agent 在后端真跑了，但用户看不到 thinking / tool call / 实时进度。

**正解**：文档页面只创建 session、不发消息；workspace 才是真正的「发起 + 监听」单一职责入口。

### 改动文件

| 文件 | 改动 |
|------|------|
| `v2-frontend/src/app/dashboard/documents/[id]/page.tsx` | 删除 `createOrderFromDocument` import, 改 import `createChatSession`；`handleCreateOrder` → `handleProcessViaAgent`；删除「强制建单」按钮，缺字段时改为静态提示文字 |
| `v2-frontend/src/app/dashboard/workspace/page.tsx` | 加 `useSearchParams` / `useRouter`；新增 `autoSelectedRef` + `promptDispatchedRef`；新增两阶段 useEffect 处理 deep-link |

### 后端没动

`POST /api/documents/{id}/create-order` 这个 endpoint **保留**，但 UI 不再调用它。理由：

- 它就是 `manage_document_order(action="create")` 工具调用的同一个底层函数 `create_or_update_order_from_document`，删除会破坏 chat agent 路径
- 真正要做的是「让 UI 不再走 REST 直连」，而不是「删除 REST 入口」
- 后续如果想完全移除直连路径，可以在路由层加 `deprecated` 标记或加权限校验

### 验证

- ✅ `npx tsc --noEmit` 通过（exit=0）
- ✅ `npm run build`（Next.js 16.1.6 + Turbopack）clean compile, 11/11 静态页面生成成功

### 这一改之后系统的真实状态

| 路径 | 是否经过 agent | 跑多远 | 是否能绕过 skill 规则 |
|------|---------------|--------|---------------------|
| 旧 UI「创建订单」按钮 | ❌ | 只到建单 | ⚠️ 强制建单可绕 gate |
| 旧 UI「强制建单」按钮 | ❌ | 只到建单 | ⚠️ 直接 force=True |
| **新 UI「让 Agent 处理」按钮** | ✅ | **建单 → 匹配 → 询价单** | ❌ skill 全程执行 |
| Chat `/process-document` | ✅ | 建单 → 匹配 → 询价单 | ❌ |

UI 用户和 chat 用户从今天起走的是**同一条路**。

### 已知限制（待 follow-up）

1. **后端 REST endpoint 仍然存在** `POST /api/documents/{id}/create-order` 没删除，理论上还能被外部调用方绕过 agent。如果要完全堵死，需要后端加权限检查或删除 endpoint。
2. **没有 in-flight stream 重连** 用户如果在 agent 跑到一半刷新页面，会看到静态消息但不会重新连上 SSE 流。这是更广的 chat UX 问题，不只是这次改动暴露的。建议作为独立任务跟踪。

---

## 2026-04-10 — Robustness 修复一轮（M3 剩余 + M5 + M5b + M5c）

### 这次回答的问题

M4 跑通之后，剩下的不是「skill 能不能用」，而是「在真实数据和真实异常下系统够不够稳」。这一轮把 4 件事一起修了。

### Fix 1: currency 归一化（M5）

**位置**: `services/document_order_projection.py`

新增 `_normalize_currency()`：

- ISO 三位代码（USD/EUR/JPY/CNY 等 28 个常用代码） → 直接返回大写
- 不歧义符号（`$`, `€`, `£`, `A$`, `HK$` 等 16 个） → 映射到对应 ISO 代码
- 歧义符号（`¥`, `￥`） → 返回 `None`，**绝不猜测**
- 空值 / 未知字符串 / 非字符串 → 返回 `None`

**关键设计原则**: 与 SKILL.md「不要猜」一致。`¥` 既可能是 JPY 也可能是 CNY，设为 None 比错猜更安全。下游需要时由更高层（vendor 国家、order 港口）来辅助消歧。

**单元测试结果** (13 个 case):

```
'$' → USD       'USD' → USD     'usd' → USD     '€' → EUR
'¥' → None      '￥' → None     'A$' → AUD      'jpy' → JPY
'cny' → CNY     'AUD' → AUD     '' → None       None → None
'XYZ' → None    'us$' → USD
```

**真实数据验证**: 对 Supabase 上 doc_id=3 调 `build_order_payload()`：
- raw `currency` in extracted_data: `'$'`
- normalized in payload: `'USD'` ✅

注意：v2_orders #70 表里的 `currency` 列仍是历史的 `'$'`（复用分支不重写字段），但任何下一次 build_order_payload 都会得到正确值。M6 之前的真实数据都需要一次 force-rewrite 才能修。

### Fix 2: Gemini 重试加固（M5b）

**位置**: `services/agent/llm/gemini_provider.py`, `services/agent/config.py`

旧逻辑的问题：
- `max_retries=2` (3 次尝试) + 线性退避 1s/2s = 总共只能熬 ~3 秒
- 4xx 错误也被无差别重试，浪费 quota 和时间
- 没有 jitter，多 worker 并发时会同步打 API

新逻辑：
- 默认 `max_retries=3` (4 次尝试)，指数退避 1s/2s/4s/8s + 0~25% jitter，上限 30s → 容忍 ~15s 抖动
- 新增 `_is_retryable_error()`：只重试 5xx/408/425/429 + 网络/超时类错误
- 4xx 业务错误直接抛，不浪费时间
- 每次重试都 `logger.warning` 留痕，方便追溯

### Fix 3: M3 剩余分支（非 PO 文档 + 产品数=0）

**位置**: `tests/_evaluate_process_document_skill_flow.py`

新增两个 fixture case：

| Case | 输入 | 期望 preview | 期望 create |
|------|------|-------------|-------------|
| `non_po_case` | `doc_type="spreadsheet_document"`, 1 个产品, 元数据全空 | `可直接建单: 否, 缺失字段: po_number, ship_name, delivery_date, doc_type` | `Error: 缺少关键字段` |
| `zero_products_case` | `doc_type="purchase_order"`, 元数据完整, products=[] | `可直接建单: 否, 阻断原因: 产品列表为空` | `Error: 当前未识别到任何产品` |

**全部 4 个 case 一次跑通的实际输出**:

```
ready_case          → preview: 可建 → create: 已新建订单 #1, 币种: USD ✅
review_case         → preview: 缺 delivery_date → create: Error 阻断 ✅
non_po_case         → preview: 缺 4 字段 → create: Error 阻断 ✅
zero_products_case  → preview: 阻断原因 产品列表为空 → create: Error 阻断 ✅
```

**注意**: ready_case 的 overview 现在显示「币种: USD」而不是「币种: $」 — currency 归一化在 mock 路径已生效。

### Fix 4: preview 与 create 阻断字段一致化（M5c）

**位置**: `services/document_order_projection.py` `summarize_order_payload()`

**发现**: 在跑 non_po_case 时第一次发现这个 bug：

- preview 用 `missing_fields`（只检查 REQUIRED_ORDER_FIELDS）
- create 用 `blocking_missing_fields`（额外检查 doc_type）
- 结果：preview 说「缺 3 字段」，create 说「缺 4 字段」 — LLM 会困惑

**修复**: preview 改用 `blocking_missing_fields`，并在产品为空时显式输出「阻断原因: 产品列表为空」。这样 preview 看到的就是 create 真正会拦截的同一个集合。

### 最终回归测试: 真实 ReActAgent E2E

修完所有改动后又跑了一次 `_e2e_process_document_agent.py`，10 次 tool call，全部成功：

```
[01-02] manage_document_order(preview, doc=3)
[03]    manage_document_order(create, doc=3) → 已复用 #70
[04]    use_skill(process-order, order_id=70)         ← 直接调 use_skill
[05]    manage_order(products, status_filter=not_matched)
[06]    match_products(70) → 100% 匹配 73/73
[07]    use_skill(process-order)                      ← 又一次直接调
[08]    tool_search(manage_inquiry)
[09]    manage_inquiry(check) → 2 供应商 ready
[10]    manage_inquiry(generate) → 2 份新询价 xlsx 落盘
```

与第一次 M4 跑通相比的进步：
- LLM 这次**直接调 use_skill**，没有再误用 tool_search 找 process-order（因为 use_skill 已经在 CORE_TOOLS 里 LLM 默认看得见）
- 全程 10 次调用，无任何 fallback / 错误路径

### 这一轮额外触发的「对照表」更新

| 字段 / 规则 | SKILL.md 期望 | 当前真实状态 | 差距 |
|------------|--------------|-------------|------|
| `currency` | 3 位大写 ISO 代码 | ✅ projection 层 normalize, 歧义返回 None | 无（M5 完成） |
| 文档类型 ≠ purchase_order 暂停 | 是 | ✅ projection 层硬阻断，preview/create 一致 | 无（M3 完成） |
| 产品数=0 阻断 | 是 | ✅ projection 层硬阻断，preview 显式说明 | 无（M3 完成） |
| Gemini API 偶发 5xx | LLM 链路应优雅恢复 | ✅ 智能重试 + 指数退避 + jitter | 无（M5b 完成） |
| preview 阻断字段 = create 阻断字段 | 必须一致 | ✅ 已对齐 blocking_missing_fields | 无（M5c 完成） |

### 历史脏数据说明

当前 Supabase 上的 v2_orders 表里，本次修复**之前**建的所有订单的 `currency` 列还是原始符号。如果未来要批量修复历史数据，建议写一次性脚本：

```python
# 伪代码
for order in db.query(Order).filter(Order.currency.notin_(_KNOWN_ISO_CODES)):
    fixed = _normalize_currency(order.currency)
    if fixed:
        order.currency = fixed
db.commit()
```

但**不在本里程碑范围内** —— 历史数据修复属于运维任务，不是 skill 落实任务。

---

## 下一步：脏数据清理（待执行）

### 范围

测试和调试过程中在 Supabase / file storage 上累积了几类历史脏数据，需要在进入 M6 扩展之前清理一次。**这是运维任务，不是 skill 落实任务**，所以单独列在这里，不在前面的里程碑里。

### 已识别的脏数据类型

#### 1. v2_orders.currency 历史符号未归一化

- **范围**: 2026-04-10 之前所有建出来的订单
- **症状**: `currency` 列里仍是 `$` / `¥` / `€` 等原始符号
- **影响**: 下游询价、汇率换算、财务对账如果按字符串匹配会出错
- **修复方式**: 一次性脚本，对全表跑 `_normalize_currency()`，结果非 None 才更新
- **风险**: 低（只覆盖未归一化的，不动已经是 ISO 代码的）

```python
# 伪代码
from services.document_order_projection import _normalize_currency, _KNOWN_ISO_CODES
for order in db.query(Order).filter(Order.currency.isnot(None)).all():
    if order.currency in _KNOWN_ISO_CODES:
        continue
    fixed = _normalize_currency(order.currency)
    if fixed:
        order.currency = fixed
db.commit()
```

#### 2. file_storage `inquiries/` 目录下的重复询价 xlsx

- **范围**: M2 / M4 / Robustness 回归测试期间，同一个订单 #70 反复调 `manage_inquiry(generate)` 累积的多份 xlsx
- **症状**: 文件名形如 `inquiry_68358749_supplier17_<6位hash>.xlsx`，同一个 supplier 在不同 hash 下有多份
- **当前已知文件**（订单 #70）:
  - `inquiry_68358749_supplier17_39e14c.xlsx` (M4 第一次)
  - `inquiry_68358749_supplier20_82a901.xlsx` (M4 第一次)
  - `inquiry_68358749_supplier17_2d9be0.xlsx` (Robustness 回归测试)
  - `inquiry_68358749_supplier20_966317.xlsx` (Robustness 回归测试)
- **影响**: storage 体积膨胀；如果前端按 supplier_id 列出文件可能展示出多份过期版本
- **修复方式**: 按 (order_id, supplier_id) 分组，只保留 `inquiry_data` 里指向的最新一份，其它删除
- **风险**: 中（需要确认 v2_orders.inquiry_data 真的指向最新版，删之前先 dry-run）

#### 3. v2_documents 测试文档（68358749.pdf 上传过两次）

- **范围**: 真实 PDF E2E 测试期间创建的 Document 记录
- **当前已知**: `document_id = 3` 对应 `68358749.pdf`，`order_id = 70` 对应它的订单
- **决策项**: 这条数据本身就是真实 PDF 的真实抽取结果，价值很高，**建议保留**作为今后回归测试的 ground truth
- **如果要清理**: 删除 Document → 级联删除 Order → 删除 file_storage 上的 PDF + xlsx → 删除 inquiry preview HTML

#### 4. v2_agent_sessions / v2_agent_messages 测试会话

- **范围**: M4 + Robustness 回归测试创建的 ReActAgent session
- **session_id**: `e2e-process-document`（脚本里硬编码）
- **影响**: 看 chat 历史时会有这些测试 session 混在真实用户 session 里
- **修复方式**: `DELETE FROM v2_agent_sessions WHERE id = 'e2e-process-document'`（如果级联删除已配置则消息也跟着走）

### 建议清理顺序

1. **先做 currency 归一化** —— 风险最低、收益最大、最影响生产数据正确性
2. **再做 inquiries xlsx 去重** —— 需要先 dry-run 确认 inquiry_data 指向的版本，再删除其它
3. **测试 session 删除** —— 纯整理，可以最后做
4. **测试 Document #3 + Order #70 保留** —— 作为 ground truth

### 安全规则

执行任何清理脚本之前必须遵守：

1. **每个清理脚本必须先 dry-run** —— 输出「将要修改 / 删除哪些行」，不实际写库
2. **dry-run 结果必须人工 review 一次** —— 不能 dry-run 完直接跑实战
3. **实战脚本必须可回滚** —— currency 修复保留旧值到 audit log；xlsx 删除前先复制到 `archive/` 子目录
4. **生产库操作之前先在本地 SQLite 复刻一份测试** —— 不直接拿生产 DB 做实验

### 这件事什么时候做

由用户决定。在做之前不要进入 M6 范围扩展，避免新数据和脏数据混在一起更难分离。

---

## 2026-04-10 → 2026-04-11 — 大规模并行扩建（独立工作 + 集成）

### 概述

这一段时间内同时推进了 5 条并行支线：
1. **Documents UI 商业化重设计**（列表页表格化、详情页双栏 + BlocksViewer）
2. **Stage 1 Universal Extractor**（type-agnostic 抽取层 + PO projector）
3. **Document Manual Override Layer**（用户字段修正不重抽）
4. **Document Context Package + 受约束 Agent**（处理速度优化）
5. **询价单生成单一确定性主路径**（清理 fallback 与不一致）

每一条都有完整代码 + 单元测试。今天 (04-11) 在收尾阶段发现并修了 2 个隐藏的 NameError，
并补了一个**字节码级静态名称解析测试**作为长期防御。

---

### 1. Documents UI 商业化重设计

**目标**：替换之前 4 套色调 emerald/blue/amber/violet 的塑料感界面，做成 Linear/Stripe 风格。

**改动**：
- `v2-frontend/src/app/dashboard/documents/page.tsx` — 列表页改 shadcn Table（不是 card grid）
  - 状态用 dot + 文字（不再用彩色背景 pill）
  - 删除按钮藏在 ⋯ DropdownMenu（不再 hover 才出现的图标）
  - 整行可点击进详情
  - inline summary：「N 份文档 · M 待处理 · K 已成单」
  - **列表页 polling**：发现有 in-progress 文档时 2s 轮询，全部完成自动停
- `v2-frontend/src/app/dashboard/documents/[id]/page.tsx` — 详情页改双栏
  - 左侧大区：PDF 预览
  - 右侧 sidebar：filename + status dot + metadata `<dl>` + 主 CTA + footer
  - 删除「强制建单」按钮（与 SKILL.md「不要猜」原则对齐）
  - 删除按钮放在 ⋯ 下拉里
- 新增 **`BlocksViewer`** 组件 — 显示完整 universal blocks
  - heading / paragraph / field_group / table / list / signature_block / other 七种类型独立渲染
  - 表格用文档**原文列名**作 key（如 `Product Number / Order Quantity / Extended Value ($)`，不再硬编码 `product_code/quantity/total_price`）
  - 默认展开，每个 block 标 `01 · 字段组 · p.1 · header` 元数据
  - 老文档 fallback 到 legacy markdown collapsible
- **删除流程**：`POST /documents/{id}/delete` → 默认拒绝有 linked order，`?force=true` 时解除关联但保留订单

### 2. Stage 1 Universal Extractor — type-agnostic 抽取层

**目标**：让任何 PDF 都能上传并被忠实提取，不再被 PO schema 强制污染。

**研究结论（写入代码注释）**：
- 当前模型 `gemini-2.5-flash`，**输出上限 65,535 tokens**（vs 2.0 Flash 的 8,192）
- PDF 单文件 50 MB / 1000 页 / 每页 258 input tokens / 1M context window
- 65K output ≈ 500-600 产品行的结构化 JSON，**远超当前任何文档需求**
- **决定**：单次调用 + `max_output_tokens=65535` + truncation 显式检测 + **不 chunk**

**新增文件**（604 行）：
- `services/extraction/__init__.py` — 导出
- `services/extraction/schema.py` — universal block schema v1.0（heading/paragraph/field_group/table/list/signature_block/other + ExtractionStats）
- `services/extraction/base.py` — `BaseExtractor` ABC + `ExtractionError(kind=config|input|provider|truncated|parse|empty)`
- `services/extraction/gemini_block.py` — `GeminiBlockExtractor`，type-agnostic prompt（明确告诉 LLM 文档类型未知、表格用列名作 key、不要解释只要忠实提取）
- `services/projection/__init__.py`
- `services/projection/purchase_order.py` — universal blocks → legacy `{metadata, products}` 的 fuzzy match projector，含 confidence 评分
- `tests/test_extraction_v1.py` — 真实 PDF E2E 验证

**修改**：
- `services/document_processor.py` — PDF 走新路径，Excel 仍走 legacy；**dual-write**（同时写 `extracted_data.metadata` 旧字段和 `extracted_data.blocks` 新字段，向后兼容）
- `_classify_document_legacy` 改成 `_classify_from_confidence`：基于 confidence verdict 而不是循环论证
- 30 MB 上限：`config.py` + 前端 `maxSizeMB={30}`

**真实测试结果**（68358749.pdf, 73 产品, 3 页）：
- elapsed: ~95s
- finish_reason: STOP（不截断）
- input_tokens: 2115
- output_tokens: ~8300
- block 类型分布：1 heading + 3 field_group + 9 paragraph + 1 table（73 行）
- po_number / ship_name / vendor / delivery_date 全部正确
- confidence: **12/12 满分**

### 3. Document Manual Override Layer

**目标**：用户能在不重新跑 100s Gemini 抽取的情况下修正字段。

**新增**（`services/document_order_projection.py`）：
- `EDITABLE_DOCUMENT_FIELDS` — 8 个可编辑字段
- `apply_document_field_overrides(document, updates, clear_fields)` — 写 manual_overrides
- `get_document_extracted_view(document)` — 读 view 自动 merge overrides
- `_normalize_override_value` — currency/date/total_amount 归一化

**新增 manage_document_order actions**（`services/tools/document_order.py`）：
- `update_fields` — 更新文档字段修正层
- `clear_fields` — 清除字段修正
- `products` — 文档级产品列表（不需要建单）
- `compute_total` — 总金额计算（优先 total_price，回退 quantity × unit_price）

**测试**：`test_document_overrides.py`（3 个 case）

### 4. Document Context Package + 受约束 Agent

**目标**：把「让 Agent 处理为订单」从 3-5 分钟 Agent 自由探索变成「Agent 拿固定 package + 收窄工具」。

**核心设计**（讨论得出）：
- **Context Package**：第一轮 system 注入一份固定骨架，Agent 不需要从原始 blocks/projection 自己探索
- **受约束 Agent**：scenario 收窄工具集，无关工具直接 deny + defer
- **分层处理**（暂未做）：复杂单据再启动深推理

**新增**（`services/document_context_package.py`，11 KB）：
- `build_document_context_package` 输出固定结构 JSON：document / classification / readiness / linked_order / key_fields / product_summary / manual_overrides / metadata
- `render_document_context_package` 渲染成 markdown 注入用
- `_recommended_next_action` 给 Agent 明确的「下一步」提示
- `detect_document_id_from_message` 从用户消息中提取 doc_id（支持 5 种正则模式）

**注入机制**：
- `routes/chat.py:187` — 在 ToolContext 上挂 `_scenario_context_injection`
- `services/agent/engine.py:540-588` — 第一轮 system message 注入 `[Scenario Context]\n{package}`，其后从 history 移除（避免 token 浪费）

**Scenario 工具收窄**（`services/agent/scenarios.py`）：
- `document_processing` 白名单：`manage_document_order, manage_order, match_products, manage_inquiry, search_product_database, modify_excel, use_skill` + common
- `chat.py:204-209` 强制 defer 非白名单工具 + `chat.py:222-225` 权限层 deny 兜底
- 真正的双层防护：LLM 看不到 + 调用了也被拒

**process-document SKILL.md v2 重写**：
- 「Context Package 优先」节：先读 package，package 够就直接答，不必为了保险再调 preview
- 字段修正流程：先 `update_fields` → 再 `preview` → 再回报
- 「Document 不是 Order」边界：在拿到真 order_id 之前禁止调 manage_order
- Step 1 改成「先读 package，不必先 preview」
- Step 2 末尾加：用户当前意图只是修正时停止，不要自动进入建单

**测试**：`test_document_context_package.py`（3 个 case）

### 5. 询价单生成单一确定性主路径

**目标**：把链路从「多条 fallback 的混乱状态」收敛成「一条主路径 + 显式 repair」。

**新增 production policy**（`inquiry_agent.py`）：
- `template_has_zone_config(template)` — 必须有根级 zone_config
- `get_production_templates(all)` — 过滤掉 legacy 模板
- `select_template(supplier_id, all, override)` — 三态返回：exact / candidate_auto / unavailable
- **legacy 模板永远不会被选**，包括 user override 也会被拒

**主路径重构**（`inquiry_agent.py:_generate_single_supplier`）：
- 只要有 zone_config 就走 `template_engine.fill_template` → 0 LLM
- `engine_verify` 校验失败也保存（进入 review/repair），**不再悄悄 fallback 到别的路径**
- `_engine_verify_to_results` — engine verify report 转成前端 verify_results

**新增 template_contract v2**（`services/template_contract.py`）：
- `build_template_contract(file_bytes, zone_config)` — 提取模板结构不变量
- v1 信号：header_merged_ranges / summary_relative_merges / summary_static_labels / formula_anchors
- **v2 新增**（解决 flat table 模板，如 Jeju / 韩国）：
  - `product_header_cells` — 产品列表头单元格（含相对偏移）
  - `header_field_anchors` — 表单字段标签锚点
- `verify_template_contract(ws, contract, ...)` — round-trip 校验
- `template_engine.verify_output` 自动调用 contract 校验

**测试**：
- `test_template_contract.py`（3 个 case：正常通过 / 改坏 summary label / 改坏 flat table 表头）
- `test_inquiry_template_policy.py`（3 个 case：legacy 过滤 / resolve 拒 legacy / select 拒 override）
- `test_inquiry_verify_results.py`（2 个 case：pass / fail 转换）

**回填**：Supabase 上 3 个成熟模板已经回填 contract_version=2：
- 11 Jeju サンプル：product_header_count=9
- 12 韩国模版：product_header_count=10
- 13 日本模版测试 2：product_header_count=7

**前端对齐**（按 user 反馈逐项收）：
- 删除「通用格式」入口（误导，因为后端已不允许无 zone_config）
- blocked 状态拆成「无模板」/「缺必填」两类
- 「继续生成其余」真的只生成可用供应商（前后端 supplier_ids 过滤）
- 模板上传文案改回真实能力（仅 .xlsx/.xls，不写 .pdf）
- 询价 tab 改成只要订单 ready + 有 match_results 就显示（不再依赖 inquiry_data 已存在）
- 询价生成 cancel：后端 endpoint + 前端 stop 按钮 + SSE cancelled 事件
- readiness 加载失败不再静默吞错
- inline gap 自动保存反馈：保存中 / 已保存 / 保存失败状态

---

## 2026-04-11 — 修两个隐藏 NameError + 字节码级防御性测试

### 问题暴露

用户在 UI 上点击「生成询价单」时报 `name 'load_workbook' is not defined`。

### 第一个 bug（root cause）

```python
inquiry_agent.py:30:  from openpyxl import load_workbook as _load_workbook_raw   # 改名
inquiry_agent.py:783: wb._wb = load_workbook(io.BytesIO(excel_bytes))            # 用原名 → NameError
```

import 时把 `load_workbook` aliased 成 `_load_workbook_raw`，但 line 783 还在用原名。
全文件 grep `_load_workbook_raw` 只有 line 30 一处定义、零处使用 — **这个 alias 是 100% 死代码**，没有任何 wrapper 用它。

**为什么现在炸**：之前 inquiry generation 有 LLM fallback 路径，最近的「单路径架构」重构把 fallback 删了，
所以 line 782-784（包回 InquiryWorkbook 准备保存）现在是 100% 必经路径，每次询价生成都触发。

**为什么测试没抓到**：现有 `test_inquiry_template_policy.py` / `test_inquiry_verify_results.py` /
`test_template_contract.py` 都是测拼图碎片（pure functions），**没有任何测试调用 `_generate_single_supplier`
或 `run_inquiry_orchestrator`**，函数体里的 NameError 永远不被触发。

**修复**（`services/inquiry_agent.py:30`）：
```python
- from openpyxl import load_workbook as _load_workbook_raw
+ from openpyxl import load_workbook
```

### 第二个 bug（顺便发现）

新加的字节码静态分析测试**第一次跑就发现了第二个**：

```
FAIL: test_run_inquiry_orchestrator_resolves
AssertionError: {'get_or_create_cancel_event'} is not false :
  run_inquiry_orchestrator references undefined module globals: ['get_or_create_cancel_event']
```

`run_inquiry_orchestrator` 用了 `get_or_create_cancel_event`（line 1395）但模块没 import 它。
另两个函数（`_save_workbook` / `run_inquiry_single_supplier`）的 cancel 路径加 local import 时漏了 orchestrator。

**修复**（模块级 import，3 处都受益）：
```python
+ from services.agent.stream_queue import get_or_create_cancel_event, push_event
```

这个 bug **从未被任何测试发现过**。如果今天没修第一个 bug + 加新测试，它会在用户真的取消询价生成时炸出来。

### 长期防御：字节码级名称解析测试

**新文件**：`tests/test_inquiry_agent_name_resolution.py`

**核心思路**：用 Python `dis` 模块走 `_generate_single_supplier` 等高风险函数的字节码，
找出所有 `LOAD_GLOBAL` 指令，断言每个 referenced name 都能在模块 globals 或 builtins 里解析。

```python
def _walk_code(code, names):
    for instr in dis.get_instructions(code):
        if instr.opname == "LOAD_GLOBAL":
            names.add(instr.argval)
    for const in code.co_consts:
        if isinstance(const, CodeType):
            _walk_code(const, names)  # 递归到嵌套 closures
```

**这个测试能抓**：
- import alias 没改完
- typo'd 函数名
- 删除但还被引用的模块级符号
- 任何「函数体里 NameError 但未运行」的潜在 bug

**这个测试不能抓**：
- 逻辑错（参数错、控制流错）
- 运行时 type error
- 条件 import / 动态 import

**覆盖范围**：8 个高风险函数
- `_generate_single_supplier`（炸过的那个）
- `_save_workbook` / `run_inquiry_orchestrator` / `run_inquiry_single_supplier` / `run_inquiry_pre_analysis`
- `select_template` / `resolve_template` / `_engine_verify_to_results`

**实测代价**：22 个测试总耗时 ~250ms，新测试 8 个 ~1.1s（dis 字节码扫描）。可接受。

### 验证

```bash
PYTHONPATH=. ./venv/bin/python -m unittest \
    tests.test_inquiry_agent_name_resolution \
    tests.test_template_contract \
    tests.test_inquiry_template_policy \
    tests.test_inquiry_verify_results \
    tests.test_document_overrides \
    tests.test_document_context_package -v
```

**结果**：22 个测试全通过，0 失败，0 错误，0.249s。

### 这次事件的真正教训

1. **「单路径架构」最大的 fail 模式是这条单路径没人测**。fallback 的好处是「即使主路径 broken 也有兜底」，
   但缺点是 broken 不可见。一旦切到单路径，必须立刻配套加 path-coverage 测试。
2. **静态分析比 mock-heavy 集成测试更值**：bytecode walker ~30 行代码、零 mock、零外部依赖、~1 秒跑完，
   抓出了 2 个真实 bug。一个 mock-heavy integration test 同样的工作量可能也只抓 1 个。
3. **「孤儿命名」永远是 refactor 残余**。看到 `as _xxx` 这种 alias，第一反应应该是 grep 验证它真的有 wrapper 在用。

---

## 当前未做项（按优先级）

| # | 项 | 备注 |
|---|---|---|
| P0 | **真实 UI 端到端速度实测** | Document Context Package 已落地，但还没量化「让 Agent 处理为订单」从 3-5min 降到了多少 |
| P1 | **询价模板 family 架构（日本/澳洲）** | 已讨论结论是「按地区/供应商分模板族」，未实现 |
| P1 | **xlsx skill 二线 repair** | 讨论结论：作为 verify 失败后的 repair 层，不替换主路径，未实现 |
| P1 | **产品级 repair 入口** | 当前 Review/Repair 只修 header fields，产品行只读 |
| P1 | **模板 onboarding Draft/Published 门禁** | 当前可保存无 zone_config 的草稿模板，会让管理员困惑 |
| P2 | **历史脏数据清理** | currency 历史符号、重复询价 xlsx、e2e-process-document 测试 session |
| P2 | **PendingRollbackError 根因修复** | chat.py:712 已加 db.rollback() 兜底，但没定位肇事 tool |
| P2 | **process-document-skill-research 文档** | 旧研究文档没更新，反映的是 04-09 时代的设计 |
| P3 | **退役 legacy `smart_extract` 路径** | 还在被 routes/orders.py 和 services/tools/order_extraction.py 调用 |

---

## 维护规则

- 每完成一次真实跑通或修复，**追加新的日期节**，不修改旧节
- 每个新里程碑开始时更新顶部「当前里程碑」勾选
- 真实数据（document_id / order_id / 耗时）必须记录，以便回溯
- 发现的任何「skill 描述 vs 系统真实行为」差距，必须写进「Skill 设计与现状的对照表」
- 范围扩展时（例如开始支持新的 doc_type），必须先更新「范围声明」一节
- **新增主链路或重写时，必须同步加 path-coverage 测试**（04-11 教训）
- **对任何 `from X import Y as _z` alias，grep 验证有 wrapper 在用，否则禁止存在**（04-11 教训）
