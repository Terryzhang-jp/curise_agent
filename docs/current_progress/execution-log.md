# 执行日志

---

## [2026-04-10] 文档中心界面已做务实增强，当前可刷新测试

### 本轮目标
- 优化 documents 首页与详情页的可读性和可操作性
- 增加 PDF 首页 preview / 文档 preview / tag 系统
- 把上传区改成点击按钮后再出现

### 已完成
1. ✅ 后端 documents 接口增强
   - `DocumentResponse` 增加 `preview_url`
   - `DocumentResponse` 增加 `preview_text`
   - 前端可直接拿到最小预览信息

2. ✅ 文档中心列表页优化
   - 卡片增加 PDF 首页 preview
   - 非 PDF 文档显示摘要 preview
   - 增加 tag 系统：文件类型 / 文档类型 / 关联订单 / 待建单 / 非订单文档 / 需复核
   - 上传区改成点击“上传文档”按钮后再打开弹层

3. ✅ 文档详情页优化
   - 增加原始文件预览区
   - PDF 显示首页 iframe preview
   - 增加详情页 tags
   - 保留对未来非订单文档 preview 的扩展位

### 验证
- `pnpm build` ✅
- 后端已重启并正常提供 `8001` API ✅
- 前端开发服务继续可用：`http://localhost:3001` ✅

### 结论
- 文档中心已经不再只是“列表 + 按钮”，而是具备 preview、tag、审核前态的最小可用界面
- 当前版本仍然务实：只对 purchase_order 完整建单，但非订单文档的 future 扩展位已经保留

---

## [2026-04-10] 前端默认入口已切到 documents，当前已可测试

### 本轮目标
- 用最务实的方式把前端默认入口正式切到 documents
- 保留未来非订单文档的衍生空间，但当前只完整支持 purchase order
- 让现在的前端直接可测试

### 已完成
1. ✅ 新增 `documents-api.ts`
   - `uploadDocument`
   - `listDocuments`
   - `getDocument`
   - `getDocumentOrderPayload`
   - `createOrderFromDocument`

2. ✅ 新增前端页面
   - `v2-frontend/src/app/dashboard/documents/page.tsx`
   - `v2-frontend/src/app/dashboard/documents/[id]/page.tsx`

3. ✅ 默认入口切换
   - Dashboard 根路径改到 `/dashboard/documents`
   - 左侧导航新增“文档中心”
   - 订单页上传按钮改为“前往文档中心”

4. ✅ 后端补最小支撑接口
   - `GET /api/documents`
   - `DocumentResponse` 增加 `linked_order_id`
   - 修复 documents 上传路由中的重复调度问题

5. ✅ 订单页联动
   - 订单详情页增加“查看源文档”回链
   - `Order` 前端类型补充 `document_id`

### 务实设计结果
- 当前只对 `purchase_order` 提供完整建单按钮
- 非订单文档同样能进入 documents 页面并被审核
- 但不会被强行投影为 `Order`
- 这为未来 invoice / quotation / delivery note 保留了明确扩展位

### 验证
- `python -m py_compile routes/documents.py routes/orders.py services/document_workflow.py services/document_order_projection.py services/order_processor.py` ✅
- `pnpm build` ✅
  - 成功生成：
    - `/dashboard/documents`
    - `/dashboard/documents/[id]`
- 本地开发预览已启动：`http://localhost:3001` ✅
- 后端已确认以下路由存在：
  - `/api/documents`
  - `/api/documents/upload`
  - `/api/documents/{document_id}`
  - `/api/documents/{document_id}/order-payload`
  - `/api/documents/{document_id}/create-order`

### 结论
- 前端现在已经改了
- 当前已经可以测试
- 这是“只做必要的事”的版本：先把 documents 作为默认入口立住，再保留非订单文档未来扩展空间

---

## [2026-04-10] 第三阶段 3A/3B 与基础设施稳健性补强已完成

### 3A — 上传主入口切换
- `routes/orders.py` 的 `/api/orders/upload` 已改为 document-first façade
- 现在上传流程是：
  - 先创建 `Document`
  - 再创建占位 `Order`
  - 后台统一走 `services/document_workflow.py`
- 结果：前端兼容保持不变，但真实入口已切到 document layer

### 3B — document 驱动默认链路
- 新增 `services/document_workflow.py`
  - 统一处理文档创建、提取、建单、错误传播
- 现有链路已形成：
  - `Document` 提取
  - `order_payload` 投影
  - `Order` 创建/更新
  - `process-document` skill 可继续衔接既有 `process-order`

### 稳健性补强
- 文档未提取完成时，禁止直接投影/建单
- 重复建单通过 `document_id` 做防重
- `smart_extract()` 不再只按产品数选最佳结果，新增 metadata completeness tie-break
- `Order` 现在明确关联 `document_id`

### 回归验证
- `python -m py_compile routes/orders.py routes/documents.py services/document_workflow.py services/document_order_projection.py services/order_processor.py` ✅
- `PYTHONPATH=. python tests/_phase3_validation.py` ✅
  - 样本 1：`document_status=extracted`，`order_status=extracted`，73 产品
  - 样本 2：`document_status=extracted`，`order_status=extracted`，22 产品
  - `manage_document_order` 工具已注册

### 结论
- 3A 已完成：入口已切
- 3B 已完成：链路已串
- 当前更需要推进“调用方全面切换”和“更高层集成测试”，而不是继续扩底层模型

---

## [2026-04-10] 第二阶段 document → order payload 最小闭环已落地

### 本轮目标
- 把 `Document` 提取结果转成稳定的 `order_payload`
- 支持从 `document_id` 创建 `Order`
- 遇到关键字段缺失时进入 review 路径，而不是静默补全

### 已完成
1. ✅ 新增订单投影服务 `v2-backend/services/document_order_projection.py`
   - 定义 `order_payload`
   - 定义关键字段缺失策略
   - 支持从 `Document` 创建或更新 `Order`

2. ✅ 新增订单与文档关联
   - `models.py` 给 `Order` 增加 `document_id`
   - migration: `v2-backend/migrations/manual/028_link_orders_to_documents.sql`

3. ✅ 扩展文档路由 `v2-backend/routes/documents.py`
   - `GET /api/documents/{document_id}/order-payload`
   - `POST /api/documents/{document_id}/create-order`

4. ✅ 新增 Agent 工具 `v2-backend/services/tools/document_order.py`
   - `manage_document_order(action=\"preview\"|\"create\")`

5. ✅ 新增技能 `v2-backend/skills/process-document/SKILL.md`
   - 先预览文档投影
   - 再建单
   - 再衔接既有 `process-order`

6. ✅ 更新场景注入
   - `services/agent/scenarios.py` 新增 `document_processing`
   - `routes/chat.py` 新增 `process-document` 自动注入

### 阶段验证
- `python -m py_compile ...` 覆盖新增与修改文件 ✅
- 样本 1 `68358749.pdf`
  - `ready_for_order_creation=True` ✅
  - `missing_fields=[]` ✅
  - 成功创建订单，`order.document_id` 正确回指文档 ✅
- 样本 2 `CYI-REQ2561 ... Read-Only.pdf`
  - `ready_for_order_creation=False` ✅
  - `missing_fields=['delivery_date']` ✅
  - 创建出的订单带 `processing_error=待补充关键字段: delivery_date` ✅
- `manage_document_order` 已在 chat registry 注册 ✅
- `document_processing` 场景识别正常 ✅

### 结论
- 第二阶段最小闭环已成立：`Document -> order_payload -> Order`
- 现在 Agent 已能从 `document_id` 起步，而不是必须先依赖旧订单入口
- 下一步更适合做“入口切换和流程串联”，而不是优先做 embedding/pgvector

---

## [2026-04-10] 第一阶段统一文档入口已落地

### 本轮目标
- 建立独立于 `Order` 的统一 document layer
- 维护持久进度文档，便于后续上下文恢复
- 用指定真实 PDF 样本验证第一阶段可行性

### 已完成
1. ✅ 新建持久进度文档 `AGENT_JOURNAL.md`
   - 记录阶段目标、验证标准、ADR、恢复点
   - 后续上下文直接从该文件恢复

2. ✅ 新增 `Document` 模型 — `v2-backend/models.py`
   - 新表: `v2_documents`
   - 字段: 文件信息、提取结果、状态、错误、时间戳

3. ✅ 新增 migration — `v2-backend/migrations/manual/027_add_documents_foundation.sql`
   - 创建 `v2_documents`
   - 增加基础索引

4. ✅ 新增 `document_processor` — `v2-backend/services/document_processor.py`
   - 复用现有 `smart_extract`
   - 统一输出 `doc_type + content_markdown + extracted_data + extraction_method`

5. ✅ 新增 `/documents/upload` 路由 — `v2-backend/routes/documents.py`
   - 上传文件进入 `documents` 存储目录
   - 后台提取并更新 `v2_documents.status`
   - 保持旧 `/orders/upload` 不受影响

6. ✅ 接入主应用 — `v2-backend/main.py`
   - 挂载 `/api/documents`

### 阶段验证
- `python -m py_compile main.py routes/documents.py services/document_processor.py models.py` ✅
- `import main` 后确认 `/api/documents` 路由存在 ✅
- SQLite 内存库创建 `v2_documents` 并插入 `Document` 记录 ✅
- 样本 1 `/Users/yichuanzhang/Desktop/curise_system_2/68358749.pdf`
  - `doc_type=purchase_order` ✅
  - `product_count=73` ✅
  - `po_number=68358749` ✅
- 样本 2 `/Users/yichuanzhang/Desktop/curise_system_2/20251213 PO No CYI-REQ2561 PO01.xlsx  -  Read-Only.pdf`
  - `doc_type=purchase_order` ✅
  - `product_count=22` ✅
  - `po_number=CYI-REQ2561/PO01` ✅
  - `vendor_name` / `delivery_date` 为空 ⚠️

### 结论
- 第一阶段“统一文档入口”最小闭环成立
- 目前尚不需要把 chunking/embedding/pgvector 作为前置条件
- 第二阶段重点应切到“订单填写 skill 如何消费 document layer 结果并处理缺字段”
- `v2_documents` 已在代码和 migration 中准备好，是否执行到实际数据库可在下一步按环境落地

---

## [2026-04-09 16:00] 开始架构改版

### 决策记录
- 自动推进 + 异常暂停: 写进 skill
- 多订单并发: 暂时串联
- 前端需要适配: 是 (status 流转变化)

### 执行计划 (6 步)
1. ✅ 新建 `extract_order` tool — `services/tools/order_extraction.py`
   - 包装 smart_extract(), 写入 Order.extraction_data/products/order_metadata
   - 支持 force=true 重新提取
   - 返回: 产品数 + 元数据摘要 + 数值验证警告
   - 新 status: "extracted" (提取完成, 等待匹配)

2. ✅ 新建 `match_products` tool — `services/tools/order_matching.py`
   - 包装 run_agent_matching(), 写入 match_results/statistics
   - 自动运行 financial_analysis + inquiry_pre_analysis
   - 返回: 匹配率 + 未匹配产品列表 + 询价就绪状态

3. ✅ 改 `routes/orders.py` — upload 后只做提取
   - `_run_extract_only()`: 只提取, status="extracted", 不自动匹配
   - `_run_process_order()`: 保留作为 legacy fallback
   - 前端适配: models.py 的 status 约束加了 "extracted"

4. ✅ 新建 `process-order` skill — `skills/process-order/SKILL.md`
   - 4 步: 检查提取 → 匹配 → 检查询价就绪 → 生成
   - 自动推进规则: 产品数>0且元数据完整 → 自动匹配
   - 异常暂停规则: 0 产品/缺交货日期/匹配率<80%/blocking gap

5. ✅ 注册新 tools + 更新 scenarios
   - `__init__.py`: 注册 order_extraction + order_matching
   - `scenarios.py`: 新增 "order_processing" 场景 + intent 检测
   - `chat.py`: _SCENARIO_SKILL_MAP 加 "order_processing" → "process-order"
   - 16 tools total (14 + 2 new)

6. ⬜ 端到端测试

### 验证
- 53 core tests pass ✅
- 16 tools correctly registered ✅
- "extracted" status added to DB constraint ✅

---

## [2026-04-09 18:00] Layer 2+3 测试全部通过

### 测试结果
- **Layer 2** (上传只提取): ✅ status=extracted, 73 产品, 不自动匹配
- **Test 3.1** (extract_order 跳过已提取): ✅
- **Test 3.2** (match_products): ✅ 匹配率 100%, 73/73, 2 供应商
- **Test 3.3** (manage_order overview): ✅
- **Test 3.4** (manage_inquiry check): ✅ 2 供应商 ready

### 修复
- DB CHECK 约束: 加了 "extracted" 状态 (ALTER TABLE)
- 需要在生产 DB 也执行: `migrations/manual/026_add_extracted_status.sql`

### 状态流转验证
```
uploading → extracted → matching → ready ✅
```

## [2026-04-09 17:00] Step 1-5 完成, 准备端到端测试
