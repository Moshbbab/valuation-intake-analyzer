"""Tests for CIL-1 extended evidence-quality dimensions.

Covers each new factor scorer (computable + neutral fallback), the merged
factor/weight defaults, weight/strategy overrides, the tri-part advisory
envelope (result / explanation / assumptions_used), explainability-first
ordering, and the AVM-risk invariants (advisory flag, no value/admission key).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.comparable_intelligence import config as cfg  # noqa: E402
from engine.comparable_intelligence.quality import (  # noqa: E402
    ALL_FACTOR_SCORERS,
    EXTENDED_FACTOR_SCORERS,
    score_adjustment_burden,
    score_data_completeness,
    score_market_relevance,
    score_quality,
    score_transaction_reliability,
)
from engine.evidence import config as ecfg  # noqa: E402

NEUTRAL = ecfg.DEFAULT_NEUTRAL_SCORE


def _comp(**kwargs):
    base = {"comparable_id": "C-1"}
    base.update(kwargs)
    return base


# ─── data_completeness ────────────────────────────────────────────────────────

def test_data_completeness_fraction():
    # 3 of the 6 default required fields present.
    comp = _comp(unit_rate=1000, area=500, date="2025-01-01")
    assert score_data_completeness(comp, {}) == pytest.approx(0.5)


def test_data_completeness_empty_treats_blank_as_missing():
    comp = _comp(unit_rate=1000, area="", date=None)
    assert score_data_completeness(comp, {}) == pytest.approx(1 / 6)


def test_data_completeness_custom_required_fields():
    comp = _comp(unit_rate=1000, area=500)
    ctx = {"required_fields": ("unit_rate", "area")}
    assert score_data_completeness(comp, ctx) == pytest.approx(1.0)


# ─── transaction_reliability ──────────────────────────────────────────────────

def test_transaction_reliability_arms_and_verified():
    comp = _comp(arms_length=True, verified=True)
    assert score_transaction_reliability(comp, {}) == pytest.approx(1.0)


def test_transaction_reliability_unverified_blend():
    comp = _comp(arms_length=True, verified=False)  # [1.0, 0.5] -> 0.75
    assert score_transaction_reliability(comp, {}) == pytest.approx(0.75)


def test_transaction_reliability_sale_conditions_map():
    comp = _comp(sale_conditions="Distressed")
    assert score_transaction_reliability(comp, {}) == pytest.approx(0.20)


def test_transaction_reliability_no_signals_is_neutral():
    assert score_transaction_reliability(_comp(), {}) == pytest.approx(NEUTRAL)


# ─── market_relevance ─────────────────────────────────────────────────────────

def test_market_relevance_all_match():
    comp = _comp(use="office", zoning="C1")
    ctx = {"subject_use": "Office", "subject_zoning": "c1"}
    assert score_market_relevance(comp, ctx) == pytest.approx(1.0)


def test_market_relevance_partial():
    comp = _comp(use="office", zoning="C2")
    ctx = {"subject_use": "office", "subject_zoning": "C1"}
    assert score_market_relevance(comp, ctx) == pytest.approx(0.5)


def test_market_relevance_no_comparable_attrs_is_neutral():
    assert score_market_relevance(_comp(), {}) == pytest.approx(NEUTRAL)


# ─── adjustment_burden ────────────────────────────────────────────────────────

def _pct(value, direction="upward"):
    return {"adjustment_value": {"type": "percentage", "value": value,
                                 "direction": direction}}


def test_adjustment_burden_percentage():
    comp = _comp(unit_rate=1000, adjustments=[_pct(10), _pct(5, "downward")])
    # gross 0.15 over cap 1.0 -> 0.85
    assert score_adjustment_burden(comp, {}) == pytest.approx(0.85)


def test_adjustment_burden_absolute_uses_base():
    comp = _comp(unit_rate=1000, adjustments=[
        {"adjustment_value": {"type": "absolute", "value": 200,
                              "direction": "downward"}}])
    assert score_adjustment_burden(comp, {}) == pytest.approx(0.8)


def test_adjustment_burden_no_adjustments_is_neutral():
    assert score_adjustment_burden(_comp(unit_rate=1000), {}) == pytest.approx(NEUTRAL)


def test_adjustment_burden_cap_configurable():
    comp = _comp(unit_rate=1000, adjustments=[_pct(10)])
    assert score_adjustment_burden(comp, {"adjustment_burden_cap": 0.5}) \
        == pytest.approx(0.8)  # 1 - 0.10/0.5


# ─── factor registry ──────────────────────────────────────────────────────────

def test_extended_and_all_registries():
    assert set(EXTENDED_FACTOR_SCORERS) == {
        "data_completeness", "transaction_reliability",
        "market_relevance", "adjustment_burden"}
    # base evidence factors are included in the merged registry.
    assert "recency" in ALL_FACTOR_SCORERS
    assert "adjustment_burden" in ALL_FACTOR_SCORERS


# ─── score_quality envelope ───────────────────────────────────────────────────

def test_score_quality_envelope_shape():
    env = score_quality(_comp(unit_rate=1000, area=500, date="2025-01-01",
                              arms_length=True, verified=True))
    assert set(env) == {"result", "explanation", "assumptions_used",
                        "advisory", "basis"}
    assert env["advisory"] is True
    assert isinstance(env["explanation"], list) and env["explanation"]
    # explainability-first: reasoning headline mentions judgment, not a verdict.
    assert "judgment" in env["explanation"][0].lower()


def test_score_quality_result_metrics_present():
    env = score_quality(_comp(unit_rate=1000))
    result = env["result"]
    assert result["comparable_id"] == "C-1"
    assert 0.0 <= result["reliability_score"] <= 1.0
    assert set(result["factor_scores"]) == set(ALL_FACTOR_SCORERS)
    assert result["confidence_level"] in ("High", "Medium", "Low")


def test_score_quality_assumptions_used_records_provenance():
    env = score_quality(_comp(unit_rate=1000))
    used = env["assumptions_used"]
    assert used["strategy"] == "weighted"
    assert "data_completeness" in used["weights"]
    assert "recency" in used["weights"]
    assert used["required_fields"] == list(cfg.DEFAULT_REQUIRED_FIELDS)
    assert used["adjustment_burden_cap"] == cfg.DEFAULT_ADJUSTMENT_BURDEN_CAP


def test_score_quality_weight_override_changes_result():
    comp = _comp(unit_rate=1000, area=500, date="2025-01-01")
    low = score_quality(comp, config=cfg.QualityConfig(
        weights={"data_completeness": 1.0}))
    # only data_completeness weighted -> reliability equals its factor score.
    assert low["result"]["reliability_score"] == pytest.approx(
        low["result"]["factor_scores"]["data_completeness"])


def test_score_quality_context_defaults_applied():
    comp = _comp(unit_rate=1000, area=500)
    env = score_quality(comp, config=cfg.QualityConfig(
        context_defaults={"required_fields": ("unit_rate", "area")}))
    assert env["result"]["factor_scores"]["data_completeness"] == pytest.approx(1.0)
    assert env["assumptions_used"]["required_fields"] == ["unit_rate", "area"]


# ─── AVM-risk invariants ──────────────────────────────────────────────────────

def test_no_value_or_admission_keys():
    env = score_quality(_comp(unit_rate=1000))
    for forbidden in ("value", "adopted_value", "final_value", "concluded_value",
                      "price", "opinion", "admission", "inclusion_decision"):
        assert forbidden not in env["result"]
    assert "not a value" in env["basis"]
