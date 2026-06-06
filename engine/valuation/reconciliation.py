"""Cross-Approach Reconciliation — calculation support.

Combines independent approach value indications (e.g. comparable approach,
direct capitalization, DCF) into a reconciled indicated range and an optional
caller-weighted central figure, with a per-approach surface and explanation.

Calculation support only: it does not produce an adopted/final value, a
valuation opinion, or a reconciliation narrative. It does not import the
approach modules — it reads their already-produced output values, so the caller
maps each producer's output into a normalized indication.

Avoid rigid systems: which approaches are included, their weights (per
indication or via config; callable strategy allowed) and the aggregation are all
injectable. There is no default approach hierarchy and no default weighting
other than an equal-weight fallback when the caller supplies no weights at all.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import (
    DEFAULT_RECONCILIATION_CONFIG,
    ReconciliationConfig,
)


class ReconciliationError(ValueError):
    """Raised when reconciliation inputs are invalid."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, config: ReconciliationConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _bounds(indication: Mapping):
    """Return (low, high, central) for one indication.

    Accepts a point ``value`` and/or a ``range`` ({low, high}). When both are
    given, ``value`` is the central and ``range`` is the envelope.
    """
    point = indication.get("value")
    range_block = indication.get("range")
    has_point = _is_number(point)
    has_range = (isinstance(range_block, Mapping)
                 and _is_number(range_block.get("low"))
                 and _is_number(range_block.get("high")))
    if has_range:
        low = float(range_block["low"])
        high = float(range_block["high"])
        central = float(point) if has_point else (low + high) / 2.0
        return low, high, central
    if has_point:
        return float(point), float(point), float(point)
    raise ReconciliationError(
        "each indication needs a numeric 'value' or a 'range' {low, high}")


def _approach_name(indication: Mapping) -> str:
    name = indication.get("approach")
    if not name:
        raise ReconciliationError("each indication needs an 'approach' name")
    return name


def normalize_approach_weights(indications: Iterable[Mapping], *,
                               config: Optional[ReconciliationConfig] = None) -> Dict:
    """Return ``{approach: weight}`` normalized to sum to 1.

    Weight source per approach: the indication's own ``weight`` if present, else
    ``config.weights[approach]``. If none of the approaches resolve a weight,
    equal weights are used. A partial set (some resolved, some not) is rejected
    rather than guessed.
    """
    config = config or DEFAULT_RECONCILIATION_CONFIG
    indications = list(indications)
    config_weights = config.weights or {}

    resolved: Dict[str, Optional[float]] = {}
    for indication in indications:
        approach = _approach_name(indication)
        if "weight" in indication and indication["weight"] is not None:
            resolved[approach] = float(indication["weight"])
        elif approach in config_weights:
            resolved[approach] = float(config_weights[approach])
        else:
            resolved[approach] = None

    supplied = [w for w in resolved.values() if w is not None]
    if not supplied:
        count = len(resolved)
        equal = (1.0 / count) if count else 0.0
        return {approach: equal for approach in resolved}
    if len(supplied) != len(resolved):
        missing = [a for a, w in resolved.items() if w is None]
        raise ReconciliationError(
            f"weights given for some approaches but missing for {missing}; "
            "supply all weights or none")

    total = sum(supplied)
    if total <= 0:
        raise ReconciliationError("approach weights must sum to a positive value")
    return {approach: weight / total for approach, weight in resolved.items()}


def reconcile(indications: Iterable[Mapping], *,
              config: Optional[ReconciliationConfig] = None,
              audit_store: Any = None,
              audit_config: Any = None) -> Dict:
    """Reconcile approach indications into a supported range + weighted central.

    Each entry in ``indications`` is ``{"approach", "value"?, "range"?, "weight"?}``.
    Returns the ``reconciled_range`` envelope, a ``weighted_indication``, the
    per-approach surface, an explanation and an explicit non-opinion ``basis``.
    Records a ``reconciled`` audit event only when ``audit_store`` is given; the
    result is computed before the audit call and cannot be affected by it.
    """
    config = config or DEFAULT_RECONCILIATION_CONFIG
    indications = list(indications)
    if not indications:
        raise ReconciliationError("at least one approach indication is required")

    weights = normalize_approach_weights(indications, config=config)

    approaches: List[Dict] = []
    lows: List[float] = []
    highs: List[float] = []
    centrals: Dict[str, float] = {}
    for indication in indications:
        approach = _approach_name(indication)
        low, high, central = _bounds(indication)
        lows.append(low)
        highs.append(high)
        centrals[approach] = central
        approaches.append({
            "approach": approach,
            "low": _round(low, config),
            "high": _round(high, config),
            "central": _round(central, config),
            "weight": weights.get(approach, 0.0),
        })

    if callable(config.aggregation):
        weighted = config.aggregation(centrals, weights)
    elif config.aggregation == "weighted_mean":
        weight_sum = sum(weights.values())
        weighted = (sum(centrals[a] * weights.get(a, 0.0) for a in centrals)
                    / weight_sum) if weight_sum > 0 else None
    else:
        raise ReconciliationError(
            f"Unknown aggregation strategy: {config.aggregation!r}")

    result = {
        "reconciled_range": {"low": _round(min(lows), config),
                             "high": _round(max(highs), config)},
        "weighted_indication": _round(weighted, config),
        "approaches": approaches,
        "explanation": [
            f"approaches={[a['approach'] for a in approaches]}",
            f"weights={ {a['approach']: a['weight'] for a in approaches} }",
            f"reconciled_range=[{_round(min(lows), config)}, "
            f"{_round(max(highs), config)}]",
            f"weighted_indication={_round(weighted, config)}",
        ],
        "basis": ("calculation support — cross-approach reconciled range and "
                  "weighted indication; not an adopted value, concluded value "
                  "or valuation opinion"),
    }

    if audit_store is not None:
        record_event(
            "valuation", (indications[0].get("property_id")
                          if indications else None), "reconciled",
            before=None,
            after={"reconciled_range": result["reconciled_range"],
                   "weighted_indication": result["weighted_indication"]},
            rationale="cross-approach reconciliation calculation support",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return result
