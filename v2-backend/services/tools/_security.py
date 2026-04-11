"""Shared row-level ownership helper for chat-reachable tools.

Context: 2026-04-12 P0 audit found every tool that queried Order / Document
by primary key with no tenant filter. Any employee could read or mutate
other tenants' data by guessing the id.

This helper centralizes the fix so:

  1. Every tool uses the same filter (easy to audit)
  2. Adding a new protected model only touches one place
  3. Tests can exercise the behavior once and trust it everywhere

Usage
=====

    from services.tools._security import scope_to_owner

    def some_tool(..., order_id: int):
        from models import Order
        query = ctx.db.query(Order).filter(Order.id == order_id)
        query = scope_to_owner(query, Order, ctx)
        order = query.first()
        if not order:
            return "Error: 订单不存在"   # intentional: same message whether
                                          # it doesn't exist or belongs to someone else

Design decisions
================

  - **Return 'not found' on permission denial** to avoid existence-leaks.
    An attacker probing ids should get the same response for "doesn't exist"
    and "exists but yours".

  - **superadmin bypasses the filter entirely** — they own all tenants by
    definition.

  - **Missing ctx.user_id fails closed** (query filtered to an impossible
    user) so the tool never returns data when auth context is missing.
"""
from __future__ import annotations

from typing import Any


# Models that the audit identified as needing row-level ownership checks.
# Extend this set whenever a new model gets a user_id column that represents
# tenant ownership.
_OWNED_BY_USER_ID = ("Order", "Document", "Inquiry")


def scope_to_owner(query, model, ctx) -> Any:
    """Filter a SQLAlchemy query so it only returns rows owned by ctx.user_id.

    Args:
        query: An existing SQLAlchemy query (typically `db.query(Model).filter(...)`).
        model: The model class. Must have a `user_id` column.
        ctx: ToolContext with `user_id` and `user_role` attributes.

    Returns:
        The same query, narrowed by `model.user_id == ctx.user_id`, UNLESS
        ctx.user_role is "superadmin" in which case the query is returned
        unchanged.

        If ctx.user_id is None (missing auth context), the query is filtered
        to `model.user_id == -1` (a row that cannot exist) so the tool
        returns no results rather than leaking data.
    """
    user_role = getattr(ctx, "user_role", "employee")
    if user_role == "superadmin":
        return query

    user_id = getattr(ctx, "user_id", None)
    if user_id is None:
        # Fail closed: no auth context → no results
        return query.filter(model.user_id == -1)

    return query.filter(model.user_id == user_id)


def owner_filter_kwargs(ctx) -> dict:
    """Return filter_by-compatible kwargs for owner scoping.

    Useful when you can't chain .filter() (e.g. using filter_by). For
    superadmin returns empty dict (no filter). For missing user_id returns
    `{"user_id": -1}` (fail closed).
    """
    user_role = getattr(ctx, "user_role", "employee")
    if user_role == "superadmin":
        return {}
    user_id = getattr(ctx, "user_id", None)
    if user_id is None:
        return {"user_id": -1}
    return {"user_id": user_id}
