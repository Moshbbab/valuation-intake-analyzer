"""Tests for the configurable Evidence Registry scoring.

These tests deliberately exercise the *configurability* of the module: custom
weights, custom thresholds, alternative strategies, pluggable scorers and the
manual-override mechanism — i.e. the "avoid rigid systems" guarantees, not just
the happy path.
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.evidence import config as cfg  # noqa: E402
from engine.evidence.scoring import (  # noqa: E402
    assess_comparable,
    decide_inclusion,
    score_evidence,
    score_source_quality,
)


def _fresh_comparable():
    """A high-quality, recent, well-located, similarly sized comparable."""
    return {
        "comparable_id": "C-1",
        "source": "registry",
        "date": date.today().isoformat(),
        "area": 100.0,
        "location_score": 0.9,
    }


# ─── score_evidence ───────────────────────────────────────────────────────────

def test_score_in_unit_range_and_has_breakdown():
    result = score_evidence(_fresh_comparable(),
                            context={"subject_area": 100.0})
    assert 0.0 <= result["reliability_score"] <= 1.0
    assert set(result["factor_scores"]) == set(cfg.DEFAULT_WEIGHTS)
    assert result["explanation"]  # non-empty, auditable breakdown


def test_strong_comparable_scores_high():
    result = score_evidence(_fresh_comparable(),
                            context={"subject_area": 100.0})
    assert result["reliability_score"] >= cfg.DEFAULT_CONFIDENCE_BANDS["high"]
    assert result["confidence_level"] == "High"


def test_weights_are_configurable_and_change_the_result():
    comp = _fresh_comparable()
    comp["source"] = "anecdotal"  # weak source
    default = score_evidence(comp, context={"subject_area": 100.0})
    # Re-weight everything onto source_quality -> score must drop noticeably.
    reweighted = score_evidence(
        comp,
        context={"subject_area": 100.0},
        weights={"recency": 0, "location_proximity": 0,
                 "source_quality": 1, "size_similarity": 0},
    )
    assert reweighted["reliability_score"] < default["reliability_score"]


def test_source_quality_map_is_configurable():
    comp = _fresh_comparable()
    comp["source"] = "my_trusted_desk"
    result = score_evidence(
        comp,
        context={"source_quality_map": {"my_trusted_desk": 1.0}},
        weights={"source_quality": 1},
        factor_scorers={"source_quality": score_source_quality},
    )
    assert result["reliability_score"] == 1.0


def test_recency_decays_with_age():
    old = _fresh_comparable()
    old["date"] = (date.today() - timedelta(days=730)).isoformat()
    fresh = score_evidence(_fresh_comparable())["reliability_score"]
    aged = score_evidence(old)["reliability_score"]
    assert aged < fresh


def test_min_strategy_is_conservative():
    comp = _fresh_comparable()
    comp["source"] = "anecdotal"  # forces one low factor
    weighted = score_evidence(comp, context={"subject_area": 100.0},
                              strategy="weighted")["reliability_score"]
    worst = score_evidence(comp, context={"subject_area": 100.0},
                           strategy="min")["reliability_score"]
    assert worst <= weighted


def test_custom_strategy_callable_is_an_alternative_path():
    comp = _fresh_comparable()
    result = score_evidence(
        comp,
        strategy=lambda factors, weights: 0.123,
    )
    assert result["reliability_score"] == 0.123
    assert result["strategy"] == "custom"


def test_missing_inputs_fall_back_to_neutral_not_crash():
    sparse = {"comparable_id": "C-2", "source": "unknown_source"}
    result = score_evidence(sparse)
    assert 0.0 <= result["reliability_score"] <= 1.0


# ─── decide_inclusion ─────────────────────────────────────────────────────────

def test_auto_decision_thresholds():
    assert decide_inclusion(0.9)["inclusion_decision"] == "include"
    assert decide_inclusion(0.5)["inclusion_decision"] == "review"
    assert decide_inclusion(0.1)["inclusion_decision"] == "exclude"


def test_thresholds_are_configurable():
    # Tighten the bar so a 0.8 score no longer auto-includes.
    decision = decide_inclusion(0.8, thresholds={"include": 0.95,
                                                 "review": 0.6})
    assert decision["inclusion_decision"] == "review"


def test_manual_override_wins_but_records_auto():
    decision = decide_inclusion(
        0.1,  # would auto-exclude
        manual_override={"decision": "include",
                         "rationale": "Comparable verified on site",
                         "actor": "lead_valuer"},
    )
    assert decision["inclusion_decision"] == "include"
    assert decision["decided_by"] == "manual_override"
    assert decision["auto_decision"] == "exclude"  # still auditable
    assert decision["rationale"]


# ─── assess_comparable (end-to-end convenience) ───────────────────────────────

def test_assess_comparable_combines_score_and_decision():
    result = assess_comparable(_fresh_comparable(),
                               context={"subject_area": 100.0})
    assert "reliability_score" in result
    assert result["inclusion_decision"] in {"include", "review", "exclude"}


def test_assess_comparable_respects_embedded_override():
    comp = _fresh_comparable()
    comp["source"] = "anecdotal"
    comp["manual_override"] = {"decision": "exclude",
                               "rationale": "Distressed sale, not arm's length"}
    result = assess_comparable(comp, context={"subject_area": 100.0})
    assert result["inclusion_decision"] == "exclude"
    assert result["decided_by"] == "manual_override"
