"""Tests for the minimal, non-rigid Adjustment Foundation.

These exercise the required capabilities (create / list / override), the
required validation (missing fields, confidence level), custom injectable
config, and the override's preservation of the prior value.
"""

import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.adjustments.config import AdjustmentConfig  # noqa: E402
from engine.adjustments.registry import (  # noqa: E402
    AdjustmentError,
    apply_override,
    create_adjustment,
    list_adjustments,
)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..",
                            "data-contracts", "adjustment.schema.json")


def _valid_adjustment(**overrides):
    data = {
        "comparable_id": "C-1",
        "factor": "location",
        "direction": "upward",
        "amount_or_range": "5% to 8%",
        "rationale": "Subject occupies a superior corner position.",
        "evidence_reference": "comparable:C-1",
        "confidence_level": "Medium",
    }
    data.update(overrides)
    return data


# ─── create_adjustment ────────────────────────────────────────────────────────

def test_create_valid_adjustment():
    record = create_adjustment(_valid_adjustment())
    assert record["adjustment_id"].startswith("ADJ-")
    assert record["manual_override"] is None
    assert record["created_at"]
    assert record["factor"] == "location"


def test_create_preserves_extra_fields():
    record = create_adjustment(_valid_adjustment(engagement_ref="ENG-42"))
    assert record["engagement_ref"] == "ENG-42"  # additionalProperties


def test_amount_or_range_accepts_number_and_object():
    numeric = create_adjustment(_valid_adjustment(amount_or_range=0))
    assert numeric["amount_or_range"] == 0
    ranged = create_adjustment(
        _valid_adjustment(amount_or_range={"low": 0.05, "high": 0.08}))
    assert ranged["amount_or_range"] == {"low": 0.05, "high": 0.08}


def test_reject_missing_required_field():
    bad = _valid_adjustment()
    del bad["factor"]
    with pytest.raises(AdjustmentError) as exc:
        create_adjustment(bad)
    assert "factor" in str(exc.value)


def test_reject_none_required_field():
    with pytest.raises(AdjustmentError):
        create_adjustment(_valid_adjustment(amount_or_range=None))


def test_create_does_not_mutate_input():
    data = _valid_adjustment()
    create_adjustment(data)
    assert "adjustment_id" not in data
    assert "created_at" not in data


# ─── configuration-driven vocabulary ──────────────────────────────────────────

def test_unknown_factor_rejected_by_default_config():
    with pytest.raises(AdjustmentError):
        create_adjustment(_valid_adjustment(factor="paranormal"))


def test_unknown_confidence_level_rejected():
    with pytest.raises(AdjustmentError):
        create_adjustment(_valid_adjustment(confidence_level="Certain"))


def test_custom_config_allows_custom_vocabulary():
    config = AdjustmentConfig(factors=("bespoke",),
                              directions=("sideways",),
                              confidence_levels=("Indicative",))
    record = create_adjustment(
        _valid_adjustment(factor="bespoke", direction="sideways",
                          confidence_level="Indicative"),
        config=config,
    )
    assert record["factor"] == "bespoke"
    assert record["direction"] == "sideways"


def test_empty_vocabulary_is_unrestricted():
    config = AdjustmentConfig(factors=(), directions=(), confidence_levels=())
    record = create_adjustment(
        _valid_adjustment(factor="anything", direction="whatever",
                          confidence_level="freeform"),
        config=config,
    )
    assert record["factor"] == "anything"


# ─── list_adjustments ─────────────────────────────────────────────────────────

def test_list_and_filter():
    a1 = create_adjustment(_valid_adjustment(factor="location"))
    a2 = create_adjustment(_valid_adjustment(factor="time", comparable_id="C-2"))
    store = [a1, a2]
    assert len(list_adjustments(store)) == 2
    assert list_adjustments(store, factor="time") == [a2]
    assert list_adjustments(store, comparable_id="C-2") == [a2]


def test_list_filter_overridden():
    a1 = create_adjustment(_valid_adjustment())
    a2 = create_adjustment(_valid_adjustment())
    a2 = apply_override(a2, changes={"confidence_level": "High"},
                        rationale="Corroborated by a second comparable")
    store = [a1, a2]
    assert list_adjustments(store, overridden=True) == [a2]
    assert list_adjustments(store, overridden=False) == [a1]


# ─── apply_override ───────────────────────────────────────────────────────────

def test_apply_override_records_change_and_explanation():
    record = create_adjustment(_valid_adjustment(confidence_level="Low"))
    updated = apply_override(
        record,
        changes={"confidence_level": "High", "amount_or_range": "10%"},
        rationale="Two arm's-length comparables confirm the magnitude",
        actor="lead_valuer",
    )
    override = updated["manual_override"]
    assert updated["confidence_level"] == "High"
    assert updated["amount_or_range"] == "10%"
    assert override["applied"] is True
    assert override["actor"] == "lead_valuer"
    assert override["changes"]["confidence_level"] == {"from": "Low", "to": "High"}
    assert override["timestamp"]
    assert override["explanation"]  # ready for audit-trail recording


def test_override_preserves_prior_value_and_original_recoverable():
    record = create_adjustment(_valid_adjustment(confidence_level="Low"))
    updated = apply_override(record, changes={"confidence_level": "High"},
                             rationale="see file note 7")
    # original record untouched and recoverable ...
    assert record["confidence_level"] == "Low"
    assert record["manual_override"] is None
    # ... and prior value snapshotted on the new record
    assert updated["manual_override"]["previous"]["confidence_level"] == "Low"


def test_override_requires_rationale():
    record = create_adjustment(_valid_adjustment())
    with pytest.raises(AdjustmentError):
        apply_override(record, changes={"confidence_level": "High"}, rationale=" ")


def test_override_requires_nonempty_changes():
    record = create_adjustment(_valid_adjustment())
    with pytest.raises(AdjustmentError):
        apply_override(record, changes={}, rationale="x")


def test_override_validates_against_config():
    record = create_adjustment(_valid_adjustment())
    with pytest.raises(AdjustmentError):
        apply_override(record, changes={"factor": "paranormal"},
                       rationale="reclassify")


# ─── contract ────────────────────────────────────────────────────────────────

def test_schema_is_valid_json():
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    assert schema["title"] == "Adjustment"


def test_created_adjustment_matches_schema_if_jsonschema_available():
    jsonschema = pytest.importorskip("jsonschema")
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    record = create_adjustment(_valid_adjustment())
    jsonschema.validate(record, schema)
