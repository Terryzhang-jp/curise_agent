---
name: query-data
description: 查询业务数据（产品、订单、供应商等），SQL + 数据分析
---

## 数据查询指南

### 重要数据表
- **v2_orders**: 上传的订单（order_metadata, products, match_results 是 JSON 字段）
- **products**: 产品主数据库（品名、价格、供应商、国家、港口等）
- **countries / ports**: 国家和港口
- **suppliers**: 供应商
- **categories**: 产品分类
- **v2_upload_batches**: 产品数据上传批次
- **v2_staging_products**: 暂存产品行
- **v2_product_changelog**: 产品变更日志

### 查询规则
- 先用 `get_db_schema` 了解表结构，再用 `query_db` 查询
- 只允许 SELECT 查询，不能修改数据
- v2_orders 中 JSON 字段使用 PostgreSQL JSON 操作符查询
- 查询结果务必用 **markdown 表格**格式展示
- 编写 SQL 时仔细分析用户意图：
  - 「按X统计」→ GROUP BY
  - 「不同X的Y」→ GROUP BY 或 ROW_NUMBER() OVER (PARTITION BY ...)
  - 不要误用 ORDER BY + LIMIT 替代分组
- 表格中数值字段保留合理精度，价格保留2位小数
- 结果太多只展示关键信息并说明总数

$ARGUMENTS
