"""
Phase 3: PRODUCT_MATCHING tools.

Tools for matching digitized order products against the database.
Two-tier matching: exact code match + fuzzy name similarity.
"""

from __future__ import annotations

import logging
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _persist_session_data(ctx):
    """Write ctx.session_data back to PipelineSession.phase_results."""
    if ctx.db and ctx.pipeline_session_id:
        from models import PipelineSession
        session = ctx.db.query(PipelineSession).filter(
            PipelineSession.id == ctx.pipeline_session_id
        ).first()
        if session:
            session.phase_results = dict(ctx.session_data)
            session.updated_at = datetime.utcnow()
            ctx.db.flush()


def _match_products_against_db(products, db, country_id=None, port_id=None, delivery_date=None):
    """Core matching logic."""
    from models import ProductReadOnly
    from sqlalchemy import or_

    query = db.query(ProductReadOnly).filter(ProductReadOnly.status == True)
    if country_id:
        query = query.filter(ProductReadOnly.country_id == country_id)
    if port_id:
        query = query.filter(ProductReadOnly.port_id == port_id)
    if delivery_date:
        query = query.filter(
            or_(ProductReadOnly.effective_from.is_(None),
                ProductReadOnly.effective_from <= delivery_date)
        ).filter(
            or_(ProductReadOnly.effective_to.is_(None),
                ProductReadOnly.effective_to >= delivery_date)
        )

    db_products = query.all()
    results = []

    for product in products:
        item_code = (product.get("product_code") or "").strip()
        product_name = (product.get("product_name") or "").strip()

        best_match = None
        best_score = 0.0
        best_reason = ""

        for dbp in db_products:
            # Tier 1: exact code match
            if item_code and dbp.code and item_code.upper() == dbp.code.upper():
                score = 1.0
                reason = "产品代码完全匹配"
                if score > best_score:
                    best_score = score
                    best_match = dbp
                    best_reason = reason
                continue

            # Tier 2: name similarity
            similarities = []
            if dbp.product_name_en and product_name:
                sim = SequenceMatcher(None, product_name.upper(), dbp.product_name_en.upper()).ratio()
                similarities.append(sim)
            if dbp.product_name_jp and product_name:
                sim = SequenceMatcher(None, product_name.upper(), dbp.product_name_jp.upper()).ratio()
                similarities.append(sim)

            name_sim = max(similarities) if similarities else 0.0
            geo_score = 0.0
            if country_id and dbp.country_id == country_id:
                geo_score += 0.7
            if port_id and dbp.port_id == port_id:
                geo_score += 0.3

            score = name_sim * 0.7 + geo_score * 0.3
            reason = f"名称相似度 {name_sim:.2f}, 地理匹配 {geo_score:.2f}"

            if score > best_score:
                best_score = score
                best_match = dbp
                best_reason = reason

        # Determine status
        if best_score >= 0.9:
            status = "matched"
        elif best_score >= 0.7:
            status = "possible_match"
        else:
            status = "not_matched"

        match_result = {
            "product_code": item_code,
            "product_name": product_name,
            "quantity": product.get("quantity"),
            "unit": product.get("unit"),
            "unit_price": product.get("unit_price"),
            "match_status": status,
            "match_score": round(best_score, 3),
            "match_reason": best_reason,
        }

        if best_match and best_score >= 0.7:
            match_result["matched_product"] = {
                "id": best_match.id,
                "code": best_match.code,
                "product_name_en": best_match.product_name_en,
                "product_name_jp": best_match.product_name_jp,
                "price": float(best_match.price) if best_match.price else None,
                "currency": best_match.currency,
                "supplier_id": best_match.supplier_id,
                "category_id": best_match.category_id,
                "pack_size": best_match.pack_size,
                "unit": best_match.unit,
            }

        results.append(match_result)

    return results


def create_matching_tools(registry, ctx):

    @registry.tool(
        description="将订单产品与数据库产品进行自动匹配（两层匹配：精确代码+模糊名称）。可以不传任何参数直接调用。",
        parameters={
            "country_id": {"type": "INTEGER", "description": "可选 - 国家ID，用于地理过滤，不知道就不传", "required": False},
            "port_id": {"type": "INTEGER", "description": "可选 - 港口ID，用于地理过滤，不知道就不传", "required": False},
        },
        group="pipeline",
    )
    def match_products(country_id: str = "", port_id: str = "") -> str:
        try:
            phase2 = ctx.session_data.get("ORDER_DIGITIZATION", {})
            products = phase2.get("products", [])

            if not products:
                return "Error: 没有产品数据可匹配"

            # Parse optional IDs
            cid = int(country_id) if country_id and str(country_id).isdigit() else None
            pid = int(port_id) if port_id and str(port_id).isdigit() else None

            results = _match_products_against_db(products, ctx.db, cid, pid)

            matched = sum(1 for r in results if r["match_status"] == "matched")
            possible = sum(1 for r in results if r["match_status"] == "possible_match")
            unmatched = sum(1 for r in results if r["match_status"] == "not_matched")

            summary = (
                f"产品匹配完成: {len(results)} 个产品, "
                f"匹配 {matched}, 可能匹配 {possible}, 未匹配 {unmatched}"
            )

            result_data = {
                "match_results": results,
                "statistics": {
                    "total": len(results),
                    "matched": matched,
                    "possible_match": possible,
                    "not_matched": unmatched,
                    "match_rate": round(matched / len(results) * 100, 1) if results else 0,
                },
            }

            ctx.session_data["PRODUCT_MATCHING"] = result_data
            ctx.current_phase = "PRODUCT_MATCHING"
            _persist_session_data(ctx)

            return summary

        except Exception as e:
            logger.error("Product matching failed: %s", str(e), exc_info=True)
            return f"Error: 产品匹配失败: {str(e)}"

    @registry.tool(
        description="展示匹配结果摘要给用户",
        parameters={},
        group="pipeline",
    )
    def show_match_results() -> str:
        match_data = ctx.session_data.get("PRODUCT_MATCHING", {})
        results = match_data.get("match_results", [])
        stats = match_data.get("statistics", {})

        if not results:
            return "Error: 没有匹配结果可展示"

        lines = [
            f"匹配结果: {stats.get('total', 0)} 个产品",
            f"  已匹配: {stats.get('matched', 0)}",
            f"  可能匹配: {stats.get('possible_match', 0)}",
            f"  未匹配: {stats.get('not_matched', 0)}",
            f"  匹配率: {stats.get('match_rate', 0)}%",
            "",
        ]

        unmatched = [r for r in results if r["match_status"] == "not_matched"]
        if unmatched:
            lines.append("未匹配产品:")
            for r in unmatched[:10]:
                lines.append(f"  - {r['product_name']} (代码: {r.get('product_code', 'N/A')})")

        return "\n".join(lines)

    @registry.tool(
        description="通过关键词搜索产品数据库",
        parameters={
            "keyword": {"type": "STRING", "description": "搜索关键词"},
        },
        group="pipeline",
    )
    def search_product_database(keyword: str = "") -> str:
        if not keyword:
            return "Error: 请提供搜索关键词"

        from models import ProductReadOnly

        results = (
            ctx.db.query(ProductReadOnly)
            .filter(
                ProductReadOnly.status == True,
                (
                    ProductReadOnly.product_name_en.ilike(f"%{keyword}%")
                    | ProductReadOnly.code.ilike(f"%{keyword}%")
                    | ProductReadOnly.product_name_jp.ilike(f"%{keyword}%")
                ),
            )
            .limit(20)
            .all()
        )

        if not results:
            return f"未找到包含 '{keyword}' 的产品"

        lines = [f"找到 {len(results)} 个匹配 '{keyword}' 的产品:"]
        for p in results:
            price_str = f"${float(p.price):.2f}" if p.price else "N/A"
            lines.append(f"  - [{p.code or 'N/A'}] {p.product_name_en} | {price_str} | 供应商#{p.supplier_id}")

        return "\n".join(lines)
