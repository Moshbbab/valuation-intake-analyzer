"""Tests for cross-approach agreement / dispersion calculation support.

Covers central extraction (point/range), mean vs weighted mean, spread and
percentage, std dev / weighted std dev, coefficient of variation, per-approach
deviations, the degenerate single-approach case, the normalize_against option,
rounding, weight reuse from reconciliation, and the absence of any confidence
label or adopted value.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.valuation.agreement import approach_dispersion  # noqa: E402
from engine.valuation.config import AgreementConfig  # noqa: E402
from engine.valuation.reconciliation import (  # noqa: E402
    ReconciliationError,
    reconcile,
)


def _two_equal():
    return [{"approach": "comparable", "value": 1000000},
            {"approach": "income", "value": 1200000}]


# ─── central tendency ─────────────────────────────────────────────────────────

def test_mean_and_weighted_mean_equal_weights():
    result = approach_dispersion(_two_equal())
    assert result["mean"] == 1100000
    assert result["weighted_mean"] == 1100000


def test_weighted_mean_matches_reconcile():
    inds = [{"approach": "comparable", "value": 1000000, "weight": 3},
            {"approach": "income", "value": 1200000, "weight": 1}]
    disp = approach_dispersion(inds)
    rec = reconcile(inds)
    assert disp["weighted_mean"] == rec["weighted_indication"]


def test_range_uses_midpoint():
    result = approach_dispersion([
        {"approach": "a", "range": {"low": 900000, "high": 1100000}},
        {"approach": "b", "value": 1100000},
    ])
    assert result["centrals"]["a"] == 1000000  # midpoint
    assert result["mean"] == 1050000


def test_value_overrides_range_for_central():
    result = approach_dispersion([
        {"approach": "a", "value": 1180000,
         "range": {"low": 1000000, "high": 1300000}},
    ])
    assert result["centrals"]["a"] == 1180000


# ─── dispersion ───────────────────────────────────────────────────────────────

def test_spread_and_std_and_cov():
    result = approach_dispersion(_two_equal())
    assert result["spread"] == 200000
    assert result["std_dev"] == pytest.approx(100000.0)
    assert result["spread_pct"] == pytest.approx(200000 / 1100000)
    assert result["coefficient_of_variation"] == pytest.approx(100000 / 1100000)


def test_deviations_from_weighted_mean():
    result = approach_dispersion(_two_equal())
    assert result["deviations"]["comparable"] == pytest.approx(-100000)
    assert result["deviations"]["income"] == pytest.approx(100000)
    assert result["max_abs_deviation"] == pytest.approx(100000)


def test_weighted_std_dev():
    inds = [{"approach": "a", "value": 1000000, "weight": 3},
            {"approach": "b", "value": 1200000, "weight": 1}]
    result = approach_dispersion(inds)
    wm = 1050000.0  # 0.75*1,000,000 + 0.25*1,200,000
    expected = math.sqrt(0.75 * (1000000 - wm) ** 2 + 0.25 * (1200000 - wm) ** 2)
    assert result["weighted_std_dev"] == pytest.approx(expected)


# ─── degenerate / edges ───────────────────────────────────────────────────────

def test_single_approach_zero_dispersion():
    result = approach_dispersion([{"approach": "only", "value": 1000000}])
    assert result["n"] == 1
    assert result["spread"] == 0
    assert result["std_dev"] == 0
    assert result["spread_pct"] == pytest.approx(0.0)
    assert result["coefficient_of_variation"] == pytest.approx(0.0)


def test_empty_rejected():
    with pytest.raises(ReconciliationError):
        approach_dispersion([])


def test_missing_value_rejected():
    with pytest.raises(ReconciliationError):
        approach_dispersion([{"approach": "a"}])


def test_missing_approach_rejected():
    with pytest.raises(ReconciliationError):
        approach_dispersion([{"value": 1000000}])


# ─── config ───────────────────────────────────────────────────────────────────

def test_normalize_against_mean_vs_weighted_mean():
    inds = [{"approach": "a", "value": 1000000, "weight": 3},
            {"approach": "b", "value": 1200000, "weight": 1}]
    against_mean = approach_dispersion(
        inds, config=AgreementConfig(normalize_against="mean"))
    against_wm = approach_dispersion(
        inds, config=AgreementConfig(normalize_against="weighted_mean"))
    assert against_mean["spread_pct"] == pytest.approx(200000 / 1100000)
    assert against_wm["spread_pct"] == pytest.approx(200000 / 1050000)


def test_normalize_against_callable():
    cfg = AgreementConfig(normalize_against=lambda centrals, weights: max(centrals.values()))
    result = approach_dispersion(_two_equal(), config=cfg)
    assert result["spread_pct"] == pytest.approx(200000 / 1200000)


def test_unknown_normalize_against_rejected():
    with pytest.raises(ReconciliationError):
        approach_dispersion(_two_equal(),
                            config=AgreementConfig(normalize_against="nope"))


def test_rounding_configurable():
    result = approach_dispersion(_two_equal(), config=AgreementConfig(rounding=2))
    assert result["spread_pct"] == round(200000 / 1100000, 2)


# ─── no confidence label / adopted value ──────────────────────────────────────

def test_no_confidence_or_adopted_output():
    result = approach_dispersion(_two_equal())
    for forbidden in ("confidence", "reliability_rating", "adopted_value",
                      "verdict", "band", "pass"):
        assert forbidden not in result
    assert "not a confidence opinion" in result["basis"]
