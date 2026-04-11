"""Tests for ZoneConfigV1 Pydantic schema.

Two goals:
1. **Compatibility**: every production zone_config (saved as fixture) must
   parse cleanly. If it doesn't, the schema is wrong.
2. **Strictness**: malformed inputs must be rejected with clear errors.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.templates.zone_config_schema import (
    ZoneConfigV1,
    ZoneConfigValidationError,
    is_valid_zone_config,
    parse_zone_config,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "templates"
PRODUCTION_TEMPLATE_IDS = [11, 12, 13]


# ──────────────────────────────────────────────────────────────────────
# Compatibility tests — every production template must parse
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("template_id", PRODUCTION_TEMPLATE_IDS)
def test_production_zone_config_parses(template_id: int):
    """All real production templates must successfully parse against the schema."""
    raw = json.loads((FIXTURE_DIR / f"template_{template_id}_zone_config.json").read_text())
    config = parse_zone_config(raw)
    assert isinstance(config, ZoneConfigV1)
    # Sanity: zones must always be present and well-formed
    assert config.zones.product_data.start >= 1
    assert config.zones.summary.start >= config.zones.product_data.end


def test_all_production_templates_pass_is_valid():
    """The boolean check should agree with parse_zone_config."""
    for template_id in PRODUCTION_TEMPLATE_IDS:
        raw = json.loads((FIXTURE_DIR / f"template_{template_id}_zone_config.json").read_text())
        assert is_valid_zone_config(raw), f"template {template_id} should be valid"


# ──────────────────────────────────────────────────────────────────────
# Strictness tests — malformed inputs must be rejected
# ──────────────────────────────────────────────────────────────────────


def test_missing_zones_rejected():
    with pytest.raises(ZoneConfigValidationError) as ei:
        parse_zone_config({})
    assert "zones" in str(ei.value)


def test_zones_missing_product_data_rejected():
    with pytest.raises(ZoneConfigValidationError):
        parse_zone_config({"zones": {"summary": {"start": 5, "end": 6}}})


def test_zone_range_end_less_than_start_rejected():
    with pytest.raises(ZoneConfigValidationError) as ei:
        parse_zone_config({
            "zones": {
                "product_data": {"start": 10, "end": 5},
                "summary": {"start": 11, "end": 12},
            }
        })
    assert ">=" in str(ei.value) or "end" in str(ei.value)


def test_zone_range_zero_start_rejected():
    with pytest.raises(ZoneConfigValidationError):
        parse_zone_config({
            "zones": {
                "product_data": {"start": 0, "end": 5},
                "summary": {"start": 6, "end": 7},
            }
        })


def test_header_field_invalid_key_rejected():
    with pytest.raises(ZoneConfigValidationError) as ei:
        parse_zone_config({
            "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 6}},
            "header_fields": {"not_a_cell": "ship_name"},
        })
    assert "header_fields" in str(ei.value)


def test_product_columns_invalid_key_rejected():
    with pytest.raises(ZoneConfigValidationError):
        parse_zone_config({
            "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 6}},
            "product_columns": {"D5": "product_name"},  # should be "D" not "D5"
        })


def test_product_row_formula_missing_row_placeholder_rejected():
    with pytest.raises(ZoneConfigValidationError) as ei:
        parse_zone_config({
            "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 6}},
            "product_row_formulas": {"F": "=D5*E5"},  # hardcoded row, should use {row}
        })
    assert "row" in str(ei.value)


def test_product_row_formula_missing_equals_rejected():
    with pytest.raises(ZoneConfigValidationError):
        parse_zone_config({
            "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 6}},
            "product_row_formulas": {"F": "D{row}*E{row}"},  # missing leading =
        })


def test_relative_summary_formula_needs_template():
    with pytest.raises(ZoneConfigValidationError) as ei:
        parse_zone_config({
            "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 8}},
            "summary_formulas": [{"cell": "F6", "type": "relative", "label": "Tax"}],
        })
    assert "formula_template" in str(ei.value)


def test_minimal_valid_config_accepted():
    config = parse_zone_config({
        "zones": {
            "product_data": {"start": 5, "end": 5},
            "summary": {"start": 6, "end": 8},
        }
    })
    assert config.zones.product_data.start == 5
    assert config.header_fields == {}
    assert config.product_columns == {}


def test_full_realistic_config_accepted():
    config = parse_zone_config({
        "zones": {
            "product_data": {"start": 22, "end": 32},
            "summary": {"start": 33, "end": 35},
        },
        "header_fields": {
            "B2": "ship_name",
            "B3": "suppliers.{sid}.supplier_name",
        },
        "product_columns": {
            "A": "line_number",
            "B": "product_name",
            "D": "quantity",
        },
        "product_row_formulas": {"F": "=D{row}*E{row}"},
        "summary_formulas": [
            {"cell": "L33", "type": "product_sum", "col": "L", "label": "Sub Total"},
            {"cell": "L34", "type": "relative", "formula_template": "={sum_cell}*0.08", "label": "Tax"},
        ],
        "summary_static_values": {"A33": "Sub Total", "A34": "Tax"},
        "stale_columns_in_summary": ["G", "H"],
        "external_refs": [
            {"cell": "H16", "formula_template": "={grand_total_cell}"},
        ],
    })
    assert len(config.summary_formulas) == 2
    assert config.summary_formulas[0].type == "product_sum"
    assert config.summary_formulas[1].formula_template == "={sum_cell}*0.08"
    assert len(config.external_refs) == 1


def test_legacy_opaque_fields_passthrough():
    """Legacy fields like cells/column_widths/template_contract should be accepted as opaque."""
    config = parse_zone_config({
        "zones": {"product_data": {"start": 5, "end": 5}, "summary": {"start": 6, "end": 6}},
        "cells": {"foo": "bar"},
        "column_widths": {"A": 12.0},
        "row_heights": {"1": 25},
        "merged_ranges": [],
        "field_schema": [],
        "product_row_style": {"foo": "bar"},
        "template_contract": {"version": 2},
    })
    assert config.template_contract == {"version": 2}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
