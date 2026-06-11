"""Comparable Market Engine — adopted land rate range (valuation production).

Input: comparable transactions (each with a price/m^2 ``unit_rate`` and optional
machine-readable ``adjustments``, or a pre-computed ``adjusted_rate``).

Output: adjusted rate per comparable, median, weighted average, percentile
range, outlier exclusion, and a recommended market rate — reduced to an adopted
land rate range ``{low, base, high}``.

This produces a valuation number (the adopted land rate that feeds the Land
Value Engine). It applies the caller's adjustments and configuration only; no
market rate is assumed and no final value opinion is formed.
"""

from typing import Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation._rate_support import aggregate_rates
from engine.valuation.comparable_approach import adjusted_unit_rate
from engine.valuation.config import DEFAULT_MARKET_RATE_CONFIG, MarketRateConfig


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _adjusted_central(comparable: Mapping) -> Optional[float]:
    """Adjusted price/m^2 for one comparable, or None when not computable."""
    pre = comparable.get("adjusted_rate")
    if _is_number(pre):
        return float(pre)
    adjusted = adjusted_unit_rate(comparable, comparable.get("adjustments", []))
    value = adjusted["adjusted"]
    if isinstance(value, Mapping):
        return (value["low"] + value["high"]) / 2.0
    return float(value) if _is_number(value) else None


def adopted_market_rate(comparables: Iterable[Mapping], *,
                        config: Optional[MarketRateConfig] = None,
                        audit_store=None, audit_config=None) -> Dict:
    """Compute an adopted land rate range from comparable transactions.

    Returns ``adopted_rate`` ({low, base, high}), the supporting ``statistics``
    (median, weighted average, percentiles, min/max), the per-comparable
    ``rates``, and the ``excluded`` outlier ids. Records an optional non-blocking
    ``market_rate_adopted`` audit event.
    """
    config = config or DEFAULT_MARKET_RATE_CONFIG
    comparables = list(comparables)

    items: List[Dict] = []
    rates: List[Dict] = []
    skipped: List = []
    for comparable in comparables:
        cid = comparable.get("comparable_id")
        rate = _adjusted_central(comparable)
        if rate is None:
            skipped.append(cid)
            continue
        weight = comparable.get(config.weight_field)
        weight = float(weight) if _is_number(weight) else 1.0
        items.append({"id": cid, "value": rate, "weight": weight})
        rates.append({"comparable_id": cid, "adjusted_rate": rate,
                      "weight": weight})

    if not items:
        return {"adopted_rate": {"low": None, "base": None, "high": None},
                "statistics": {"count": 0}, "rates": rates,
                "excluded": [], "skipped": skipped,
                "basis": "comparable market engine — no computable rates",
                "deliverable": "adopted land rate range"}

    reduced = aggregate_rates(
        items, outlier_method=config.outlier_method, iqr_k=config.iqr_k,
        central=config.central, range_basis=config.range_basis,
        low_pct=config.low_pct, high_pct=config.high_pct,
        rounding=config.rounding)

    result = {
        "adopted_rate": reduced["adopted"],
        "statistics": reduced["statistics"],
        "rates": rates,
        "excluded": reduced["excluded"],
        "skipped": skipped,
        "notes": reduced["notes"],
        "deliverable": "adopted land rate range",
        "basis": ("comparable market engine — adopted land rate range from "
                  "adjusted comparable evidence; supports the land value "
                  "calculation"),
    }

    if audit_store is not None:
        record_event(
            "valuation", None, "market_rate_adopted",
            before=None, after={"adopted_rate": result["adopted_rate"],
                                "included": reduced["included"],
                                "excluded": reduced["excluded"]},
            rationale="comparable market engine adopted land rate",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG)

    return result
