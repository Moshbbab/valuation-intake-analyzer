"""Tests for the Evidence Decision Ledger (Path-3 single policy seam).

The ledger resolves ALL evidence-set policy in one human-ratifiable record;
engines apply it verbatim (pure functions) and decide nothing themselves.
"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.decision_ledger import (  # noqa: E402
    apply_decision,
    build_decision_record,
)
from engine.valuation.market_rate import adopted_market_rate  # noqa: E402
from engine.valuation.valuation_run import run_valuation  # noqa: E402

CLUSTER = [1000, 1010, 1020, 1030, 1040, 9000]


def _entries(values):
    return [{"id": f"C-{i}", "value": v}
            for i, v in enumerate(values, start=1)]


def _comps(rates):
    return [{"comparable_id": f"C-{i}", "unit_rate": r}
            for i, r in enumerate(rates, start=1)]


# ─── record building ──────────────────────────────────────────────────────────


def test_default_record_flags_but_includes_outlier():
    rec = build_decision_record(_entries(CLUSTER))
    assert rec["outlier_flags"] == ["C-6"]
    assert "C-6" in rec["included_ids"]
    assert rec["excluded_ids"] == []
    by_id = {d["id"]: d for d in rec["decisions"]}
    assert by_id["C-6"]["decided_by"] == "default"
    assert "retained pending appraiser decision" in by_id["C-6"]["reason"]


def test_explicit_policy_exclusion_documented():
    rec = build_decision_record(_entries(CLUSTER), outlier_action="exclude")
    assert rec["excluded_ids"] == ["C-6"]
    by_id = {d["id"]: d for d in rec["decisions"]}
    assert by_id["C-6"]["decided_by"] == "configured_policy"


def test_manual_override_wins_and_documented():
    rec = build_decision_record(
        _entries(CLUSTER), outlier_action="exclude",
        overrides={"force_include": ["C-6"], "rationale": "verified premium",
                   "actor": "appraiser-1"})
    assert rec["excluded_ids"] == []
    by_id = {d["id"]: d for d in rec["decisions"]}
    assert by_id["C-6"]["decided_by"] == "manual_override"
    assert by_id["C-6"]["reason"] == "verified premium"


def test_weight_overrides_applied():
    rec = build_decision_record(_entries([1000, 1200]),
                                weights={"C-1": 3.0})
    assert rec["weights"]["C-1"] == 3.0
    assert rec["weights"]["C-2"] == 1.0


def test_gate_counts_and_zero_output_warning():
    rec = build_decision_record(
        _entries([1000, 1010]),
        overrides={"force_exclude": ["C-1", "C-2"], "rationale": "r",
                   "actor": "a"})
    assert rec["gate"]["included_count"] == 0
    assert any("ZERO OUTPUT" in w for w in rec["gate"]["warnings"])


def test_assumptions_snapshot_reproducible():
    rec = build_decision_record(_entries(CLUSTER), iqr_k=2.0,
                                outlier_action="flag")
    used = rec["assumptions_used"]
    assert used["iqr_k"] == 2.0
    assert used["outlier_action"] == "flag"
    assert used["outlier_method"] == "iqr"


def test_audit_event_recorded():
    store = InMemoryAuditStore()
    build_decision_record(_entries(CLUSTER), audit_store=store)
    events = store.list()
    assert events[0]["action"] == "decision_record_built"


# ─── engines as pure functions over the record ────────────────────────────────


def test_apply_decision_selects_and_weights():
    rec = build_decision_record(_entries(CLUSTER), outlier_action="exclude")
    decided = apply_decision(_entries(CLUSTER), rec)
    assert [d["id"] for d in decided] == ["C-1", "C-2", "C-3", "C-4", "C-5"]


def test_engine_applies_record_verbatim():
    comps = _comps(CLUSTER)
    entries = [{"id": c["comparable_id"], "value": c["unit_rate"]}
               for c in comps]
    rec = build_decision_record(
        entries, overrides={"force_exclude": ["C-6"],
                            "rationale": "unverified", "actor": "appraiser"})
    out = adopted_market_rate(comps, decision=rec)
    assert out["excluded"] == ["C-6"]
    assert out["statistics"]["count"] == 5
    assert any("decision record" in n for n in out["notes"])


def test_engine_same_record_same_numbers():
    comps = _comps(CLUSTER)
    entries = [{"id": c["comparable_id"], "value": c["unit_rate"]}
               for c in comps]
    rec = build_decision_record(entries)
    a = adopted_market_rate(comps, decision=rec)
    b = adopted_market_rate(comps, decision=rec)
    assert a["adopted_rate"] == b["adopted_rate"]  # pure over (evidence, record)


# ─── run_valuation integration ────────────────────────────────────────────────


def _evidence():
    return {"comparables": _comps(CLUSTER)}


def test_run_builds_decision_record_stage():
    result = run_valuation({"subject_id": "S-1", "area": 500}, _evidence())
    assert "decision_record" in result["stages_completed"]
    rec = result["stages"]["decision_record"]
    assert rec["outlier_flags"] == ["C-6"]
    assert rec["excluded_ids"] == []  # flag-only default holds end-to-end


def test_run_market_overrides_flow_through_ledger():
    result = run_valuation(
        {"subject_id": "S-2", "area": 500}, _evidence(),
        configs={"market_overrides": {"force_exclude": ["C-6"],
                                      "rationale": "unverified",
                                      "actor": "appraiser-1"}})
    rec = result["stages"]["decision_record"]
    assert rec["excluded_ids"] == ["C-6"]
    assert result["stages"]["market_rate"]["statistics"]["count"] == 5
    # gate surfaces the override warning
    assert any("manual override" in w for w in result["gate"]["warnings"])


def test_run_ledger_audited_and_chained():
    from engine.audit.recorder import verify_chain
    store = InMemoryAuditStore()
    run_valuation({"subject_id": "S-3", "area": 500}, _evidence(),
                  audit_store=store)
    actions = [e["action"] for e in store.list()]
    assert "decision_record_built" in actions
    assert verify_chain(store.list())["valid"] is True
