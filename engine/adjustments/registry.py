"""Create, list and override professional adjustments — the minimal foundation.

Scope guardrails (by design, not omission):
* no valuation math, no percentage limits, no factor hierarchy and no automatic
  value conclusion;
* no fixed workflow — these are plain functions over plain dicts;
* factor / direction / confidence_level are validated against an *injectable*
  ``AdjustmentConfig`` (empty vocabulary = unrestricted), never a hard-coded
  enum;
* registry logic validates structure only; it embeds no professional judgment;
* ``apply_override`` records professional judgment while preserving the prior
  value, and emits a rationale/explanation ready for a future Audit Trail.
"""

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional

from engine.adjustments.config import AdjustmentConfig, DEFAULT_CONFIG

# Fields required to create an adjustment. ``adjustment_id`` is auto-generated
# when absent and ``manual_override``/``created_at`` are managed by the
# functions, so they are not part of the caller-required set.
REQUIRED_FIELDS = (
    "comparable_id",
    "factor",
    "direction",
    "amount_or_range",
    "rationale",
    "evidence_reference",
    "confidence_level",
)


class AdjustmentError(ValueError):
    """Raised when an adjustment or override is invalid."""


def _now() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _missing(data: Mapping, field: str) -> bool:
    """A field is missing if absent, None, or a blank string.

    Numbers, ranges and objects (valid ``amount_or_range`` shapes) count as
    present, so the check imposes no type rigidity.
    """
    if field not in data:
        return True
    value = data[field]
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _validate_controlled_fields(values: Mapping,
                                config: AdjustmentConfig) -> None:
    """Validate factor / direction / confidence_level against the config.

    An empty vocabulary tuple means that field is unrestricted.
    """
    if ("factor" in values and config.factors
            and values["factor"] not in config.factors):
        raise AdjustmentError(
            f"factor '{values['factor']}' is not in configured factors "
            f"{config.factors}"
        )
    if ("direction" in values and config.directions
            and values["direction"] not in config.directions):
        raise AdjustmentError(
            f"direction '{values['direction']}' is not in configured directions "
            f"{config.directions}"
        )
    if ("confidence_level" in values and config.confidence_levels
            and values["confidence_level"] not in config.confidence_levels):
        raise AdjustmentError(
            f"confidence_level '{values['confidence_level']}' is not in configured "
            f"levels {config.confidence_levels}"
        )


def create_adjustment(data: Mapping, *,
                      config: Optional[AdjustmentConfig] = None) -> Dict:
    """Create a validated adjustment record from ``data``.

    Required fields are listed in ``REQUIRED_FIELDS``; ``factor``, ``direction``
    and ``confidence_level`` must be allowed by ``config``. Extra keys in
    ``data`` are preserved (additionalProperties). Returns a new dict; the input
    is not mutated.
    """
    config = config or DEFAULT_CONFIG
    if not isinstance(data, Mapping):
        raise AdjustmentError("adjustment data must be a mapping")

    missing = [f for f in REQUIRED_FIELDS if _missing(data, f)]
    if missing:
        raise AdjustmentError(f"missing required fields: {', '.join(missing)}")

    _validate_controlled_fields(data, config)

    record = deepcopy(dict(data))
    record.setdefault("adjustment_id", f"ADJ-{uuid.uuid4().hex[:8]}")
    record["manual_override"] = data.get("manual_override")
    record["created_at"] = _now()
    return record


def list_adjustments(adjustments: Iterable[Mapping], *,
                     comparable_id: Optional[str] = None,
                     factor: Optional[str] = None,
                     direction: Optional[str] = None,
                     confidence_level: Optional[str] = None,
                     overridden: Optional[bool] = None) -> List[Dict]:
    """Return adjustments filtered by any supplied criteria.

    All filters are optional; with none supplied the input is returned as a
    list. ``overridden=True/False`` selects records that do / do not carry a
    manual override. No ordering or workflow is imposed.
    """
    result = [dict(a) for a in adjustments]
    if comparable_id is not None:
        result = [a for a in result if a.get("comparable_id") == comparable_id]
    if factor is not None:
        result = [a for a in result if a.get("factor") == factor]
    if direction is not None:
        result = [a for a in result if a.get("direction") == direction]
    if confidence_level is not None:
        result = [a for a in result if a.get("confidence_level") == confidence_level]
    if overridden is not None:
        result = [a for a in result
                  if (a.get("manual_override") is not None) == overridden]
    return result


def _override_explanation(diff: Mapping, rationale: str,
                          actor: Optional[str]) -> List[str]:
    """Human-readable, auditable summary of an override."""
    lines = [f"manual_override by {actor or 'unspecified'}: {rationale}"]
    for field, change in diff.items():
        lines.append(f"{field}: {change['from']!r} -> {change['to']!r}")
    return lines


def apply_override(adjustment: Mapping, *,
                   changes: Mapping,
                   rationale: str,
                   actor: Optional[str] = None,
                   config: Optional[AdjustmentConfig] = None) -> Dict:
    """Apply a professional-judgment override, preserving the prior value.

    ``changes`` is a mapping of field -> new value. A ``rationale`` is
    mandatory so the override is explainable. The returned record carries a
    ``manual_override`` block with the per-field ``changes`` diff, a
    ``previous`` snapshot of the pre-override values, the actor, the rationale,
    a timestamp and an ``explanation`` list — enough for a later 'adjustment
    overridden' audit event. The input ``adjustment`` is not mutated, so the
    original record remains recoverable.
    """
    config = config or DEFAULT_CONFIG
    if not isinstance(adjustment, Mapping):
        raise AdjustmentError("adjustment must be a mapping")
    if not isinstance(changes, Mapping) or not changes:
        raise AdjustmentError("changes must be a non-empty mapping")
    if not str(rationale or "").strip():
        raise AdjustmentError("override requires a rationale")

    _validate_controlled_fields(changes, config)

    updated = deepcopy(dict(adjustment))
    previous = {field: updated.get(field) for field in changes}
    diff = {field: {"from": updated.get(field), "to": new_value}
            for field, new_value in changes.items()}

    for field, new_value in changes.items():
        updated[field] = new_value

    updated["manual_override"] = {
        "applied": True,
        "actor": actor,
        "rationale": rationale,
        "changes": diff,
        "previous": previous,
        "timestamp": _now(),
        "explanation": _override_explanation(diff, rationale, actor),
    }
    return updated
