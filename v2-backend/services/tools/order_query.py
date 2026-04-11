"""
Order query tools — get_db_schema + query_db for Agent-based data access.

Architecture (DeerFlow-aligned):
- get_db_schema: Reads LIVE schema from information_schema (single source of truth)
- query_db: Safe SQL execution with framework-level session protection
- No hardcoded schema — agent always sees what DB actually has
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text

from services.tools.registry_loader import ToolMetaInfo

logger = logging.getLogger(__name__)

TOOL_META = {
    "get_db_schema": ToolMetaInfo(
        display_name="数据库结构",
        group="business",
        description="获取数据库表结构信息",
        prompt_description="获取数据库表结构",
        summary="获取表结构",
    ),
    "query_db": ToolMetaInfo(
        display_name="数据库查询",
        group="business",
        description="执行只读 SQL 查询获取业务数据",
        prompt_description="执行只读 SQL 查询",
        summary="查询数据库",
    ),
}


def register(registry, ctx=None):
    """Auto-discovery compatible alias for create_order_query_tools."""
    create_order_query_tools(registry, ctx)


# ============================================================
# Table annotations — business context hints (NOT schema source)
# These are hints to help the agent understand the meaning of fields.
# Column names/types come from information_schema (live DB).
# ============================================================

_TABLE_HINTS: dict[str, str] = {
    "countries": "国家表。name=英文名, code=国家代码如JP/AU",
    "ports": "港口表。name 字段**可能是日文**（如「東京」「横浜 大さん橋」「神戸」），搜索时用 ILIKE 同时匹配中日英。country_id→countries",
    "products": "产品主数据。code=SKU, price=单价, supplier_id→suppliers, category_id→categories, effective_from/to=价格有效期",
    "suppliers": "供应商。name 可能是日文（如「株式会社　松武」）或英文。搜索时用 ILIKE 模糊匹配。country_id→countries",
    "categories": "产品分类。name=分类名如PRODUCE/DAIRY",
    "supplier_categories": "供应商-分类多对多关联表",
    "v2_orders": "订单表。order_metadata/products/match_results 是 **JSON 类型**（不是 JSONB）。"
                 "用 json_array_elements() 展开数组，用 ->>/-> 提取字段。"
                 "status: uploading/extracting/matching/ready/error。"
                 "fulfillment_status: pending/inquiry_sent/quoted/confirmed/delivering/delivered/invoiced/paid",
    "v2_upload_batches": "产品数据上传批次。status=staging/validating/completed/failed/rolled_back。与v2_orders不同",
    "v2_staging_products": "暂存产品行(上传中)。batch_id→v2_upload_batches",
    "v2_product_changelog": "产品变更审计日志。change_type=created/updated/rolled_back",
    "v2_supplier_templates": "供应商询价模板。template_name=模板名, supplier_id/supplier_ids=关联供应商, "
                             "template_file_url=模板文件, field_positions=字段位置映射, "
                             "product_table_config=产品表配置, template_styles=样式信息",
    "v2_order_format_templates": "订单格式模板。name=模板名, column_mapping=列映射, "
                                 "header_row/data_start_row=表头和数据起始行, source_company=来源公司",
    "v2_delivery_locations": "配送点/仓库。port_id→ports, name=地点名, address=地址, contact_person/phone=联系人",
    "v2_company_config": "公司配置（键值对）。key=配置键, value=配置值, label=显示标签",
}

# Tables to discover
_TABLES_TO_DISCOVER = [
    "countries", "ports", "products", "suppliers", "categories",
    "supplier_categories", "v2_orders", "v2_upload_batches",
    "v2_staging_products", "v2_product_changelog",
    "v2_supplier_templates", "v2_order_format_templates",
    "v2_delivery_locations", "v2_company_config",
]

# SQL keywords that indicate write operations
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)


# ============================================================
# SQL Auto-Correction Helpers
# ============================================================

def _get_real_tables(session) -> list[str]:
    """Get all public table names from DB."""
    result = session.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    ))
    return [r[0] for r in result.fetchall()]


def _extract_bad_table(error_str: str) -> str | None:
    """Extract non-existent table name from PostgreSQL error message."""
    # Pattern: relation "xxx" does not exist
    m = re.search(r'relation "([^"]+)" does not exist', error_str)
    return m.group(1) if m else None


def _extract_bad_column(error_str: str) -> str | None:
    """Extract non-existent column name from PostgreSQL error message."""
    m = re.search(r'column "([^"]+)" does not exist', error_str)
    return m.group(1) if m else None


def _guess_table_from_sql(sql: str) -> str | None:
    """Extract the first FROM table reference in SQL."""
    m = re.search(r'\bFROM\s+(\w+)', sql, re.IGNORECASE)
    return m.group(1) if m else None


def _fuzzy_match_table(bad_name: str, real_tables: list[str]) -> str | None:
    """Find the best matching real table for a non-existent table name.

    Strategy:
    1. Prefix preservation (v2_ matches v2_ tables first)
    2. Word overlap scoring
    3. Substring containment as tiebreaker
    """
    bad_has_v2 = bad_name.lower().startswith("v2_")
    bad_words = set(bad_name.lower().replace("v2_", "").split("_"))
    bad_words.discard("")
    # Add plural/singular variants for better matching
    bad_words_expanded = set(bad_words)
    for w in bad_words:
        if w.endswith("s"):
            bad_words_expanded.add(w[:-1])  # templates → template
        else:
            bad_words_expanded.add(w + "s")  # template → templates

    candidates: list[tuple[int, str]] = []

    for real in real_tables:
        real_has_v2 = real.lower().startswith("v2_")
        real_words = set(real.lower().replace("v2_", "").split("_"))
        real_words.discard("")

        # Word overlap (with singular/plural expansion)
        overlap = bad_words_expanded & real_words
        if not overlap:
            continue

        score = len(overlap) * 40

        # Bonus: same prefix family (v2_ matches v2_)
        if bad_has_v2 == real_has_v2:
            score += 20

        # Bonus: similar total word count (penalize very different lengths)
        len_diff = abs(len(bad_words) - len(real_words))
        score -= len_diff * 5

        candidates.append((score, real))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _safe_rollback(db):
    """Rollback DB session safely and ensure it's usable for subsequent queries.

    Supabase's connection pooler (port 6543) can leave sessions in
    'InFailedSqlTransaction' state after rollback(). We force-clear
    by executing a no-op query after rollback to confirm the session
    is healthy.
    """
    if db is None:
        return
    try:
        db.rollback()
    except Exception:
        pass
    # Force-clear: verify session is usable after rollback
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        # Last resort: try rollback again
        try:
            db.rollback()
        except Exception:
            pass


def _read_live_schema(db, table_name: str) -> str | None:
    """Read actual column info from information_schema.

    Uses an isolated DB session to avoid polluting the shared ctx.db,
    especially when called in parallel or when a previous query failed.
    """
    from core.database import SessionLocal
    schema_db = SessionLocal()
    try:
        result = schema_db.execute(text("""
            SELECT column_name, data_type, is_nullable,
                   column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = :tbl
            ORDER BY ordinal_position
        """), {"tbl": table_name})
        rows = result.fetchall()
        if not rows:
            return None

        lines = [f"### {table_name}"]

        # Add business hint if available
        hint = _TABLE_HINTS.get(table_name)
        if hint:
            lines.append(f"*{hint}*")

        for row in rows:
            col_name, data_type, nullable, default, max_len = row
            type_str = data_type.upper()
            if max_len:
                type_str = f"{type_str}({max_len})"
            extras = []
            if default and "nextval" in str(default):
                extras.append("PK")
            if nullable == "NO" and not extras:
                extras.append("NOT NULL")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"- {col_name} ({type_str}{extra_str})")

        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to read schema for %s: %s", table_name, e)
        return None
    finally:
        schema_db.close()


# ============================================================
# Tool Registration
# ============================================================

def create_order_query_tools(registry, ctx):
    """Register get_db_schema and query_db tools onto the registry."""

    @registry.tool(
        description="获取数据库表结构信息（从数据库实时读取，包含所有列名和类型）",
        parameters={
            "table_name": {
                "type": "STRING",
                "description": "可选：指定表名只查看该表。留空查看所有表。",
            },
        },
    )
    def get_db_schema(table_name: str = "") -> str:
        """Read LIVE schema from information_schema — single source of truth."""
        parts = ["## Database Schema\n"]

        if table_name:
            # Single table mode
            schema = _read_live_schema(ctx.db, table_name.strip())
            if schema:
                parts.append(schema)
            else:
                parts.append(f"表 '{table_name}' 不存在或无法访问。")
            return "\n".join(parts)

        # All tables mode
        available = []
        unavailable = []

        for tbl in _TABLES_TO_DISCOVER:
            schema = _read_live_schema(ctx.db, tbl)
            if schema:
                available.append(tbl)
                parts.append(schema)
            else:
                unavailable.append(tbl)

        if unavailable:
            parts.append(f"\n注意：以下表在当前数据库中不存在: {', '.join(unavailable)}")

        # Add JSON usage reminder (critical for preventing jsonb errors)
        parts.append("""
## JSON 字段提醒
v2_orders 的 products/match_results/order_metadata 列类型是 **JSON（不是 JSONB）**。
- 展开数组: `json_array_elements(match_results)` (不是 jsonb_array_elements)
- 提取字段: `mr->>'match_status'`, `mr->'matched_product'->>'supplier_id'`
- 如需 JSONB 函数: 先强转 `match_results::jsonb`
""")

        return "\n".join(parts)

    @registry.tool(
        description=(
            "执行只读 SQL 查询（仅允许 SELECT）。\n"
            "注意：如果你已经从其他工具（如 get_order_overview、check_inquiry_readiness）获得了所需信息，"
            "不要重复查询相同数据。只在需要新数据时使用。"
        ),
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

        # Use an ISOLATED DB session per query (DeerFlow: Sandbox pattern).
        from core.database import SessionLocal
        query_db_session = SessionLocal()
        try:
            return _execute_sql(query_db_session, sql)
        finally:
            query_db_session.close()

    def _execute_sql(session, sql: str, _retried: bool = False) -> str:
        """Execute SQL with auto-correction for non-existent tables/columns."""
        try:
            result = session.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            for row in rows:
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                    elif isinstance(v, (float, int, bool, str)) or v is None:
                        pass
                    else:
                        row[k] = str(v)

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
            err_str = str(e)
            err_lower = err_str.lower()
            session.rollback()

            # === Auto-correct: table name fuzzy matching ===
            # If a table doesn't exist, find the closest real table and retry
            if not _retried and "does not exist" in err_lower and "relation" in err_lower:
                bad_table = _extract_bad_table(err_str)
                if bad_table:
                    real_tables = _get_real_tables(session)
                    best_match = _fuzzy_match_table(bad_table, real_tables)
                    if best_match:
                        corrected_sql = re.sub(
                            r'\b' + re.escape(bad_table) + r'\b',
                            best_match,
                            sql,
                        )
                        logger.info("query_db auto-correct: %s → %s", bad_table, best_match)
                        return _execute_sql(session, corrected_sql, _retried=True)

            # === Auto-correct: column name ===
            # If column doesn't exist, show actual columns for that table
            if "does not exist" in err_lower and "column" in err_lower:
                bad_col = _extract_bad_column(err_str)
                table_hint = _guess_table_from_sql(sql)
                if table_hint:
                    try:
                        cols_result = session.execute(text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :tbl ORDER BY ordinal_position"
                        ), {"tbl": table_hint})
                        real_cols = [r[0] for r in cols_result.fetchall()]
                        if real_cols:
                            return (
                                f"Error: 列 '{bad_col}' 不存在。"
                                f"表 {table_hint} 的实际列: {', '.join(real_cols)}"
                            )
                    except Exception:
                        pass

            # Fallback: return error with available tables
            logger.warning("query_db SQL error: %s | SQL: %s", err_str[:200], sql[:200])
            error_msg = f"Error: SQL execution failed — {err_str}"
            try:
                tables = _get_real_tables(session)
                error_msg += f"\n\n可用的表: {', '.join(tables)}"
            except Exception:
                pass
            return error_msg
