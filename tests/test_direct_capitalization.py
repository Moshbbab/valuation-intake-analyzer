"""Tests for Direct Capitalization calculation support.

Verifies value = NOI / cap_rate, cap_rate validation, value range from a
cap-rate range, sensitivity over caller-supplied rates, no default/derived cap
rate, optional non-blocking audit, and absence of adopted-value / DCF output.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.config import DirectCapConfig  # noqa: E402
from engine.valuation.direct_capitalization import (  # noqa: E402
    DirectCapError,
    capitalize,
    direct_capitalization,
    sensitivity_grid,
    value_from_cap_rate_range,
)


# ─── capitalize ───────────────────────────────────────────────────────────────

def test_value_is_noi_over_cap_rate():
    assert capitalize(100000, 0.08) == 1250000.0


def test_reject_cap_rate_zero():
    with pytest.raises(DirectCapError):
        capitalize(100000, 0)


def test_reject_cap_rate_negative():
    with pytest.raises(DirectCapError):
        capitalize(100000, -0.05)


def test_reject_non_numeric_noi():
    with pytest.raises(DirectCapError):
        capitalize("lots", 0.08)


# ─── value_from_cap_rate_range ────────────────────────────────────────────────

def test_cap_rate_range_produces_sorted_value_range():
    # lower rate -> higher value; result must be sorted ascending by value
    result = value_from_cap_rate_range(100000, {"low": 0.07, "high": 0.09})
    assert result["low"] < result["high"]
    assert result["low"] == 100000 / 0.09       # high rate -> low value
    assert result["high"] == 100000 / 0.07      # low rate  -> high value


def test_cap_rate_range_unsorted_when_disabled():
    cfg = DirectCapConfig(sort_range=False)
    result = value_from_cap_rate_range(100000, {"low": 0.07, "high": 0.09},
                                       config=cfg)
    assert result["low"] == 100000 / 0.07       # follows input order (low rate)
    assert result["high"] == 100000 / 0.09


def test_cap_rate_range_rejects_nonpositive():
    with pytest.raises(DirectCapError):
        value_from_cap_rate_range(100000, {"low": 0.0, "high": 0.09})


# ─── sensitivity_grid ─────────────────────────────────────────────────────────

def test_sensitivity_grid_over_caller_rates_only():
    grid = sensitivity_grid(100000, [0.07, 0.08, 0.09])
    assert [row["cap_rate"] for row in grid] == [0.07, 0.08, 0.09]
    assert grid[1]["value"] == 1250000.0
    assert len(grid) == 3  # exactly the caller's rates, no generated bands


def test_sensitivity_grid_marks_bad_rate_without_aborting():
    grid = sensitivity_grid(100000, [0.08, 0])
    assert grid[0]["value"] == 1250000.0
    assert grid[1]["value"] is None
    assert "error" in grid[1]


# ─── no default / derived cap rate ────────────────────────────────────────────

def test_no_default_cap_rate_requires_a_source():
    with pytest.raises(DirectCapError):
        direct_capitalization({"noi": 100000})  # no cap_rate/range/rates


def test_no_derived_cap_rate_present():
    # the public surface exposes no cap-rate derivation/build-up
    import engine.valuation.direct_capitalization as dc
    names = dir(dc)
    assert not any("derive" in n or "build_up" in n or "market" in n
                   for n in names)


# ─── direct_capitalization orchestrator ───────────────────────────────────────

def test_direct_capitalization_full_output():
    result = direct_capitalization({
        "noi": 100000,
        "cap_rate": 0.08,
        "cap_rate_range": {"low": 0.07, "high": 0.09},
        "cap_rates": [0.07, 0.08, 0.09],
    })
    assert result["noi"] == 100000
    assert result["value_indication"] == 1250000.0
    assert result["value_range"]["low"] < result["value_range"]["high"]
    assert len(result["sensitivity"]) == 3
    assert "not an adopted value" in result["basis"]


def test_rounding_configurable():
    result = direct_capitalization({"noi": 100000, "cap_rate": 0.083},
                                   config=DirectCapConfig(rounding=2))
    assert result["value_indication"] == round(100000 / 0.083, 2)


# ─── audit (optional, non-blocking) ───────────────────────────────────────────

def test_audit_absent_by_default():
    result = direct_capitalization({"noi": 100000, "cap_rate": 0.08})
    assert result["value_indication"] == 1250000.0  # works with no store


def test_audit_records_event_when_store_given():
    store = InMemoryAuditStore()
    direct_capitalization({"property_id": "P-1", "noi": 100000, "cap_rate": 0.08},
                          audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["entity_type"] == "valuation"
    assert events[0]["action"] == "capitalized"
    assert events[0]["after"]["value_indication"] == 1250000.0


# ─── no adopted value / DCF / reconciliation output ───────────────────────────

def test_no_adopted_value_or_dcf_output():
    result = direct_capitalization({"noi": 100000, "cap_rate": 0.08})
    for forbidden in ("adopted_value", "final_value", "dcf", "npv",
                      "reconciliation", "exit_cap_rate"):
        assert forbidden not in result
