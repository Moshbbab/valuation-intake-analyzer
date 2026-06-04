"""NOI Builder — net-operating-income calculation support.

Builds NOI transparently: Potential Gross Income → less vacancy & collection
loss → plus other income → Effective Gross Income → less operating expenses →
less optional reserves → NOI, with a per-line breakdown and explanation.

It is calculation support only: no adopted/stabilized NOI, no cap rate, no
value, no opinion. Overrides are intentionally *not* implemented here — adjust
vacancy/expense/reserve inputs through assumption-backed values and record
changes via the Audit Trail rather than duplicating override semantics.

Avoid rigid systems: income and expense categories are caller-supplied line
items (no fixed categories), there is no default vacancy rate or expense ratio,
reserves apply only when provided, and the summation strategy is configurable or
callable.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.config import DEFAULT_NOI_CONFIG, NOIConfig


class NOIError(ValueError):
    """Raised when NOI inputs are invalid."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _amount(item: Mapping, config: NOIConfig) -> float:
    """Read a line item's amount via the configured field; 0.0 if absent."""
    value = item.get(config.amount_field)
    return float(value) if _is_number(value) else 0.0


def _aggregate(amounts: List[float], config: NOIConfig) -> float:
    """Combine amounts with the built-in 'sum' or an injected callable."""
    if callable(config.aggregation):
        return float(config.aggregation(amounts))
    if config.aggregation == "sum":
        return float(sum(amounts))
    raise NOIError(f"Unknown aggregation strategy: {config.aggregation!r}")


def _round(value, config: NOIConfig):
    if config.rounding is not None and _is_number(value):
        return round(value, config.rounding)
    return value


def _coerce_income(value, config: NOIConfig) -> float:
    """Accept a number, a list of line items, or None for other income."""
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple)):
        return _aggregate([_amount(item, config) for item in value], config)
    return float(value) if _is_number(value) else 0.0


def _vacancy_loss(pgi: float, vacancy, config: NOIConfig) -> float:
    """Vacancy/collection loss. No default rate — must be stated explicitly.

    ``vacancy`` may be:
      * None -> 0.0
      * {"type": "rate", "value": fraction}  -> pgi * fraction
      * {"type": "absolute", "value": amount} -> amount
      * a bare number -> treated as an absolute amount (no implicit rate)
    """
    if vacancy is None:
        return 0.0
    if isinstance(vacancy, Mapping):
        value = vacancy.get("value")
        if not _is_number(value):
            return 0.0
        vtype = vacancy.get("type")
        if vtype == "rate":
            return pgi * value
        if vtype == "absolute":
            return float(value)
        raise NOIError(f"Unknown vacancy type: {vtype!r}")
    if _is_number(vacancy):
        return float(vacancy)
    return 0.0


def potential_gross_income(income_items: Iterable[Mapping], *,
                           config: Optional[NOIConfig] = None) -> float:
    """Sum the supplied income line items into Potential Gross Income."""
    config = config or DEFAULT_NOI_CONFIG
    return _aggregate([_amount(item, config) for item in income_items], config)


def total_operating_expenses(expense_items: Iterable[Mapping], *,
                             config: Optional[NOIConfig] = None) -> float:
    """Sum the supplied operating-expense line items."""
    config = config or DEFAULT_NOI_CONFIG
    return _aggregate([_amount(item, config) for item in expense_items], config)


def effective_gross_income(income_items: Iterable[Mapping], *,
                           vacancy=None, other_income=None,
                           config: Optional[NOIConfig] = None) -> float:
    """EGI = PGI − vacancy/collection loss + other income."""
    config = config or DEFAULT_NOI_CONFIG
    pgi = potential_gross_income(income_items, config=config)
    loss = _vacancy_loss(pgi, vacancy, config)
    other = _coerce_income(other_income, config)
    return pgi - loss + other


def build_noi(inputs: Mapping, *,
              config: Optional[NOIConfig] = None,
              audit_store: Any = None,
              audit_config: Any = None) -> Dict:
    """Build NOI from ``inputs`` and return the full calculation support.

    ``inputs`` keys: ``income_items`` (list), ``vacancy`` (rate/absolute/None),
    ``other_income`` (number/list/None), ``expense_items`` (list), and optional
    ``reserves`` (number). Returns the build-up, a line-item breakdown, an
    explanation and an explicit non-opinion ``basis``. When ``audit_store`` is
    given, a single ``noi_built`` event is recorded (vocabulary stays
    injectable; defaults to unrestricted so the Audit Trail is unchanged).
    """
    config = config or DEFAULT_NOI_CONFIG
    income_items = list(inputs.get("income_items", []))
    expense_items = list(inputs.get("expense_items", []))
    vacancy = inputs.get("vacancy")
    other_income = inputs.get("other_income")
    reserves_raw = inputs.get("reserves")

    pgi = potential_gross_income(income_items, config=config)
    vacancy_loss = _vacancy_loss(pgi, vacancy, config)
    other = _coerce_income(other_income, config)
    egi = pgi - vacancy_loss + other
    opex = total_operating_expenses(expense_items, config=config)
    reserves = float(reserves_raw) if _is_number(reserves_raw) else 0.0
    noi = egi - opex - reserves

    breakdown = {
        "income_items": [
            {"name": item.get(config.name_field), "amount": _amount(item, config)}
            for item in income_items],
        "expense_items": [
            {"name": item.get(config.name_field), "amount": _amount(item, config)}
            for item in expense_items],
        "reserves_provided": _is_number(reserves_raw),
    }

    explanation = [
        f"PGI={_round(pgi, config)}",
        f"vacancy_loss={_round(vacancy_loss, config)}",
        f"other_income={_round(other, config)}",
        f"EGI={_round(egi, config)}",
        f"operating_expenses={_round(opex, config)}",
        f"reserves={_round(reserves, config)}",
        f"NOI={_round(noi, config)}",
    ]

    result = {
        "potential_gross_income": _round(pgi, config),
        "vacancy_loss": _round(vacancy_loss, config),
        "other_income": _round(other, config),
        "effective_gross_income": _round(egi, config),
        "operating_expenses": _round(opex, config),
        "reserves": _round(reserves, config),
        "noi": _round(noi, config),
        "breakdown": breakdown,
        "explanation": explanation,
        "basis": ("calculation support — net operating income build-up; "
                  "not an adopted NOI, cap rate or value opinion"),
    }

    if audit_store is not None:
        record_event(
            "noi", inputs.get("property_id"), "noi_built",
            before=None,
            after={"potential_gross_income": result["potential_gross_income"],
                   "effective_gross_income": result["effective_gross_income"],
                   "noi": result["noi"]},
            rationale="NOI build-up calculation support",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return result
