---
name: query-data
description: 查询业务数据（产品、订单、供应商等），SQL 分析 + 报告生成
---

## 查询流程

### Step 1: 了解表结构
先调用 `get_db_schema()` 获取实际列名（从数据库实时读取，100% 准确）。

### Step 2: 编写 SQL
- 每条 SQL 只做一件事。复杂分析拆成多条简单 SQL
- 先用 LIMIT 5 测试，确认无误后去掉 LIMIT

### Step 3: 展示结果
- 查询结果用 **markdown 表格**格式展示
- 数值保留合理精度，价格保留 2 位小数
- 结果太多只展示关键信息并说明总数

## JSON 字段使用指南

v2_orders 的 products/match_results/order_metadata 列类型是 **JSON（不是 JSONB）**：
```sql
-- ✅ 正确
SELECT json_array_elements(match_results) AS item FROM v2_orders WHERE id = 60

-- ✅ 需要 JSONB 函数时先强转
SELECT * FROM v2_orders, jsonb_array_elements(match_results::jsonb) AS mr WHERE ...

-- ❌ 错误（会报 function does not exist）
SELECT jsonb_array_elements(match_results) ...

-- ✅ 提取嵌套字段
SELECT mr->>'match_status', mr->'matched_product'->>'supplier_id'
FROM v2_orders, json_array_elements(match_results) AS mr WHERE id = 60
```

## SQL 错误恢复
遇到报错时：
1. 用 think 分析原因（类型不匹配？列名错误？）
2. **不要用相同的 SQL 重试** — 必须修改出错部分
3. 如果表名报错，错误信息会自动附带可用表名列表

$ARGUMENTS
