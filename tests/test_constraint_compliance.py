"""Tests for the non-negotiable-constraint compliance fixes (Path-1 first aid).

1. IQR is a signal only: flag by default, exclusion only by explicit opt-in.
2. Documented manual overrides (force include/exclude) win, auto retained.
3. Zero Output Trap: loud warnings instead of silent empty results.
4. Mandatory pre-output gate in run_valuation (record/outlier/warning counts).
5. Configurable approach weights (appraiser judgment, not locked).
6. Methodology guard: cap-rate on land/wasting assets warns.
7. SHA-256 audit hash chain + tamper detection.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.config import UNRESTRICTED_CONFIG  # noqa: E402
from engine.audit.recorder import record_event, verify_chain  # noqa: E402
from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.cap_rate import adopted_cap_rate  # noqa: E402
from engine.valuation.config import MarketRateConfig  # noqa: E402
from engine.valuation.market_rate import adopted_market_rate  # noqa: E402
from engine.valuation.valuation_run import run_valuation  # noqa: E402

CLUSTER = [1000, 1010, 1020, 1030, 1040, 9000]


def _comps(rates):
    return [{"comparable_id": f"C-{i}", "unit_rate": r}
            for i, r in enumerate(rates, start=1)]


# ─── 1. flag by default / explicit exclude ────────────────────────────────────

def test_default_flags_and_keeps_outlier():
    out = adopted_market_rate(_comps(CLUSTER))
    assert out["outlier_flags"] == ["C-6"]
    assert out["excluded"] == []
    assert out["statistics"]["count"] == 6
    assert out["record_count"] == 6


def test_explicit_exclude_opt_in_warns_loudly():
    out = adopted_market_rate(
        _comps(CLUSTER), config=MarketRateConfig(outlier_action="exclude"))
    assert out["excluded"] == ["C-6"]
    assert out["statistics"]["count"] == 5
    assert any("EXCLUDED by explicit configuration" in w
               for w in out["warnings"])


def test_unknown_outlier_action_rejected():
    with pytest.raises(ValueError):
        adopted_market_rate(_comps(CLUSTER),
                            config=MarketRateConfig(outlier_action="nope"))


def test_cap_rate_flags_by_default_too():
    txns = [{"transaction_id": f"T{i}", "cap_rate": c}
            for i, c in enumerate([0.07, 0.075, 0.08, 0.082, 0.30], 1)]
    out = adopted_cap_rate(txns)
    assert "T5" in out["outlier_flags"]
    assert out["excluded"] == []


# ─── 2. documented overrides win, auto retained ───────────────────────────────

def test_force_exclude_override_documented():
    out = adopted_market_rate(
        _comps(CLUSTER),
        overrides={"force_exclude": ["C-6"], "rationale": "unverified sale",
                   "actor": "appraiser-1"})
    assert out["excluded"] == ["C-6"]
    assert out["overrides_applied"]["actor"] == "appraiser-1"
    assert out["overrides_applied"]["auto_excluded"] == []  # flag mode: none


def test_force_include_beats_explicit_exclusion():
    out = adopted_market_rate(
        _comps(CLUSTER),
        config=MarketRateConfig(outlier_action="exclude"),
        overrides={"force_include": ["C-6"], "rationale": "verified premium",
                   "actor": "appraiser-2"})
    assert out["excluded"] == []
    assert out["statistics"]["count"] == 6
    assert out["overrides_applied"]["auto_excluded"] == ["C-6"]  # retained


# ─── 3. zero-output warnings ─────────────────────────────────────────────────

def test_zero_output_warned_not_silent():
    out = adopted_market_rate(
        _comps([1000, 1010]),
        overrides={"force_exclude": ["C-1", "C-2"], "rationale": "test",
                   "actor": "a"})
    assert out["adopted_rate"]["base"] is None
    assert any("ZERO OUTPUT" in w for w in out["warnings"])


# ─── 4-6. run_valuation gate, weights, guard ─────────────────────────────────

def _evidence():
    return {
        "comparables": _comps(CLUSTER),
        "income": {"rental_income": [{"name": "rent", "amount": 120000}],
                   "vacancy_rate": 0.05,
                   "operating_expenses": [{"name": "opex", "amount": 30000}]},
        "cap_rate_transactions": [
            {"transaction_id": "T1", "noi": 80000, "price": 1000000},
            {"transaction_id": "T2", "noi": 82000, "price": 1000000}],
    }


def test_gate_present_with_counts_and_warnings():
    result = run_valuation({"subject_id": "S-1", "area": 500}, _evidence())
    gate = result["gate"]
    assert gate["record_count"]["market_rate"] == 6
    assert gate["outlier_count"] >= 1
    assert gate["warning_count"] == len(gate["warnings"]) > 0
    assert any("NOT excluded" in w for w in gate["warnings"])


def test_zero_indications_warned_in_gate():
    result = run_valuation({"subject_id": "S-2"}, {})
    assert any("ZERO OUTPUT" in w for w in result["gate"]["warnings"])
    assert "reconciliation" not in result["stages_completed"]


def test_approach_weights_configurable():
    evidence = _evidence()
    evidence["approach_weights"] = {"comparable": 3, "income": 1}
    result = run_valuation({"subject_id": "S-3", "area": 500}, evidence)
    weights = {i["approach"]: i["weight"]
               for i in result["approach_indications"]}
    assert weights["comparable"] == 3.0
    assert weights["income"] == 1.0


def test_wasting_asset_guard_warns():
    result = run_valuation({"subject_id": "S-4", "area": 500,
                            "asset_type": "land"}, _evidence())
    assert any("METHODOLOGY WARNING" in w for w in result["gate"]["warnings"])


def test_non_wasting_asset_no_guard_warning():
    result = run_valuation({"subject_id": "S-5", "area": 500,
                            "asset_type": "office"}, _evidence())
    assert not any("METHODOLOGY WARNING" in w
                   for w in result["gate"]["warnings"])


# ─── 7. SHA-256 audit chain ───────────────────────────────────────────────────

def test_events_carry_sha256_chain():
    store = InMemoryAuditStore()
    record_event("valuation", "V-1", "created", store=store, config=UNRESTRICTED_CONFIG)
    record_event("valuation", "V-1", "updated", store=store, config=UNRESTRICTED_CONFIG)
    events = store.list()
    assert len(events[0]["event_hash"]) == 64
    assert events[0]["prev_event_hash"] is None
    assert events[1]["prev_event_hash"] == events[0]["event_hash"]


def test_verify_chain_valid_and_tamper_detected():
    store = InMemoryAuditStore()
    for i in range(3):
        record_event("valuation", f"V-{i}", "created", store=store, config=UNRESTRICTED_CONFIG)
    events = store.list()
    assert verify_chain(events)["valid"] is True
    events[1]["rationale"] = "tampered"
    outcome = verify_chain(events)
    assert outcome["valid"] is False
    assert outcome["first_invalid"] == events[1]["event_id"]


def test_run_valuation_audited_when_store_given():
    store = InMemoryAuditStore()
    run_valuation({"subject_id": "S-6", "area": 500}, _evidence(),
                  audit_store=store)
    actions = [e["action"] for e in store.list()]
    assert "valuation_run_completed" in actions
    assert "market_rate_adopted" in actions
    assert verify_chain(store.list())["valid"] is True
