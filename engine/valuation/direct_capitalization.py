"""Direct Capitalization — value-indication calculation support.

Capitalizes a caller-supplied NOI at a caller-supplied cap rate:
``value = NOI / cap_rate``. Also supports a value range from a cap-rate range
and a sensitivity grid over caller-supplied rates.

Calculation support only: no adopted value, no valuation opinion, no cap-rate
derivation/build-up, no market default, no risk/growth/exit assumptions, no DCF
or reconciliation. Cap rate selection is professional judgment and stays with
the appraiser — this module only does the arithmetic on values it is given.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import DEFAULT_DIRECT_CAP_CONFIG, DirectCapConfig


class DirectCapError(ValueError):
    """Raised when capitalization inputs are invalid."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, config: DirectCapConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _require_cap_rate(cap_rate) -> float:
    """Validate a caller-supplied cap rate; never substitute a default."""
    if not _is_number(cap_rate):
        raise DirectCapError("cap_rate must be a number (caller-supplied)")
    if cap_rate <= 0:
        raise DirectCapError("cap_rate must be greater than 0")
    return float(cap_rate)


def _require_noi(noi) -> float:
    if not _is_number(noi):
        raise DirectCapError("noi must be a number (caller-supplied)")
    return float(noi)


def capitalize(noi: float, cap_rate: float, *,
               config: Optional[DirectCapConfig] = None) -> float:
    """Capitalize NOI at a cap rate: ``value = NOI / cap_rate``.

    Both are caller-supplied. Raises when ``cap_rate <= 0`` or inputs are not
    numbers. No default cap rate is ever applied.
    """
    config = config or DEFAULT_DIRECT_CAP_CONFIG
    noi = _require_noi(noi)
    rate = _require_cap_rate(cap_rate)
    return _round(noi / rate, config)


def value_from_cap_rate_range(noi: float, cap_rate_range: Mapping, *,
                              config: Optional[DirectCapConfig] = None) -> Dict:
    """Value range from a caller-supplied cap-rate range ``{low, high}``.

    A lower cap rate yields a higher value, so by default the returned
    ``{low, high}`` is sorted ascending by value. Both bound rates must be > 0.
    """
    config = config or DEFAULT_DIRECT_CAP_CONFIG
    if not isinstance(cap_rate_range, Mapping):
        raise DirectCapError("cap_rate_range must be a mapping with low/high")
    low_rate = _require_cap_rate(cap_rate_range.get("low"))
    high_rate = _require_cap_rate(cap_rate_range.get("high"))
    noi = _require_noi(noi)

    value_a = noi / low_rate
    value_b = noi / high_rate
    if config.sort_range:
        low_value, high_value = sorted((value_a, value_b))
    else:
        low_value, high_value = value_a, value_b
    return {"low": _round(low_value, config), "high": _round(high_value, config)}


def sensitivity_grid(noi: float, cap_rates: Iterable[float], *,
                     config: Optional[DirectCapConfig] = None) -> List[Dict]:
    """Value at each caller-supplied cap rate. No fixed bands are generated.

    Rates with values <= 0 are reported with an ``error`` entry rather than
    aborting the whole grid.
    """
    config = config or DEFAULT_DIRECT_CAP_CONFIG
    noi = _require_noi(noi)
    grid: List[Dict] = []
    for rate in cap_rates:
        if _is_number(rate) and rate > 0:
            grid.append({"cap_rate": rate,
                         "value": _round(noi / float(rate), config)})
        else:
            grid.append({"cap_rate": rate, "value": None,
                         "error": "cap_rate must be greater than 0"})
    return grid


def direct_capitalization(inputs: Mapping, *,
                          config: Optional[DirectCapConfig] = None,
                          audit_store: Any = None,
                          audit_config: Any = None) -> Dict:
    """Produce a direct-capitalization value indication (calculation support).

    ``inputs`` keys: ``noi`` (required), and at least one of ``cap_rate``,
    ``cap_rate_range`` ({low, high}) or ``cap_rates`` (iterable for sensitivity).
    Returns the echoed NOI, the cap rate/range used, the value indication and/or
    value range, the sensitivity grid, an explanation and an explicit non-opinion
    ``basis``. When ``audit_store`` is given a single ``capitalized`` event is
    recorded (vocabulary stays injectable; defaults to unrestricted, so the
    Audit Trail is unchanged). Audit is computed after the result and cannot
    affect it.
    """
    config = config or DEFAULT_DIRECT_CAP_CONFIG
    noi = _require_noi(inputs.get("noi"))
    cap_rate = inputs.get("cap_rate")
    cap_rate_range = inputs.get("cap_rate_range")
    cap_rates = inputs.get("cap_rates")

    if cap_rate is None and cap_rate_range is None and cap_rates is None:
        raise DirectCapError(
            "supply at least one of cap_rate, cap_rate_range or cap_rates")

    value_indication = (capitalize(noi, cap_rate, config=config)
                        if cap_rate is not None else None)
    value_range = (value_from_cap_rate_range(noi, cap_rate_range, config=config)
                   if cap_rate_range is not None else None)
    sensitivity = (sensitivity_grid(noi, cap_rates, config=config)
                   if cap_rates is not None else None)

    explanation = [f"noi={_round(noi, config)}"]
    if value_indication is not None:
        explanation.append(f"value = noi / cap_rate = {_round(noi, config)} "
                           f"/ {cap_rate} = {value_indication}")
    if value_range is not None:
        explanation.append(f"value_range from cap_rate_range {cap_rate_range} "
                           f"= {value_range}")
    if sensitivity is not None:
        explanation.append(f"sensitivity over {len(sensitivity)} caller rates")

    result = {
        "noi": _round(noi, config),
        "cap_rate": cap_rate,
        "cap_rate_range": cap_rate_range,
        "value_indication": value_indication,
        "value_range": value_range,
        "sensitivity": sensitivity,
        "explanation": explanation,
        "basis": ("calculation support — direct capitalization value "
                  "indication; not an adopted value or valuation opinion"),
    }

    if audit_store is not None:
        record_event(
            "valuation", inputs.get("property_id"), "capitalized",
            before=None,
            after={"noi": result["noi"], "cap_rate": cap_rate,
                   "value_indication": value_indication,
                   "value_range": value_range},
            rationale="direct capitalization calculation support",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return result
