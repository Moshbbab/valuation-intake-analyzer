"""Tests for the subject valuation run — a number at every stage.

Asserts the full workflow turns raw evidence into valuation numbers: adopted
land rate, land value, NOI, adopted cap rate, income value, DCF value,
sensitivity matrix and a suggested reconciled range — with no auto-adopted
final value.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.valuation.config import AdjustmentEngineConfig  # noqa: E402
from engine.valuation.valuation_run import run_valuation  # noqa: E402


def _subject():
    return {"subject_id": "S-1", "area": 500, "location_score": 0.85,
            "use": "office", "valuation_date": "2025-06-01"}


def _evidence():
    comps = [{"comparable_id": f"C{i}", "unit_rate": r, "location_score": 0.75,
              "use": "office", "date": "2024-06-01"}
             for i, r in enumerate([1900, 2000, 2050, 1980, 2020], 1)]
    return {
        "comparables": comps,
        "income": {
            "income_items": [{"name": "rent", "amount": 600000}],
            "vacancy": {"type": "rate", "value": 0.05},
            "other_income": 20000,
            "expense_items": [{"name": "opex", "amount": 150000}],
        },
        "cap_rate_transactions": [
            {"transaction_id": "T1", "noi": 78000, "price": 1000000},
            {"transaction_id": "T2", "noi": 80000, "price": 1000000},
            {"transaction_id": "T3", "noi": 82000, "price": 1000000},
        ],
        "dcf": {"cash_flows": [84000, 86520, 89116],
                "discount_rate": 0.10,
                "reversion": {"terminal_noi": 91789, "exit_cap_rate": 0.085}},
        "sensitivity": {"cap_rates": [0.075, 0.08, 0.085]},
    }


def _configs():
    return {"adjustment": AdjustmentEngineConfig(
        annual_market_trend=0.05, location_sensitivity=0.4,
        valuation_date="2025-06-01")}


def test_full_run_produces_a_number_at_every_stage():
    out = run_valuation(_subject(), _evidence(), configs=_configs())
    summary = out["value_summary"]

    # every workflow stage ran
    assert out["stages_completed"] == [
        "adjustment", "market_rate", "land_value", "noi", "cap_rate",
        "direct_capitalization", "dcf", "sensitivity", "reconciliation"]

    # each output is numeric
    assert summary["adopted_land_rate"]["base"] > 0
    assert summary["land_value_range"]["base"] > 0
    assert summary["noi"] == pytest.approx(600000 * 0.95 + 20000 - 150000)
    assert 0 < summary["adopted_cap_rate"]["base"] < 1
    assert summary["income_value_range"]["base"] > 0
    assert summary["dcf_value"] > 0
    assert all(row["value"] > 0 for row in summary["sensitivity_matrix"])
    assert summary["suggested_reconciled_range"]["weighted_indication"] > 0
    assert 0.0 <= summary["approach_agreement_score"] <= 1.0


def test_noi_drives_income_value():
    out = run_valuation(_subject(), _evidence(), configs=_configs())
    noi = out["value_summary"]["noi"]
    cap = out["value_summary"]["adopted_cap_rate"]["base"]
    assert out["value_summary"]["income_value_range"]["base"] == pytest.approx(
        noi / cap)


def test_land_value_equals_area_times_rate():
    out = run_valuation(_subject(), _evidence(), configs=_configs())
    rate = out["value_summary"]["adopted_land_rate"]["base"]
    assert out["value_summary"]["land_value_range"]["base"] == pytest.approx(
        500 * rate)


def test_three_approaches_feed_reconciliation():
    out = run_valuation(_subject(), _evidence(), configs=_configs())
    approaches = {ind["approach"] for ind in out["approach_indications"]}
    assert approaches == {"comparable", "income", "dcf"}


def test_partial_evidence_income_only():
    out = run_valuation(
        {"subject_id": "S-2"},
        {"income": {"income_items": [{"name": "rent", "amount": 500000}],
                    "expense_items": [{"name": "opex", "amount": 100000}]},
         "cap_rate_transactions": [{"transaction_id": "T1", "cap_rate": 0.08}]})
    assert "noi" in out["stages_completed"]
    assert out["value_summary"]["income_value_range"]["base"] == pytest.approx(
        400000 / 0.08)
    assert "land_value" not in out["stages_completed"]


def test_no_final_value_adopted():
    out = run_valuation(_subject(), _evidence(), configs=_configs())
    assert out["appraiser_decision"] is None
    assert "not produced here" in out["basis"]
    for forbidden in ("adopted_value", "final_value", "concluded_value"):
        assert forbidden not in out["value_summary"]


def test_empty_evidence_yields_no_stages():
    out = run_valuation({"subject_id": "S-3"}, {})
    assert out["stages_completed"] == []
    assert out["value_summary"] == {}
