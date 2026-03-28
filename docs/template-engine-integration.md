# Template Engine Integration — COMPLETED

## Goal
Replace LLM-based inquiry Excel generation with deterministic template engine.
- Before: Template + LLM mapping call (~5-15s per supplier)
- After: Template + zone config → deterministic fill (~0.5s per supplier, zero LLM)
- Fallback: No zone_config → existing LLM path (backward compat)

## Implementation Status

| Step | Status | Validation |
|------|--------|------------|
| 1. Zone Config Auto-Builder | DONE | Auto-detects zones, formulas, cross-refs from template |
| 2. Template Engine | DONE | 1707 round-trip checks passed (150 products) |
| 3. Inquiry Pipeline Integration | DONE | Fast path with auto-fallback to LLM |
| 4. Analyze Endpoint Integration | DONE | Zone config auto-generated on template upload |
| 5. Round-trip Quality Test | DONE | Full cell-by-cell verification |

## Files

| File | Action | Lines |
|------|--------|-------|
| `services/zone_config_builder.py` | NEW | ~300 |
| `services/template_engine.py` | NEW | ~330 |
| `services/inquiry_agent.py` | MODIFIED | +120 (engine path + order data builder) |
| `routes/settings.py` | MODIFIED | +15 (zone config in analyze endpoint) |
| `tests/test_template_engine.py` | NEW | ~150 (5 tests) |

## Architecture

```
Template Upload (settings.py)
  → AI analysis (template_analysis_agent.py)
  → Style extraction (template_style_extractor.py)
  → Zone config build (zone_config_builder.py)     ← NEW
  → Save to SupplierTemplate.template_styles

Inquiry Generation (inquiry_agent.py)
  → Template resolution
  → Check template_styles for zone_config
  → IF zone_config exists:
      → template_engine.fill_template()             ← NEW (0.5s, no LLM)
      → template_engine.verify_output()             ← NEW (round-trip check)
      → _save_workbook() (existing: upload + preview)
  → ELSE:
      → Existing LLM path (v6.2, ~5-15s)
```

## Key Design Decisions

1. **Zone-based config**: Template divided into explicit zones (product_data, summary).
   All formulas captured at config time → zero runtime inference.

2. **Auto cross-ref detection**: Code scans ALL cells outside managed zones for
   formula references inside → no manual `external_refs` maintenance.

3. **Graceful fallback**: If engine fails verification, falls back to LLM path.
   If no zone_config exists, uses LLM path. Zero breaking changes.

4. **Round-trip verification**: Generated Excel read back cell-by-cell against
   source data. Every header field, every product field, every formula checked.

5. **Reuses existing infrastructure**: Same `_save_workbook()` for Supabase upload,
   HTML preview, SSE events. Same API endpoints, same frontend.
