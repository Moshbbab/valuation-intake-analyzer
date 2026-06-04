"""Comparable-approach calculation support.

Composes Evidence (reliability + inclusion), Adjustments (machine-readable
``adjustment_value``) and, optionally, the Audit Trail into:

* an adjusted unit rate (point or range) per included comparable,
* normalized comparable weights,
* an indicated value range with an evidence-weighted central figure.

This module computes *support*, not a conclusion. It applies no caps, forces no
single-point value, runs no method sequence, and embeds no professional
judgment — the free-form ``amount_or_range`` note is never interpreted, only the
explicit ``adjustment_value`` is used for math, and missing/invalid values are
skipped safely.
"""

from typing import Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import ComparableApproachConfig, DEFAULT_CONFIG

_VALUE_TYPES = ("percentage", "absolute", "range_percentage", "range_absolute")


def _sign(direction: Optional[str]) -> int:
    """Map a direction to a sign; anything unknown is treated as neutral (0)."""
    if direction == "upward":
        return 1
    if direction == "downward":
        return -1
    return 0


def parse_adjustment_value(adjustment: Mapping) -> Optional[Dict]:
    """Return a normalized machine-readable adjustment value, or None.

    Reads the optional ``adjustment_value`` field only; the free-form
    ``amount_or_range`` note is never parsed. Returns None (safe skip) when the
    field is absent or malformed. ``direction`` falls back to the adjustment's
    top-level ``direction`` when not set on ``adjustment_value``.
    """
    value_block = adjustment.get("adjustment_value")
    if not isinstance(value_block, Mapping):
        return None
    value_type = value_block.get("type")
    value = value_block.get("value")
    if value_type not in _VALUE_TYPES:
        return None
    if value_type in ("percentage", "absolute"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
    else:  # range_*
        if not (isinstance(value, Mapping)
                and isinstance(value.get("low"), (int, float))
                and isinstance(value.get("high"), (int, float))):
            return None
    direction = value_block.get("direction") or adjustment.get("direction") \
        or "neutral"
    return {"type": value_type, "value": value, "direction": direction,
            "unit": value_block.get("unit")}


def apply_adjustment_to_rate(rate: float, adj_value: Mapping):
    """Apply one normalized adjustment value to a rate.

    Returns a float for point types and a ``{"low", "high"}`` dict for range
    types. Direction sets the sign; neutral leaves the rate unchanged.
    """
    sign = _sign(adj_value["direction"])
    value_type = adj_value["type"]
    if value_type == "percentage":
        return rate * (1 + sign * adj_value["value"] / 100.0)
    if value_type == "absolute":
        return rate + sign * adj_value["value"]
    low = adj_value["value"]["low"]
    high = adj_value["value"]["high"]
    if value_type == "range_percentage":
        end_a = rate * (1 + sign * low / 100.0)
        end_b = rate * (1 + sign * high / 100.0)
    else:  # range_absolute
        end_a = rate + sign * low
        end_b = rate + sign * high
    return {"low": min(end_a, end_b), "high": max(end_a, end_b)}


def _round_value(value, config: ComparableApproachConfig):
    if config.rounding is not None and isinstance(value, (int, float)):
        return round(value, config.rounding)
    return value


def adjusted_unit_rate(comparable: Mapping, adjustments: Iterable[Mapping], *,
                       config: Optional[ComparableApproachConfig] = None) -> Dict:
    """Chain a comparable's machine-readable adjustments onto its unit rate.

    Returns ``base_rate``, the ``adjusted`` result (a number, or a
    ``{"low","high"}`` dict when any range adjustment applied), and counts of
    applied / skipped adjustments. Safe when ``unit_rate`` is missing or no
    machine-readable adjustment is present.
    """
    config = config or DEFAULT_CONFIG
    adjustments = list(adjustments)
    base = comparable.get("unit_rate")
    if not isinstance(base, (int, float)) or isinstance(base, bool):
        return {"base_rate": base, "adjusted": None, "adjusted_low": None,
                "adjusted_high": None, "applied": 0, "skipped": len(adjustments),
                "note": "no numeric unit_rate; cannot compute"}

    low = high = float(base)
    applied = skipped = 0
    for adjustment in adjustments:
        adj_value = parse_adjustment_value(adjustment)
        if adj_value is None:
            skipped += 1
            continue
        out_low = apply_adjustment_to_rate(low, adj_value)
        out_high = apply_adjustment_to_rate(high, adj_value)
        lows: List[float] = []
        highs: List[float] = []
        for out in (out_low, out_high):
            if isinstance(out, Mapping):
                lows.append(out["low"])
                highs.append(out["high"])
            else:
                lows.append(out)
                highs.append(out)
        low, high = min(lows), max(highs)
        applied += 1

    low = _round_value(low, config)
    high = _round_value(high, config)
    adjusted = low if low == high else {"low": low, "high": high}
    return {"base_rate": base, "adjusted": adjusted, "adjusted_low": low,
            "adjusted_high": high, "applied": applied, "skipped": skipped}


def normalize_weights(assessed: Iterable[Mapping], *,
                      config: Optional[ComparableApproachConfig] = None) -> Dict:
    """Return ``{comparable_id: weight}`` for included comparables only.

    ``assessed`` is an iterable of entries each with a ``comparable`` (carrying
    ``comparable_id``) and an ``assessment`` (carrying ``reliability_score`` and
    ``inclusion_decision``). The built-in strategy normalizes reliability across
    included comparables; a callable strategy may replace it entirely. Excluded
    and review comparables get no weight.
    """
    config = config or DEFAULT_CONFIG
    assessed = list(assessed)
    if callable(config.weighting):
        return dict(config.weighting(assessed))

    included = [e for e in assessed
                if e["assessment"].get("inclusion_decision")
                in config.included_decisions]
    total = sum(e["assessment"].get("reliability_score", 0.0) for e in included)
    if total <= 0:
        count = len(included)
        equal = (1.0 / count) if count else 0.0
        return {e["comparable"]["comparable_id"]: equal for e in included}
    return {e["comparable"]["comparable_id"]:
            e["assessment"].get("reliability_score", 0.0) / total
            for e in included}


def _central(adjusted) -> Optional[float]:
    if isinstance(adjusted, Mapping):
        return (adjusted["low"] + adjusted["high"]) / 2.0
    return adjusted


def indicated_range(adjusted_by_id: Mapping, weights: Mapping, *,
                    config: Optional[ComparableApproachConfig] = None) -> Dict:
    """Aggregate adjusted rates into an indicated range (calculation support).

    Returns the overall ``low``/``high`` envelope and a weighted central
    ``weighted_indication``. This is support for reconciliation, not a final
    value opinion.
    """
    config = config or DEFAULT_CONFIG
    lows: List[float] = []
    highs: List[float] = []
    weighted = 0.0
    weight_sum = 0.0
    for comparable_id, adjusted in adjusted_by_id.items():
        if adjusted is None:
            continue
        if isinstance(adjusted, Mapping):
            low, high = adjusted["low"], adjusted["high"]
        else:
            low = high = adjusted
        lows.append(low)
        highs.append(high)
        weight = weights.get(comparable_id, 0.0)
        weighted += weight * _central(adjusted)
        weight_sum += weight

    if not lows:
        return {"low": None, "high": None, "weighted_indication": None,
                "note": "no included comparables with computable rates"}

    weighted_indication = weighted / weight_sum if weight_sum > 0 else None
    result = {"low": min(lows), "high": max(highs),
              "weighted_indication": weighted_indication}
    return {key: _round_value(value, config) for key, value in result.items()}


def _record_valuation_event(entry: Mapping, adjusted: Dict, weight: float,
                            store, config) -> None:
    """Record one comparable-approach calculation event (optional)."""
    record_event(
        "comparable", entry["comparable"].get("comparable_id"), "valued",
        before=None,
        after={"base_rate": adjusted["base_rate"],
               "adjusted": adjusted["adjusted"], "weight": weight},
        rationale="comparable-approach calculation support",
        store=store, config=config or UNRESTRICTED_CONFIG,
    )


def run_comparable_approach(cases: Iterable[Mapping], *,
                            config: Optional[ComparableApproachConfig] = None,
                            audit_store=None,
                            audit_config=None) -> Dict:
    """Produce comparable-approach calculation support from assessed cases.

    Each entry in ``cases`` is ``{"comparable", "assessment", "adjustments"}``.
    Returns weights, per-comparable reconciliation rows, the indicated range,
    the list of excluded comparable ids, and an explicit non-opinion ``basis``.
    When an ``audit_store`` is supplied, a 'valued' event is recorded per
    included comparable (vocabulary stays injectable; defaults to unrestricted).
    """
    config = config or DEFAULT_CONFIG
    cases = list(cases)
    weights = normalize_weights(cases, config=config)
    included_ids = set(weights)

    adjusted_by_id: Dict = {}
    reconciliation: List[Dict] = []
    excluded: List = []
    for entry in cases:
        comparable_id = entry["comparable"].get("comparable_id")
        if comparable_id not in included_ids:
            excluded.append(comparable_id)
            continue
        adjusted = adjusted_unit_rate(entry["comparable"],
                                      entry.get("adjustments", []), config=config)
        adjusted_by_id[comparable_id] = adjusted["adjusted"]
        reconciliation.append({
            "comparable_id": comparable_id,
            "base_rate": adjusted["base_rate"],
            "adjusted": adjusted["adjusted"],
            "weight": weights[comparable_id],
            "confidence_level": entry["assessment"].get("confidence_level"),
            "adjustments_applied": adjusted["applied"],
            "adjustments_skipped": adjusted["skipped"],
        })
        if audit_store is not None:
            _record_valuation_event(entry, adjusted, weights[comparable_id],
                                    audit_store, audit_config)

    return {
        "indicated_range": indicated_range(adjusted_by_id, weights, config=config),
        "weights": weights,
        "comparables": reconciliation,
        "excluded": excluded,
        "basis": ("calculation support — evidence-weighted indicated range; "
                  "not a final valuation opinion"),
    }
