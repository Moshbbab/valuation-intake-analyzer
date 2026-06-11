"""Cap Rate Engine — adopted capitalisation rate (valuation production).

Input: market transactions carrying NOI and price (and/or pre-computed yield
evidence).

Output: implied cap rate (NOI / price) per transaction, the range, and a
weighted recommendation — reduced to an adopted cap-rate range ``{low, base,
high}`` that feeds the Direct Capitalization Engine.

This quantifies a valuation assumption (the adopted cap rate) from supplied
evidence only. No market cap rate is assumed.
"""

from typing import Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation._rate_support import aggregate_rates
from engine.valuation.config import CapRateConfig, DEFAULT_CAP_RATE_CONFIG


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _implied_cap(transaction: Mapping) -> Optional[float]:
    """Implied cap rate for one transaction (explicit yield, or NOI/price)."""
    explicit = transaction.get("cap_rate")
    if _is_number(explicit):
        return float(explicit)
    noi = transaction.get("noi")
    price = transaction.get("price", transaction.get("sale_price"))
    if _is_number(noi) and _is_number(price) and price > 0:
        return noi / price
    return None


def adopted_cap_rate(transactions: Iterable[Mapping], *,
                     config: Optional[CapRateConfig] = None,
                     audit_store=None, audit_config=None) -> Dict:
    """Compute an adopted cap-rate range from market yield evidence.

    Returns ``adopted_cap_rate`` ({low, base, high}), the supporting
    ``statistics``, the per-transaction ``implied_cap_rates``, and the
    ``excluded`` outlier ids. Records an optional ``cap_rate_adopted`` event.
    """
    config = config or DEFAULT_CAP_RATE_CONFIG
    transactions = list(transactions)

    items: List[Dict] = []
    implied: List[Dict] = []
    skipped: List = []
    for transaction in transactions:
        tid = transaction.get("transaction_id", transaction.get("comparable_id"))
        cap = _implied_cap(transaction)
        if cap is None or cap <= 0:
            skipped.append(tid)
            continue
        weight = transaction.get(config.weight_field)
        weight = float(weight) if _is_number(weight) else 1.0
        items.append({"id": tid, "value": cap, "weight": weight})
        implied.append({"transaction_id": tid, "implied_cap_rate": cap,
                        "weight": weight})

    if not items:
        return {"adopted_cap_rate": {"low": None, "base": None, "high": None},
                "statistics": {"count": 0}, "implied_cap_rates": implied,
                "excluded": [], "skipped": skipped,
                "deliverable": "adopted cap rate",
                "basis": "cap rate engine — no computable implied cap rates"}

    reduced = aggregate_rates(
        items, outlier_method=config.outlier_method, iqr_k=config.iqr_k,
        central=config.central, range_basis=config.range_basis,
        low_pct=config.low_pct, high_pct=config.high_pct,
        rounding=config.rounding)

    result = {
        "adopted_cap_rate": reduced["adopted"],
        "statistics": reduced["statistics"],
        "implied_cap_rates": implied,
        "excluded": reduced["excluded"],
        "skipped": skipped,
        "notes": reduced["notes"],
        "deliverable": "adopted cap rate",
        "basis": ("cap rate engine — adopted capitalisation rate range from "
                  "implied market yields; supports direct capitalization"),
    }

    if audit_store is not None:
        record_event(
            "valuation", None, "cap_rate_adopted",
            before=None, after={"adopted_cap_rate": result["adopted_cap_rate"],
                                "included": reduced["included"],
                                "excluded": reduced["excluded"]},
            rationale="cap rate engine adopted capitalisation rate",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG)

    return result
