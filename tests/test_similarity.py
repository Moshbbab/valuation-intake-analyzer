"""Tests for comparable similarity & weighting intelligence (decision support).

Verifies per-dimension similarity, ranking, weighting suggestions, the
similarity/reliability separation (pure similarity by default), the explicit
optional reliability blend, and that the weighting strategy plugs into the
existing ComparableApproachConfig.weighting callable.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.valuation.config import (  # noqa: E402
    ComparableApproachConfig,
    SimilarityConfig,
)
from engine.valuation.comparable_approach import run_comparable_approach  # noqa: E402
from engine.valuation.similarity import (  # noqa: E402
    as_weighting_strategy,
    confidence_contribution,
    rank_comparables,
    score_similarity,
    similarity_weights,
)

SUBJECT = {"location_score": 0.90, "area": 100.0, "age": 10,
           "use": "office", "zoning": "commercial"}


def _case(cid, *, location=0.9, area=100.0, age=10, use="office",
          zoning="commercial", decision="include", reliability=0.8,
          unit_rate=1000.0):
    comparable = {"comparable_id": cid, "unit_rate": unit_rate}
    for key, value in (("location_score", location), ("area", area),
                       ("age", age), ("use", use), ("zoning", zoning)):
        if value is not None:
            comparable[key] = value
    return {"comparable": comparable,
            "assessment": {"inclusion_decision": decision,
                           "reliability_score": reliability,
                           "confidence_level": "High"},
            "adjustments": []}


# ─── per-dimension similarity ─────────────────────────────────────────────────

def test_location_similarity():
    near = score_similarity(SUBJECT, {"comparable_id": "C", "location_score": 0.88})
    far = score_similarity(SUBJECT, {"comparable_id": "C", "location_score": 0.40})
    assert near["components"]["location"] > far["components"]["location"]


def test_area_similarity():
    near = score_similarity(SUBJECT, {"comparable_id": "C", "area": 105})
    far = score_similarity(SUBJECT, {"comparable_id": "C", "area": 300})
    assert near["components"]["area"] > far["components"]["area"]


def test_age_similarity():
    near = score_similarity(SUBJECT, {"comparable_id": "C", "age": 12})
    far = score_similarity(SUBJECT, {"comparable_id": "C", "age": 60})
    assert near["components"]["age"] > far["components"]["age"]


def test_use_similarity():
    same = score_similarity(SUBJECT, {"comparable_id": "C", "use": "office"})
    diff = score_similarity(SUBJECT, {"comparable_id": "C", "use": "retail"})
    assert same["components"]["use"] == 1.0
    assert diff["components"]["use"] == 0.0


def test_zoning_similarity():
    same = score_similarity(SUBJECT, {"comparable_id": "C", "zoning": "commercial"})
    diff = score_similarity(SUBJECT, {"comparable_id": "C", "zoning": "industrial"})
    assert same["components"]["zoning"] == 1.0
    assert diff["components"]["zoning"] == 0.0


def test_missing_dimension_handled_safely():
    comp = {"comparable_id": "C", "location_score": 0.9, "area": 100}  # no age/use/zoning
    result = score_similarity(SUBJECT, comp)
    assert result["similarity"] is not None  # computed from available dims
    assert "age" in result["missing_dimensions"]
    assert result["components"]["age"] is None


# ─── injectable scorers / dimensions / weights ────────────────────────────────

def test_custom_dimension_scorer():
    config = SimilarityConfig(
        scorers={"frontage": lambda s, c: 1.0 if c.get("frontage") else 0.0},
        dimensions=("frontage",))
    yes = score_similarity(SUBJECT, {"comparable_id": "C", "frontage": 20}, config=config)
    no = score_similarity(SUBJECT, {"comparable_id": "C"}, config=config)
    assert yes["similarity"] == 1.0
    assert no["similarity"] == 0.0


def test_custom_dimension_weights_change_aggregate():
    comp = {"comparable_id": "C", "location_score": 0.0, "area": 100,
            "age": 10, "use": "office", "zoning": "commercial"}
    # location is the only mismatched dim; weighting it heavily lowers similarity
    light = score_similarity(SUBJECT, comp,
                             config=SimilarityConfig(weights={"location": 1}))
    heavy = score_similarity(SUBJECT, comp,
                             config=SimilarityConfig(weights={"location": 100}))
    assert heavy["similarity"] < light["similarity"]


def test_unknown_dimension_skipped_safely():
    config = SimilarityConfig(dimensions=("location", "nonexistent"))
    result = score_similarity(SUBJECT, {"comparable_id": "C", "location_score": 0.9},
                              config=config)
    assert result["components"]["nonexistent"] is None
    assert result["similarity"] is not None


# ─── weighting suggestions: pure similarity by default ────────────────────────

def test_pure_similarity_default_ignores_reliability():
    # A is far less similar but has far higher reliability; default must follow similarity.
    cases = [
        _case("A", location=0.1, area=20, age=80, use="retail", zoning="industrial",
              reliability=0.99),
        _case("B", location=0.9, area=100, age=10, use="office", zoning="commercial",
              reliability=0.10),
    ]
    weights = similarity_weights(SUBJECT, cases)
    assert weights["B"] > weights["A"]            # similarity wins, not reliability


def test_weighting_suggestions_normalized():
    cases = [_case("A"), _case("B", location=0.5, area=150)]
    weights = similarity_weights(SUBJECT, cases)
    assert round(sum(weights.values()), 6) == 1.0


def test_review_comparable_not_auto_included():
    cases = [_case("A"), _case("R", decision="review")]
    weights = similarity_weights(SUBJECT, cases)
    assert "R" not in weights


def test_excluded_comparable_not_weighted():
    cases = [_case("A"), _case("X", decision="exclude")]
    weights = similarity_weights(SUBJECT, cases)
    assert "X" not in weights


# ─── optional, explicit reliability blend ─────────────────────────────────────

def test_reliability_blend_explicitly_enabled():
    cases = [
        _case("A", location=0.1, area=20, age=80, use="retail", zoning="industrial",
              reliability=0.99),
        _case("B", location=0.9, area=100, age=10, use="office", zoning="commercial",
              reliability=0.10),
    ]
    pure = similarity_weights(SUBJECT, cases)
    blended = similarity_weights(SUBJECT, cases,
                                 config=SimilarityConfig(blend_reliability=1.0))
    # full reliability blend flips the ordering relative to pure similarity
    assert pure["B"] > pure["A"]
    assert blended["A"] > blended["B"]


def test_confidence_contribution_reports_mode():
    cases = [_case("A"), _case("B", location=0.6)]
    weights = similarity_weights(SUBJECT, cases)
    pure = confidence_contribution(cases, weights)
    assert pure["mode"] == "pure_similarity"
    blended_cfg = SimilarityConfig(blend_reliability=0.5)
    blended = confidence_contribution(cases, weights, config=blended_cfg)
    assert "blended(reliability=0.5)" in blended["mode"]
    assert "A" in pure["contributions"]


# ─── ranking ──────────────────────────────────────────────────────────────────

def test_ranking_output():
    cases = [_case("A", location=0.2, area=40, age=70, use="retail", zoning="industrial"),
             _case("B")]  # B identical to subject
    ranked = rank_comparables(SUBJECT, cases)
    assert ranked[0]["comparable_id"] == "B"
    assert ranked[0]["rank"] == 1


def test_custom_ranking_callable():
    cases = [_case("A"), _case("B")]
    config = SimilarityConfig(ranking=lambda rows: list(reversed(rows)))
    ranked = rank_comparables(SUBJECT, cases, config=config)
    assert [r["comparable_id"] for r in ranked] == ["B", "A"]


# ─── plug into the existing comparable approach ───────────────────────────────

def test_as_weighting_strategy_plugs_into_comparable_approach():
    cases = [
        _case("A", location=0.9, area=100, unit_rate=1000.0),   # very similar
        _case("B", location=0.2, area=300, unit_rate=2000.0),   # dissimilar
    ]
    strategy = as_weighting_strategy(SUBJECT)
    cfg = ComparableApproachConfig(weighting=strategy)
    result = run_comparable_approach(cases, config=cfg)
    # weights came from similarity (A more similar -> higher weight)
    assert result["weights"]["A"] > result["weights"]["B"]
    assert round(sum(result["weights"].values()), 6) == 1.0
    assert "not a final valuation opinion" in result["basis"]
