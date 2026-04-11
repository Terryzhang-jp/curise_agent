"""ZoneConfig Pydantic schema (v1).

The zone_config dict is the structured contract between:
  - template upload / analysis (writes it)
  - fill_template / compose_render (reads it to fill data)
  - verify_output (reads it to validate output)
  - template_contract (derives from it)

Before this schema existed, every consumer used `.get(key, default)` patterns
that silently swallowed missing fields. A template uploaded with a broken
zone_config would still be saved to DB; it would only blow up at inquiry
generation time, often with cryptic errors.

This module provides:

  - `ZoneConfigV1` — strict typed model that mirrors every field used by
    fill_template / compose_render / verify_output / template_contract
  - `parse_zone_config(raw)` — validates a dict against the schema, raises
    `ZoneConfigValidationError` with field paths on failure
  - `ZoneConfigValidationError` — typed exception with `.errors()` returning
    a list of human-readable issues

The schema is intentionally PERMISSIVE for legacy fields (cells / column_widths
/ template_contract / row_heights / merged_ranges / field_schema / product_row_style
are stored as Any). The STRICT validation focuses on fields that the
generation pipeline actually depends on for correctness.

Adding a new field:
  1. Add it to the appropriate model below
  2. Add a unit test that exercises it
  3. Bump SCHEMA_VERSION if it's a breaking change
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


SCHEMA_VERSION = "1.0"


# ─── Sub-models ───────────────────────────────────────────────────────


class ZoneRange(BaseModel):
    """A row range, used for product_data and summary zones.

    `start` and `end` are 1-indexed row numbers, inclusive on both ends.
    `end >= start` is enforced.
    """
    model_config = ConfigDict(extra="forbid")

    start: int = Field(..., ge=1, description="1-indexed start row (inclusive)")
    end: int = Field(..., ge=1, description="1-indexed end row (inclusive)")

    @field_validator("end")
    @classmethod
    def _end_ge_start(cls, v: int, info) -> int:
        start = info.data.get("start")
        if start is not None and v < start:
            raise ValueError(f"end ({v}) must be >= start ({start})")
        return v


class Zones(BaseModel):
    """Top-level zones declaration."""
    model_config = ConfigDict(extra="forbid")

    product_data: ZoneRange
    summary: ZoneRange


SummaryFormulaType = Literal["product_sum", "relative"]


class SummaryFormula(BaseModel):
    """A declared formula in the summary zone.

    `cell` is the cell reference in the ORIGINAL template (e.g. "L33").
    The renderer shifts it to the new position based on the actual row count.

    `type`:
      - "product_sum": auto-build SUM over the product range
      - "relative": use `formula_template` with placeholders like
        `{sum_cell}`, `{tax_cell}`, `{grand_total_cell}` that get substituted
        with the new (post-shift) cell addresses

    `label` is used for human display AND for routing relative formulas to
    semantic placeholders ("tax" / "grand total" / etc).
    """
    model_config = ConfigDict(extra="forbid")

    cell: str = Field(..., min_length=2)
    type: SummaryFormulaType
    label: str = ""
    col: str | None = None  # column letter for product_sum
    formula_template: str | None = None  # required for relative

    @model_validator(mode="after")
    def _relative_needs_template(self) -> "SummaryFormula":
        if self.type == "relative" and not self.formula_template:
            raise ValueError(
                f"relative summary formula at cell {self.cell!r} must have formula_template"
            )
        return self


class ExternalRef(BaseModel):
    """A formula in the header (or anywhere outside the summary zone) that
    references summary cells. Common pattern: a Total at the top of the page
    that mirrors the Grand Total at the bottom.

    Without this declaration, the renderer would copy the original formula
    text verbatim and miss the row shift, resulting in stale references.
    """
    model_config = ConfigDict(extra="forbid")

    cell: str = Field(..., min_length=2)
    formula_template: str = Field(..., min_length=1)


# ─── Main model ───────────────────────────────────────────────────────


class ZoneConfigV1(BaseModel):
    """The complete zone_config schema.

    Fields are split into:

      STRICT (validated): fields the generation pipeline depends on for
      correctness. These have strong types and rules.

      PERMISSIVE (Any): legacy / decorative fields that the renderer either
      doesn't need or treats opaquely. We accept whatever is there to avoid
      breaking old templates, but they don't get validation guarantees.
    """
    model_config = ConfigDict(extra="ignore")

    # ── STRICT: zone definitions ──
    zones: Zones

    # ── STRICT: cell-level mappings ──
    header_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Map of header cell ref → data path. E.g. 'B2' → 'ship_name'",
    )
    product_columns: dict[str, str] = Field(
        default_factory=dict,
        description="Map of column letter → product field name. E.g. 'D' → 'product_name'",
    )
    product_row_formulas: dict[str, str] = Field(
        default_factory=dict,
        description="Map of column letter → formula template. {row} placeholder gets substituted.",
    )

    # ── STRICT: summary handling ──
    summary_formulas: list[SummaryFormula] = Field(default_factory=list)
    summary_static_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Map of cell ref → static value to restore after row resize",
    )
    stale_columns_in_summary: list[str] = Field(
        default_factory=list,
        description="Column letters whose values in summary zone should be cleared "
                    "before restoring static values",
    )
    external_refs: list[ExternalRef] = Field(default_factory=list)

    # ── PERMISSIVE: legacy / opaque fields ──
    cells: Any = None
    column_widths: Any = None
    row_heights: Any = None
    merged_ranges: Any = None
    field_schema: Any = None
    product_row_style: Any = None
    template_contract: Any = None  # built lazily, opaque to schema

    # ── Computed validators ──

    @field_validator("header_fields")
    @classmethod
    def _validate_header_field_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Each key must look like a cell reference (letters + digits)."""
        import re
        for key in v.keys():
            if not re.fullmatch(r"[A-Z]{1,3}\d+", key):
                raise ValueError(
                    f"header_fields key {key!r} must be a cell reference like 'B2'"
                )
        return v

    @field_validator("product_columns")
    @classmethod
    def _validate_product_column_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Keys must be column letters."""
        import re
        for key in v.keys():
            if not re.fullmatch(r"[A-Z]{1,3}", key):
                raise ValueError(
                    f"product_columns key {key!r} must be a column letter like 'D'"
                )
        return v

    @field_validator("product_row_formulas")
    @classmethod
    def _validate_formula_keys(cls, v: dict[str, str]) -> dict[str, str]:
        import re
        for key, formula in v.items():
            if not re.fullmatch(r"[A-Z]{1,3}", key):
                raise ValueError(f"product_row_formulas key {key!r} must be a column letter")
            if not formula.startswith("="):
                raise ValueError(f"product_row_formulas[{key}] must start with '='")
            if "{row}" not in formula:
                raise ValueError(
                    f"product_row_formulas[{key}] must contain '{{row}}' placeholder"
                )
        return v


# ─── Public API ───────────────────────────────────────────────────────


class ZoneConfigValidationError(ValueError):
    """Raised when a raw zone_config dict fails schema validation.

    Has a `.errors` attribute with structured Pydantic errors.
    """

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors_list = errors or []


def parse_zone_config(raw: Any) -> ZoneConfigV1:
    """Parse and validate a raw dict against the ZoneConfig schema.

    Raises:
        ZoneConfigValidationError: with `.errors_list` containing field-path
        details on any validation failure.
    """
    if not isinstance(raw, dict):
        raise ZoneConfigValidationError(
            f"zone_config must be a dict, got {type(raw).__name__}"
        )
    try:
        return ZoneConfigV1.model_validate(raw)
    except ValidationError as exc:
        # Build a human-readable summary
        problems = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            problems.append(f"  - {loc}: {err['msg']}")
        msg = "zone_config validation failed:\n" + "\n".join(problems)
        raise ZoneConfigValidationError(msg, errors=exc.errors()) from exc


def is_valid_zone_config(raw: Any) -> bool:
    """Cheap boolean check — useful for filtering production templates."""
    try:
        parse_zone_config(raw)
        return True
    except ZoneConfigValidationError:
        return False
