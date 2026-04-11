# AGENT_JOURNAL — curise_agent
> 创建时间: 2026-04-10  当前状态: RUNNING

---

## 🎯 任务简报
**目标**: 为 curise_agent 设计并执行第一阶段“统一文档入口”改造，先建立 document layer 与阶段验证机制，再用指定 PDF 样本验证。

**范围**:
- 在 `curise_agent/v2-backend` 内实现第一阶段最小闭环
- 维护可持续更新的进度文档，便于后续上下文恢复
- 为阶段性验证定义通过标准，并用用户提供的 2 个 PDF 样本执行验证

**本阶段不在范围内**:
- 不重写整条订单匹配/询价链路
- 不先做完整 embedding + pgvector 生产级检索闭环，先预留接口并评估是否进入第二阶段
- 不改动 `curise_agent` 之外的目录

**Definition of Done**:
- [x] 已建立并维护进度文档与恢复点
- [x] 已写出可执行阶段计划和通过标准
- [x] 已完成第一阶段代码落地：统一 document model / service / route 最小闭环
- [x] 已用 `68358749.pdf` 与 `CYI-REQ2561 ... Read-Only.pdf` 完成第一阶段验证
- [x] 已完成第二阶段最小闭环：document → order payload → create order
- [x] 已验证缺字段文档会进入 review 路径而不是静默建完整单
- [x] 已完成 3A：上传主入口切到 document-first，且保持 orders/upload 兼容
- [x] 已完成 3B：document 驱动链路可串到建单与后续 skill
- [x] 已补强关键稳健性：错误传播、重复创建防护、元数据优选
- [x] 已完成前端默认入口切换：Dashboard 默认进入 documents，订单页上传入口降级为文档中心入口
- [x] 已提供可测试的 documents 列表/详情页，并保留未来非订单文档扩展位

---

## 📋 执行计划
| # | Step | 状态 | 备注 |
|---|------|------|------|
| 1 | 创建 AGENT_JOURNAL 并固化计划、验证标准 | DONE | 已建立持久进度文档 |
| 2 | 调研并确认第一阶段最小闭环落点 | DONE | 复用 `smart_extract`，暂不引入检索层 |
| 3 | 实现 document 数据模型与 migration | DONE | 已新增 `v2_documents` 与 SQL migration |
| 4 | 实现 document_processor 服务 | DONE | 已统一输出 doc_type / markdown / extracted_data |
| 5 | 实现 `/documents/upload` 路由并接入主应用 | DONE | 已接入 `main.py`，不影响旧 `/orders/upload` |
| 6 | 运行阶段验证并记录结果 | DONE | 两个指定 PDF 已验证 |
| 7 | 更新日志、恢复点、下一阶段建议 | DONE | 第二阶段准入条件已记录 |
| 8 | 定义 `order_payload` 与缺字段策略 | DONE | `document_order_projection.py` |
| 9 | 实现文档建单接口与 Agent 工具 | DONE | route + tool + skill 已接入 |
| 10 | 验证第二阶段最小闭环 | DONE | 样本 1 可建单，样本 2 进入 review |
| 11 | 3A：切换上传主入口到 document-first | DONE | `orders/upload` 现在先建 Document 再建/更新 Order |
| 12 | 3B：串联 document 驱动默认链路 | DONE | `process-document` + document workflow helper 已成型 |
| 13 | 稳健性补强与回归验证 | DONE | 状态防护、重复创建防护、metadata tie-break 已验证 |
| 14 | 前端默认入口切到 documents | DONE | 新增 documents 页面、导航与 API |
| 15 | 前端构建验证与预览 | DONE | Next build 通过，3001 可预览 |

---

## ✅ 阶段验证标准

### Phase 1 — 文档入口底座
- [x] 已新增 `v2_documents` 模型与 migration
- [x] 上传路由代码已保存原始文件路径与基础元信息
- [x] 提取结果统一保存为 `doc_type + content_markdown + extracted_data + extraction_method`
- [x] 旧的 `/orders/upload` 行为不被破坏

### Phase 2 — 提取结果质量
- [x] 样本 1 能提取出非空元数据与产品信息
- [x] 样本 2 能提取出非空元数据与产品信息
- [x] 至少能区分 `purchase_order` 与 `unknown`
- [x] 错误路径会把状态落为 `error` 并保存 `processing_error`

### Phase 3 — 是否进入检索层的准入标准
- [ ] 如果 Agent 在单文档内已能稳定填充订单，则 chunking/embedding 可后置
- [ ] 如果样本验证显示需要跨页/跨区块频繁定位证据，则第二阶段加入 chunking
- [ ] 如果后续明确需要跨文档搜索，再引入 embedding + pgvector

### Phase 4 — 文档到订单投影
- [x] 已定义标准 `order_payload`
- [x] 已能从 `Document` 生成 `Order`
- [x] 缺关键字段时不静默伪造数据，而是标记 review
- [x] Agent 已有 `manage_document_order` 工具与 `process-document` skill 可用

---

## 📝 进度日志

### [Entry 1] — 初始化任务外置记忆
**做了什么**: 创建 AGENT_JOURNAL，记录目标、边界、执行步骤与阶段验证标准。
**结果**: 成功 ✅
**发现**: 当前代码已具备 ReActAgent 与订单提取能力，但缺少统一 document layer。
**下一步**: 基于现有 `smart_extract` 和上传链路实现第一阶段最小闭环。

### [Entry 2] — 第一阶段底座完成
**做了什么**: 新增 `Document` 模型、`027_add_documents_foundation.sql`、`services/document_processor.py`、`routes/documents.py`，并将 documents router 接入主应用。
**结果**: 成功 ✅
**发现**: 现有 `smart_extract` 足以支撑第一阶段统一文档入口，无需立即引入 chunking/embedding。
**下一步**: 第二阶段评估订单填写 skill 如何读取 document layer 产物并产出标准 order payload。

### [Entry 3] — 指定样本验证通过
**做了什么**: 用 `68358749.pdf` 与 `20251213 PO No CYI-REQ2561 PO01.xlsx  -  Read-Only.pdf` 调用 `process_document()` 验证。
**结果**: 成功 ✅
**发现**: 样本 1 识别为 `purchase_order`，提取 73 个产品；样本 2 识别为 `purchase_order`，提取 22 个产品，但供应商和交货日期为空，说明第二阶段 skill 仍需补“缺字段处理”。
**下一步**: 进入 document → order payload 投影设计，确定字段缺失时的暂停/澄清策略。

### [Entry 4] — Document 模型本地持久化验证通过
**做了什么**: 用 SQLite 内存库创建 `v2_documents` 表并插入一条 `Document` 记录，验证模型最小持久化路径。
**结果**: 成功 ✅
**发现**: 第一阶段模型层与最小写入路径可用，无需先连接真实业务库就能确认表结构正确。
**下一步**: 在目标环境执行 migration 后，再做真实数据库层面的上传/提取链路验证。

### [Entry 5] — 第二阶段投影层完成
**做了什么**: 新增 `document_order_projection.py`，定义 `order_payload`、缺字段策略，并实现从 `Document` 创建或更新 `Order`。
**结果**: 成功 ✅
**发现**: 以 `po_number/ship_name/delivery_date` 为关键字段的最小规则足以区分“可直接建单”与“需要 review”。
**下一步**: 让更多 Agent 场景直接从 document 起步，而不是从 order 起步。

### [Entry 6] — 第二阶段接口与工具验证通过
**做了什么**: 新增 `/documents/{id}/order-payload`、`/documents/{id}/create-order`，新增 `manage_document_order` 工具和 `process-document` skill，并加上 `document_processing` 场景自动注入。
**结果**: 成功 ✅
**发现**: 样本 1 可直接建单；样本 2 因缺 `delivery_date` 被标记为待补充，不会静默构造完整订单。
**下一步**: 评估是否需要把前端上传默认入口从 `orders` 切换到 `documents`。

### [Entry 7] — 3A 完成：orders/upload 切到 document-first
**做了什么**: 重写 `routes/orders.py` 的上传入口，先创建 `Document`，再创建占位 `Order`，后台统一走 `document_workflow.run_document_pipeline()`。
**结果**: 成功 ✅
**发现**: 这样可以在不破坏前端兼容性的前提下，把真实入口切换到 document layer。
**下一步**: 继续让 document-first 链路覆盖更多后续流程。

### [Entry 8] — 稳健性补强完成
**做了什么**: 新增 `document_workflow.py` 统一上传/提取/建单流程；给文档接口增加“提取未完成不可投影/建单”的防护；在 `smart_extract` 中增加 metadata completeness tie-break。
**结果**: 成功 ✅
**发现**: 相比单看产品数，增加 metadata 优先级更适合当前订单场景，可减少提取结果在关键字段上的波动。
**下一步**: 第三阶段可优先考虑前端和业务流全面切到 documents 入口。

### [Entry 9] — 前端默认入口已切到 documents
**做了什么**: 新增 `documents-api.ts`、`/dashboard/documents`、`/dashboard/documents/[id]` 页面；Dashboard 根路径改为默认进入 documents；订单页上传按钮改为跳转文档中心；订单详情页增加“查看源文档”回链。
**结果**: 成功 ✅
**发现**: 这种做法既务实又保留未来扩展：当前只完整支持 purchase_order 投影，非订单文档也能先进入 documents 审核态。
**下一步**: 如需继续推进，可把更多调用方和后续匹配/询价操作显式改成从 `document_id` 起步。

### [Entry 10] — 前端已可测试
**做了什么**: 补了 `GET /api/documents` 列表接口和 `linked_order_id` 返回，完成前后端联调；执行 `pnpm build` 通过，并启动前端本地预览。
**结果**: 成功 ✅
**发现**: 当前可直接测试 documents 列表页、详情页、上传后跳转、订单回链；开发预览可用。
**下一步**: 视需要补 API 级/浏览器级更细的集成测试。

### [Entry 11] — 登录故障已恢复
**做了什么**: 诊断浏览器 `ERR_CONNECTION_REFUSED http://localhost:8001/api/auth/login`，确认原因是后端 API 未启动；已在本机启动 FastAPI 服务，并补执行 `028_link_orders_to_documents.sql` 解决启动日志里的 `v2_orders.document_id` 缺列问题。
**结果**: 成功 ✅
**发现**: 现在 `/api/auth/login` 已可达，空请求返回 422，说明网络层与路由层正常。
**下一步**: 让用户直接重试登录；如登录凭据仍失败，再排查账号/密码与 auth 数据。

### [Entry 12] — 文档中心 UI 已做务实增强
**做了什么**: 为 documents 列表与详情页增加 preview_url 支持、PDF 首页预览、结构化文档预览、派生 tag 系统，并把上传区改成点击按钮后再打开弹层。
**结果**: 成功 ✅
**发现**: 当前方案兼顾务实与扩展性：purchase_order 走完整建单路径；非订单文档也能以 preview + tag + 审核态被接住。
**下一步**: 如需继续推进，可再做浏览器级交互细测和更细的 preview 表现优化。

### [Entry 13] — 文档中心商业化工作台已收敛并验证
**做了什么**: 将 documents 列表页重构为更克制的商业化工作台，加入决策型 Hero、指标卡、语义化文档卡片；将 documents 详情页重构为“左原文、右决策”的审核布局，并完成 TypeScript 诊断与 `pnpm build` 验证。
**结果**: 成功 ✅
**发现**: 文档中心更适合作为默认入口时，不应强调“上传动作”，而应强调“系统先理解文档，再只给一个合适的下一步”；详情页则应让原文、关键信息与建单决策在同一屏完成。
**下一步**: 如需继续推进，可把同样的商业化语言延伸到订单详情页和后续 document-driven 工作流。

### [Entry 14] — process-document Skill 已做流程级验证
**做了什么**: 新增流程评估脚本，对“上传文档 → 提取完成 → preview → create → order overview”做最小可运行验证，并分别覆盖可直接建单与缺 `delivery_date` 两种场景。
**结果**: 部分成功 ⚠️
**发现**: Skill 文本与预览门禁逻辑本身符合预期；可直接建单场景能顺利进入建单与订单概览。但底层 `manage_document_order(action="create")` 仍可在 preview 明确“不应建单”时直接创建 `status=ready` 的订单，只是附带 warning，说明真正的阻断目前还在 Skill 层，不在 Tool/Projection 层。
**下一步**: 如继续推进，优先把“缺关键字段时禁止直接 create”下沉到 Tool 或投影层，避免任何调用方绕过 Skill 门禁。

---

## 🧠 Experience Bank

### ✅ 成功经验
- **先做统一文档入口再接 Agent**: 在当前双轨架构下，先抽离 document layer 风险最小，可复用现有提取和 Agent 能力。
- **先用真实样本验证再决定检索层**: 指定 PDF 已证明单文档提取闭环成立，因此 chunking/embedding 可以由第二阶段需求驱动。
- **先做投影层再谈自动化编排**: 先把 document 转成稳定的 `order_payload`，再接 skill，能显著降低 Agent 直接读原始文档的不确定性。
- **提取结果选择不能只看产品数**: 在多次 LLM 提取里，用“产品数 + 元数据完整度”选最佳结果，比只看产品数更稳。
- **默认入口切换宜先改用户心智而非一次性删兼容接口**: 先把 Dashboard 根路径、导航、上传按钮切到 documents，再保留 `/orders/upload` 兼容，迁移成本最低。

### ❌ 失败记录
- 暂无

### ⚠️ 坑点备忘
- 当前 `Order` 同时承担文件载体和业务实体职责，第一阶段必须避免继续把新能力写回 `Order.extraction_data` 作为唯一来源。
- 第二个 PDF 存在字段缺失，说明订单填写 skill 需要把“缺字段”视为一等状态，而不是假设 metadata 总能完整。

---

## 🏗️ 架构决策记录（ADR）

### ADR-1: 第一阶段先不上 embedding + pgvector
**决策**: 第一阶段先实现统一 document 入口、提取与验证，不把 embedding/pgvector 作为前置条件。
**理由**: 当前最关键的是先跑通“文件进入 document layer 并产出可消费 JSON”的闭环；检索层应由验证结果驱动。
**放弃的方案**: 一次性做完整文档中台 + 检索层（原因: 范围过大，验证周期变长，风险上升）。

### ADR-2: 第一阶段复用 `smart_extract`，统一输出 document 结构
**决策**: `document_processor` 直接复用 `services/order_processor.py` 中的 `smart_extract`，并转换为 `doc_type + content_markdown + extracted_data`。
**理由**: 当前真实能力已经在 `smart_extract` 中验证过，用统一包装层即可快速形成 document layer。
**放弃的方案**: 立即重写全新的文档提取器（原因: 会重复建设，且无法在本轮快速验证）。

### ADR-3: 第二阶段先实现投影层和 review 机制
**决策**: 先实现 `Document -> order_payload -> Order` 的投影闭环，并把缺关键字段转成 review 信号，而不是立即做自动补全。
**理由**: 真实样本已经证明缺字段是常态，先把“可继续/需暂停”边界做清楚，比提早做复杂推理或检索更重要。
**放弃的方案**: 先上 embedding 检索或自动猜测缺失字段（原因: 容易制造伪确定性，且不利于订单准确性）。

### ADR-4: 3A 采用兼容式入口切换
**决策**: 保留 `/orders/upload` 对前端兼容，但其内部实现切换为 document-first：先建 `Document`，再建占位 `Order`，后台统一走 document workflow。
**理由**: 这样能完成入口切换，同时避免一次性改前端和所有现有调用方。
**放弃的方案**: 直接删除 `/orders/upload` 或要求前端立刻切到 `/documents/upload`（原因: 破坏面过大）。

### ADR-5: 稳健性优先于激进自动化
**决策**: 当前阶段优先补 `document_workflow`、提取完成保护、重复建单防护、metadata tie-break，而不是再堆新的自动流程。
**理由**: 基础设施一旦不稳，后续 Agent 编排只会放大问题。
**放弃的方案**: 先继续扩展更多能力点（原因: 会在不稳底座上叠复杂度）。

### ADR-6: 前端采用“documents 为前态、orders 为后态”的务实切换
**决策**: 先新增 documents 列表/详情页和 `documents-api.ts`，把 Dashboard 默认入口和订单页上传按钮切到 documents；但只对 purchase_order 提供完整建单按钮，其他 doc_type 暂时停留在 documents 审核态。
**理由**: 这是最小改动且兼容未来非订单文档衍生的方案。
**放弃的方案**: 立即为所有文档类型实现完整业务投影（原因: 过度建设，不务实）。

---

## 🔴 当前阻塞
无

---

## ⏭️ 恢复点（Context 重置后从这里开始）
**当前执行到**: process-document Skill 已完成草案并通过流程级验证
**已完成的文件**: `AGENT_JOURNAL.md`, `docs/current_progress/process-document-skill-research-2026-04-10.md`, `v2-backend/models.py`, `v2-backend/schemas.py`, `v2-backend/routes/documents.py`, `v2-backend/routes/orders.py`, `v2-backend/services/document_processor.py`, `v2-backend/services/document_order_projection.py`, `v2-backend/services/document_workflow.py`, `v2-backend/services/order_processor.py`, `v2-backend/services/tools/document_order.py`, `v2-backend/services/tools/__init__.py`, `v2-backend/services/agent/scenarios.py`, `v2-backend/routes/chat.py`, `v2-backend/skills/process-document/SKILL.md`, `v2-backend/tests/_phase3_validation.py`, `v2-backend/tests/_evaluate_process_document_skill_flow.py`, `v2-frontend/src/lib/documents-api.ts`, `v2-frontend/src/app/dashboard/page.tsx`, `v2-frontend/src/app/dashboard/layout.tsx`, `v2-frontend/src/app/dashboard/documents/page.tsx`, `v2-frontend/src/app/dashboard/documents/[id]/page.tsx`, `v2-frontend/src/app/dashboard/orders/page.tsx`, `v2-frontend/src/app/dashboard/orders/[id]/page.tsx`, `v2-frontend/src/lib/orders-api.ts`
**立即需要做的**: 如继续推进，优先把“preview 不允许时禁止 create”下沉到 Tool/Projection 层，然后再做真实 API key 环境下的端到端 PDF 抽取验证
**绝对不要做的**: 不要把非订单文档强行投影成 Order；不要回退到 order-first 上传心智
**关键上下文**: 当前方案是务实切换：documents 成为默认入口，purchase_order 有完整建单投影，其他 doc_type 先停留在 documents 审核态，为未来 invoice/quotation 等衍生保留空间
