"""Shared rate-aggregation support for the valuation production engines.

Both the Comparable Market Engine (land rate/m^2) and the Cap Rate Engine
(implied NOI/price yields) reduce a set of evidence-derived rates into an
adopted ``{low, base, high}`` range with supporting statistics.

Governing principle (non-negotiable constraint): statistical outlier detection
is a WARNING SIGNAL only. By default (``outlier_action="flag"``) outliers are
flagged and reported but NEVER removed — the exclusion decision belongs to the
appraiser. Automatic exclusion happens only under explicit configuration
(``outlier_action="exclude"``) and is then surfaced loudly in ``warnings``.
Documented manual overrides (force include/exclude with rationale and actor)
always win over the automatic treatment, and the automatic result is retained.
"""

from typing import Callable, Dict, List, Mapping, Optional, Tuple, Union


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


def detect_outliers(items: List[Dict], method: Union[str, Callable],
                    iqr_k: float) -> Tuple[List, List[str]]:
    """Return (flagged_ids, notes) — detection only, never removal."""
    if callable(method):
        keep = set(method(items))
        return [it["id"] for it in items if it["id"] not in keep], []
    if method == "none":
        return [], []
    if method != "iqr":
        raise ValueError(f"Unknown outlier_method: {method!r}")
    if len(items) < 4:
        return [], [f"outlier detection skipped (n={len(items)} < 4 for IQR)"]
    values = sorted(it["value"] for it in items)
    q1 = _percentile(values, 25.0)
    q3 = _percentile(values, 75.0)
    iqr = q3 - q1
    if iqr == 0:
        return [], ["outlier detection skipped (zero IQR)"]
    low_fence, high_fence = q1 - iqr_k * iqr, q3 + iqr_k * iqr
    flagged = [it["id"] for it in items
               if not low_fence <= it["value"] <= high_fence]
    return flagged, []


def _apply_decisions(items: List[Dict], flagged: List, outlier_action: str,
                     overrides: Optional[Mapping]):
    """Resolve the evidence set: flag-only default, explicit exclude, overrides.

    Returns (included, excluded, warnings, override_report). Overrides always
    win and are reported with the automatic treatment retained.
    """
    overrides = overrides or {}
    force_include = set(overrides.get("force_include", ()))
    force_exclude = set(overrides.get("force_exclude", ()))
    warnings: List[str] = []

    if outlier_action == "flag":
        auto_excluded_ids: set = set()
        if flagged:
            warnings.append(
                f"{len(flagged)} outlier(s) flagged, NOT excluded: {flagged} — "
                "exclusion is the appraiser's decision")
    elif outlier_action == "exclude":
        auto_excluded_ids = set(flagged)
        if flagged:
            warnings.append(
                f"{len(flagged)} outlier(s) EXCLUDED by explicit configuration "
                f"(outlier_action='exclude'): {flagged}")
    else:
        raise ValueError(f"Unknown outlier_action: {outlier_action!r}")

    excluded_ids = (auto_excluded_ids - force_include) | force_exclude
    included = [it for it in items if it["id"] not in excluded_ids]
    excluded = [it for it in items if it["id"] in excluded_ids]

    override_report: Dict = {}
    if force_include or force_exclude:
        override_report = {
            "force_include": sorted(force_include),
            "force_exclude": sorted(force_exclude),
            "rationale": overrides.get("rationale"),
            "actor": overrides.get("actor"),
            "auto_excluded": sorted(auto_excluded_ids),
        }
        warnings.append(
            f"manual override applied by {overrides.get('actor')!r}: "
            f"+{sorted(force_include)} -{sorted(force_exclude)} "
            f"(rationale: {overrides.get('rationale')!r})")
    return included, excluded, warnings, override_report


def _round(value, rounding: Optional[int]):
    if rounding is not None and _is_number(value):
        return round(value, rounding)
    return value


def aggregate_rates(items: List[Dict], *, outlier_method: Union[str, Callable],
                    iqr_k: float, central: Union[str, Callable],
                    range_basis: str, low_pct: float, high_pct: float,
                    rounding: Optional[int],
                    outlier_action: str = "flag",
                    overrides: Optional[Mapping] = None) -> Dict:
    """Reduce ``items`` ({id, value, weight}) into an adopted range + stats.

    Outliers are detected and FLAGGED by default; they are excluded only when
    ``outlier_action="exclude"`` is explicitly configured or a documented
    manual override says so. Returns ``adopted`` ({low, base, high}),
    ``statistics``, ``outlier_flags``, ``warnings``, ``record_count`` and the
    ``included``/``excluded`` id lists.
    """
    flagged, notes = detect_outliers(items, outlier_method, iqr_k)
    included, excluded, warnings, override_report = _apply_decisions(
        items, flagged, outlier_action, overrides)

    base_result = {
        "outlier_flags": flagged,
        "warnings": warnings,
        "notes": notes,
        "record_count": len(items),
        "included": [it["id"] for it in included],
        "excluded": [it["id"] for it in excluded],
        "overrides_applied": override_report,
    }

    if not included:
        warnings.append("ZERO OUTPUT: no included rates after decisions — "
                        "review exclusions/overrides before relying on this")
        return {**base_result,
                "adopted": {"low": None, "base": None, "high": None},
                "statistics": {"count": 0}}

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
    return {**base_result,
            "adopted": {"low": _round(low, rounding),
                        "base": _round(base, rounding),
                        "high": _round(high, rounding)},
            "statistics": statistics}
