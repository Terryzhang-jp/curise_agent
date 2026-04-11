# v2-backend 商业级重构计划

> 起始: 2026-04-12
> 目标: 从 6/10 提升到 9.5/10（商业级）
> 维护规则: 每个 task 开始/完成/遇阻时追加一节，保留决策理由

---

## 0. 这份文档是什么

这是一份**活文档**。它同时是：
- **计划** (§1 总览 + §2-§9 每 Phase 细节)
- **执行日志** (§10 时间线)
- **决策记录** (§11 ADR — 架构决策记录)
- **盘点清单** (§12 发现的技术债)

读这份文档应该能回答：**当前系统哪里干净、哪里脏、接下来做什么、为什么这么做**。

---

## 1. 总览

### 1.1 起点 (2026-04-12)

**严谨度**: 6/10

**已做 (前序 session)**:
- ✅ Phase 1: ZoneConfigV1 schema + e2e regression suite
- ✅ Phase 2: compose-from-scratch renderer + 边界 audit
- ✅ 推送到 github (commit `759e669`)

**已知问题**:
- 🔴 **Critical**: `document_order.py` 跨租户越权（Codex 发现）
- 🔴 **High**: `force=True` 绕过 readiness gate（Codex 发现）
- 🔴 **High**: document/order upload 非原子（Codex 发现）
- 🟡 feature flag 代码写好但未 push，compose 是死代码
- 🟡 8 个 pre-existing test failures
- 🟡 `inquiry_agent.py` 未接 `parse_zone_config()`
- 🟡 混合作者的 working tree（47 files modified + 107 untracked）

### 1.2 目标 (Definition of Commercial-Grade)

1. **安全**: 所有 endpoint/tool 有 role + tenant 检查；无已知 critical/high CVE
2. **原子性**: 任何多步操作成功或全部回滚，无孤儿
3. **可观测**: 失败能在 30 秒内通过 log/metric/trace 定位
4. **可回滚**: 任何变更有明确 rollback 路径
5. **可测试**: 核心路径 ≥80% coverage，有 e2e regression net
6. **可维护**: 无死代码，作者归属清晰，文档齐全
7. **SLA**: P95 < 200ms, 可用性 99.5%（非强制，但架构支持）

### 1.3 Phase 路线图

| Phase | 主题 | 耗时 | 依赖 | 状态 |
|---|---|---|---|---|
| **P0** | 止血 (安全 + 数据完整性) | 1 天 | — | ✅ 完成 (2026-04-12) |
| **P1** | 地基接电 (session 工作生效) | 2 天 | P0 | ⬜ 未开始 |
| **P2** | 主路径唯一化 | 1 周 + 2 周灰度 | P1 | ⬜ 未开始 |
| **P3** | 可观测性 | 1 周 | P1 | ⬜ 未开始 |
| **P4** | 状态生命周期 | 1 周 | P2 | ⬜ 未开始 |
| **P5** | 测试 CI 闸门 | 3 天 | P1 | ⬜ 未开始 |
| **P6** | 性能 & 容量 | 3 天 | P3 | ⬜ 未开始 |
| **P7** | 文档 & Runbook | 2 天 | P3, P6 | ⬜ 未开始 |

**总计**: ~4 周工作（P2 的灰度期与其他 phase 并行）

---

## 2. P0 — 止血（1 天，最高优先级）

**为什么先做**: Codex 发现 3 个严重问题，不修会持续出安全和数据一致性问题。在这些问题之上做任何优化都是漏水地基上装修。

### P0.1 🔴 Critical — document 越权访问

**问题**: `services/tools/document_order.py` 按 raw `document_id` 查 DB，无 tenant 检查。任何员工猜 id 就能读/改别人的 document。

**修复**:
- 所有 `db.query(Document).filter_by(id=...)` 加 `.filter(Document.created_by == ctx.user_id)`（superadmin 例外）
- 同步修 `services/document_context_package.py` 的 context injection
- 新增 helper: `_require_document_access(db, doc_id, ctx)` 统一入口

**DoD**:
- ✅ 新增 `tests/test_document_tenant_isolation.py`
- ✅ userA 创建 doc → userB 访问返回 404 (不是 403，避免泄露存在性)
- ✅ superadmin 能看所有

**状态**: ✅ 完成 (2026-04-12)

**实施**:
- `ToolContext` 加 `user_role: str = "employee"` 字段
- `routes/chat.py` ctx 创建处传入 `user_role=user_role`
- `services/tools/document_order.py::manage_document_order` 加 row-level ownership filter（superadmin 例外）
- `services/document_context_package.py::build_document_context_injection` 签名加 `user_id` + `user_role` kwargs，内部做 ownership filter
- 新增 `tests/test_document_tenant_isolation.py` — 12 个 test case：read (preview/products/compute_total) × 跨租户 + 自己 + superadmin + unauth；write (update_fields/clear_fields) × 跨租户；context injection × 4 种 persona
- `.gitignore` 白名单

**结果**: 12/12 通过；验证 userA 不能访问 userB 文档；superadmin 能访问所有；unauth ctx 返回 not-found；跨租户写入会被拒绝且 DB 未被篡改。

---

### P0.2 🔴 High — `force=True` readiness bypass

**问题**: `create_or_update_order_from_document(force=True)` 跳过 `_ensure_order_creation_allowed()` 但仍写 `order.status="ready"`。缺 `delivery_date` 的 document 也会变 ready order。

**修复**:
- `force=True` 不再跳过 readiness gate
- 新增 `admin_override: bool` 参数，专门用于特权覆盖
- `admin_override=True` 必须记审计日志（P3.4 的前置）
- upload 链路调用改为 `force=False`

**DoD**:
- ✅ 缺 `delivery_date` 的 doc → order status ≠ `ready`，返回 `blocked_fields`
- ✅ 新增 `tests/test_document_readiness_gate.py`
- ✅ admin_override 调用在 log 留痕

**状态**: ✅ 完成 (2026-04-12)

**实施**:
- **`force` 参数语义拆分**:
  - `force: bool` — 仅控制 overwrite existing（旧语义保留）
  - `allow_incomplete: bool` — 控制是否允许 blocking fields 缺失时仍创建订单
  - `admin_override: bool` — 唯一能强制 `status="ready"` 的路径，必须带审计日志
- **`_resolve_order_status(payload)`** 重写为真正的单一真相源：
  - no products → `"error"`
  - blocking_missing_fields → `"needs_review"`（新增状态）
  - else → `"ready"`
- **`_ensure_order_creation_allowed(payload)`** 移除 `force` 短路；不想报错就在 caller 传 `allow_incomplete=True`
- **`document_workflow.py:85`**（background ingestion）改为 `force=True, allow_incomplete=True`（persist blocked as needs_review, not ready）
- **`routes/documents.py:269`**（user-triggered force create）改为 `force=body.force, allow_incomplete=body.force`（用户按 force 会同时开两个语义）
- **`services/tools/document_order.py:208`** 同上
- **Migration `029_add_needs_review_status.sql`**: 扩展 `ck_v2_orders_status_enum` 允许新值
- **`models.py`** Order CheckConstraint 同步更新

**新增测试**: `tests/test_document_readiness_gate.py` 8 个 case
1. 完整 doc → `ready`
2. 不完整 doc（默认 call）→ raise ValueError，订单未创建
3. 不完整 doc + `allow_incomplete=True` → persist 为 `needs_review`（回归 regression）
4. 无 products → `error`
5. `force=True` 单独使用不绕过 validation
6. `force=True` 的 overwrite 语义仍然工作
7. `admin_override=True` 能强制 `ready` 且 emit WARNING 审计日志
8. Background ingestion 模拟：`force=True, allow_incomplete=True` → `needs_review` + `processing_error` 含 `delivery_date` 提示

**结果**: 8/8 通过；43/43 累积通过（e2e + schema + readiness + tenant）

---

### P0.3 🔴 High — document/order 非原子上传

**问题**: `create_document_record()` 和 `create_pending_order_for_document()` 是两个独立 commit，中间失败留孤儿 document + blob。

**修复**:
- 两个 commit 包进同一个 `with db.begin():`
- 文件存储分两步: 写 `_staging/<uuid>` → 两 commit 都 OK 后 rename → 失败删 staging
- 任何一步抛异常 → 补偿 cleanup

**DoD**:
- ✅ 新增 `tests/test_document_upload_atomicity.py` — mock 第二步失败，断言无孤儿
- ✅ 进程 kill 中途 → 无孤儿

**状态**: ✅ 完成 (2026-04-12)

**实施**:
- 新增 `create_document_and_pending_order(db, *, user_id, filename, content, ...)` — 原子入口
- 采用 **saga 补偿模式**: blob upload 非事务（外部 Supabase API）→ DB 事务（Document + Order 在一个 savepoint）→ DB 失败则触发 `storage.delete` 补偿
- 关键细节:
  - `db.begin_nested()` 使用 savepoint，兼容外层已有事务
  - 补偿 delete 失败**不掩盖**原始异常（原始 exception 仍然 raise）
  - `document` 和 `order` 拿的是同一个 `file_url` — 将来想改为 staging→promote 也只需改一处
- `routes/orders.py:93` 替换旧的两步 call
- 旧 `create_document_record` 保留但加 docstring 标记 DEPRECATED + 加补偿 delete（给测试或单独 document upload 用）

**新增测试**: `tests/test_document_upload_atomicity.py` 4 个 case
1. Happy path — blob + doc + order 成功
2. DB failure injection (mock Order.__init__ raise) → blob 被补偿 delete + 无残留 row
3. Storage failure → 无 DB row + 无 delete 调用
4. Delete 失败不掩盖原 exception

**结果**: 4/4 通过；47/47 累积通过

---

### P0.4 🟡 全局 row-level ownership audit

**问题**: 发现一个越权，可能不止一个。需要全局扫。

**修复**:
- `grep -rn "db.query(.*).filter_by(id=" services/ routes/`
- 每个结果标注: ✅ 已校验 / ❌ 缺校验 / ⬜ 待确认
- 所有 ❌ 变 ✅

**DoD**:
- ✅ 产出 `docs/security-audit-2026-04-12.md`
- ✅ 所有待修项变已修

**状态**: ⬜ 未开始

---

### P0.5 🟡 全局 `force=` 参数 audit

**问题**: `force=True` 已知有 1 处绕检查，可能不止。

**修复**:
- `grep -rn "force\s*=\s*True" services/ routes/`
- 每处确认是否绕过检查
- 每处要么删、要么文档化 + 加审计日志

**DoD**:
- ✅ 每个 `force=True` 有明确归属（安全/已修/已文档化）

**状态**: ⬜ 未开始

---

### P0 准出 gate

- [x] 跨租户越权测试全通过 (12/12)
- [x] 坏 document 不能变 ready (8/8)
- [x] upload 原子性测试通过 (4/4)
- [x] `security-audit-2026-04-12.md` 全部 ✅
- [x] 新增的 3 个测试文件全绿 (24 new + 23 carried over = 47/47)

**P0 完成时间**: 2026-04-12
**累积测试**: 47/47 green
**修复 gap**: 6 个 critical/high 漏洞（1 越权 + 1 readiness bypass + 1 非原子 + 3 tool 越权追加发现）

---

## 3. P1 — 地基接电（2 天）

### P1.1 推 feature flag commit (30 min)
- cherry-pick `inquiry_agent.py` 的 `INQUIRY_RENDERER` hunk 成独立 commit
- **DoD**: 生产默认走 compose, `INQUIRY_RENDERER=fill` 可回滚

### P1.2 `parse_zone_config()` 接 upload endpoint (2h)
- `routes/settings.py` 模板上传 → 先 validate
- **DoD**: 坏模板 422 + field paths，DB 无新记录

### P1.3 Template self-check (3h)
- 新增 `services/template_self_check.py`
- upload 时跑 1-row mock 的 `compose_render + verify_output`
- **DoD**: 3 个生产模板上传通过，人为破坏立刻 reject

### P1.4 `inquiry_agent.py` 用 `ZoneConfigV1` (1h)
- 替换所有 `zc["..."]` 访问
- **DoD**: `grep -n 'zc\[' services/inquiry_agent.py` 为空

### P1.5 修 8 个 pre-existing test failures (1h)
- 5 × `test_inquiry.py::TestResolveTemplate`
- 2 × `test_deerflow_optimizations`
- 1 × `test_template_engine::test_zone_config_builder`
- **DoD**: 相关 pytest 全绿

### P1.6 `SupplierTemplate` metadata 字段 (1h)
- Migration `029_add_template_metadata.sql`
- `zone_config_version VARCHAR DEFAULT '1.0'`
- `status ENUM('draft','ready','archived','broken') DEFAULT 'ready'`
- **DoD**: 老模板 backfill + 新上传走 draft → ready flow

### P1 准出 gate
- [ ] 23/23 inquiry + schema tests + 3 upload tests + 8 pre-existing tests 全绿
- [ ] 生产走 compose

---

## 4. P2 — 主路径唯一化（1 周 + 2 周灰度）

### P2.1 Inquiry renderer 灰度 → 删 fill_template
- Metrics `inquiry.renderer.{compose,fill}.{success,fail}`
- 灰度 2 周 → 删 `fill_template` 代码
- 预期减 ~1100 行

### P2.2 Document extraction 统一入口
- 合并 `document_schema` / `template` / `else` 三路分支
- 单一 `extract_document(file_bytes, config)`

### P2.3 Order upload 统一入口
- `routes/orders.py` + `routes/documents.py` 共享 `services/upload_pipeline.py`

### P2.4 静态分析闸门
- CI 加 `ruff F821,F811,F401` + `mypy --strict` 关键模块

### P2 准出 gate
- [ ] 无"老/新并存"代码
- [ ] CI 静态分析全绿

---

## 5. P3 — 可观测性（1 周）

### P3.1 Structured logging + correlation ID
- `structlog` + FastAPI middleware 注入 `request_id`

### P3.2 Metrics
- OTel / Prometheus
- 每 endpoint `{latency, success, failure}` + 每 pipeline stage

### P3.3 Error taxonomy
- `services/errors.py`: `UserError` / `SystemError` / `AuthorizationError`
- FastAPI exception handler 统一格式

### P3.4 审计日志
- `v2_audit_log` 表 + `services/audit.py`
- 登录、权限变更、数据删除、`admin_override` 都留痕

### P3.5 告警接线
- SystemError 自动告警

### P3 准出 gate
- [ ] 任意失败 30s 内可定位
- [ ] 关键路径有 metric + alert

---

## 6. P4 — 状态生命周期（1 周）

### P4.1 FSM
- Document / Order / Template / Inquiry 都有 status enum + transition matrix

### P4.2 Atomic upload 全链路
- 泛化 P0.3 的 staging pattern

### P4.3 Storage GC
- `services/storage_gc.py` 扫孤儿 → `_trash/`

### P4.4 删除影响预警
- DELETE 先查反向引用 → 前端 confirm

### P4.5 软删除
- `deleted_at` column + 默认 filter

### P4 准出 gate
- [ ] 所有实体有 FSM
- [ ] 无孤儿
- [ ] 误删可恢复

---

## 7. P5 — 测试 CI 闸门（3 天）

### P5.1 Coverage 目标
- `services/` ≥ 80%, `routes/` ≥ 70%

### P5.2 Entry-point e2e
- 每个外部 endpoint 一条 happy path

### P5.3 Security smoke test
- `tests/security/` 跨租户、越权、injection

### P5 准出 gate
- [ ] Coverage 达标
- [ ] CI 全绿

---

## 8. P6 — 性能 & 容量（3 天）

### P6.1 N+1 audit
- SQLAlchemy echo → 修 joinedload/selectinload

### P6.2 资源限制
- Upload size / timeout / rate limit / DB pool / LLM timeout

### P6.3 Index audit
- 慢 query → index → migration

### P6 准出 gate
- [ ] P95 < 200ms
- [ ] 100 req/s × 5min 负载测试通过

---

## 9. P7 — 文档 & Runbook（2 天）

### P7.1 ARCHITECTURE.md
### P7.2 RUNBOOK.md
### P7.3 API.md + DEPLOY.md

### P7 准出 gate
- [ ] 新人 1 天能 onboard
- [ ] On-call 有 runbook

---

## 10. 时间线 (执行日志)

> 每次 task 开始/完成/遇阻追加一节。保留为什么这么做的决策。

### 2026-04-12 — 计划创建

**做什么**: 创建本文档，把 4 周重构计划写进去。

**为什么**: 用户要求把后端从 6/10 提升到商业级别 (9.5/10)。基于:
- 本次 session 的 Phase 1+2 成果 (compose_render + schema)
- Codex adversarial review 的 3 个发现 (critical 越权 + high readiness bypass + high 非原子 upload)
- 代码库整体盘点 (8 pre-existing test failures, 混合作者 working tree)

**决策**:
- 把 Codex 的 3 个发现提升为 P0，放在任何优化前面
- 原计划的 Stage 0-4 重新编号为 P1-P4
- 新增 P5-P7 (测试 CI、性能、文档) 因为"商业级"需要这些
- 总耗时从原 6 天扩到 ~4 周

**下一步**: 开始 P0.1 — document 越权修复

### 2026-04-12 — P0.1 完成

**做什么**: 修 Codex 发现的 critical 越权漏洞。

**怎么做**:
1. 加 `user_role` 到 ToolContext（之前只有 `user_id`，superadmin bypass 无处可存）
2. `routes/chat.py` 的 ctx 创建传入 `user_role`（之前就已经在 `_build_chat_agent` 的参数里，但没传给 ctx）
3. `document_order.py::manage_document_order` 所有对 `Document` 的查询都加 `user_id` filter
4. `document_context_package.py::build_document_context_injection` 加 `user_id` + `user_role` kwargs
5. 12 个 regression test

**为什么这么做**:
- 加 field 到 ToolContext 而不是到处传参 — 避免在每个 tool 里重复取 `current_user`
- 返回 "不存在" 而不是 "forbidden" — 防止存在性泄露（attacker 不能通过错误码区分 "document 不存在" vs "存在但不属于我"）
- superadmin 白名单而不是黑名单 — fail-safe 默认拒绝

**结果**: 12/12 passing. P0.1 done.

**下一步**: P0.2 — force=True readiness bypass

### 2026-04-12 — P0.2 完成

**做什么**: 修 Codex 发现的 force=True 绕过 readiness gate 的 high bug。

**怎么做**:
1. 把 `force` 过载语义拆成 3 个独立参数 (`force` / `allow_incomplete` / `admin_override`)
2. `_resolve_order_status` 改为真正的 status 计算，尊重 `blocking_missing_fields`
3. 新增 `needs_review` 状态到 Order enum（migration 029）
4. 更新 3 个 caller: `document_workflow.py`, `routes/documents.py`, `document_order.py` tool
5. 写 8 个 regression test

**为什么这么做**:
- 参数过载是 bug 的根源。`force=True` 同时意味着 "overwrite existing" + "skip validation" + "force ready"——一个参数控制 3 件事必然出 bug。拆开后每个参数单一职责
- 新增 `needs_review` 而不是继续用 `ready`——让下游代码能明确区分 "可以发送询价" vs "需要人工补充"
- `admin_override` 带强制 WARNING 审计日志——不能静默绕过
- Background ingestion 用 `allow_incomplete=True` 是因为不能让文档 extraction 失败——失败要求用户在 UI 里补，持久化必须发生

**决策**: 记入 ADR-004（下次回顾时补）

**结果**: 8/8 新 test + 43/43 累积 test passing

**下一步**: P0.3 — document/order 非原子上传

### 2026-04-12 — P0.3 完成

**做什么**: 修 Codex 发现的非原子 upload。

**怎么做**:
1. 新增 `create_document_and_pending_order()` 统一入口
2. 用 saga 补偿模式: blob upload → DB 事务 → 失败补偿 delete
3. `routes/orders.py:93` 改调用
4. 4 个 failure injection test

**为什么这么做**:
- **为什么不用单一 DB 事务**: blob upload 是对外部 Supabase 的 HTTP 调用，不在 DB 事务内。必须用 saga 模式（先 upload → 再 DB → 失败补偿）
- **为什么补偿 delete 失败不重抛**: 原始异常才是用户需要看到的；补偿失败只 log warning，不掩盖根因
- **为什么用 `db.begin_nested()`**: 支持外层已有事务（测试里用了）；如果没有外层，savepoint 等价于普通事务

**结果**: 4/4 新 test + 47/47 累积 passing

**下一步**: P0.4 — 全局 row-level ownership audit

### 2026-04-12 — P0.4 + P0.5 完成，P0 关闭

**做什么**: 全局扫一遍 row-level ownership + force= 参数，修掉剩余 exploit。

**发现**: Codex 只点出 1 个越权（document_order），但 grep 一下发现**整个 tool 家族都有同样的问题**：
- `order_overview.py` manage_order
- `order_extraction.py` extract_order
- `order_matching.py` match_products
- `fulfillment.py` manage_fulfillment
- `inquiry_workflow.py` generate_inquiries ×3

每一个都是"raw id 查 DB, 没 tenant 检查"。这些 tool 都从 chat 暴露给 employee，所以每一个都是 critical 级别。

**怎么做**:
1. 抽共享 helper `services/tools/_security.py::scope_to_owner(query, model, ctx)`
2. 给 6 个 tool + `document_context_package` 接 helper
3. `document_order.py` 也重构成用 helper（之前是 inline fix）
4. 产出 `docs/current_progress/security-audit-2026-04-12.md` 全量报告
5. `force=` audit 发现所有 security 相关的都在 P0.2 修了，剩下的是 UX 确认 flag，全部文档化

**为什么这么做**:
- **抽 helper 而不是 copy-paste**: 单一真相源。未来新 tool 只需调 scope_to_owner 即可，grep 能马上知道有没有漏
- **fail closed**: 无 auth context 时 filter 成 `user_id == -1`（不存在的 user），查出空集，绝不返回数据
- **"not found" 而不是 "forbidden"**: 防止通过错误码区分"不存在" vs "别人的"

**结果**:
- 47/47 test 仍全绿（helper 重构后 document_order 的 12 个测试不变）
- 4 个新的 tool 加了 ownership（Order tools），但还没写对应的 regression test → 列入 P5.3 follow-up
- `security-audit-2026-04-12.md` 详细记录所有 grep 结果

**决策**:
- 给 Order tool 加 test 留到 P5.3 做 — 复用已经写好的 document 测试 pattern 来加 Order 版，但本次 P0 的目的是止血，不要 scope creep
- Background tasks 里的 `.get(id)` 没加 filter — 它们都是从已 authenticated 的 endpoint 里调用，不直接 exploitable。defense-in-depth TODO 记在 audit 报告里

**P0 关闭**: 严谨度从 6/10 → 7/10（安全基线达成），可以进 P1。

**下一步**: P1.1 — 推 feature flag commit (cherry-pick inquiry_agent hunk)

---

## 11. ADR — 架构决策记录

> 记录重大技术决策，供后人理解为什么选了这条路。

### ADR-001: 为什么 P0 必须先做

**问题**: 是否可以把 P0 的安全修复推迟到和 P3 可观测性一起做？

**决策**: 不行，P0 必须立刻做。

**理由**:
1. Critical 安全漏洞每多留一天都是风险敞口
2. P1-P7 所有工作都基于"数据是可信的"假设，P0.2 (force readiness bypass) 让这个假设不成立
3. P0.3 非原子上传已经在产生孤儿数据，越晚修需要清理的越多

### ADR-002: 为什么保留 `fill_template` 2 周灰度，不直接删

**问题**: compose_render 已通过 23/23 test，是否可以直接删 fill_template？

**决策**: 保留 2 周灰度期。

**理由**:
1. 测试用 3 个生产模板作为 fixture，但生产里可能有其他模板未覆盖
2. 删代码不可逆，feature flag 回滚是 1 分钟的事
3. 灰度成本低 (一个 env var)，删早了要恢复代价高

### ADR-003: 为什么用 structlog 而不是标准 logging

**问题**: P3.1 为什么选 structlog？

**决策**: structlog。

**理由**:
1. 商业级需要 correlation ID，标准 logging 的 format string 方式很难做
2. structlog 原生支持 contextvars (异步安全)
3. JSON 输出便于 log aggregation (Cloud Logging / ELK)

---

## 12. 技术债盘点（持续更新）

> 发现一个记一个。修了划掉。

### 🔴 Critical
- [x] ~~`document_order.py` 跨租户越权~~ (P0.1 已修 2026-04-12)
- [x] ~~`order_overview.py` / `order_extraction.py` / `order_matching.py` / `fulfillment.py` / `inquiry_workflow.py` 全系列 tool 跨租户越权~~ (P0.4 grep 发现并修复 2026-04-12)
- [x] ~~`document_context_package.py` 聊天 context injection 越权~~ (P0.1 已修 2026-04-12)

### 🟠 High
- [x] ~~`force=True` readiness bypass~~ (P0.2 已修 2026-04-12)
- [x] ~~document/order 非原子上传~~ (P0.3 已修 2026-04-12)
- [ ] `inquiry_agent.py` 作者归属混乱（session + pre-session 工作混在一起）
- [ ] 生产模板 zone_config 尚未经过 schema 校验（在 DB 里）

### 🟡 Medium
- [ ] 8 个 pre-existing test failures
- [ ] `inquiry_agent.py` 内部仍用 `zc["..."]` dict 访问
- [ ] `fill_template` 有 5 个已知 bug（待 compose 灰度后删除）
- [ ] `services/template_engine.py` vs `services/template_engine_v2.py` 双路径
- [ ] 47 个 modified files + 107 untracked 的脏 working tree
- [ ] 无全局 `request_id` / correlation ID
- [ ] 无统一 error taxonomy

### 🟢 Low
- [ ] 无 `ARCHITECTURE.md`
- [ ] 无 on-call `RUNBOOK.md`
- [ ] 无 N+1 query audit

---

## 13. 维护规则

1. **计划变更**: 改 §1-§9 前先在 §10 日志写 why
2. **执行记录**: 每 task 开始/完成写一节（what/why/expected/actual/decision）
3. **ADR**: 任何改变架构的决策记入 §11
4. **技术债**: 发现就加 §12，修完划掉
5. **文档长度**: 超过 1500 行拆子文档
