---
name: generate-inquiry
description: 为订单生成供应商询价单 Excel（检查就绪→补充字段→一键生成）
---

## 询价单生成流程

### Step 1: 确认订单和供应商

用 query_db 根据用户线索定位订单和供应商：
```sql
-- 查最近订单
SELECT id, order_metadata->>'po_number' as po, order_metadata->>'ship_name' as ship,
       product_count, created_at
FROM v2_orders WHERE status='ready' ORDER BY created_at DESC LIMIT 10

-- 查订单涉及的供应商
SELECT DISTINCT s.id, s.name, count(*) as product_count
FROM v2_orders o, jsonb_array_elements(o.match_results::jsonb) as mr, suppliers s
WHERE o.id=<order_id> AND s.id=(mr->'matched_product'->>'supplier_id')::int
GROUP BY s.id, s.name
```

### Step 2: 检查就绪状态

调用 `check_inquiry_readiness(order_id=X)` 获取各供应商的数据完整性报告。

返回结果包含：
- **ready**: 可以直接生成
- **needs_input**: 有 blocking 缺失字段需要补充
- **completed**: 已经生成过

### Step 3: 补充缺失字段（如需要）

如果 Step 2 报告有 blocking gaps，调用 `fill_inquiry_gaps`：
```
fill_inquiry_gaps(order_id=X, supplier_id=Y, field_values='{"H8": "2026/04/01", "B5": "SUPPLIER CO LTD"}')
```

字段值来源优先级：
1. 用户明确提供的值
2. 从订单元数据推断（delivery_date、ship_name 等）
3. 从供应商信息推断（name、email、phone 等）
4. 无法确定 → 询问用户

### Step 4: 生成询价单

```
generate_inquiries(order_id=X, supplier_id=Y)          -- 单个供应商
generate_inquiries(order_id=X)                          -- 全部供应商
generate_inquiries(order_id=X, supplier_id=Y, template_id=Z)  -- 指定模板
```

后端编排器自动完成：模板解析 → 数据填充 → 格式设置 → 文件上传 → 返回结果摘要。

### Step 5: 报告结果

告知用户：
- 生成了几个供应商的询价单
- 成功/失败数量
- 耗时
- 文件会自动显示下载卡片

## 规则
- **不需要手写 Excel 代码**，generate_inquiries 工具自动处理一切
- **不要用 bash + openpyxl 生成询价单**，这是旧方案
- 如需修改已生成的询价单，用 generate_inquiries 重新生成（传入 field_overrides）
- **严禁编造数据**，所有值来源于数据库或用户输入

$ARGUMENTS
