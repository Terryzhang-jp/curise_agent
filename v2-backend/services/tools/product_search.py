"""Product search tool — search products database by keyword."""

from __future__ import annotations

import json

from sqlalchemy import text

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "search_product_database": ToolMetaInfo(
        display_name="产品搜索",
        group="business",
        description="按关键词搜索产品数据库",
        prompt_description="按关键词搜索产品数据库",
        summary="搜索产品数据库",
        is_enabled_default=True,
        auto_register=True,
    ),
}


def register(registry, ctx=None):
    """Register product search tool."""

    @registry.tool(
        description="按关键词搜索产品数据库，返回匹配的产品列表（品名、代码、价格、供应商等）",
        parameters={
            "keyword": {
                "type": "STRING",
                "description": "搜索关键词（产品名、代码、品牌等）",
            },
            "limit": {
                "type": "NUMBER",
                "description": "返回数量上限（默认 20）",
                "required": False,
            },
        },
        group="business",
    )
    def search_product_database(keyword: str = "", limit: int = 20) -> str:
        if not keyword.strip():
            return "Error: 请提供搜索关键词"
        limit = min(int(limit), 50)
        kw = f"%{keyword.strip()}%"
        try:
            sql = text("""
                SELECT id, product_name_en, product_name_jp, code, brand,
                       unit, price, currency, pack_size, country_of_origin
                FROM products
                WHERE product_name_en ILIKE :kw
                   OR product_name_jp ILIKE :kw
                   OR code ILIKE :kw
                   OR brand ILIKE :kw
                ORDER BY product_name_en
                LIMIT :lim
            """)
            rows = ctx.db.execute(sql, {"kw": kw, "lim": limit}).fetchall()
            columns = ["id", "product_name_en", "product_name_jp", "code", "brand",
                        "unit", "price", "currency", "pack_size", "country_of_origin"]
            results = []
            for row in rows:
                d = dict(zip(columns, row))
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                    elif not isinstance(v, (float, int, bool, str)) and v is not None:
                        d[k] = str(v)
                results.append(d)
            return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False, default=str)
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 产品搜索失败 — {str(e)}"
