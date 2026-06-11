"""Shared rate-aggregation support for the valuation production engines.

Both the Comparable Market Engine (land rate/m^2) and the Cap Rate Engine
(implied NOI/price yields) reduce a set of evidence-derived rates into an
adopted ``{low, base, high}`` range with supporting statistics. That reduction
— optional outlier exclusion, central recommendation, and range bounds — lives
here so the two engines stay consistent. No rate is ever assumed; everything is
computed from the supplied values only.
"""

from typing import Callable, Dict, List, Optional, Tuple, Union


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low_index = int(rank)
    high_index = min(low_index + 1, len(sorted_values) - 1)
    fraction = rank - low_index
    return (sorted_values[low_index] * (1 - fraction)
            + sorted_values[high_index] * fraction)


def _median(sorted_values: List[float]) -> float:
    return _percentile(sorted_values, 50.0)


def _weighted_mean(items: List[Tuple[float, float]]) -> Optional[float]:
    total_w = sum(weight for _, weight in items)
    if total_w <= 0:
        return sum(value for value, _ in items) / len(items) if items else None
    return sum(value * weight for value, weight in items) / total_w


def _exclude_outliers(items: List[Dict], method: Union[str, Callable],
                      iqr_k: float) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Return (included, excluded, notes) per the configured method."""
    if callable(method):
        keep = set(method(items))
        included = [it for it in items if it["id"] in keep]
        excluded = [it for it in items if it["id"] not in keep]
        return included, excluded, []
    if method == "none":
        return list(items), [], []
    if method != "iqr":
        raise ValueError(f"Unknown outlier_method: {method!r}")
    if len(items) < 4:
        return list(items), [], [f"outlier exclusion skipped (n={len(items)} "
                                 "< 4 for IQR)"]
    values = sorted(it["value"] for it in items)
    q1 = _percentile(values, 25.0)
    q3 = _percentile(values, 75.0)
    iqr = q3 - q1
    if iqr == 0:
        return list(items), [], ["outlier exclusion skipped (zero IQR)"]
    low_fence, high_fence = q1 - iqr_k * iqr, q3 + iqr_k * iqr
    included = [it for it in items if low_fence <= it["value"] <= high_fence]
    excluded = [it for it in items if not low_fence <= it["value"] <= high_fence]
    return included, excluded, []


def _round(value, rounding: Optional[int]):
    if rounding is not None and _is_number(value):
        return round(value, rounding)
    return value


def aggregate_rates(items: List[Dict], *, outlier_method: Union[str, Callable],
                    iqr_k: float, central: Union[str, Callable],
                    range_basis: str, low_pct: float, high_pct: float,
                    rounding: Optional[int]) -> Dict:
    """Reduce ``items`` ({id, value, weight}) into an adopted range + stats.

    Returns ``adopted`` ({low, base, high}), ``statistics`` (count, mean,
    median, weighted_mean, min, max, the two percentiles), and the
    ``included``/``excluded`` id lists. ``base`` is the central recommendation;
    ``low``/``high`` are the percentile or min/max bounds of the included set.
    """
    included, excluded, notes = _exclude_outliers(items, outlier_method, iqr_k)
    if not included:
        return {"adopted": {"low": None, "base": None, "high": None},
                "statistics": {"count": 0},
                "included": [], "excluded": [it["id"] for it in excluded],
                "notes": notes + ["no included rates after exclusion"]}

    values = sorted(it["value"] for it in included)
    weighted_pairs = [(it["value"], it["weight"]) for it in included]
    mean = sum(values) / len(values)
    weighted = _weighted_mean(weighted_pairs)
    median = _median(values)
    p_low = _percentile(values, low_pct)
    p_high = _percentile(values, high_pct)

    if callable(central):
        base = central(included)
    elif central == "weighted_mean":
        base = weighted
    elif central == "median":
        base = median
    elif central == "mean":
        base = mean
    else:
        raise ValueError(f"Unknown central strategy: {central!r}")

    if range_basis == "percentile":
        low, high = p_low, p_high
    elif range_basis == "min_max":
        low, high = values[0], values[-1]
    else:
        raise ValueError(f"Unknown range_basis: {range_basis!r}")

    statistics = {
        "count": len(included),
        "mean": _round(mean, rounding),
        "median": _round(median, rounding),
        "weighted_mean": _round(weighted, rounding),
        "min": _round(values[0], rounding),
        "max": _round(values[-1], rounding),
        f"p{int(low_pct)}": _round(p_low, rounding),
        f"p{int(high_pct)}": _round(p_high, rounding),
    }
    return {
        "adopted": {"low": _round(low, rounding), "base": _round(base, rounding),
                    "high": _round(high, rounding)},
        "statistics": statistics,
        "included": [it["id"] for it in included],
        "excluded": [it["id"] for it in excluded],
        "notes": notes,
    }
