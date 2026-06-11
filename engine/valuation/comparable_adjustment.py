"""Comparable Adjustment Engine — dimension-specific adjusted price/m^2.

Computes the classic appraisal adjustment grid: time, location, size, frontage
and use adjustments derived from the subject-vs-comparable attribute
differences, then combines them onto the comparable's unit rate to yield an
adjusted price/m^2.

Each dimension is driven by a caller-supplied sensitivity coefficient — the
engine performs the mechanics and assumes no market movement or coefficient
itself (all default to 0 = no adjustment). The sign and magnitude of every
adjustment are the appraiser's assumption; nothing is hard-coded.
"""

from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional

from engine.valuation.config import (
    AdjustmentEngineConfig,
    DEFAULT_ADJUSTMENT_ENGINE_CONFIG,
)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _round(value, config: AdjustmentEngineConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


# ─── Per-dimension adjustments (each returns a relative pct, e.g. 0.05 == +5%) ─

def time_adjustment(subject: Mapping, comparable: Mapping,
                    config: AdjustmentEngineConfig) -> float:
    """Market movement between the comparable's sale date and the valuation date."""
    if not config.annual_market_trend:
        return 0.0
    comp_date = _as_date(comparable.get(config.date_field))
    val_date = _as_date(config.valuation_date or subject.get("valuation_date"))
    if comp_date is None or val_date is None:
        return 0.0
    years = (val_date - comp_date).days / 365.25
    return (1 + config.annual_market_trend) ** years - 1


def location_adjustment(subject: Mapping, comparable: Mapping,
                        config: AdjustmentEngineConfig) -> float:
    """Location-score difference (subject - comparable) x sensitivity."""
    subj = subject.get("location_score")
    comp = comparable.get("location_score")
    if not (_is_number(subj) and _is_number(comp)) or not config.location_sensitivity:
        return 0.0
    diff = (subj - comp) / (config.location_scale or 1.0)
    return diff * config.location_sensitivity


def size_adjustment(subject: Mapping, comparable: Mapping,
                    config: AdjustmentEngineConfig) -> float:
    """Relative area difference (comparable vs subject) x sensitivity."""
    subj = subject.get("area")
    comp = comparable.get("area")
    if not (_is_number(subj) and _is_number(comp)) or subj <= 0 \
            or not config.size_sensitivity:
        return 0.0
    return ((comp - subj) / subj) * config.size_sensitivity


def frontage_adjustment(subject: Mapping, comparable: Mapping,
                        config: AdjustmentEngineConfig) -> float:
    """Relative frontage difference (subject vs comparable) x sensitivity."""
    subj = subject.get("frontage")
    comp = comparable.get("frontage")
    if not (_is_number(subj) and _is_number(comp)) or subj <= 0 \
            or not config.frontage_sensitivity:
        return 0.0
    return ((subj - comp) / subj) * config.frontage_sensitivity


def use_adjustment(subject: Mapping, comparable: Mapping,
                   config: AdjustmentEngineConfig) -> float:
    """Categorical use adjustment from the configured (comp_use, subj_use) map."""
    subj = subject.get("use")
    comp = comparable.get("use")
    if subj is None or comp is None:
        return 0.0
    if str(subj).strip().lower() == str(comp).strip().lower():
        return 0.0
    mapping = config.use_adjustment_map or {}
    key = (str(comp).strip().lower(), str(subj).strip().lower())
    value = mapping.get(key)
    return float(value) if _is_number(value) else 0.0


_DIMENSIONS = {
    "time": time_adjustment,
    "location": location_adjustment,
    "size": size_adjustment,
    "frontage": frontage_adjustment,
    "use": use_adjustment,
}


def _combine(base: float, pct_by_dim: Mapping,
             config: AdjustmentEngineConfig) -> float:
    if callable(config.combination):
        return config.combination(base, pct_by_dim)
    if config.combination == "multiplicative":
        factor = 1.0
        for pct in pct_by_dim.values():
            factor *= (1 + pct)
        return base * factor
    if config.combination == "additive":
        return base * (1 + sum(pct_by_dim.values()))
    raise ValueError(f"Unknown combination: {config.combination!r}")


def adjust_comparable(subject: Mapping, comparable: Mapping, *,
                      config: Optional[AdjustmentEngineConfig] = None) -> Dict:
    """Adjust one comparable to the subject; return the adjusted price/m^2.

    Returns the ``base_rate``, the per-dimension ``adjustments`` (each a relative
    pct), the ``gross_adjustment`` (sum of absolute pcts), the ``net_adjustment``
    and the ``adjusted_rate``. Returns ``adjusted_rate`` None when the comparable
    has no numeric ``unit_rate``.
    """
    config = config or DEFAULT_ADJUSTMENT_ENGINE_CONFIG
    base = comparable.get("unit_rate")
    pct_by_dim = {name: func(subject, comparable, config)
                  for name, func in _DIMENSIONS.items()}

    if not _is_number(base):
        return {"comparable_id": comparable.get("comparable_id"),
                "base_rate": base, "adjustments": pct_by_dim,
                "gross_adjustment": None, "net_adjustment": None,
                "adjusted_rate": None,
                "note": "no numeric unit_rate; cannot compute adjusted rate"}

    adjusted = _combine(float(base), pct_by_dim, config)
    gross = sum(abs(pct) for pct in pct_by_dim.values())
    return {
        "comparable_id": comparable.get("comparable_id"),
        "base_rate": base,
        "adjustments": {name: _round(pct, config)
                        for name, pct in pct_by_dim.items()},
        "gross_adjustment": _round(gross, config),
        "net_adjustment": _round(adjusted / base - 1.0, config),
        "adjusted_rate": _round(adjusted, config),
    }


def adjustment_grid(subject: Mapping, comparables: Iterable[Mapping], *,
                    config: Optional[AdjustmentEngineConfig] = None) -> Dict:
    """Run the adjustment engine across a set of comparables.

    Returns the per-comparable ``rows`` (each with its adjusted price/m^2) and a
    convenience ``adjusted_rates`` list keyed by comparable id — ready to feed
    the Comparable Market Engine via its ``adjusted_rate`` field.
    """
    config = config or DEFAULT_ADJUSTMENT_ENGINE_CONFIG
    rows: List[Dict] = [adjust_comparable(subject, comp, config=config)
                        for comp in comparables]
    adjusted_rates = [{"comparable_id": row["comparable_id"],
                       "adjusted_rate": row["adjusted_rate"]}
                      for row in rows if row["adjusted_rate"] is not None]
    return {
        "rows": rows,
        "adjusted_rates": adjusted_rates,
        "dimensions": list(_DIMENSIONS.keys()),
        "deliverable": "adjusted price/m^2 per comparable",
        "basis": ("comparable adjustment engine — time/location/size/frontage/"
                  "use adjustments to adjusted price/m^2; sensitivities are "
                  "caller-supplied assumptions, not market judgments"),
    }
