"""Tests for the comparable-approach calculation support.

Exercises the calculation against the real Evidence and Adjustments foundations
where useful, and with crafted assessment dicts where deterministic inclusion
decisions are needed. Verifies it produces support (adjusted rates, weights,
indicated range) without forcing a conclusion.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.adjustments.registry import (  # noqa: E402
    apply_override,
    create_adjustment,
)
from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.config import ComparableApproachConfig  # noqa: E402
from engine.valuation.comparable_approach import (  # noqa: E402
    adjusted_unit_rate,
    apply_adjustment_to_rate,
    indicated_range,
    normalize_weights,
    parse_adjustment_value,
    run_comparable_approach,
)


def _adj(comparable_id, factor, direction, adjustment_value, **extra):
    data = {
        "comparable_id": comparable_id,
        "factor": factor,
        "direction": direction,
        "amount_or_range": "see adjustment_value",
        "rationale": "test",
        "evidence_reference": comparable_id,
        "confidence_level": "High",
    }
    if adjustment_value is not None:
        data["adjustment_value"] = adjustment_value
    data.update(extra)
    return create_adjustment(data)


def _case(comparable_id, unit_rate, decision, reliability, adjustments=None,
          confidence="High"):
    return {
        "comparable": {"comparable_id": comparable_id, "unit_rate": unit_rate},
        "assessment": {"inclusion_decision": decision,
                       "reliability_score": reliability,
                       "confidence_level": confidence},
        "adjustments": adjustments or [],
    }


# ─── apply_adjustment_to_rate / parse ─────────────────────────────────────────

def test_percentage_upward():
    av = {"type": "percentage", "value": 10, "direction": "upward"}
    assert apply_adjustment_to_rate(1000.0, av) == 1100.0


def test_percentage_downward():
    av = {"type": "percentage", "value": 10, "direction": "downward"}
    assert apply_adjustment_to_rate(1000.0, av) == 900.0


def test_absolute_and_neutral():
    assert apply_adjustment_to_rate(
        1000.0, {"type": "absolute", "value": 50, "direction": "upward"}) == 1050.0
    assert apply_adjustment_to_rate(
        1000.0, {"type": "absolute", "value": 50, "direction": "neutral"}) == 1000.0


def test_range_percentage_returns_range():
    av = {"type": "range_percentage", "value": {"low": 5, "high": 10},
          "direction": "upward"}
    out = apply_adjustment_to_rate(1000.0, av)
    assert out == {"low": 1050.0, "high": 1100.0}


def test_parse_skips_missing_or_malformed():
    assert parse_adjustment_value({"factor": "x"}) is None  # no field
    assert parse_adjustment_value(
        {"adjustment_value": {"type": "bogus", "value": 1}}) is None
    assert parse_adjustment_value(
        {"adjustment_value": {"type": "percentage", "value": "lots"}}) is None
    good = parse_adjustment_value(
        {"adjustment_value": {"type": "percentage", "value": 5},
         "direction": "downward"})
    assert good["direction"] == "downward"  # falls back to top-level direction


# ─── adjusted_unit_rate ───────────────────────────────────────────────────────

def test_adjusted_unit_rate_percentage():
    comp = {"comparable_id": "C-1", "unit_rate": 1000.0}
    adjustments = [_adj("C-1", "location", "upward",
                        {"type": "percentage", "value": 5})]
    result = adjusted_unit_rate(comp, adjustments)
    assert result["adjusted"] == 1050.0
    assert result["applied"] == 1 and result["skipped"] == 0


def test_adjusted_unit_rate_downward():
    comp = {"comparable_id": "C-2", "unit_rate": 1000.0}
    adjustments = [_adj("C-2", "size", "downward",
                        {"type": "percentage", "value": 8})]
    assert adjusted_unit_rate(comp, adjustments)["adjusted"] == 920.0


def test_adjusted_unit_rate_range():
    comp = {"comparable_id": "C-3", "unit_rate": 1000.0}
    adjustments = [_adj("C-3", "location", "upward",
                        {"type": "range_percentage",
                         "value": {"low": 5, "high": 10}})]
    assert adjusted_unit_rate(comp, adjustments)["adjusted"] == {
        "low": 1050.0, "high": 1100.0}


def test_missing_machine_readable_adjustment_is_skipped_safely():
    comp = {"comparable_id": "C-4", "unit_rate": 1000.0}
    adjustments = [_adj("C-4", "condition", "upward", None)]  # free-form only
    result = adjusted_unit_rate(comp, adjustments)
    assert result["adjusted"] == 1000.0  # unchanged
    assert result["applied"] == 0 and result["skipped"] == 1


def test_missing_unit_rate_handled_safely():
    result = adjusted_unit_rate({"comparable_id": "C-5"}, [])
    assert result["adjusted"] is None
    assert "note" in result


def test_manual_override_on_adjustment_preserved():
    adj = _adj("C-6", "location", "upward", {"type": "percentage", "value": 5})
    overridden = apply_override(adj, changes={"confidence_level": "Low"},
                                rationale="downgraded after review",
                                actor="lead")
    # the override block survives ...
    assert overridden["manual_override"]["applied"] is True
    # ... and the calculation still reads the adjustment_value correctly
    result = adjusted_unit_rate({"comparable_id": "C-6", "unit_rate": 1000.0},
                                [overridden])
    assert result["adjusted"] == 1050.0


# ─── normalize_weights ────────────────────────────────────────────────────────

def test_weight_normalization_sums_to_one():
    cases = [_case("C-1", 1000, "include", 0.9),
             _case("C-2", 1000, "include", 0.3)]
    weights = normalize_weights(cases)
    assert round(sum(weights.values()), 6) == 1.0
    assert weights["C-1"] > weights["C-2"]


def test_excluded_comparable_ignored():
    cases = [_case("C-1", 1000, "include", 0.9),
             _case("C-9", 1000, "exclude", 0.8)]
    weights = normalize_weights(cases)
    assert "C-9" not in weights
    assert set(weights) == {"C-1"}


def test_review_comparable_not_auto_included():
    cases = [_case("C-1", 1000, "include", 0.9),
             _case("C-7", 1000, "review", 0.7)]
    weights = normalize_weights(cases)
    assert "C-7" not in weights


def test_custom_weighting_callable():
    cases = [_case("C-1", 1000, "include", 0.9),
             _case("C-2", 1000, "include", 0.3)]
    config = ComparableApproachConfig(
        weighting=lambda assessed: {e["comparable"]["comparable_id"]: 0.5
                                    for e in assessed})
    weights = normalize_weights(cases, config=config)
    assert weights == {"C-1": 0.5, "C-2": 0.5}


# ─── indicated_range & run_comparable_approach ────────────────────────────────

def test_indicated_range_support_only():
    adjusted = {"C-1": 1050.0, "C-2": 950.0}
    weights = {"C-1": 0.7, "C-2": 0.3}
    rng = indicated_range(adjusted, weights)
    assert rng["low"] == 950.0 and rng["high"] == 1050.0
    assert 950.0 <= rng["weighted_indication"] <= 1050.0


def test_run_comparable_approach_end_to_end():
    cases = [
        _case("C-1", 1000, "include", 0.9,
              [_adj("C-1", "location", "upward",
                    {"type": "percentage", "value": 5})]),
        _case("C-2", 1200, "include", 0.6,
              [_adj("C-2", "size", "downward",
                    {"type": "percentage", "value": 10})]),
        _case("C-3", 800, "exclude", 0.2,
              [_adj("C-3", "time", "upward",
                    {"type": "percentage", "value": 5})]),
        _case("C-4", 900, "review", 0.5),
    ]
    audit = InMemoryAuditStore()
    result = run_comparable_approach(cases, audit_store=audit)

    # excluded + review are not used
    assert set(result["weights"]) == {"C-1", "C-2"}
    assert "C-3" in result["excluded"] and "C-4" in result["excluded"]
    # adjusted rates computed for included
    rows = {r["comparable_id"]: r for r in result["comparables"]}
    assert rows["C-1"]["adjusted"] == 1050.0
    assert rows["C-2"]["adjusted"] == 1080.0
    # indicated range is support, not a single forced opinion
    assert result["indicated_range"]["low"] == 1050.0
    assert result["indicated_range"]["high"] == 1080.0
    assert "not a final valuation opinion" in result["basis"]
    # audit recorded one event per included comparable
    assert len(audit) == 2


def test_rounding_is_configurable():
    comp = {"comparable_id": "C-1", "unit_rate": 1000.0}
    adjustments = [_adj("C-1", "location", "upward",
                        {"type": "percentage", "value": 3.333})]
    config = ComparableApproachConfig(rounding=2)
    assert adjusted_unit_rate(comp, adjustments, config=config)["adjusted"] == 1033.33
