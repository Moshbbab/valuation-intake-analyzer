"""Subject Valuation Run — raw evidence to valuation numbers (vertical).

Runs the full valuation workflow for one subject and emits a numeric output at
every stage:

    Raw evidence
      -> comparable adjustments (adjusted price/m^2)
      -> market rate (adopted land rate range)
      -> land value (land market value range)
      -> NOI (stabilized NOI)
      -> market-derived cap rate (adopted cap range)
      -> direct capitalization (income value range)
      -> DCF (DCF value)
      -> sensitivity (value matrix)
      -> reconciliation (suggested range + agreement)
      -> appraiser decision (left to the human; never auto-adopted)

Each stage runs only when its evidence is supplied and reuses the existing
valuation engines. The final adopted value is the appraiser's; it is not
produced here.
"""

from typing import Dict, List, Mapping, Optional

from engine.valuation.cap_rate import market_derived_cap_rate
from engine.valuation.comparable_adjustment import adjustment_grid
from engine.valuation.dcf import discounted_cash_flow
from engine.valuation.direct_capitalization import (
    capitalize,
    sensitivity_grid,
    value_from_cap_rate_range,
)
from engine.valuation.land_value import land_value
from engine.valuation.market_rate import adopted_market_rate
from engine.valuation.noi import build_noi
from engine.valuation.reconciliation_engine import reconcile_approaches


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _land_approach(subject, evidence, configs, ctx) -> None:
    """Comparable adjustments -> market rate -> land value (numbers each step)."""
    comparables = evidence.get("comparables")
    if not comparables:
        return
    stages, summary, indications, completed = ctx

    grid = adjustment_grid(subject, comparables, config=configs.get("adjustment"))
    stages["adjustment"] = grid
    completed.append("adjustment")

    market = adopted_market_rate(grid["adjusted_rates"],
                                 config=configs.get("market_rate"))
    stages["market_rate"] = market
    summary["adopted_land_rate"] = market["adopted_rate"]
    completed.append("market_rate")

    area = subject.get("area")
    if not _is_number(area):
        return
    lv = land_value(area, market["adopted_rate"], config=configs.get("land_value"))
    stages["land_value"] = lv
    summary["land_value_range"] = lv["land_value"]
    completed.append("land_value")
    if _is_number(lv["land_value"].get("base")):
        indications.append({"approach": "comparable",
                            "value": lv["land_value"]["base"],
                            "range": {"low": lv["land_value"]["low"],
                                      "high": lv["land_value"]["high"]},
                            "weight": 1})


def _income_value(noi_value, cap, configs, ctx) -> None:
    """NOI / adopted cap rate -> income value range (direct capitalization)."""
    stages, summary, indications, completed = ctx
    if not (_is_number(noi_value) and _is_number(cap["adopted_cap_rate"]["base"])):
        return
    base_value = capitalize(noi_value, cap["adopted_cap_rate"]["base"])
    low_r, high_r = cap["adopted_cap_rate"]["low"], cap["adopted_cap_rate"]["high"]
    value_range = None
    if _is_number(low_r) and _is_number(high_r) and low_r > 0 and high_r > 0:
        value_range = value_from_cap_rate_range(noi_value,
                                                {"low": low_r, "high": high_r})
    income_value = {"low": value_range["low"] if value_range else None,
                    "base": base_value,
                    "high": value_range["high"] if value_range else None}
    stages["direct_capitalization"] = {
        "noi": noi_value, "cap_rate": cap["adopted_cap_rate"],
        "income_value": income_value,
        "deliverable": "income approach value range",
        "basis": "direct capitalization — NOI / adopted cap rate"}
    summary["income_value_range"] = income_value
    completed.append("direct_capitalization")
    indications.append({"approach": "income", "value": base_value,
                        "range": {"low": income_value["low"],
                                  "high": income_value["high"]}, "weight": 1})


def _income_approach(evidence, configs, ctx):
    """NOI -> market-derived cap rate -> income value. Returns the NOI."""
    stages, summary, _, completed = ctx
    noi_value = None
    if evidence.get("income"):
        noi_result = build_noi(evidence["income"], config=configs.get("noi"))
        stages["noi"] = noi_result
        noi_value = noi_result["noi"]
        summary["noi"] = noi_value
        completed.append("noi")
    if evidence.get("cap_rate_transactions"):
        cap = market_derived_cap_rate(evidence["cap_rate_transactions"],
                                      config=configs.get("cap_rate"))
        stages["cap_rate"] = cap
        summary["adopted_cap_rate"] = cap["adopted_cap_rate"]
        completed.append("cap_rate")
        _income_value(noi_value, cap, configs, ctx)
    return noi_value


def run_valuation(subject: Mapping, evidence: Mapping, *,
                  configs: Optional[Mapping] = None) -> Dict:
    """Run the full valuation workflow for one subject and return numbers.

    ``subject`` carries the subject attributes (``area`` and the fields the
    adjustment engine compares). ``evidence`` may carry any of: ``comparables``,
    ``income`` (NOI inputs), ``cap_rate_transactions``, ``dcf`` (DCF inputs) and
    ``sensitivity`` ({cap_rates}). ``configs`` optionally maps stage name ->
    config. Returns ``stages`` (full output per stage), ``value_summary`` (the
    headline numbers), ``approach_indications`` and ``stages_completed``. The
    ``appraiser_decision`` is always None — the human adopts the final value.
    """
    configs = configs or {}
    stages: Dict[str, Dict] = {}
    summary: Dict = {}
    indications: List[Dict] = []
    completed: List[str] = []
    ctx = (stages, summary, indications, completed)

    _land_approach(subject, evidence, configs, ctx)
    noi_value = _income_approach(evidence, configs, ctx)

    # ── DCF ───────────────────────────────────────────────────────────────────
    if evidence.get("dcf"):
        dcf_result = discounted_cash_flow(evidence["dcf"],
                                          config=configs.get("dcf"))
        stages["dcf"] = dcf_result
        summary["dcf_value"] = dcf_result["value_indication"]
        completed.append("dcf")
        if _is_number(dcf_result["value_indication"]):
            indications.append({"approach": "dcf",
                                "value": dcf_result["value_indication"],
                                "weight": 1})

    # ── Sensitivity ───────────────────────────────────────────────────────────
    sens = evidence.get("sensitivity") or {}
    if _is_number(noi_value) and sens.get("cap_rates"):
        grid = sensitivity_grid(noi_value, sens["cap_rates"])
        stages["sensitivity"] = {"income_value_by_cap_rate": grid,
                                 "deliverable": "value sensitivity matrix"}
        summary["sensitivity_matrix"] = grid
        completed.append("sensitivity")

    # ── Reconciliation (suggested only) ───────────────────────────────────────
    if indications:
        recon = reconcile_approaches(indications,
                                     config=configs.get("reconciliation"))
        stages["reconciliation"] = recon
        summary["suggested_reconciled_range"] = recon["suggested_range"]
        summary["approach_agreement_score"] = recon["agreement_score"]
        completed.append("reconciliation")

    return {
        "subject_id": subject.get("subject_id"),
        "stages": stages,
        "value_summary": summary,
        "approach_indications": indications,
        "stages_completed": completed,
        "appraiser_decision": None,
        "basis": ("subject valuation run — numeric output at every stage; the "
                  "appraiser adopts the final value, which is not produced "
                  "here"),
    }
