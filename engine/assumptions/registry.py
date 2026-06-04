"""Create, list and override professional assumptions — the minimal foundation.

Scope guardrails (by design, not omission):
* no valuation math and no automatic valuation conclusion;
* no fixed workflow — these are plain functions over plain dicts;
* categories and confidence levels are validated against an *injectable*
  ``AssumptionConfig``, never a hard-coded enum;
* ``apply_override`` records professional judgment while preserving the prior
  value, and emits a rationale/explanation ready for a future Audit Trail.
"""

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional

from engine.assumptions.config import AssumptionConfig, DEFAULT_CONFIG

# Fields required to create an assumption. ``assumption_id`` is auto-generated
# when absent and ``manual_override``/``created_at`` are managed by the
# functions, so they are not part of the caller-required set.
REQUIRED_FIELDS = (
    "category",
    "statement",
    "basis",
    "confidence_level",
    "rationale",
    "affected_method",
    "sensitivity_link",
)


class AssumptionError(ValueError):
    """Raised when an assumption or override is invalid."""


def _now() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _validate_controlled_fields(values: Mapping, config: AssumptionConfig) -> None:
    """Validate category / confidence_level against the injected config."""
    if "category" in values and values["category"] not in config.categories:
        raise AssumptionError(
            f"category '{values['category']}' is not in configured categories "
            f"{config.categories}"
        )
    if ("confidence_level" in values
            and values["confidence_level"] not in config.confidence_levels):
        raise AssumptionError(
            f"confidence_level '{values['confidence_level']}' is not in configured "
            f"levels {config.confidence_levels}"
        )


def create_assumption(data: Mapping, *,
                      config: Optional[AssumptionConfig] = None) -> Dict:
    """Create a validated assumption record from ``data``.

    Required fields are listed in ``REQUIRED_FIELDS``; ``category`` and
    ``confidence_level`` must be allowed by ``config``. Extra keys in ``data``
    are preserved (additionalProperties). Returns a new dict; the input is not
    mutated.
    """
    config = config or DEFAULT_CONFIG
    if not isinstance(data, Mapping):
        raise AssumptionError("assumption data must be a mapping")

    missing = [f for f in REQUIRED_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        raise AssumptionError(f"missing required fields: {', '.join(missing)}")

    _validate_controlled_fields(data, config)

    record = deepcopy(dict(data))
    record.setdefault("assumption_id", f"A-{uuid.uuid4().hex[:8]}")
    record["manual_override"] = data.get("manual_override")
    record["created_at"] = _now()
    return record


def list_assumptions(assumptions: Iterable[Mapping], *,
                     category: Optional[str] = None,
                     confidence_level: Optional[str] = None,
                     affected_method: Optional[str] = None,
                     overridden: Optional[bool] = None) -> List[Dict]:
    """Return assumptions filtered by any supplied criteria.

    All filters are optional; with none supplied the input is returned as a
    list. ``overridden=True/False`` selects records that do / do not carry a
    manual override. No ordering or workflow is imposed.
    """
    result = [dict(a) for a in assumptions]
    if category is not None:
        result = [a for a in result if a.get("category") == category]
    if confidence_level is not None:
        result = [a for a in result if a.get("confidence_level") == confidence_level]
    if affected_method is not None:
        result = [a for a in result if a.get("affected_method") == affected_method]
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


def apply_override(assumption: Mapping, *,
                   changes: Mapping,
                   rationale: str,
                   actor: Optional[str] = None,
                   config: Optional[AssumptionConfig] = None) -> Dict:
    """Apply a professional-judgment override, preserving the prior value.

    ``changes`` is a mapping of field -> new value. A ``rationale`` is
    mandatory so the override is explainable. The returned record carries a
    ``manual_override`` block with the per-field ``changes`` diff, a
    ``previous`` snapshot of the pre-override values, the actor, the rationale,
    a timestamp and an ``explanation`` list. The input ``assumption`` is not
    mutated.
    """
    config = config or DEFAULT_CONFIG
    if not isinstance(assumption, Mapping):
        raise AssumptionError("assumption must be a mapping")
    if not isinstance(changes, Mapping) or not changes:
        raise AssumptionError("changes must be a non-empty mapping")
    if not str(rationale or "").strip():
        raise AssumptionError("override requires a rationale")

    _validate_controlled_fields(changes, config)

    updated = deepcopy(dict(assumption))
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
