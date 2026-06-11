"""Land Value Engine — land market value range (valuation production).

Land value = subject area x adopted rate, evaluated at the low/base/high points
of an adopted rate range (typically from the Comparable Market Engine).

This produces an actual valuation number: the land market value range. The rate
is always caller-supplied; nothing about the market is assumed here.
"""

from typing import Dict, Iterable, Mapping, Optional, Union

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import DEFAULT_LAND_VALUE_CONFIG, LandValueConfig
from engine.valuation.market_rate import adopted_market_rate


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, config: LandValueConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _as_range(rate: Union[Mapping, float]) -> Dict:
    """Normalise a scalar rate or a {low, base, high} mapping to all three."""
    if isinstance(rate, Mapping):
        base = rate.get("base")
        low = rate.get("low", base)
        high = rate.get("high", base)
        return {"low": low, "base": base, "high": high}
    return {"low": rate, "base": rate, "high": rate}


def land_value(area: float, rate: Union[Mapping, float], *,
               config: Optional[LandValueConfig] = None,
               audit_store=None, audit_config=None) -> Dict:
    """Compute the land market value range from area and an adopted rate range.

    ``rate`` is a scalar or ``{low, base, high}``. Returns ``land_value``
    ({low, base, high}) plus the inputs used. Missing/invalid points yield None
    for that point rather than raising.
    """
    config = config or DEFAULT_LAND_VALUE_CONFIG
    rate_range = _as_range(rate)

    if not _is_number(area):
        return {"land_value": {"low": None, "base": None, "high": None},
                "area": area, "rate": rate_range,
                "deliverable": "land market value range",
                "basis": "land value engine — non-numeric area; cannot compute"}

    def _value(point):
        return _round(area * point, config) if _is_number(point) else None

    result = {
        "land_value": {"low": _value(rate_range["low"]),
                       "base": _value(rate_range["base"]),
                       "high": _value(rate_range["high"])},
        "area": area,
        "rate": rate_range,
        "deliverable": "land market value range",
        "basis": ("land value engine — land market value range = area x adopted "
                  "rate; income/other approaches reconciled separately"),
    }

    if audit_store is not None:
        record_event(
            "valuation", None, "land_value_computed",
            before=None, after={"land_value": result["land_value"],
                                "area": area, "rate": rate_range},
            rationale="land value engine area x adopted rate",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG)

    return result


def land_value_from_comparables(comparables: Iterable[Mapping], area: float, *,
                                market_config=None, land_config=None,
                                audit_store=None, audit_config=None) -> Dict:
    """Chain the Comparable Market Engine into the Land Value Engine.

    Returns the land value result with the ``market_rate`` block attached, so a
    caller gets the full path comparables -> adopted rate -> land value in one
    call.
    """
    market = adopted_market_rate(comparables, config=market_config,
                                 audit_store=audit_store,
                                 audit_config=audit_config)
    valued = land_value(area, market["adopted_rate"], config=land_config,
                        audit_store=audit_store, audit_config=audit_config)
    valued["market_rate"] = market
    return valued
