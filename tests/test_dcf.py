"""Tests for DCF calculation support.

Covers discounting, present value, both reversion modes (explicit and
capitalized), the full DCF orchestrator, sensitivity over caller-supplied rates,
no default/derived discount or exit rate, optional non-blocking audit, and the
absence of adopted-value / reconciliation output.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.config import DCFConfig  # noqa: E402
from engine.valuation.dcf import (  # noqa: E402
    DCFError,
    dcf_sensitivity,
    discount_factor,
    discounted_cash_flow,
    present_value,
    reversion_value,
)


# ─── discount_factor / present_value ──────────────────────────────────────────

def test_discount_factor():
    assert discount_factor(0.10, 1) == pytest.approx(1 / 1.10)
    assert discount_factor(0.10, 2) == pytest.approx(1 / 1.21)


def test_present_value_scalar_rate():
    pv = present_value([100, 100, 100], 0.10)
    assert pv == pytest.approx(100/1.1 + 100/1.21 + 100/1.331)


def test_present_value_per_period_rates():
    pv = present_value([100, 100], [0.10, 0.20])
    expected = 100 * (1/1.10) + 100 * (1/1.10) * (1/1.20)
    assert pv == pytest.approx(expected)


def test_reject_discount_rate_at_or_below_minus_one():
    with pytest.raises(DCFError):
        present_value([100], -1)


# ─── reversion modes ──────────────────────────────────────────────────────────

def test_reversion_explicit_amount():
    rev = reversion_value({"amount": 500000})
    assert rev["reversion"] == 500000
    assert rev["method"] == "explicit"


def test_reversion_capitalized_terminal_noi():
    rev = reversion_value({"terminal_noi": 100000, "exit_cap_rate": 0.08})
    assert rev["reversion"] == 1250000.0  # 100000 / 0.08
    assert rev["method"] == "capitalized"


def test_reversion_capitalized_rejects_bad_exit_rate():
    with pytest.raises(Exception):
        reversion_value({"terminal_noi": 100000, "exit_cap_rate": 0})


def test_reversion_requires_a_mode():
    with pytest.raises(DCFError):
        reversion_value({})


# ─── Gordon growth terminal value ─────────────────────────────────────────────

def test_reversion_gordon_growth():
    rev = reversion_value({"terminal_noi": 100000, "growth_rate": 0.02},
                          discount_rate=0.10)
    assert rev["method"] == "gordon_growth"
    assert rev["reversion"] == pytest.approx(100000 / (0.10 - 0.02))  # 1,250,000
    assert rev["growth_rate"] == 0.02


def test_gordon_growth_selected_by_growth_rate_key():
    rev = reversion_value({"terminal_noi": 90000, "growth_rate": 0.03,
                           "discount_rate": 0.09})
    assert rev["method"] == "gordon_growth"
    assert rev["reversion"] == pytest.approx(90000 / (0.09 - 0.03))


def test_gordon_growth_guard_discount_must_exceed_growth():
    with pytest.raises(DCFError):
        reversion_value({"terminal_noi": 100000, "growth_rate": 0.10},
                        discount_rate=0.10)  # r == g
    with pytest.raises(DCFError):
        reversion_value({"terminal_noi": 100000, "growth_rate": 0.12},
                        discount_rate=0.10)  # r < g


def test_gordon_growth_requires_a_discount_rate():
    with pytest.raises(DCFError):
        reversion_value({"terminal_noi": 100000, "growth_rate": 0.02})  # no r


def test_capitalized_takes_precedence_when_both_exit_and_growth_given():
    # exit_cap_rate present -> capitalized mode (selection is key-driven)
    rev = reversion_value({"terminal_noi": 100000, "exit_cap_rate": 0.08,
                           "growth_rate": 0.02}, discount_rate=0.10)
    assert rev["method"] == "capitalized"


def test_dcf_with_gordon_growth_reversion():
    result = discounted_cash_flow({
        "cash_flows": [80000, 82000],
        "discount_rate": 0.10,
        "reversion": {"terminal_noi": 90000, "growth_rate": 0.02},
    })
    assert result["reversion"]["method"] == "gordon_growth"
    # reversion = 90000/(0.10-0.02) = 1,125,000 received at period 2
    expected_rev_pv = (90000 / (0.10 - 0.02)) / (1.10 ** 2)
    assert result["present_value_reversion"] == pytest.approx(expected_rev_pv)


def test_basis_documents_no_growth_on_explicit_flows():
    result = discounted_cash_flow({"cash_flows": [100000], "discount_rate": 0.1})
    assert "applies no growth" in result["basis"]


# ─── discounted_cash_flow ─────────────────────────────────────────────────────

def test_dcf_value_is_pv_flows_plus_pv_reversion():
    result = discounted_cash_flow({
        "cash_flows": [100000, 100000, 100000],
        "discount_rate": 0.10,
        "reversion": {"amount": 1000000},
    })
    pv_flows = 100000/1.1 + 100000/1.21 + 100000/1.331
    pv_rev = 1000000 / (1.1 ** 3)
    assert result["present_value_cash_flows"] == pytest.approx(pv_flows)
    assert result["present_value_reversion"] == pytest.approx(pv_rev)
    assert result["value_indication"] == pytest.approx(pv_flows + pv_rev)
    assert "not an adopted value" in result["basis"]


def test_dcf_with_capitalized_reversion():
    result = discounted_cash_flow({
        "cash_flows": [80000, 80000],
        "discount_rate": 0.09,
        "reversion": {"terminal_noi": 90000, "exit_cap_rate": 0.085},
    })
    assert result["reversion"]["method"] == "capitalized"
    assert result["value_indication"] > 0


def test_dcf_requires_cash_flows_and_discount_rate():
    with pytest.raises(DCFError):
        discounted_cash_flow({"discount_rate": 0.1})        # no cash_flows
    with pytest.raises(DCFError):
        discounted_cash_flow({"cash_flows": [100]})          # no discount_rate


def test_dcf_breakdown_per_period():
    result = discounted_cash_flow({"cash_flows": [100, 100],
                                   "discount_rate": 0.10})
    assert [row["period"] for row in result["breakdown"]] == [1, 2]


def test_rounding_configurable():
    result = discounted_cash_flow({"cash_flows": [100000],
                                   "discount_rate": 0.1},
                                  config=DCFConfig(rounding=2))
    assert result["value_indication"] == round(100000 / 1.1, 2)


# ─── no default / derived rates ───────────────────────────────────────────────

def test_no_default_discount_rate():
    with pytest.raises(DCFError):
        discounted_cash_flow({"cash_flows": [100000]})  # missing -> error, no default


def test_no_default_or_derived_exit_rate():
    # capitalized reversion without an exit_cap_rate is rejected, never defaulted
    with pytest.raises(DCFError):
        reversion_value({"terminal_noi": 100000})


# ─── sensitivity / scenarios ──────────────────────────────────────────────────

def test_sensitivity_over_caller_discount_rates_only():
    inputs = {"cash_flows": [100000, 100000], "discount_rate": 0.10,
              "reversion": {"amount": 1000000}}
    grid = dcf_sensitivity(inputs, discount_rates=[0.08, 0.10, 0.12])
    assert [row["discount_rate"] for row in grid] == [0.08, 0.10, 0.12]
    # lower discount rate -> higher value
    assert grid[0]["value_indication"] > grid[2]["value_indication"]


def test_sensitivity_varies_exit_cap_rate_when_capitalized():
    inputs = {"cash_flows": [80000], "discount_rate": 0.09,
              "reversion": {"terminal_noi": 90000, "exit_cap_rate": 0.08}}
    grid = dcf_sensitivity(inputs, discount_rates=[0.09],
                           exit_cap_rates=[0.07, 0.09])
    assert len(grid) == 2
    assert grid[0]["exit_cap_rate"] == 0.07


# ─── audit (optional, non-blocking) ───────────────────────────────────────────

def test_audit_absent_by_default():
    result = discounted_cash_flow({"cash_flows": [100000], "discount_rate": 0.1})
    assert result["value_indication"] == pytest.approx(100000 / 1.1)


def test_audit_records_event_when_store_given():
    store = InMemoryAuditStore()
    discounted_cash_flow({"property_id": "P-1", "cash_flows": [100000],
                          "discount_rate": 0.1}, audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["entity_type"] == "valuation"
    assert events[0]["action"] == "dcf_valued"


# ─── no adopted value / reconciliation output ─────────────────────────────────

def test_no_adopted_value_or_reconciliation_output():
    result = discounted_cash_flow({"cash_flows": [100000], "discount_rate": 0.1})
    for forbidden in ("adopted_value", "final_value", "reconciliation",
                      "opinion"):
        assert forbidden not in result
