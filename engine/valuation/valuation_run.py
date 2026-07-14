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

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation.cap_rate import market_derived_cap_rate
from engine.valuation.comparable_adjustment import adjustment_grid
from engine.valuation.decision_ledger import build_decision_record
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

    ledger_entries = [{"id": r["comparable_id"], "value": r["adjusted_rate"]}
                      for r in grid["adjusted_rates"]]
    market_config = configs.get("market_rate")
    decision = build_decision_record(
        ledger_entries,
        outlier_method=getattr(market_config, "outlier_method", "iqr"),
        iqr_k=getattr(market_config, "iqr_k", 1.5),
        outlier_action=getattr(market_config, "outlier_action", "flag"),
        overrides=configs.get("market_overrides"),
        weights=configs.get("comparable_weights"),
        audit_store=configs.get("_audit_store"),
        audit_config=configs.get("_audit_config"))
    stages["decision_record"] = decision
    completed.append("decision_record")

    market = adopted_market_rate(grid["adjusted_rates"],
                                 config=market_config,
                                 decision=decision,
                                 audit_store=configs.get("_audit_store"),
                                 audit_config=configs.get("_audit_config"))
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
                            "weight": _approach_weight(evidence, "comparable")})


def _income_value(noi_value, cap, evidence, _configs, ctx) -> None:
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
                                  "high": income_value["high"]},
                        "weight": _approach_weight(evidence, "income")})


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
                                      config=configs.get("cap_rate"),
                                      overrides=configs.get("cap_overrides"),
                                      audit_store=configs.get("_audit_store"),
                                      audit_config=configs.get("_audit_config"))
        stages["cap_rate"] = cap
        summary["adopted_cap_rate"] = cap["adopted_cap_rate"]
        completed.append("cap_rate")
        _income_value(noi_value, cap, evidence, configs, ctx)
    return noi_value


DEFAULT_WASTING_ASSET_TYPES = ("land", "vacant_land", "plot", "site")


def _build_gate(subject: Mapping, stages: Mapping, indications: List,
                configs: Mapping) -> Dict:
    """Mandatory pre-output gate: record/outlier/warning counts + guards."""
    all_warnings: List[str] = []

    # Methodological guard: cap-rate logic on wasting assets (advisory).
    wasting = configs.get("wasting_asset_types", DEFAULT_WASTING_ASSET_TYPES)
    asset_type = str(subject.get("asset_type", "")).strip().lower()
    if asset_type in tuple(wasting) and "direct_capitalization" in stages:
        all_warnings.append(
            f"METHODOLOGY WARNING: cap-rate capitalization applied to asset "
            f"type '{asset_type}' — capitalization logic is not applicable to "
            "land/wasting assets; appraiser review required")

    record_counts: Dict[str, int] = {}
    outlier_count = 0
    for name, stage in stages.items():
        for warning in stage.get("warnings", []) or []:
            all_warnings.append(f"[{name}] {warning}")
        for note in stage.get("notes", []) or []:
            all_warnings.append(f"[{name}] note: {note}")
        if "record_count" in stage:
            record_counts[name] = stage["record_count"]
        outlier_count += len(stage.get("outlier_flags", []) or [])
    if not indications:
        all_warnings.append(
            "ZERO OUTPUT: no approach produced a value indication — "
            "reconciliation skipped; supply evidence or review exclusions")
    return {"record_count": record_counts, "outlier_count": outlier_count,
            "warnings": all_warnings, "warning_count": len(all_warnings)}


def _approach_weight(evidence: Mapping, approach: str) -> float:
    """Caller-supplied approach weight (appraiser judgment); default 1."""
    weights = evidence.get("approach_weights") or {}
    weight = weights.get(approach, 1)
    return float(weight) if _is_number(weight) else 1.0


def run_valuation(subject: Mapping, evidence: Mapping, *,
                  configs: Optional[Mapping] = None,
                  audit_store=None, audit_config=None) -> Dict:
    """Run the full valuation workflow for one subject and return numbers.

    ``subject`` carries the subject attributes (``area`` and the fields the
    adjustment engine compares). ``evidence`` may carry any of: ``comparables``,
    ``income`` (NOI inputs), ``cap_rate_transactions``, ``dcf`` (DCF inputs) and
    ``sensitivity`` ({cap_rates}). ``configs`` optionally maps stage name ->
    config. Returns ``stages`` (full output per stage), ``value_summary`` (the
    headline numbers), ``approach_indications`` and ``stages_completed``. The
    ``appraiser_decision`` is always None — the human adopts the final value.
    """
    configs = dict(configs or {})
    configs["_audit_store"] = audit_store
    configs["_audit_config"] = audit_config
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
                                "weight": _approach_weight(evidence, "dcf")})

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

    gate = _build_gate(subject, stages, indications, configs)

    result = {
        "subject_id": subject.get("subject_id"),
        "gate": gate,
        "stages": stages,
        "value_summary": summary,
        "approach_indications": indications,
        "stages_completed": completed,
        "appraiser_decision": None,
        "basis": ("subject valuation run — numeric output at every stage; the "
                  "appraiser adopts the final value, which is not produced "
                  "here"),
    }

    if audit_store is not None:
        record_event(
            "valuation", subject.get("subject_id"), "valuation_run_completed",
            before=None,
            after={"value_summary": summary, "gate": gate,
                   "stages_completed": completed},
            rationale="subject valuation run",
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG)

    return result
