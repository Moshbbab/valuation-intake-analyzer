"""Tests proving the valuation core: adjustment, cap-rate derivation, reconciliation.

1. Comparable Adjustment Engine — time/location/size/frontage/use -> adjusted /m^2.
2. Market Derived Cap Rate Engine — implied NOI, implied yield, adopted range.
3. Reconciliation Engine — comparison, dispersion, agreement score, suggested
   range, with no automatic final value adoption.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.valuation.cap_rate import market_derived_cap_rate  # noqa: E402
from engine.valuation.comparable_adjustment import (  # noqa: E402
    adjust_comparable,
    adjustment_grid,
)
from engine.valuation.config import (  # noqa: E402
    AdjustmentEngineConfig,
    ReconciliationEngineConfig,
)
from engine.valuation.reconciliation_engine import (  # noqa: E402
    reconcile_approaches,
)


# ─── 1. Comparable Adjustment Engine ──────────────────────────────────────────

def test_no_adjustment_when_sensitivities_zero():
    out = adjust_comparable({"use": "office"},
                            {"comparable_id": "C-1", "unit_rate": 1000,
                             "use": "office"})
    assert out["adjusted_rate"] == 1000
    assert out["net_adjustment"] == 0.0


def test_time_adjustment():
    config = AdjustmentEngineConfig(annual_market_trend=0.10,
                                    valuation_date="2025-01-01")
    out = adjust_comparable({}, {"comparable_id": "C-1", "unit_rate": 1000,
                                 "date": "2024-01-01"}, config=config)
    # ~ +10% over ~1 year
    assert out["adjustments"]["time"] == pytest.approx(0.10, abs=0.001)
    assert out["adjusted_rate"] == pytest.approx(1100, abs=1)


def test_location_adjustment():
    config = AdjustmentEngineConfig(location_sensitivity=0.5)
    out = adjust_comparable({"location_score": 0.8},
                            {"comparable_id": "C-1", "unit_rate": 1000,
                             "location_score": 0.6}, config=config)
    # diff 0.2 * 0.5 = +10%
    assert out["adjustments"]["location"] == pytest.approx(0.10)
    assert out["adjusted_rate"] == pytest.approx(1100)


def test_size_adjustment_relative():
    config = AdjustmentEngineConfig(size_sensitivity=-0.20)
    out = adjust_comparable({"area": 500},
                            {"comparable_id": "C-1", "unit_rate": 1000,
                             "area": 600}, config=config)
    # (600-500)/500 = 0.2 * -0.20 = -4%
    assert out["adjustments"]["size"] == pytest.approx(-0.04)
    assert out["adjusted_rate"] == pytest.approx(960)


def test_frontage_adjustment():
    config = AdjustmentEngineConfig(frontage_sensitivity=0.30)
    out = adjust_comparable({"frontage": 20},
                            {"comparable_id": "C-1", "unit_rate": 1000,
                             "frontage": 16}, config=config)
    # (20-16)/20 = 0.2 * 0.30 = +6%
    assert out["adjustments"]["frontage"] == pytest.approx(0.06)


def test_use_adjustment_map():
    config = AdjustmentEngineConfig(
        use_adjustment_map={("retail", "office"): -0.15})
    out = adjust_comparable({"use": "office"},
                            {"comparable_id": "C-1", "unit_rate": 1000,
                             "use": "retail"}, config=config)
    assert out["adjustments"]["use"] == pytest.approx(-0.15)
    assert out["adjusted_rate"] == pytest.approx(850)


def test_combined_multiplicative_vs_additive():
    comp = {"comparable_id": "C-1", "unit_rate": 1000, "location_score": 0.7,
            "area": 600}
    subject = {"location_score": 0.8, "area": 500}
    mult = adjust_comparable(subject, comp, config=AdjustmentEngineConfig(
        location_sensitivity=0.5, size_sensitivity=-0.2))
    add = adjust_comparable(subject, comp, config=AdjustmentEngineConfig(
        location_sensitivity=0.5, size_sensitivity=-0.2,
        combination="additive"))
    # loc +0.05, size -0.04: mult = 1000*1.05*0.96=1008; add=1000*1.01=1010
    assert mult["adjusted_rate"] == pytest.approx(1008)
    assert add["adjusted_rate"] == pytest.approx(1010)


def test_adjustment_grid_feeds_market_engine_shape():
    subject = {"location_score": 0.8}
    comps = [{"comparable_id": "A", "unit_rate": 1000, "location_score": 0.7},
             {"comparable_id": "B", "unit_rate": 1200}]
    grid = adjustment_grid(subject, comps,
                           config=AdjustmentEngineConfig(location_sensitivity=0.5))
    assert grid["dimensions"] == ["time", "location", "size", "frontage", "use"]
    assert len(grid["adjusted_rates"]) == 2
    assert grid["adjusted_rates"][0]["adjusted_rate"] == pytest.approx(1050)


def test_adjustment_no_numeric_rate():
    out = adjust_comparable({}, {"comparable_id": "C-1"})
    assert out["adjusted_rate"] is None


# ─── 2. Market Derived Cap Rate Engine ────────────────────────────────────────

def test_implied_yield_from_noi_and_price():
    out = market_derived_cap_rate([
        {"transaction_id": "T1", "noi": 80000, "price": 1000000}])
    row = out["implied_noi"][0]
    assert row["implied_yield"] == pytest.approx(0.08)
    assert row["implied_noi"] == pytest.approx(80000)
    assert row["price"] == pytest.approx(1000000)


def test_implied_noi_from_cap_and_price():
    out = market_derived_cap_rate([
        {"transaction_id": "T1", "cap_rate": 0.075, "price": 2000000}])
    row = out["implied_noi"][0]
    # implied NOI = 0.075 * 2,000,000 = 150,000
    assert row["implied_noi"] == pytest.approx(150000)
    assert row["implied_yield"] == pytest.approx(0.075)


def test_adopted_cap_range_from_transactions():
    out = market_derived_cap_rate([
        {"transaction_id": "T1", "noi": 75000, "price": 1000000},
        {"transaction_id": "T2", "noi": 80000, "price": 1000000},
        {"transaction_id": "T3", "noi": 85000, "price": 1000000}])
    assert out["adopted_cap_rate"]["base"] == pytest.approx(0.08)
    assert out["deliverable"] == "adopted cap rate"


# ─── 3. Reconciliation Engine ─────────────────────────────────────────────────

def _indications():
    return [{"approach": "comparable", "value": 1000000, "weight": 2},
            {"approach": "income", "value": 1100000, "weight": 1},
            {"approach": "dcf", "value": 1050000, "weight": 1}]


def test_reconciliation_comparison_and_suggested_range():
    out = reconcile_approaches(_indications())
    assert {row["approach"] for row in out["comparison"]} == {
        "comparable", "income", "dcf"}
    rng = out["suggested_range"]
    assert rng["low"] == 1000000 and rng["high"] == 1100000
    # weighted indication = (2*1.0M + 1*1.1M + 1*1.05M)/4 = 1,037,500
    assert rng["weighted_indication"] == pytest.approx(1037500)


def test_reconciliation_agreement_score_high_when_close():
    close = reconcile_approaches([{"approach": "a", "value": 1000000},
                                  {"approach": "b", "value": 1010000}])
    far = reconcile_approaches([{"approach": "a", "value": 1000000},
                                {"approach": "b", "value": 2000000}])
    assert close["agreement_score"] > far["agreement_score"]
    assert 0.0 <= far["agreement_score"] <= 1.0


def test_reconciliation_dispersion_present():
    out = reconcile_approaches(_indications())
    assert "coefficient_of_variation" in out["dispersion"]
    assert "spread" in out["dispersion"]


def test_reconciliation_agreement_basis_configurable():
    out = reconcile_approaches(
        _indications(),
        config=ReconciliationEngineConfig(agreement_basis="spread_pct"))
    assert out["agreement_basis"] == "spread_pct"


def test_reconciliation_unknown_basis_rejected():
    with pytest.raises(ValueError):
        reconcile_approaches(
            _indications(),
            config=ReconciliationEngineConfig(agreement_basis="nope"))


def test_reconciliation_no_final_value_adopted():
    out = reconcile_approaches(_indications())
    for forbidden in ("adopted_value", "final_value", "concluded_value",
                      "value"):
        assert forbidden not in out
    assert "not produced here" in out["basis"]
    assert out["deliverable"].startswith("suggested")


def test_reconciliation_single_approach_full_agreement():
    out = reconcile_approaches([{"approach": "only", "value": 1000000}])
    assert out["agreement_score"] == pytest.approx(1.0)
