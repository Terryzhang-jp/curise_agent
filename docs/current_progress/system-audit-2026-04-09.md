# 系统全面审计 — 2026-04-09

## 1. 文件存储架构

### Supabase Storage 桶结构
```
v2-files/                         ← STORAGE_BUCKET
  ├── orders/                     ← 用户上传的订单 PDF/Excel
  │     └── abc123_order.pdf
  ├── templates/                  ← 管理员上传的模板文件
  │     └── supplier_template.xlsx
  ├── inquiries/                  ← 系统生成的询价 Excel + HTML preview
  │     ├── inquiry_PO123_supplier5_abc.xlsx
  │     └── inquiry_PO123_supplier5_abc.html
  ├── chat/                       ← Chat 中上传的文件
  ├── attachments/                ← 订单附件 (照片/发票)
  ├── workspace/{session_id}/     ← Agent 生成的文件 (per-session)
  │     ├── _workspace_manifest.json
  │     ├── inquiry_supplier_123.xlsx
  │     └── inquiry_supplier_123_v1.xlsx (旧版本)
  └── line/                       ← LINE bot 图片
```

### 本地文件系统
```
/tmp/workspace/{session_id}/      ← Agent 工作目录 (每个 chat session 一个)
  ├── uploaded_file.pdf           ← 用户在 chat 中上传的文件
  ├── inquiry_supplier_123.xlsx   ← 生成的询价单
  └── _workspace_manifest.json

/path/to/backend/uploads/         ← UPLOAD_DIR (静态文件)
  └── product_upload_template.xlsx
```

### 文件生命周期
| 文件类型 | 创建 | 存储 | 清理 |
|---------|------|------|------|
| 订单 PDF | routes/orders.py:80 | Supabase `orders/` | 永不清理 |
| Chat 上传 | routes/chat.py:459 | Supabase `chat/` + workspace | 永不清理 |
| 询价 Excel | inquiry_agent.py | workspace → Supabase `inquiries/` + `workspace/` | 版本累积, 不清理 |
| 模板文件 | routes/settings.py | Supabase `templates/` | 手动删除 |
| 附件 | fulfillment.py | Supabase `attachments/` | 永不清理 |
| Workspace 本地 | routes/chat.py:167 | /tmp/workspace/{session_id}/ | **从不清理** (运维债) |

---

## 2. 数据库核心模型 (Order)

### JSON 列详情
```
Order
  ├── extraction_data    ← AI 原始提取结果 (完整保留, 用于审计)
  ├── order_metadata     ← 8 个标准字段:
  │     {po_number, ship_name, vendor_name, delivery_date,
  │      order_date, currency, destination_port, total_amount,
  │      extra_fields: {...}}
  ├── products           ← 标准化产品列表:
  │     [{line_number, product_code, product_name,
  │       quantity, unit, unit_price, total_price}, ...]
  ├── match_results      ← 匹配结果 (per-product):
  │     [{..., match_status, matched_product: {id, supplier_id, price, ...}}, ...]
  ├── match_statistics   ← 匹配统计: {total, matched, possible, not_matched, match_rate}
  ├── anomaly_data       ← 异常检测结果
  ├── financial_data     ← 财务分析结果
  ├── inquiry_data       ← 询价生成状态 (per-supplier):
  │     {suppliers: {sid: {status, template, missing_fields, file, ...}}}
  └── delivery_environment ← 交货环境 (潮汐+天气)
```

### 状态流
```
uploading → extracting → matching → ready
         → pending_template (需用户选模板)
         → error (任一步失败)

ready 后的履约: pending → inquiry_sent → quoted → confirmed
               → delivering → delivered → invoiced → paid
```

---

## 3. 当前 14 个 Tools

### Core (始终可见, 9 个)
| Tool | 读什么 | 写什么 |
|------|--------|--------|
| `manage_order` | Order (DB) | match_results, match_statistics |
| `query_db` | 任意表 (SELECT) | 无 |
| `get_db_schema` | information_schema | 无 |
| `think` | 无 | 无 (记录思考) |
| `modify_excel` | workspace 文件 | workspace 文件 |
| `calculate` | 无 | 无 |
| `ask_clarification` | 无 | HITL 暂停 |
| `request_confirmation` | 无 | HITL 暂停 |
| `use_skill` | ctx.skills | 无 (注入 prompt) |

### Deferred (按需激活, 5 个)
| Tool | 读什么 | 写什么 |
|------|--------|--------|
| `manage_inquiry` | Order.inquiry_data, SupplierTemplate | inquiry_data, 生成 Excel 到 workspace |
| `manage_fulfillment` | Order 履约字段 | fulfillment_status, delivery_data, attachments |
| `manage_upload` | ctx.file_bytes, UploadBatch | products 表, ProductChangeLog |
| `parse_upload` | ctx.file_bytes | UploadBatch, StagingProduct |
| `manage_todo` | ctx.todo_items | ctx.todo_items |
| `bash` | workspace 文件系统 | workspace 文件系统 |
| `search_product_database` | products 表 | 无 |

---

## 4. 当前 5 个 Skills

| Skill | 对应工具 | 核心步骤 |
|-------|---------|---------|
| `query-data` | query_db, get_db_schema | get_schema → write SQL → display |
| `generate-inquiry` | manage_inquiry | check → fill_gaps → generate |
| `data-upload` | parse_upload, manage_upload | parse → prepare → confirm → execute |
| `modify-inquiry` | modify_excel | 定位文件 → read → write → 确认 |
| `fulfillment` | manage_fulfillment | view → update → record_delivery → attach |

---

## 5. Agent 调用链路

```
POST /chat/sessions/{sid}/message (content + optional file)
  │
  ├── 文件处理: 存 Supabase + workspace
  ├── 消息存 DB (v2_agent_messages)
  ├── SSE queue 创建
  │
  └── 后台线程: _run_chat_agent()
        │
        ├── 创建 ToolContext (db, file_bytes, workspace_dir, user_id)
        ├── 加载 Skills (文件系统 + DB overlay)
        ├── 创建 ToolRegistry (14 tools, core + deferred)
        ├── 权限设置 (employee/admin/superadmin)
        ├── 中间件链 (11 个)
        ├── Scenario 检测 + Skill 注入
        │
        └── ReActAgent.run(message)
              │
              └── 循环 (max 25 轮):
                    LLM 调用 → 解析 tool_use → 执行 tool → 结果回 LLM
                    │
                    ├── 每轮: 推送 SSE 事件
                    ├── 每轮: 检查 compact 阈值
                    └── 完成: sync workspace → push "done"
```

---

## 6. Claude Code 的关键模式 (适用于我们的场景)

### 模式 1: 文件状态缓存 (FileStateCache)
- LRU 缓存记录 agent 读过哪些文件 + 时间戳
- 写文件前必须先读 (防止幻觉编辑)
- Compact 后选择性恢复最近 5 个文件

**我们的等价物**: `ctx.file_hashes` (MD5 校验) — 但只在 filesystem tools 中使用, 不在业务 tools 中使用。

### 模式 2: Read-Before-Write 契约
- FileWriteTool 验证 `readFileState.has(filePath)` 才允许写
- 时间戳校验防止并发冲突

**我们的等价物**: `edit_file` 要求先 `read_file` (MD5 校验), 但 `modify_excel` 没有此约束。

### 模式 3: 并发安全标记
- 每个 tool 声明 `isConcurrencySafe(input)`
- 读操作可并行, 写操作独占

**我们的等价物**: ThreadPoolExecutor 并行所有 tools, 无安全标记。

### 模式 4: 系统上下文注入
- `systemContext` 每轮刷新 (git status, cwd, 日期等)
- `userContext` 一次性加载 (CLAUDE.md, 用户配置)

**我们的等价物**: `_environment_layer()` 注入日期; WorkspaceStateMiddleware 注入文件列表。

### 模式 5: Task 追踪
- TaskCreate/Get/Update/List 工具让 Agent 跟踪多步骤进度
- 支持依赖关系 (blockedBy/blocks)

**我们的等价物**: `manage_todo` (简化版, 无依赖关系)。

### 模式 6: 大结果持久化
- Tool 结果 > 50KB 自动存盘, 返回引用 + 预览
- Compact 时清理旧结果

**我们的等价物**: tool_result 截断到 200 chars (engine.py), 无持久化。
