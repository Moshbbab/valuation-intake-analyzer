"""Tests for the minimal, non-rigid Assumptions Foundation.

These exercise the required capabilities (create / list / override), the
required validation (missing fields rejected), the override's preservation of
the prior value, and the configuration-driven categories / confidence levels.
"""

import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.assumptions.config import AssumptionConfig  # noqa: E402
from engine.assumptions.registry import (  # noqa: E402
    AssumptionError,
    apply_override,
    create_assumption,
    list_assumptions,
)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..",
                            "data-contracts", "assumption.schema.json")


def _valid_assumption(**overrides):
    data = {
        "category": "special",
        "statement": "Vacant possession is assumed at the valuation date.",
        "basis": "Client instruction letter dated 2026-05-01",
        "confidence_level": "Medium",
        "rationale": "No tenancy schedule provided; instructed to assume vacant.",
        "affected_method": "income",
        "sensitivity_link": "scenario:vacant-vs-let",
    }
    data.update(overrides)
    return data


# ─── create_assumption ────────────────────────────────────────────────────────

def test_create_valid_assumption():
    record = create_assumption(_valid_assumption())
    assert record["assumption_id"].startswith("A-")
    assert record["manual_override"] is None
    assert record["created_at"]
    assert record["category"] == "special"


def test_create_preserves_extra_fields():
    record = create_assumption(_valid_assumption(engagement_ref="ENG-42"))
    assert record["engagement_ref"] == "ENG-42"  # additionalProperties


def test_reject_missing_required_field():
    bad = _valid_assumption()
    del bad["statement"]
    with pytest.raises(AssumptionError) as exc:
        create_assumption(bad)
    assert "statement" in str(exc.value)


def test_reject_blank_required_field():
    with pytest.raises(AssumptionError):
        create_assumption(_valid_assumption(basis="   "))


def test_create_does_not_mutate_input():
    data = _valid_assumption()
    create_assumption(data)
    assert "assumption_id" not in data
    assert "created_at" not in data


# ─── configuration-driven categories / confidence levels ──────────────────────

def test_unknown_category_rejected_by_default_config():
    with pytest.raises(AssumptionError):
        create_assumption(_valid_assumption(category="bespoke"))


def test_custom_config_allows_custom_category_and_level():
    config = AssumptionConfig(categories=("bespoke",),
                              confidence_levels=("Indicative",))
    record = create_assumption(
        _valid_assumption(category="bespoke", confidence_level="Indicative"),
        config=config,
    )
    assert record["category"] == "bespoke"
    assert record["confidence_level"] == "Indicative"


def test_unknown_confidence_level_rejected():
    with pytest.raises(AssumptionError):
        create_assumption(_valid_assumption(confidence_level="Certain"))


# ─── list_assumptions ─────────────────────────────────────────────────────────

def test_list_and_filter():
    a1 = create_assumption(_valid_assumption(category="special"))
    a2 = create_assumption(_valid_assumption(category="market",
                                             affected_method="comparison"))
    store = [a1, a2]
    assert len(list_assumptions(store)) == 2
    assert list_assumptions(store, category="market") == [a2]
    assert list_assumptions(store, affected_method="comparison") == [a2]


def test_list_filter_overridden():
    a1 = create_assumption(_valid_assumption())
    a2 = create_assumption(_valid_assumption())
    a2 = apply_override(a2, changes={"confidence_level": "High"},
                        rationale="Corroborated by registry comparable")
    store = [a1, a2]
    assert list_assumptions(store, overridden=True) == [a2]
    assert list_assumptions(store, overridden=False) == [a1]


# ─── apply_override ───────────────────────────────────────────────────────────

def test_apply_override_records_change_and_explanation():
    record = create_assumption(_valid_assumption(confidence_level="Low"))
    updated = apply_override(
        record,
        changes={"confidence_level": "High"},
        rationale="Two arm's-length comparables confirm the position",
        actor="lead_valuer",
    )
    override = updated["manual_override"]
    assert updated["confidence_level"] == "High"
    assert override["applied"] is True
    assert override["actor"] == "lead_valuer"
    assert override["changes"]["confidence_level"] == {"from": "Low", "to": "High"}
    assert override["explanation"]  # ready for audit-trail recording


def test_override_preserves_prior_value():
    record = create_assumption(_valid_assumption(confidence_level="Low"))
    updated = apply_override(record, changes={"confidence_level": "High"},
                             rationale="see file note 7")
    # original record untouched ...
    assert record["confidence_level"] == "Low"
    assert record["manual_override"] is None
    # ... and prior value snapshotted on the new record
    assert updated["manual_override"]["previous"]["confidence_level"] == "Low"


def test_override_requires_rationale():
    record = create_assumption(_valid_assumption())
    with pytest.raises(AssumptionError):
        apply_override(record, changes={"confidence_level": "High"}, rationale=" ")


def test_override_requires_nonempty_changes():
    record = create_assumption(_valid_assumption())
    with pytest.raises(AssumptionError):
        apply_override(record, changes={}, rationale="x")


def test_override_validates_against_config():
    record = create_assumption(_valid_assumption())
    with pytest.raises(AssumptionError):
        apply_override(record, changes={"category": "bespoke"},
                       rationale="reclassify")


# ─── contract ────────────────────────────────────────────────────────────────

def test_schema_is_valid_json():
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    assert schema["title"] == "Assumption"


def test_created_assumption_matches_schema_if_jsonschema_available():
    jsonschema = pytest.importorskip("jsonschema")
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    record = create_assumption(_valid_assumption())
    # manual_override may be null on a fresh record; the schema allows that.
    jsonschema.validate(record, schema)
