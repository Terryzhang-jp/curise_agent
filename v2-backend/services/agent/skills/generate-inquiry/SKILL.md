---
name: generate-inquiry
description: 为订单生成供应商询价单 Excel（检查就绪→补充字段→生成→修改）
---

## 前置准备

先激活询价工具（它们默认是隐藏的）：
```
tool_search("inquiry")
```
这会激活: check_inquiry_readiness, fill_inquiry_gaps, generate_inquiries

## 询价单生成流程

### Step 1: 确认订单和供应商

用 get_order_overview(order_id) 获取订单概览。
如果用户没给 order_id，用 query_db 搜索：
```sql
SELECT id, order_metadata->>'po_number' as po, order_metadata->>'ship_name' as ship,
       product_count, created_at
FROM v2_orders WHERE status='ready' ORDER BY created_at DESC LIMIT 10
```

查询模板（如果用户指定了模板名）：
```sql
SELECT id, template_name FROM v2_supplier_templates
WHERE template_name ILIKE '%关键词%' LIMIT 5
```

### Step 2: 检查就绪状态

调用 `check_inquiry_readiness(order_id)` — 返回每个供应商的状态：
- **ready**: 可以直接生成
- **needs_input**: 有缺失字段需要补充
- **completed**: 已经生成过（再次生成会覆盖）

### Step 3: 补充缺失字段（如有）

如果 Step 2 有 blocking gaps：
```
fill_inquiry_gaps(order_id, supplier_id, field_values='{"H8": "2026/04/01"}')
```

### Step 4: 生成询价单

```
generate_inquiries(order_id, supplier_id, template_id)
```
- supplier_id: 指定供应商，留空=全部
- template_id: 指定模板，留空=自动匹配

生成后文件自动保存到工作目录，会显示下载卡片。

### Step 5: 后续修改（如用户要求改税率、日期等）

**直接用 modify_excel**，不需要重新查数据库：
```
modify_excel(filename="inquiry_xxx.xlsx", action="read", cells='["L34", "H8"]')
modify_excel(filename="inquiry_xxx.xlsx", action="write", cells='{"L34": "=L33*0.10", "H8": "31-Mar-2026"}')
```

## 规则
- **不需要手写 Excel 代码**，generate_inquiries 自动处理一切
- 修改已生成文件用 **modify_excel**，不用 bash
- JSON 字段用 **json_array_elements**（不是 jsonb_array_elements）
- **严禁编造数据**，所有值来源于数据库或用户输入

$ARGUMENTS
