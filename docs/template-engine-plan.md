# 模板引擎方案 — 询价单 Excel 生成

## 背景

当前 Sub-Agent 用 LLM 生成 openpyxl 代码从零创建 Excel，无法可靠复现模板格式。
新方案：**复制模板 → 确定性填充**，AI 只负责理解数据，Excel 操作全部由代码完成。

## 整体架构（三步走）

```
Step 1: 模板分析 → template_config（语义层 + 样式层）
Step 2: 数据组装 → order_data.json（订单 + 供应商 + 配送 + 公司）
Step 3: 确定性生成 → TemplateEngine.fill()（复制模板 → 扩展行 → 填数据 → 调公式）
```

```
┌─────────────────────────────────────────────────────────┐
│                     设置中心 (Admin)                      │
│                                                          │
│  供应商模板管理 ──→ template_config (结构+样式)           │
│  供应商信息管理 ──→ suppliers (地址/支付方式)             │
│  仓库/配送点管理 ──→ delivery_locations (仓库/联系人)     │
│  公司信息管理   ──→ company_config (Merit Trading 信息)  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  生成询价单 (Runtime)                      │
│                                                           │
│  Step 1: AI 分析模板 → cell_map + styles → template_config│
│      ↓                                                    │
│  Step 2: 组装 order_data.json                             │
│      orders + suppliers + delivery_locations + company     │
│      ↓                                                    │
│  Step 3: TemplateEngine 确定性填充                        │
│      load_workbook → expand rows → fill data → save       │
└──────────────────────────────────────────────────────────┘
```

---

## Phase 0: 数据基础设施 ✅ 已完成

### 完成内容

| 项目 | 文件 | 状态 |
|------|------|------|
| DB 迁移 | `migrations/manual/022_extend_suppliers_and_locations.sql` | ✅ 已执行 |
| Supplier +5 字段 | `models.py` (address, zip_code, fax, payment_method, payment_terms) | ✅ |
| DeliveryLocation 模型 | `models.py` (v2_delivery_locations 表) | ✅ |
| CompanyConfig 模型 | `models.py` (v2_company_config 表, 7条初始数据) | ✅ |
| Pydantic Schemas | `schemas.py` (6 个新 schema) | ✅ |
| Backend API (8 endpoints) | `routes/settings.py` | ✅ |
| Frontend API 层 | `settings-api.ts` (types + functions) | ✅ |
| SupplierInfoTab | 搜索 + 表格 + 编辑对话框 | ✅ |
| DeliveryLocationTab | 卡片列表 + 创建/编辑/删除 | ✅ |
| CompanyConfigTab | 表单 + 批量保存 | ✅ |
| Settings page 注册 | 7 个 tab (原 4 + 新 3) | ✅ |

### API Endpoints

```
GET    /settings/suppliers                  → 供应商列表（含扩展字段，支持搜索）
PATCH  /settings/suppliers/{id}             → 更新供应商信息

GET    /settings/delivery-locations          → 配送点列表（可按 port_id 筛选）
POST   /settings/delivery-locations          → 创建配送点
PUT    /settings/delivery-locations/{id}     → 更新配送点
DELETE /settings/delivery-locations/{id}     → 删除配送点

GET    /settings/company-config              → 获取公司配置
PUT    /settings/company-config              → 批量更新公司配置
```

---

## Phase 1: 模板分析 + 样式提取 ✅ 已完成

### 完成内容

| 项目 | 文件 | 状态 |
|------|------|------|
| 样式提取模块 | `services/template_style_extractor.py` (新建) | ✅ |
| `extract_template_styles()` | 提取 cell_styles, merged_ranges, column_widths, row_heights | ✅ |
| `merge_semantic_and_styles()` | AI 语义层 + 代码样式层 → compact template_config | ✅ |
| 内容边界过滤 | 只提取有内容区域，避免空cell样式bloat | ✅ |
| Product row style | 产品区首行样式单独存储用于行克隆 | ✅ |
| 分析 API 集成 | `POST /supplier-templates/analyze` 返回 template_styles | ✅ |
| SupplierTemplate 字段 | `template_styles` JSON column (migration 022) | ✅ |

### 架构：两层分离

```
语义层 (AI) ──→ cell_map: {pos: {source_type, writable, data_from, field_key}}
                由 template_analysis_agent.py 的 Gemini JSON-mode 生成
                回答: "这个cell是什么？需要填什么？"

样式层 (Code) ─→ cell_styles: {pos: {font, fill, border, alignment, number_format}}
                由 template_style_extractor.py 的 openpyxl 提取
                回答: "这个cell长什么样？"

合并 ──────────→ template_config: {cells: {pos: {semantic + style}},
                                   merged_ranges, column_widths, row_heights,
                                   product_row_style}
```

### 验证结果（日本地区模板）

```
AI 分析: 12.5s, 42 semantic cells
样式提取: 0.3s, code-based
合并后: 54 cells compact, 25.7 KB (原始 2214 cells / 445 KB)
Product row style: 12 columns (A-L) 含 font/border/alignment
```

### 提取的样式维度

- **Font**: name, size, bold, italic, underline, color (RGB/theme/indexed)
- **Fill**: type (solid/pattern), fg_color, bg_color
- **Border**: left/right/top/bottom × (style, color)
- **Alignment**: horizontal, vertical, wrap_text, text_rotation
- **Number format**: `#,##0`, `YYYY/MM/DD` 等
- **Layout**: merged_ranges, column_widths, row_heights

---

## Phase 2: 数据组装 ✅ 已完成

### 完成内容

| 项目 | 文件 | 状态 |
|------|------|------|
| Supplier 完整信息 | `services/tools/inquiry.py` | ✅ |
| Company config 获取 | `services/tools/inquiry.py` | ✅ |
| Delivery location 获取 | `services/tools/inquiry.py` | ✅ |
| order_data.json 结构增强 | 新增 company / delivery_location / supplier_info | ✅ |

### order_data.json 完整结构

```json
{
  "order_id": 60,
  "po_number": "PO112240CCI",
  "ship_name": "CELEBRITY MILLENNIUM",
  "delivery_date": "28-Mar-2026",
  "order_date": "",
  "currency": "JPY",
  "destination_port": "",
  "delivery_address": "",
  "total_products": 50,

  "company": {
    "name": "株式会社メリットトレーディング",
    "zip_code": "〒900-0003",
    "address": "沖縄県那覇市安謝1-2-21 アーバンウエスト秋桜201",
    "tel": "098-917-2295",
    "fax": "098-917-2296",
    "email": "cruise.merit@gmail.com",
    "contact": "邢　080-4311-1145"
  },

  "delivery_location": {
    "name": "...",
    "address": "...",
    "contact_person": "...",
    "contact_phone": "...",
    "delivery_notes": "...",
    "ship_name_label": "..."
  },

  "suppliers": {
    "2": {
      "supplier_name": "株式会社　松武",
      "supplier_info": {
        "name": "株式会社　松武",
        "contact": "阿明",
        "email": "cruise.merit@gmail.com",
        "phone": "03-5492-3105",
        "fax": null,
        "address": null,
        "zip_code": null,
        "default_payment_method": null,
        "default_payment_terms": null
      },
      "product_count": 50,
      "products": [
        {
          "product_code": "99PRD010588",
          "product_name": "APPLE GRANNY SMITH US EXTRA FANCY 125CT/40LB",
          "product_name_jp": "",
          "quantity": 50.0,
          "unit": "CT",
          "unit_price": 8800.0,
          "pack_size": "",
          "currency": "JPY",
          "supplier_id": 2,
          "match_status": "matched"
        }
      ]
    }
  }
}
```

### 数据覆盖率

| 数据类型 | 字段 | 来源 | 状态 |
|----------|------|------|------|
| 订单 | po_number, ship_name, delivery_date, order_date, currency | order.order_metadata | ✅ 可用 |
| 公司 | name, zip_code, address, tel, fax, email, contact (7项) | v2_company_config | ✅ 已有数据 |
| 供应商 | name, contact, email, phone | suppliers 表 | ✅ 已有数据 |
| 供应商(扩展) | fax, address, zip_code, payment_method, payment_terms | suppliers 表 (新字段) | ⚠️ 待管理员填充 |
| 配送 | name, address, contact, phone, notes, ship_name_label | v2_delivery_locations | ⚠️ 待管理员创建 |
| 产品 | code, name, name_jp, quantity, unit, unit_price, pack_size | order.match_results | ✅ 可用 |

> ⚠️ 标记的字段结构和 API 已就绪，需管理员通过设置中心填入业务数据。

### field_key → 数据路径映射

```
order fields:     ship_name        → order_data.ship_name
                  delivery_date    → order_data.delivery_date
                  po_number        → order_data.po_number
                  currency         → order_data.currency

supplier fields:  supplier_name    → suppliers[sid].supplier_name
                  supplier_contact → suppliers[sid].supplier_info.contact
                  supplier_tel     → suppliers[sid].supplier_info.phone
                  supplier_fax     → suppliers[sid].supplier_info.fax
                  supplier_address → suppliers[sid].supplier_info.address

company fields:   company_name     → company.name
                  company_address  → company.address
                  company_tel      → company.tel
                  company_fax      → company.fax
                  company_email    → company.email
                  company_contact  → company.contact

delivery fields:  delivery_address → delivery_location.address
                  delivery_contact → delivery_location.contact_person
                  delivery_notes   → delivery_location.delivery_notes
```

---

## Phase 3: TemplateEngine 确定性填充 ← 下一步

### 核心逻辑

```python
class TemplateEngine:
    def fill(self, template_path, order_data, template_config, output_path) -> dict:
        """
        1. wb = load_workbook(template_path)  — 保留所有原始格式
        2. 计算行差: need = len(products), have = template_rows
           - need > have → insert_rows (openpyxl 自动调整公式引用+合并单元格)
           - need < have → delete_rows
        3. 从 product_row_style 复制样式到新插入的行
        4. field_positions → 填 header 字段 (order/supplier/company/delivery)
        5. product_table_config.columns → 逐行填产品数据
        6. formula_column_details → 写 per-row 公式 (如 =H{row}*J{row})
        7. 修正 SUM 范围 (如 =SUM(L22:L32) → =SUM(L22:L{last_row}))
        8. wb.save(output_path)
        9. 返回验证结果 {rows_written, formulas_updated, ...}
        """
```

### 数据流

```
template_config (from Phase 1)        order_data.json (from Phase 2)
├── cells[pos].field_key ──────────→  order_data[field_key] 的值
├── cells[pos].style ──────────────→  应用到新插入行
├── product_row_style ─────────────→  克隆到每个产品行
├── merged_ranges ─────────────────→  行扩展时自动调整
├── column_widths ─────────────────→  保持不变(模板自带)
└── product_table_config.columns ──→  逐列填产品字段
```

### 改动范围

| 文件 | 改动 |
|------|------|
| `services/excel_writer.py` | 新增 `TemplateEngine` 类 |
| `services/tools/inquiry.py` | 新增 `fill_template` 工具 |
| `skills/generate-inquiry/SKILL.md` | 重写为 fill_template 流程 |
| `sub_agents/excel_generator.py` | enabled_tools 加 fill_template，更新 prompt |

### 关键技术点

1. **openpyxl insert_rows**: 自动 shift 公式引用 + merged cell 范围
2. **样式克隆**: 从 product_row_style 复制 Font/Fill/Border/Alignment 到新行
3. **公式模板化**: `=H{row}*J{row}` 按行号参数化
4. **SUM 范围修正**: 检测 SUM(Lxx:Lyy) 类公式，更新 yy 为实际最后产品行
5. **空值处理**: field_key 对应值为 null 时跳过，不清空模板原值

### 验证方案

1. 聊天："帮我生成订单60的询价单"
2. Agent 调用 prepare_inquiry_workspace → order_data.json
3. Agent 调用 fill_template → 生成 Excel
4. 验证：
   - 格式与原模板一致（字体、颜色、边框、合并单元格）
   - 数据正确（公司名、供应商名、产品列表）
   - 公式有效（小计/税/合计自动计算）
   - 行数正确（产品数量 ≠ 模板默认行数时，正确扩展/收缩）

---

## 技术债务清理

### 本次清理（Phase 3 一起做）

| 债务 | 位置 | 处理 |
|------|------|------|
| SKILL.md 的"严禁 load_workbook"指令 | skills/generate-inquiry/SKILL.md | 重写为 fill_template 流程 |
| excel_generator.py "从零创建"提示 | sub_agents/excel_generator.py | 更新系统 prompt |
| layers.py 中硬编码的"询价单生成"prompt | services/agent/prompts/layers.py | 简化为调用 fill_template |

### 不触碰

| 项目 | 原因 |
|------|------|
| engine.py ReAct 循环 | 无需改动，天然支持多轮 |
| template_analysis_agent.py 核心逻辑 | 已验证准确，只加了样式提取集成 |
| v1 前端/后端 (admin-frontend/backend) | 不触碰 |

---

## 文件改动汇总

| 文件 | Phase | 状态 |
|------|-------|------|
| `migrations/manual/022_extend_suppliers_and_locations.sql` | 0 | ✅ 新建+执行 |
| `models.py` | 0 | ✅ +Supplier 5字段, +DeliveryLocation, +CompanyConfig |
| `schemas.py` | 0 | ✅ +6 新 schema |
| `routes/settings.py` | 0+1 | ✅ +8 API endpoints, +style extraction |
| `v2-frontend settings-api.ts` | 0 | ✅ +types + API functions |
| `v2-frontend settings/page.tsx` | 0 | ✅ +3 TabsTrigger |
| `v2-frontend SupplierInfoTab.tsx` | 0 | ✅ 新建 |
| `v2-frontend DeliveryLocationTab.tsx` | 0 | ✅ 新建 |
| `v2-frontend CompanyConfigTab.tsx` | 0 | ✅ 新建 |
| `services/template_style_extractor.py` | 1 | ✅ 新建 |
| `services/tools/inquiry.py` | 2 | ✅ prepare_inquiry_workspace 增强 |
| `services/excel_writer.py` | 3 | 🔲 +TemplateEngine 类 |
| `services/tools/inquiry.py` | 3 | 🔲 +fill_template 工具 |
| `skills/generate-inquiry/SKILL.md` | 3 | 🔲 重写 |
| `sub_agents/excel_generator.py` | 3 | 🔲 更新 prompt + tools |
