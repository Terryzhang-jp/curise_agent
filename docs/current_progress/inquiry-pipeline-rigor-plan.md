# Inquiry Pipeline 严谨度审查 + 修复 Plan

> 起始日期: 2026-04-11
> 范围: 用户上传 supplier 模板 → 订单 → 匹配 → 生成询价单 全链路
> 目标: 干净的代码 + 稳固的流程 + 显式的 fallback 机制
> 维护方式: 每完成一项修复，更新对应 task 状态 + 追加日期节
>
> 相关文档:
> - `process-document-skill-implementation-progress.md` — 上游文档处理进度
> - `poc-compose-renderer-outputs/` — compose renderer POC 验证产物

---

## 0. 为什么写这份 plan

2026-04-11 一天内在询价生成链路上**找到了 5 个真实生产 bug**：

1. `load_workbook` NameError（fill_template 完全跑不通）
2. `get_or_create_cancel_event` NameError（orchestrator cancel 路径会炸）
3. blank field verify 误判（71 项 false negative，整张单子被拒）
4. summary merge 在 row resize 后丢失（3 项 missing merge）
5. number_format 在 fill_template 里被 openpyxl insert_rows 静默丢失（compose POC 暴露的 latent bug）

加上 POC 阶段又发现 5 个 missing feature（header_fields / order_context / stale cleanup / static_values restore / external_refs），**这条链路一天暴露了 10 个真实问题**。

这不是某个具体函数的 bug，是**整条链路的严谨度不足**。本文档把所有 gap 系统化梳理，给出可执行的修复 plan。

---

## 1. 当前严谨度评分

| 阶段 | 评分 | 主要问题 |
|---|---|---|
| 1 - 模板上传 | **3/10** | 3 endpoint 编排 + 静默失败 + 无 Draft 状态 + 文件孤儿 |
| 2 - 模板-供应商绑定 | **5/10** | JSON 数组无外键 + 多模板时随机选 + 删除无回退 |
| 3 - 订单 → 匹配 → 进入询价 | **6/10** | matched_product 缺 supplier_id 静默丢弃 + 币种错配无检查 |
| 4 - fill_template | **5/10** | 今天才修了 5 个 bug，1 个未修；零端到端测试 |
| 5 - verify_output | **4/10** | 维度不全；verify 通过 ≠ 正确；error 路径自相矛盾 |
| 6 - orchestrator | **6/10** | 并行 OK；但部分失败 + 取消的状态管理混乱 |
| 7 - 用户体验 | **4/10** | 错误信息无 actionable；版本/历史无管理 |

**整体：5/10，能跑通但不严谨**。

---

## 2. 7 个阶段的 gap 清单

### Stage 1 — 模板上传

**当前现实**：3 个独立 endpoint，前端必须自己编排 analyze → create → upload-file

#### Gap 1.1 — 分析失败 ≠ 拒绝保存
**位置**: `routes/settings.py:495 analyze_supplier_template`
**症状**: zone_config / template_contract 构建包在 try/except，失败只 log warning。用户能保存一个分析"成功"但 zone_config 是 None 的模板。
**严重性**: 🔴 High — 用户以为模板可用，到生成时才发现
**修法**: 把 zone_config 构建从 try/except 中移出，失败立即返回 400 + 详细错误。**没有 zone_config 的模板根本不应该被允许保存**。

#### Gap 1.2 — 3 步之间没有 transaction
**位置**: `routes/settings.py:495 analyze` + `:396 create` + `:457 upload-file`
**症状**: analyze 时已经把文件上传到 storage（line 514-518），后续步骤失败时文件成为孤儿，永远占用 storage 空间。
**严重性**: 🟡 Medium — storage 累积、没有功能影响
**修法**: 合并成单一 endpoint `POST /supplier-templates/upload-and-analyze`，内部走完整流水线，任何一步失败都 cleanup 已上传的文件。

#### Gap 1.3 — 没有 Draft / Published 状态
**位置**: `models.py:SupplierTemplate`
**症状**: 模板要么"存在"要么"不存在"。zone_config 残缺的模板会被 `get_production_templates` 默默过滤，但用户在自己的模板列表里**还能看到它**。
**严重性**: 🟡 Medium — UX confusion
**修法**: SupplierTemplate 加 `status` 字段，枚举值 `draft / analyzing / analyzed / ready / archived`。前端列表显示状态。`get_production_templates` 只返回 `ready`。

#### Gap 1.4 — AI 分析的准确度无验证
**位置**: `services/template_analysis_agent.py`
**症状**: `run_template_analysis_agent` 是 LLM 分析，可能把 D 列识别成 product_name 但实际是 description。没人验证。
**严重性**: 🟡 Medium — 错误要等到生成时才发现
**修法**: 分析后让 agent 自己生成一个 dummy order data，跑一次 fill + verify，verify 通过才标记为 ready；否则进入 draft 状态等用户人工确认。

---

### Stage 2 — 模板-供应商绑定

#### Gap 2.1 — 没有外键约束
**位置**: `models.py:SupplierTemplate.supplier_ids` (JSON array)
**症状**: 可以填任何 ID，包括不存在的 supplier。没人检查。
**严重性**: 🟢 Low — 不会造成数据损坏，只是 select_template 静默匹配不上
**修法**: 在 `services/inquiry_agent.py:select_template` 入口做一次 supplier 存在性 check，记录 warning。

#### Gap 2.2 — 一个供应商可以绑多个模板
**位置**: `services/inquiry_agent.py:163 resolve_template`
**症状**: 线性扫描，第一个匹配的就用。如果 supplier 绑了 2 个模板，永远只用第一个，取决于 DB 返回顺序。用户没法选。
**严重性**: 🟡 Medium — 多模板场景行为不可预测
**修法**:
- 短期：在前端 UI 显式禁止给同一个 supplier 绑多个模板（创建/编辑时校验）
- 长期：加 `priority` 字段，按 priority 排序，相同时按 created_at desc

#### Gap 2.3 — 删除无回退
**位置**: `routes/settings.py:438 delete_supplier_template`
**症状**: 删完之后，绑过这个模板的 supplier 没有 fallback。下次生成直接报"无可用模板"。
**严重性**: 🟡 Medium
**修法**: 删除时检查这个模板是否被 supplier 绑定，如果有，要求用户确认 + 显示影响范围。

---

### Stage 3 — 订单 → 匹配 → 进入询价

#### Gap 3.1 — matched_product 必须有 supplier_id 否则被丢弃
**位置**: `services/inquiry_agent.py:1404 run_inquiry_orchestrator`
**症状**: orchestrator 按 `matched_product.supplier_id` 分组。如果某个 product 匹配上但 supplier_id 是 None（DB 没填），那个产品**完全消失**，生成出来比订单少几个，没人提示。
**严重性**: 🔴 High — 数据丢失，用户看不到
**修法**:
1. 分组之前预 scan，统计 `unassigned_count`
2. 如果 `unassigned_count > 0`，在生成结果里加 `unassigned_products: [...]` 字段
3. 前端在 inquiry tab 显示「⚠️ 3 个产品没有供应商，未生成询价」

#### Gap 3.2 — 未匹配的产品被静默丢弃
**位置**: 同上
**症状**: match_results 里 status 不是 matched 的产品完全不进入询价生成。订单页统计「73/73 已匹配」但生成出来可能少几个。
**严重性**: 🟡 Medium
**修法**: 同 Gap 3.1 — 把 unmatched_count 也报告出来。

#### Gap 3.3 — currency 和模板 currency 不匹配
**位置**: 整条链路无任何 check
**症状**: 订单 currency 是 AUD，模板假设 JPY（用 `#,##0` 整数 format），结果显示截断。今天 POC 暴露的 bug。
**严重性**: 🔴 High — 静默精度损失
**修法**: 两层防御
1. **运行时 fallback（已在 POC 里实现）**: renderer 检测数据有小数 + 模板 format 是整数 → 自动 promote 到 `#,##0.##`
2. **设计时声明**: 模板上传时 zone_config 加 `data_assumptions: {currency_class: "integer" | "decimal"}` 字段。生成前 pre-flight check 警告 mismatch（不阻断，只警告）

---

### Stage 4 — fill_template

#### Gap 4.1 — 5 个已知 bug + 1 个未修
**位置**: `services/inquiry_agent.py` + `services/template_engine.py`
**已修**:
- ✅ `load_workbook` NameError
- ✅ `get_or_create_cancel_event` NameError
- ✅ blank field verify false negative
- ✅ summary merge re-creation 后丢失
**未修**:
- ❌ **format loss**：fill_template 通过 openpyxl insert_rows 后，原 cell 的 number_format 被重置成 `General`。Step 8 的 clone styles 又从被重置的 cell 复制，结果整列 format 丢失。今天 POC 暴露。
**严重性**: 🟡 Medium — fill_template 因为 format 丢失反而"宽容"地显示了所有数据，但模板原意丢了
**修法**: 不修 fill_template，**用 compose_render 替代**。fill_template 进入 deprecated 阶段。

#### Gap 4.2 — 零端到端测试
**位置**: `tests/`
**症状**: `_generate_single_supplier`、`run_inquiry_orchestrator`、`_save_workbook` 没有任何 unit test 调用过。今天加的字节码静态分析只能抓 NameError 类。
**严重性**: 🔴 High — 任何 logic bug 都得等用户在 UI 点按钮才会发现
**修法**: 见全局 P1 — 端到端 integration test。

---

### Stage 5 — verify_output

#### Gap 5.1 — verify 通过 ≠ 输出正确
**位置**: `services/template_engine.py:293 verify_output`
**症状**: 今天的 format loss 是最好例子。fill_template 把 unit_price 的 `#,##0` format 弄丢了，verify 看 cell 值对的就 PASS。
**严重性**: 🟡 Medium
**修法**: verify_output 加 number_format 验证维度——比对 cell 的 format 和 template 原 format 是否兼容。

#### Gap 5.2 — verify 不检查 cross-references
**位置**: 同上
**症状**: H16 的 `=L35` cross-reference bug——header 引用 summary 的 grand total，row 数没更新。verify 完全不检查。
**严重性**: 🟡 Medium
**修法**: verify_output 走过 zone_config.external_refs 列表，验证每个 cell 的 formula 文本里包含正确的目标地址。

#### Gap 5.3 — verify 失败的处理路径自相矛盾
**位置**: `services/inquiry_agent.py:791-803`
**症状**: line 791-797 verify 失败时仍然保存（status=repair_required），但 line 798 `except Exception: raise` 又抛异常。两条路径互相矛盾，取决于失败发生在哪一行。
**严重性**: 🟡 Medium
**修法**: 明确分两类：
- **结构错误**（merge 缺失、formula 错）→ 进 repair_required 队列，文件保存
- **致命错误**（拿不到 template、写文件失败）→ 抛异常，supplier 标记 failed
- 加测试覆盖两种路径

---

### Stage 6 — Orchestrator

#### Gap 6.1 — 部分失败时没有重试
**位置**: `services/inquiry_agent.py:1377 run_inquiry_orchestrator`
**症状**: 5 个 supplier 中 3 成功 2 失败，用户看到 mix。没有 retry 按钮，也没有"为什么失败"的具体诊断。
**严重性**: 🟡 Medium
**修法**:
- 失败时记录 error_kind（template_missing / fill_error / verify_repair_required / cancelled）
- 前端按 error_kind 显示 actionable hint
- 单 supplier 重试按钮直接调 `run_inquiry_single_supplier`

#### Gap 6.2 — cancel 后状态不可恢复
**位置**: `services/inquiry_agent.py:_ensure_not_cancelled`
**症状**: 取消时已经写到 storage 但还没写到 inquiry_data 的文件成为孤儿。
**严重性**: 🟢 Low
**修法**: cancel 后调一次 cleanup pass 删除半成品文件，或者在 inquiry_data 里记录 cancelled supplier 的孤儿 file_url 给后续 GC。

---

### Stage 7 — 用户体验

#### Gap 7.1 — 错误信息对用户不友好
**位置**: 前端 inquiry workspace
**症状**: `Row 22 F (description): expected 'kg', got blank`——用户不知道 row 22 是什么、F 是什么列、应该怎么改。
**严重性**: 🟡 Medium
**修法**:
- verify 错误带 `cell_label`（产品列名而不是 letter）
- 错误带 `repair_action`（"打开产品 #1 编辑 unit 字段"）
- error_kind 分类（structural / data / template）

#### Gap 7.2 — 「下载」「重新生成」之间无版本概念
**位置**: 全链路
**症状**: 重新生成产生新 hash 文件，旧文件留在 storage 不清理。订单 #75 的 supplier 17 可能有 5 份历史 inquiry。
**严重性**: 🟢 Low — 累积型，不影响功能
**修法**: 重新生成时把旧版本移到 `archived/` 子目录，保留最近 3 个版本，更老的清理。

---

## 3. 三类架构性根因（全局视角）

把上面 17 个 gap 抽象出来，**只有 3 类根本问题**：

### 类 1 — 没有契约，靠隐性约定
`zone_config`、`template_contract`、`field_positions`、`product_columns`、`summary_formulas` 全部散落在 `SupplierTemplate.template_styles` 这个 JSON 里，**没有 Pydantic schema、没有验证、没有版本号**。任何代码读它们都靠 `.get(key, default)`，缺字段就静默回退。

**影响的 gap**: 1.1, 1.4, 4.1, 5.1, 5.2

**修复**: 给 zone_config 定义 Pydantic v2 model `ZoneConfigV1`，所有字段强类型 + 必填 / 可选明确。所有读取从 `.get()` 改成 `model.field`。Schema 不通过的模板**根本不能保存**。

### 类 2 — 多步操作没有 transaction
模板上传 3-step / verify 失败的保存路径 / orchestrator 部分失败 / cancel 中途——全部都是"做一半丢一半"。Storage 文件、DB 记录、in-memory state 之间没有原子性。

**影响的 gap**: 1.2, 5.3, 6.2, 7.2

**修复**: 关键 cross-resource 操作（upload + DB write、generate + save + record）用 context manager 包起来，失败时自动 cleanup。Storage 上传都先 stage 到 `_pending/` 路径，确认 DB 写入成功后再 rename 到正式路径。

### 类 3 — 测试覆盖只测正向 path 的局部
fill_template / verify_output / template_engine 现有测试是**小型合成 fixture + 验证返回值**。**没有任何测试**：
- 跑过完整的 `_generate_single_supplier`
- 跑过完整的 `run_inquiry_orchestrator`
- 用真实生产模板做过 round-trip
- 测试过 partial failure 场景
- 测试过 cancel 流程
- 测试过 currency mismatch
- 测试过模板上传的 3 步编排

**影响的 gap**: 1.4, 4.2, 5.1, 5.2, 6.1

**修复**: 写一个 `test_inquiry_pipeline_e2e.py`，用 sqlite + mock storage + 真实生产模板的字节内容（作为 fixture）跑完整流程。10-20 个测试覆盖所有阶段所有失败模式。

---

## 4. 可执行修复 plan（按优先级）

**核心理念**：先打地基（schema + e2e test），再换主路径（compose_render），最后做 UX。每个 phase 独立可交付，不依赖下一 phase。

### Phase 1 — 地基 (P0, 2-3 天)

#### Task 1.1: ZoneConfig Pydantic schema
- **位置**: 新增 `services/zone_config_schema.py`
- **内容**: 定义 `ZoneConfigV1` 模型，包含所有当前 zone_config 字段：`zones / header_fields / product_columns / product_row_formulas / summary_formulas / summary_static_values / stale_columns_in_summary / external_refs / template_contract`
- **每个字段强类型 + 必填/可选明确**
- **acceptance**: 用 3 个生产模板的 zone_config 验证 model 能解析（不报错），所有未声明字段被拒绝

#### Task 1.2: 端到端 integration test
- **位置**: 新增 `tests/test_inquiry_pipeline_e2e.py`
- **内容**:
  1. 用 sqlite in-memory + mock file_storage
  2. 真实生产模板字节内容作为 test fixture（已经有 3 个在 `current_progress/poc-compose-renderer-outputs/`）
  3. 真实订单 + 73 个产品的 mock data
  4. 跑 `_generate_single_supplier` 完整 → 断言 verify_output 通过
  5. 跑 `run_inquiry_orchestrator` 多 supplier 并行 → 断言所有 supplier 都成功
  6. 测 partial failure（一个 supplier template_file_url 不存在）
  7. 测 cancel 中途
  8. 测 currency mismatch（订单 AUD + 模板 JPY format）
- **acceptance**: 至少 8 个 test case，全部通过；总耗时 < 10 秒；今天的 5 个 bug 在测试里都能被抓住

#### Task 1.3: 修复 fill_template format loss
- **位置**: `services/template_engine.py:_copy_row_styles` (Step 8)
- **方案**: 不修 fill_template；而是把 Phase 2 (compose_render) 替代它
- **acceptance**: compose_render 在 3 个生产模板上 round-trip 通过

---

### Phase 2 — 主路径换 compose_render (P0, 3-4 天)

#### Task 2.1: 把 POC compose_render 产品化
- **位置**: 新增 `services/template_engine_v2.py` (compose_render)
- **内容**: 把 `tests/_poc_compose_renderer.py` 的代码挪到生产位置，加完整 docstring + 类型声明
- **acceptance**: 通过 Phase 1 写的所有 e2e test

#### Task 2.2: 加 feature flag 让 inquiry_agent 切换 renderer
- **位置**: `services/inquiry_agent.py:_generate_single_supplier`
- **内容**: 环境变量 `INQUIRY_RENDERER=compose|fill` 控制走哪条
- **默认 fill**（保守）→ 真实流量验证 1 周 → 切换默认到 compose
- **acceptance**: 两条路径在所有 e2e test 上都通过；切换不需要重启

#### Task 2.3: compose_render 边界 audit
- **内容**: 在 3 个生产模板上验证以下边界：
  - [ ] 条件格式（conditional formatting）
  - [ ] 数据验证（data validation）
  - [ ] 单元格保护（cell protection）
  - [ ] Defined names
  - [ ] Charts / images
  - [ ] Cross-sheet references
  - [ ] 列宽 / 行高
  - [ ] 打印区域 / 冻结窗格
- 不支持的项明确文档化，由产品决定是否需要支持
- **acceptance**: audit 报告 + 不支持项的临时 workaround

#### Task 2.4: 删 fill_template 旧代码
- **触发条件**: 真实流量切换到 compose 后稳定运行 2 周
- **删除**: `fill_template` (~600 行) + `verify_output` (~250 行) + `template_contract.py` (~260 行) + 相关测试
- **acceptance**: 全部 e2e test 仍然通过；inquiry_agent.py 减少 ~1100 行

---

### Phase 3 — 模板生命周期 (P1, 2-3 天)

#### Task 3.1: SupplierTemplate.status 状态机
- **位置**: `models.py:SupplierTemplate` 加字段 `status: Literal["draft", "analyzing", "analyzed", "ready", "archived"]`
- **迁移**: 现有 3 个生产模板都标记为 `ready`
- **状态转换规则**:
  - `draft`：刚创建，没有 file
  - `analyzing`：上传后正在 AI 分析
  - `analyzed`：分析完但 zone_config 校验失败 / 用户没确认
  - `ready`：zone_config 通过 schema + 通过自检 fill→verify
  - `archived`：被管理员下架，不进入 select_template
- **acceptance**: 状态机可在 admin UI 看到每个模板的当前状态 + 能手动 archive

#### Task 3.2: 单一 endpoint `upload-and-analyze`
- **位置**: `routes/settings.py` 替代现有 3 个 endpoint
- **内容**: 接受 file，内部走 upload + analyze + zone_config 校验 + 自检 round-trip + 写 DB。任何一步失败都 cleanup
- **transaction 模型**:
  1. 上传文件到 storage `_pending/<uuid>`
  2. 分析 + zone_config 构建 + schema 校验
  3. 自检 round-trip（用 mock data 跑 compose_render + verify_output）
  4. 全部通过 → DB 写入 SupplierTemplate(status=ready) + storage rename `_pending/<uuid>` → `templates/<uuid>`
  5. 任何一步失败 → 删 `_pending/<uuid>` + 返回详细错误
- **acceptance**: 失败场景下 storage 不留孤儿；成功场景下 status 直接是 ready

#### Task 3.3: Storage `_pending/` 清理 GC
- **位置**: 新增 `services/storage_gc.py`
- **内容**: 定期扫 `_pending/` 目录，删除 > 1 小时的文件
- **acceptance**: 测试 case：上传后立即 kill 进程，1 小时后文件被清理

---

### Phase 4 — UX 加固 (P1, 2 天)

#### Task 4.1: 错误分类 + actionable hints
- **位置**: `services/inquiry_agent.py:_engine_verify_to_results` + 前端 SupplierInquiryCard.tsx
- **内容**: 每个 verify error 带 `error_kind: "structural" | "data_missing" | "format" | "template" | "system"`
- 前端按 kind 显示对应 hint：
  - `data_missing`: "请在订单页编辑产品 #N"
  - `format`: "请联系管理员调整模板"
  - `template`: "模板配置有问题，请联系管理员"
- **acceptance**: 用户能从错误里直接跳到正确的修复入口

#### Task 4.2: 单 supplier 重试按钮
- **位置**: 前端 SupplierInquiryCard.tsx + `routes/orders.py`
- **内容**: 失败的 supplier card 显示 retry 按钮，调 `run_inquiry_single_supplier`
- **acceptance**: 失败 → 修数据 → 重试 → 成功 的完整流程能跑通

#### Task 4.3: 询价单版本管理
- **位置**: `services/inquiry_agent.py:_save_workbook`
- **内容**: 保存时检查同 supplier_id 是否有旧文件，有就 move 到 `archived/<order_id>/<supplier_id>/v<n>.xlsx`，新文件作为当前版本
- **保留策略**: 最近 3 个版本，更老的硬删
- **acceptance**: 重新生成 N 次后，inquiries/ 里只剩当前版本

---

### Phase 5 — Pre-flight check (P2, 1 天)

#### Task 5.1: 生成前自检
- **位置**: `services/inquiry_agent.py:run_inquiry_orchestrator` 入口
- **内容**: 在跑生成之前，先做这些检查：
  1. 每个产品都有 supplier_id？没有 → warning
  2. 每个 supplier 都有 ready template？没有 → warning
  3. 订单 currency 和模板 currency 是否一致？不一致 → warning（不阻断）
  4. 至少有 1 个 supplier 能生成？否则 → 直接 fail，给用户清楚的信息
- **acceptance**: 4 个 check 都有对应 test case

---

## 5. Fallback 机制总览

按层次划分 fallback 策略：

### 渲染层 fallback
```
compose_render (主路径)
    ↓ 失败
fill_template (legacy fallback，保留 1-2 月观察期)
    ↓ 失败
返回 error，supplier 标记 failed
```

### 模板选择 fallback
```
exact binding (supplier_ids match)
    ↓ 找不到
candidate auto pick (return first production template)
    ↓ 没有 production template
返回 unavailable，supplier 标记"无模板"
```

### Format fallback
```
模板原 number_format
    ↓ 数据有小数 + format 是整数
auto-promote 到 #,##0.##
    ↓ 数据是字符串
不动 format
```

### Verify fallback
```
verify_output 通过
    ↓ 失败
保存到 repair_required 队列
    ↓ 致命错误
不保存，返回 error
```

### 数据完整性 fallback
```
所有产品都有 supplier_id
    ↓ 部分缺失
分组成功的部分继续生成 + 把 unassigned_count 报告给前端
    ↓ 全部缺失
直接 fail，提示用户先做产品-供应商绑定
```

### Cancel fallback
```
正常 cancel
    ↓ 已写入 storage 但未记录到 DB 的文件
GC 任务定期清理 (Task 3.3)
```

---

## 6. 验收标准（整体）

完成所有 Phase 后，系统应该能通过以下"整体严谨度测试"：

1. **上传一个故意写坏的模板**（缺关键 cell）→ 系统拒绝保存 + 给出具体错误
2. **上传一个正常模板** → 系统自动跑自检 → 自检通过 → 状态变 ready
3. **生成询价时有 1 个 supplier 没模板** → 其他 supplier 正常生成 + 那个 supplier 显示明确"无可用模板"
4. **生成时取消** → 部分文件保留 / 部分清理 → 重启系统后没有孤儿
5. **订单是 AUD + 模板是 JPY 整数 format** → renderer 自动 promote format → 显示带小数 + warning 提示用户币种不一致
6. **故意改坏 verify 期望** → e2e test 抓住，PR 不能 merge
7. **renderer 切换** → fill 和 compose 在所有 case 上行为一致 + e2e test 覆盖
8. **删除一个被绑定的模板** → 系统警告 + 显示影响范围
9. **生成 5 次同一个订单** → storage 里只剩最新版本 + 3 个归档版本 + 其他被清理
10. **任何 fill_template 函数体里加个 typo** → 字节码静态分析测试当场抓住

每一项都对应一个或多个具体 task，所有 task 完成后这 10 条都自动满足。

---

## 7. 时间估算

| Phase | 内容 | 估算 | 阻塞下一 phase？ |
|---|---|---|---|
| Phase 1 | ZoneConfig schema + e2e test + format loss audit | 2-3 天 | 不阻塞，但强烈建议先做 |
| Phase 2 | compose_render 产品化 + feature flag + 边界 audit + 删旧代码 | 3-4 天 | 阻塞 Phase 4 的版本管理 |
| Phase 3 | 模板生命周期 + atomic upload + storage GC | 2-3 天 | 不阻塞 |
| Phase 4 | 错误分类 + 重试 + 版本管理 | 2 天 | 不阻塞 |
| Phase 5 | Pre-flight check | 1 天 | 不阻塞 |
| **总计** | **完整严谨化** | **10-13 天** | — |

---

## 8. 立即可做的最小有用步骤

如果只能做 1 件事：**Task 1.2 端到端 integration test**。0.5-1 天工作，能立刻预防今天发生的所有 5 个 bug 类型再次发生。它不修任何 bug，但它让 future bug 变得不可能 ship 出去。

如果只能做 2 件事：**Task 1.2 + Task 1.1**（schema）。两件加一起 1-1.5 天，能把这条链路从"5/10 能跑通"提升到"7/10 有底线保护"。

如果只能做 3 件事：**Task 1.2 + Task 1.1 + Task 2.1**（compose_render 产品化）。3-4 天，能把整条链路提升到"8/10 主路径干净 + 有完整测试 + 有 schema 兜底"。

剩下的 task 都是"从 8 到 10"的精细化工作，不影响主路径稳定性。

---

## 9. 维护规则

- 每完成一个 task，更新 `## 4. 可执行修复 plan` 里那个 task 的状态
- 每完成一个 Phase，追加一个 dated 节记录 acceptance 是否达成
- 任何新发现的 gap 加进 `## 2. 7 个阶段的 gap 清单`
- 这份文档的目标长度不超过 800 行，超过就拆分子文档
