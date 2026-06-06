"""Cross-Approach Agreement / Dispersion — calculation support.

Given the same approach value indications consumed by reconciliation, this
quantifies how tightly the approaches agree: spread, standard deviation,
coefficient of variation, and each approach's deviation from the weighted mean.

Calculation support only. It does NOT emit a confidence label, a reliability
verdict, a pass/fail band or any threshold — it reports the raw dispersion and
leaves the interpretation to the appraiser. It produces no adopted/final value.

Reuse: weight resolution is delegated to
``reconciliation.normalize_approach_weights`` so weighting behaves identically to
reconciliation. The central-figure rule mirrors reconciliation's contract (a
point ``value``, else the midpoint of a ``range``; ``value`` wins when both are
given).
"""

from math import sqrt
from typing import Dict, Iterable, List, Mapping, Optional

from engine.valuation.config import (
    AgreementConfig,
    DEFAULT_AGREEMENT_CONFIG,
)
from engine.valuation.reconciliation import (
    ReconciliationError,
    normalize_approach_weights,
)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, config: AgreementConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _central(indication: Mapping) -> float:
    """Central figure for one indication; mirrors reconciliation's contract."""
    point = indication.get("value")
    range_block = indication.get("range")
    has_point = _is_number(point)
    has_range = (isinstance(range_block, Mapping)
                 and _is_number(range_block.get("low"))
                 and _is_number(range_block.get("high")))
    if has_point:
        return float(point)
    if has_range:
        return (float(range_block["low"]) + float(range_block["high"])) / 2.0
    raise ReconciliationError(
        "each indication needs a numeric 'value' or a 'range' {low, high}")


def _approach_name(indication: Mapping) -> str:
    name = indication.get("approach")
    if not name:
        raise ReconciliationError("each indication needs an 'approach' name")
    return name


def approach_dispersion(indications: Iterable[Mapping], *,
                        config: Optional[AgreementConfig] = None) -> Dict:
    """Return dispersion/agreement metrics across approach indications.

    Reports ``mean`` and ``weighted_mean`` of the approach centrals, the
    ``spread`` (max - min) and its percentage against the configured base, the
    population ``std_dev`` / ``weighted_std_dev``, the ``coefficient_of_variation``
    (std_dev / mean), each approach's ``deviations`` from the weighted mean and
    the ``max_abs_deviation``. Percentages are ``None`` when their base is 0.
    """
    config = config or DEFAULT_AGREEMENT_CONFIG
    indications = list(indications)
    if not indications:
        raise ReconciliationError("at least one approach indication is required")

    weights = normalize_approach_weights(indications)
    centrals: Dict[str, float] = {}
    values: List[float] = []
    for indication in indications:
        approach = _approach_name(indication)
        central = _central(indication)
        centrals[approach] = central
        values.append(central)

    n = len(values)
    mean = sum(values) / n
    weighted_mean = sum(centrals[a] * weights.get(a, 0.0) for a in centrals)
    spread = max(values) - min(values)

    variance = sum((c - mean) ** 2 for c in values) / n
    std_dev = sqrt(variance)
    weighted_variance = sum(weights.get(a, 0.0) * (centrals[a] - weighted_mean) ** 2
                            for a in centrals)
    weighted_std_dev = sqrt(weighted_variance)

    deviations = {a: centrals[a] - weighted_mean for a in centrals}
    max_abs_deviation = max((abs(d) for d in deviations.values()), default=0.0)

    if callable(config.normalize_against):
        base = config.normalize_against(centrals, weights)
    elif config.normalize_against == "weighted_mean":
        base = weighted_mean
    elif config.normalize_against == "mean":
        base = mean
    else:
        raise ReconciliationError(
            f"Unknown normalize_against: {config.normalize_against!r}")

    spread_pct = (spread / base) if base else None
    coefficient_of_variation = (std_dev / mean) if mean else None

    return {
        "n": n,
        "centrals": {a: _round(c, config) for a, c in centrals.items()},
        "weights": dict(weights),
        "mean": _round(mean, config),
        "weighted_mean": _round(weighted_mean, config),
        "spread": _round(spread, config),
        "spread_pct": _round(spread_pct, config),
        "std_dev": _round(std_dev, config),
        "weighted_std_dev": _round(weighted_std_dev, config),
        "coefficient_of_variation": _round(coefficient_of_variation, config),
        "deviations": {a: _round(d, config) for a, d in deviations.items()},
        "max_abs_deviation": _round(max_abs_deviation, config),
        "basis": ("calculation support — agreement/dispersion metrics across "
                  "approach indications; not a confidence opinion, reliability "
                  "verdict or adopted value"),
    }
