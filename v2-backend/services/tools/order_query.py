"""
Order query tools — get_db_schema + query_db for Agent-based order matching.

Uses the closure pattern: create_order_query_tools(registry, ctx).
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Known schema descriptions for tables the agent might need
_TABLE_SCHEMAS = {
    "countries": """### countries
- id (INTEGER, PK)
- name (VARCHAR) — 国家名称（英文），如 "Japan", "Australia"
- name_jp (VARCHAR) — 日文名
- code (VARCHAR) — 国家代码，如 "JP", "AU"
""",
    "ports": """### ports
- id (INTEGER, PK)
- name (VARCHAR) — 港口名称（英文），如 "Kobe", "Sydney"
- name_jp (VARCHAR) — 日文名
- country_id (INTEGER, FK → countries.id)
- code (VARCHAR) — 港口代码
""",
    "products": """### products
- id (INTEGER, PK)
- product_name_en (VARCHAR) — 英文品名
- product_name_jp (VARCHAR) — 日文品名
- code (VARCHAR) — 产品代码/SKU
- country_id (INTEGER) — 国家ID
- port_id (INTEGER) — 港口ID
- category_id (INTEGER) — 分类ID
- supplier_id (INTEGER) — 供应商ID
- unit (VARCHAR) — 单位，如 "KG", "EA", "CS"
- price (NUMERIC) — 单价
- currency (VARCHAR) — 货币，如 "JPY", "AUD", "USD"
- unit_size (VARCHAR) — 单位规格
- pack_size (VARCHAR) — 包装规格
- brand (VARCHAR)
- country_of_origin (VARCHAR)
- effective_from (DATETIME) — 价格生效日期
- effective_to (DATETIME) — 价格失效日期
- status (BOOLEAN) — true=有效
""",
    "suppliers": """### suppliers
- id (INTEGER, PK)
- name (VARCHAR) — 供应商名称
- email (VARCHAR)
- phone (VARCHAR)
- country_id (INTEGER)
""",
    "categories": """### categories
- id (INTEGER, PK)
- name (VARCHAR) — 分类名称，如 "Fresh Produce", "Dairy"
- parent_id (INTEGER, nullable)
""",
    "supplier_categories": """### supplier_categories (多对多关联)
- id (INTEGER, PK)
- supplier_id (INTEGER)
- category_id (INTEGER)
""",
    "v2_orders": """### v2_orders (上传的订单)
- id (INTEGER, PK)
- user_id (INTEGER) — 上传用户
- filename (VARCHAR) — 原始文件名
- file_type (VARCHAR) — "pdf" 或 "excel"
- status (VARCHAR) — uploading / extracting / matching / ready / error
- processing_error (TEXT) — 处理失败原因
- country_id (INTEGER) — 订单对应国家
- port_id (INTEGER) — 订单对应港口
- delivery_date (VARCHAR) — 交货日期
- extraction_data (JSON) — AI提取的原始数据（full_text等）
- order_metadata (JSON) — 订单元数据（PO号、客户名等）
- products (JSON) — 产品列表，每个产品含 product_name, quantity, unit_price, amount 等
- product_count (INTEGER) — 产品数量
- total_amount (NUMERIC) — 订单总金额
- match_results (JSON) — 产品匹配结果，每项含 status(matched/possible_match/not_matched), matched_product_id, confidence 等
- match_statistics (JSON) — 匹配统计 {matched, possible_match, not_matched, total}
- anomaly_data (JSON) — 异常检测结果
- inquiry_data (JSON) — 询价单生成数据
- is_reviewed (BOOLEAN) — 是否已审核
- created_at (DATETIME)
- updated_at (DATETIME)
- processed_at (DATETIME)

注意: products/match_results/order_metadata 等是 JSON 字段。
用 PostgreSQL JSON 操作符查询: products::text, order_metadata->>'po_number', jsonb_array_length(products) 等。
""",
    "v2_upload_batches": """### v2_upload_batches (产品数据上传批次)
- id (INTEGER, PK)
- session_id (VARCHAR) — 关联的聊天会话ID
- user_id (INTEGER) — 上传用户
- file_name (VARCHAR) — 上传的文件名
- file_hash (VARCHAR) — 文件哈希（去重）
- status (VARCHAR) — staging / validating / previewing / executing / completed / failed / rolled_back
- supplier_id (INTEGER) — 关联供应商
- supplier_name (VARCHAR) — 供应商名称
- country_id (INTEGER) — 关联国家
- country_name (VARCHAR) — 国家名称
- column_mapping (JSON) — 列映射关系
- summary (JSON) — 执行结果摘要（inserted/updated/skipped/failed 等）
- created_at (DATETIME)
- completed_at (DATETIME)

注意: 这是产品数据导入的批次表，与 v2_orders（订单上传）不同。
查今日上传: SELECT * FROM v2_upload_batches WHERE created_at >= CURRENT_DATE ORDER BY created_at DESC
""",
    "v2_staging_products": """### v2_staging_products (暂存产品行)
- id (INTEGER, PK)
- batch_id (INTEGER, FK → v2_upload_batches.id) — 所属批次
- row_number (INTEGER) — 原始文件行号
- raw_data (JSON) — 原始行数据
- product_name (VARCHAR) — 产品名称
- product_code (VARCHAR) — 产品代码
- price (NUMERIC) — 价格
- unit (VARCHAR) — 单位
- pack_size (VARCHAR) — 包装规格
- brand (VARCHAR) — 品牌
- currency (VARCHAR) — 货币
- country_of_origin (VARCHAR) — 原产国
- validation_status (VARCHAR) — pending / valid / invalid / quarantined
- validation_errors (JSON) — 验证错误
- match_result (JSON) — 匹配结果（含 action, confidence, db_product_id, price_change_pct 等）
- resolved_supplier_id (INTEGER)
- resolved_country_id (INTEGER)
""",
    "v2_product_changelog": """### v2_product_changelog (产品变更日志)
- id (INTEGER, PK)
- product_id (INTEGER) — 被变更的产品ID
- batch_id (INTEGER, FK → v2_upload_batches.id) — 来源批次
- change_type (VARCHAR) — created / updated / rolled_back
- field_changes (JSON) — 字段级变更详情 {"field": {"old": x, "new": y}}
- created_at (DATETIME)

查某批次的变更: SELECT * FROM v2_product_changelog WHERE batch_id = ?
查某产品的变更历史: SELECT * FROM v2_product_changelog WHERE product_id = ? ORDER BY created_at
""",
}

_QUERY_HINTS = """
## 常用查询模式
- 按国家+港口筛选产品: SELECT * FROM products WHERE country_id = ? AND port_id = ?
- 按代码精确匹配: SELECT * FROM products WHERE code = ?
- 按名称模糊搜索: SELECT * FROM products WHERE product_name_en ILIKE '%keyword%'
- 查国家: SELECT * FROM countries WHERE name ILIKE '%japan%' OR code = 'JP'
- 查港口: SELECT * FROM ports WHERE country_id = ? AND (name ILIKE '%kobe%' OR code = ?)
- 查订单列表: SELECT id, filename, status, product_count, total_amount, created_at FROM v2_orders ORDER BY created_at DESC
- 查订单产品: SELECT id, filename, products FROM v2_orders WHERE id = ?
- 查订单匹配结果: SELECT id, filename, match_results, match_statistics FROM v2_orders WHERE id = ?
- 查订单元数据: SELECT id, filename, order_metadata FROM v2_orders WHERE id = ?
- 按状态筛选订单: SELECT id, filename, status, created_at FROM v2_orders WHERE status = 'ready'
- 订单产品数量统计: SELECT id, filename, product_count, jsonb_array_length(products) FROM v2_orders
- 查上传批次: SELECT id, file_name, status, supplier_name, country_name, created_at FROM v2_upload_batches ORDER BY created_at DESC
- 查今日上传: SELECT id, file_name, status, supplier_name, summary, created_at FROM v2_upload_batches WHERE created_at >= CURRENT_DATE
- 查批次变更日志: SELECT cl.*, p.product_name_en FROM v2_product_changelog cl JOIN products p ON cl.product_id = p.id WHERE cl.batch_id = ?
"""

# SQL keywords that indicate write operations
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)

# Tables to probe for availability
_TABLES_TO_CHECK = ["countries", "ports", "products", "suppliers", "categories", "supplier_categories", "v2_orders", "v2_upload_batches", "v2_staging_products", "v2_product_changelog"]


def create_order_query_tools(registry, ctx):
    """Register get_db_schema and query_db tools onto the registry."""

    @registry.tool(
        description="获取数据库表结构信息（订单、产品、国家、港口、供应商等表的字段和关系）",
        parameters={},
    )
    def get_db_schema() -> str:
        """Dynamically discover available tables and return their schema."""
        parts = ["## Database Schema\n"]
        available = []
        unavailable = []

        for table in _TABLES_TO_CHECK:
            try:
                ctx.db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                available.append(table)
                if table in _TABLE_SCHEMAS:
                    parts.append(_TABLE_SCHEMAS[table])
            except Exception:
                ctx.db.rollback()
                unavailable.append(table)

        if unavailable:
            parts.append(f"\n注意：以下表在当前数据库中不存在: {', '.join(unavailable)}")
            parts.append("产品匹配只能使用 products 表中的信息（country_id/port_id 为数字ID）。\n")

        parts.append(_QUERY_HINTS)
        return "\n".join(parts)

    @registry.tool(
        description="执行只读 SQL 查询数据库（仅允许 SELECT）。用于查询 v2_orders/products/countries/ports/suppliers 等表。",
        parameters={
            "sql": {
                "type": "STRING",
                "description": "要执行的 SELECT SQL 语句",
            },
        },
    )
    def query_db(sql: str = "") -> str:
        if not sql or not sql.strip():
            return "Error: SQL query is empty"

        sql = sql.strip().rstrip(";")

        # Safety check: block write operations
        if _FORBIDDEN_PATTERN.search(sql):
            return "Error: Only SELECT queries are allowed. INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE are forbidden."

        # Auto-append LIMIT if missing
        if not _LIMIT_PATTERN.search(sql):
            sql = sql + " LIMIT 100"

        try:
            result = ctx.db.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # Serialize values (handle Decimal, datetime, etc.)
            for row in rows:
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                    elif isinstance(v, (float, int, bool, str)) or v is None:
                        pass
                    else:
                        row[k] = str(v)

            # Truncate if too many rows
            total = len(rows)
            if total > 50:
                rows = rows[:50]
                return json.dumps(
                    {"columns": columns, "rows": rows, "total": total, "truncated": True},
                    ensure_ascii=False, default=str,
                )

            return json.dumps(
                {"columns": columns, "rows": rows, "total": total},
                ensure_ascii=False, default=str,
            )
        except Exception as e:
            # Rollback to clear the failed transaction state so subsequent queries work
            ctx.db.rollback()
            logger.warning("query_db SQL error: %s | SQL: %s", str(e), sql[:200])
            return f"Error: SQL execution failed — {str(e)}"
