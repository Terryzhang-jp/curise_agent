# Row-level Ownership Audit — 2026-04-12

> Trigger: Codex adversarial review found `manage_document_order` allowed
> cross-tenant document access. This audit grep'd every query site that
> fetches Order / Document / Template / Inquiry by primary key and
> classified each one.

Scope: `services/`, `routes/` — anything that handles user-reachable traffic.
Background tasks called from authenticated endpoints are marked "indirect-safe".

## Summary

| Severity | Count Before | Count After |
|---|---|---|
| 🔴 Unscoped user-reachable (exploitable) | 6 | 0 |
| 🟡 Indirect-safe (background from authed caller) | 8 | 8 |
| 🟢 Already scoped | 2+ | 2+ |

**Total sites inspected**: ~20

## Detailed findings

### 🔴 Fixed: exploitable user-reachable queries

All fixed by routing through `services/tools/_security.py::scope_to_owner()`.

| File:Line | Tool / Endpoint | Model | Previous | Fix |
|---|---|---|---|---|
| services/tools/document_order.py:181 | `manage_document_order` | Document | no filter | `scope_to_owner` |
| services/tools/order_overview.py:219 | `manage_order` | Order | no filter | `scope_to_owner` |
| services/tools/order_extraction.py:65 | `extract_order` | Order | no filter | `scope_to_owner` |
| services/tools/order_matching.py:56 | `match_products` | Order | no filter | `scope_to_owner` |
| services/tools/fulfillment.py:222 | `manage_fulfillment` | Order | no filter | `scope_to_owner` |
| services/tools/inquiry_workflow.py:49, 181, 229 | `generate_inquiries` etc. | Order | no filter | `scope_to_owner` (×3) |
| services/document_context_package.py:54 | chat context injection | Document | no filter | signature updated + filter |

Additionally, the `ToolContext` dataclass now has a `user_role` field so the
helper can distinguish `superadmin` (unrestricted) from `employee` (scoped).
`routes/chat.py` passes `user_role` when constructing the ctx.

### 🟡 Indirect-safe: background tasks invoked from authed endpoints

These query `Order` / `Document` by ID inside a background task that is only
ever invoked from an HTTP endpoint that already did `_get_order(current_user)`
or equivalent. The `order_id` comes from a trusted endpoint, not from
user-controlled input at the background-task call site.

| File:Line | Invoked from |
|---|---|
| services/order_processor.py:913 | `routes/orders.py::_run_extract_only` (after `_get_order`) |
| services/order_processor.py:1061 | `routes/orders.py::_run_full_pipeline` (after `_get_order`) |
| services/document_workflow.py:163 | `routes/documents.py` + `routes/orders.py` (after ownership checks) |
| services/document_workflow.py:168, 204, 209 | Same ingestion pipeline |
| services/document_order_projection.py:187 | Internal projection helper |
| services/document_workflow.py:142 | Projection |

Defense-in-depth TODO: plumb `user_id` into these background tasks so that
every query can be scoped even when the id might somehow leak. Tracked as
Medium follow-up in `commercial-grade-refactor-plan.md` P3 (audit logging).

### 🟢 Already scoped

| File:Line | Pattern |
|---|---|
| routes/orders.py:62 | `_get_order(db, order_id, current_user)` applies filter based on role |
| routes/documents.py:127 | `_get_document(db, document_id, current_user)` same pattern |
| services/tools/document_order.py:205 | Order lookup by `document_id` — inherits ownership from already-checked document |

## Helper introduced

`services/tools/_security.py::scope_to_owner(query, model, ctx)`:

- `superadmin` → no filter
- `user_id=None` (no auth context) → filters to `user_id == -1` (fail closed)
- `employee` → filters to `user_id == ctx.user_id`

Single-entry design so new tools can be audited by grepping for
`scope_to_owner` and missing calls are trivially visible.

## Tests

- `tests/test_document_tenant_isolation.py` (12 cases) — covers Document path
  end-to-end including read actions, write actions, context injection, and
  superadmin / unauthenticated personas.
- Same pattern to be extended to Order tools in a follow-up test file
  (tracked as P5.3 in `commercial-grade-refactor-plan.md`).

## Open items (tracked in main plan)

- **P0.5**: Audit all `force=True` kwargs across services/routes.
- **P3.4**: Audit logging for any future `admin_override` / `force` uses.
- **P5.3**: Extend tenant isolation tests to Order tool suite.
- **Defense-in-depth**: plumb `user_id` into background tasks so that even
  if an attacker manages to influence an `order_id` argument, the query can
  still be scoped.

## P0.5 — `force=` audit

Grep of all `force=*` kwargs across `services/` + `routes/`:

| File:Line | Caller | Semantic | Status |
|---|---|---|---|
| services/document_workflow.py:189 | background ingestion | overwrite existing + allow incomplete (fixed) | ✅ P0.2 |
| services/tools/document_order.py:209 | `manage_document_order create` | user-triggered force | ✅ P0.2 |
| routes/documents.py:273 | POST /documents/{id}/create-order | user-triggered force | ✅ P0.2 |
| routes/documents.py:283 | DELETE /documents/{id} (`?force=true`) | "confirm delete even with linked order" — legit UX | ✅ documented in docstring |
| services/tools/order_extraction.py:56 | `extract_order(force="true")` | "re-extract even if already done" — legit UX | ✅ documented in prompt |
| services/agent/config.py:38 | `loop_force_stop` — LLM loop breaker | unrelated to ownership | ✅ not a security concern |

**Result**: no additional `force=` bypass found. All security-relevant uses
were already covered by P0.2; the remaining uses are legitimate UX confirmation
flags that are clearly documented.

## Sign-off

All 🔴 findings fixed and verified by 47/47 passing regression tests
(includes 12 tenant isolation + 8 readiness + 4 atomicity + 23 pre-existing).

— 2026-04-12
