"""Tests for the valuation production engines: market rate, land value, cap rate.

These engines produce actual valuation numbers — an adopted land rate range, a
land market value range, and an adopted cap-rate range — and chain into the
existing income approach. Tests assert the computed numbers, configurability,
outlier handling, and the end-to-end value paths.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.cap_rate import adopted_cap_rate  # noqa: E402
from engine.valuation.config import MarketRateConfig  # noqa: E402
from engine.valuation.direct_capitalization import capitalize  # noqa: E402
from engine.valuation.land_value import (  # noqa: E402
    land_value,
    land_value_from_comparables,
)
from engine.valuation.market_rate import adopted_market_rate  # noqa: E402


# ─── Priority 1 — Comparable Market Engine ────────────────────────────────────

def _comps(rates):
    return [{"comparable_id": f"C-{i}", "unit_rate": r}
            for i, r in enumerate(rates, start=1)]


def test_market_rate_basic_stats():
    out = adopted_market_rate(_comps([1000, 1100, 1200, 1300, 1400]))
    stats = out["statistics"]
    assert stats["count"] == 5
    assert stats["median"] == 1200
    assert stats["mean"] == 1200
    assert stats["min"] == 1000 and stats["max"] == 1400
    assert out["adopted_rate"]["base"] == pytest.approx(1200)  # weighted == mean
    assert out["deliverable"] == "adopted land rate range"


def test_market_rate_weighted_average():
    comps = [{"comparable_id": "A", "unit_rate": 1000, "weight": 3},
             {"comparable_id": "B", "unit_rate": 2000, "weight": 1}]
    out = adopted_market_rate(comps)
    # weighted mean = (3*1000 + 1*2000)/4 = 1250
    assert out["adopted_rate"]["base"] == pytest.approx(1250)


def test_market_rate_applies_adjustments():
    comps = [{"comparable_id": "A", "unit_rate": 1000, "adjustments": [
        {"adjustment_value": {"type": "percentage", "value": 10,
                              "direction": "upward"}}]}]
    out = adopted_market_rate(comps)
    assert out["rates"][0]["adjusted_rate"] == pytest.approx(1100)


def test_market_rate_flags_outliers_by_default_never_excludes():
    # tight cluster + one extreme; IQR flags it but does NOT remove it —
    # exclusion is the appraiser's decision (non-negotiable constraint).
    out = adopted_market_rate(_comps([1000, 1010, 1020, 1030, 1040, 9000]))
    assert "C-6" in out["outlier_flags"]
    assert out["excluded"] == []
    assert out["statistics"]["count"] == 6
    assert any("NOT excluded" in w for w in out["warnings"])


def test_market_rate_outlier_method_none_keeps_all():
    out = adopted_market_rate(_comps([1000, 1010, 1020, 1030, 1040, 9000]),
                              config=MarketRateConfig(outlier_method="none"))
    assert out["excluded"] == []
    assert out["statistics"]["count"] == 6


def test_market_rate_central_median_strategy():
    out = adopted_market_rate(
        [{"comparable_id": "A", "unit_rate": 1000, "weight": 5},
         {"comparable_id": "B", "unit_rate": 1100, "weight": 1},
         {"comparable_id": "C", "unit_rate": 1200, "weight": 1}],
        config=MarketRateConfig(central="median", outlier_method="none"))
    assert out["adopted_rate"]["base"] == 1100


def test_market_rate_percentile_vs_minmax_range():
    rates = [1000, 1100, 1200, 1300, 1400]
    pct = adopted_market_rate(_comps(rates),
                              config=MarketRateConfig(outlier_method="none"))
    mm = adopted_market_rate(
        _comps(rates),
        config=MarketRateConfig(outlier_method="none", range_basis="min_max"))
    assert mm["adopted_rate"]["low"] == 1000
    assert mm["adopted_rate"]["high"] == 1400
    assert pct["adopted_rate"]["low"] == 1100  # p25
    assert pct["adopted_rate"]["high"] == 1300  # p75


def test_market_rate_skips_non_numeric():
    out = adopted_market_rate([{"comparable_id": "A"},
                               {"comparable_id": "B", "unit_rate": 1000}])
    assert "A" in out["skipped"]
    assert out["statistics"]["count"] == 1


# ─── Priority 2 — Land Value Engine ───────────────────────────────────────────

def test_land_value_from_rate_range():
    out = land_value(500, {"low": 1000, "base": 1200, "high": 1400})
    assert out["land_value"] == {"low": 500000, "base": 600000, "high": 700000}
    assert out["deliverable"] == "land market value range"


def test_land_value_scalar_rate():
    out = land_value(500, 1200)
    assert out["land_value"] == {"low": 600000, "base": 600000, "high": 600000}


def test_land_value_non_numeric_area():
    out = land_value(None, {"low": 1000, "base": 1200, "high": 1400})
    assert out["land_value"] == {"low": None, "base": None, "high": None}


def test_land_value_from_comparables_chain():
    out = land_value_from_comparables(_comps([1000, 1100, 1200, 1300, 1400]), 500)
    # base rate 1200 (weighted==mean) x 500 = 600,000
    assert out["land_value"]["base"] == pytest.approx(600000)
    assert out["market_rate"]["deliverable"] == "adopted land rate range"


# ─── Priority 4 — Cap Rate Engine ─────────────────────────────────────────────

def test_cap_rate_implied_from_noi_and_price():
    txns = [{"transaction_id": "T1", "noi": 80000, "price": 1000000},
            {"transaction_id": "T2", "noi": 90000, "price": 1000000},
            {"transaction_id": "T3", "noi": 100000, "price": 1000000}]
    out = adopted_cap_rate(txns)
    assert out["implied_cap_rates"][0]["implied_cap_rate"] == pytest.approx(0.08)
    assert out["adopted_cap_rate"]["base"] == pytest.approx(0.09)
    assert out["deliverable"] == "adopted cap rate"


def test_cap_rate_explicit_yield_evidence():
    out = adopted_cap_rate([{"transaction_id": "T1", "cap_rate": 0.075},
                            {"transaction_id": "T2", "cap_rate": 0.085}])
    assert out["adopted_cap_rate"]["base"] == pytest.approx(0.08)


def test_cap_rate_skips_invalid():
    out = adopted_cap_rate([{"transaction_id": "T1", "noi": 80000, "price": 0},
                            {"transaction_id": "T2", "noi": 90000,
                             "price": 1000000}])
    assert "T1" in out["skipped"]
    assert out["statistics"]["count"] == 1


def test_cap_rate_weighted_recommendation():
    txns = [{"transaction_id": "T1", "cap_rate": 0.07, "weight": 3},
            {"transaction_id": "T2", "cap_rate": 0.09, "weight": 1}]
    out = adopted_cap_rate(txns)
    assert out["adopted_cap_rate"]["base"] == pytest.approx(0.075)


# ─── End-to-end valuation production ──────────────────────────────────────────

def test_end_to_end_income_value_from_cap_rate_engine():
    # adopted cap rate -> existing direct capitalization -> income value
    cap = adopted_cap_rate([{"transaction_id": "T1", "cap_rate": 0.08},
                            {"transaction_id": "T2", "cap_rate": 0.08},
                            {"transaction_id": "T3", "cap_rate": 0.08}])
    value = capitalize(100000, cap["adopted_cap_rate"]["base"])
    assert value == pytest.approx(1250000)  # 100,000 / 0.08


def test_end_to_end_land_value_from_raw_comparables():
    out = land_value_from_comparables(
        _comps([980, 1000, 1010, 1020, 1040]), 1000)
    # base ~1010 x 1000 m2 -> land value around 1.01M
    assert 1_000_000 <= out["land_value"]["base"] <= 1_020_000


def test_audit_events_recorded():
    store = InMemoryAuditStore()
    adopted_market_rate(_comps([1000, 1100, 1200, 1300]), audit_store=store)
    adopted_cap_rate([{"transaction_id": "T1", "cap_rate": 0.08}],
                     audit_store=store)
    land_value(500, 1200, audit_store=store)
    actions = {e["action"] for e in store.list()}
    assert {"market_rate_adopted", "cap_rate_adopted",
            "land_value_computed"} <= actions
