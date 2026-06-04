"""Discounted Cash Flow — present-value calculation support.

Discounts a caller-supplied stream of period cash flows at a caller-supplied
discount rate and adds the present value of a caller-defined reversion (either
an explicit amount or a terminal NOI capitalized at a caller-supplied exit cap
rate). Also supports sensitivity over caller-supplied rate sets.

Calculation support only: no adopted/final value, no valuation opinion, no
default/derived discount rate, no market default, no automatic growth, no
default exit cap rate, no reconciliation. Every economic input — cash flows,
discount rate, growth, exit cap rate, horizon, scenarios — is the appraiser's
professional judgment; this module only does the arithmetic it is given.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import DCFConfig, DEFAULT_DCF_CONFIG
from engine.valuation.direct_capitalization import capitalize


class DCFError(ValueError):
    """Raised when DCF inputs are invalid."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, config: DCFConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _require_rate(rate, name: str) -> float:
    """Validate a caller-supplied rate so that 1 + rate > 0; no default."""
    if not _is_number(rate):
        raise DCFError(f"{name} must be a number (caller-supplied)")
    if 1 + rate <= 0:
        raise DCFError(f"{name} must be greater than -1")
    return float(rate)


def discount_factor(rate: float, period: int, *,
                    config: Optional[DCFConfig] = None) -> float:
    """Discount factor 1 / (1 + rate) ** period (or an injected convention)."""
    config = config or DEFAULT_DCF_CONFIG
    if config.discount_factor is not None:
        return float(config.discount_factor(rate, period))
    rate = _require_rate(rate, "discount_rate")
    return 1.0 / ((1.0 + rate) ** period)


def _period_factors(discount_rate, count: int,
                    config: DCFConfig) -> List[float]:
    """Cumulative discount factor for each period 1..count.

    ``discount_rate`` may be a scalar (applied every period) or a per-period
    sequence (cumulative product of 1/(1+r_i)).
    """
    if isinstance(discount_rate, (list, tuple)):
        if len(discount_rate) < count:
            raise DCFError("per-period discount_rate shorter than cash_flows")
        factors = []
        cumulative = 1.0
        for index in range(count):
            rate = _require_rate(discount_rate[index], "discount_rate")
            cumulative *= 1.0 / (1.0 + rate)
            factors.append(cumulative)
        return factors
    return [discount_factor(discount_rate, period, config=config)
            for period in range(1, count + 1)]


def present_value(cash_flows: Iterable[float], discount_rate, *,
                  config: Optional[DCFConfig] = None) -> float:
    """Present value of a period cash-flow stream (period 1..n).

    ``discount_rate`` is caller-supplied — scalar or per-period sequence. No
    default rate is applied.
    """
    config = config or DEFAULT_DCF_CONFIG
    flows = list(cash_flows)
    factors = _period_factors(discount_rate, len(flows), config)
    total = sum(float(flow) * factor for flow, factor in zip(flows, factors))
    return _round(total, config)


def reversion_value(inputs: Mapping, *,
                    config: Optional[DCFConfig] = None) -> Dict:
    """Terminal/reversion value — caller chooses the mode (no default).

    Modes:
      * explicit: ``{"amount": value}``
      * capitalized: ``{"terminal_noi": noi, "exit_cap_rate": rate}`` →
        capitalizes via the Direct Capitalization identity (exit cap rate must
        be > 0, caller-supplied).
    """
    config = config or DEFAULT_DCF_CONFIG
    if "amount" in inputs and inputs.get("amount") is not None:
        amount = inputs["amount"]
        if not _is_number(amount):
            raise DCFError("reversion amount must be a number")
        return {"reversion": _round(float(amount), config), "method": "explicit"}
    if inputs.get("terminal_noi") is not None \
            and inputs.get("exit_cap_rate") is not None:
        reversion = capitalize(inputs["terminal_noi"], inputs["exit_cap_rate"])
        return {"reversion": _round(reversion, config),
                "method": "capitalized",
                "exit_cap_rate": inputs["exit_cap_rate"]}
    raise DCFError("reversion needs 'amount' or 'terminal_noi'+'exit_cap_rate'")


def discounted_cash_flow(inputs: Mapping, *,
                         config: Optional[DCFConfig] = None,
                         audit_store: Any = None,
                         audit_config: Any = None) -> Dict:
    """Produce a DCF value indication (calculation support).

    ``inputs`` keys: ``cash_flows`` (required list, period 1..n),
    ``discount_rate`` (required scalar or per-period sequence), and optional
    ``reversion`` (an explicit/capitalized spec). Optional ``reversion_period``
    sets when the reversion is received (defaults to the last cash-flow period).
    Returns PV of the flows, PV of the reversion, the ``value_indication``, a
    per-period breakdown, an explanation and an explicit non-opinion ``basis``.
    A ``dcf_valued`` audit event is recorded only when ``audit_store`` is given;
    the result is computed before the audit call and cannot be affected by it.
    """
    config = config or DEFAULT_DCF_CONFIG
    if "cash_flows" not in inputs or inputs.get("cash_flows") is None:
        raise DCFError("cash_flows is required (caller-supplied)")
    if "discount_rate" not in inputs or inputs.get("discount_rate") is None:
        raise DCFError("discount_rate is required (caller-supplied)")

    flows = list(inputs["cash_flows"])
    discount_rate = inputs["discount_rate"]
    factors = _period_factors(discount_rate, len(flows), config)

    breakdown = []
    pv_flows = 0.0
    for index, (flow, factor) in enumerate(zip(flows, factors), start=1):
        pv = float(flow) * factor
        pv_flows += pv
        breakdown.append({"period": index, "cash_flow": flow,
                          "discount_factor": _round(factor, config),
                          "present_value": _round(pv, config)})

    pv_reversion = 0.0
    reversion = None
    if inputs.get("reversion") is not None:
        reversion = reversion_value(inputs["reversion"], config=config)
        period = inputs.get("reversion_period", len(flows))
        rev_factor = (_period_factors(discount_rate, period, config)[period - 1]
                      if period >= 1 else 1.0)
        pv_reversion = reversion["reversion"] * rev_factor
        reversion["present_value"] = _round(pv_reversion, config)
        reversion["period"] = period

    value_indication = pv_flows + pv_reversion

    explanation = [f"pv_cash_flows={_round(pv_flows, config)}",
                   f"pv_reversion={_round(pv_reversion, config)}",
                   f"value_indication={_round(value_indication, config)}"]

    result = {
        "value_indication": _round(value_indication, config),
        "present_value_cash_flows": _round(pv_flows, config),
        "present_value_reversion": _round(pv_reversion, config),
        "reversion": reversion,
        "breakdown": breakdown,
        "explanation": explanation,
        "basis": ("calculation support — discounted cash flow value "
                  "indication; not an adopted value or valuation opinion"),
    }

    if audit_store is not None:
        record_event(
            "valuation", inputs.get("property_id"), "dcf_valued",
            before=None,
            after={"value_indication": result["value_indication"],
                   "present_value_cash_flows": result["present_value_cash_flows"],
                   "present_value_reversion": result["present_value_reversion"]},
            rationale="discounted cash flow calculation support",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return result


def dcf_sensitivity(inputs: Mapping, *,
                    discount_rates: Optional[Iterable[float]] = None,
                    exit_cap_rates: Optional[Iterable[float]] = None,
                    config: Optional[DCFConfig] = None) -> List[Dict]:
    """Sensitivity of the DCF value over caller-supplied rate sets only.

    Varies the discount rate (and/or the reversion's exit cap rate when in
    capitalized mode) across the caller-supplied iterables. No fixed bands are
    generated. Each combination is evaluated independently — this also supports
    scenarios, since a scenario is just a distinct input bundle.
    """
    config = config or DEFAULT_DCF_CONFIG
    discount_rates = list(discount_rates) if discount_rates is not None \
        else [inputs.get("discount_rate")]
    exit_cap_rates = list(exit_cap_rates) if exit_cap_rates is not None else [None]

    grid: List[Dict] = []
    for d_rate in discount_rates:
        for x_rate in exit_cap_rates:
            scenario = dict(inputs)
            scenario["discount_rate"] = d_rate
            if x_rate is not None and isinstance(scenario.get("reversion"),
                                                 Mapping):
                reversion = dict(scenario["reversion"])
                reversion["exit_cap_rate"] = x_rate
                scenario["reversion"] = reversion
            try:
                value = discounted_cash_flow(scenario,
                                             config=config)["value_indication"]
                row = {"discount_rate": d_rate, "value_indication": value}
            except DCFError as error:
                row = {"discount_rate": d_rate, "value_indication": None,
                       "error": str(error)}
            if x_rate is not None:
                row["exit_cap_rate"] = x_rate
            grid.append(row)
    return grid
