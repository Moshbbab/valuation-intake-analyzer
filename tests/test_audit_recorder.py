"""Tests for the append-only Audit Trail recorder and its thin adapters.

The adapters are exercised against the *real* merged producers (Assumptions
Foundation and Evidence Registry) so the mappings track the frozen outputs.
"""

import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.assumptions.registry import (  # noqa: E402
    apply_override,
    create_assumption,
)
from engine.evidence.scoring import assess_comparable  # noqa: E402
from engine.audit.config import AuditConfig  # noqa: E402
from engine.audit.recorder import (  # noqa: E402
    AuditError,
    default_store,
    record_event,
)
from engine.audit.storage import InMemoryAuditStore, JsonlAuditStore  # noqa: E402
from engine.audit.adapters import (  # noqa: E402
    record_assumption_created,
    record_assumption_overridden,
    record_comparable_assessed,
    record_inclusion_recommendation,
)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..",
                            "data-contracts", "audit-event.schema.json")


def _assumption():
    return create_assumption({
        "category": "special",
        "statement": "Vacant possession assumed.",
        "basis": "Client instruction",
        "confidence_level": "Medium",
        "rationale": "No tenancy schedule provided.",
        "affected_method": "income",
        "sensitivity_link": "scenario:vacant-vs-let",
    })


def _comparable():
    return {
        "comparable_id": "C-1",
        "source": "registry",
        "date": "2026-01-01",
        "area": 100.0,
        "location_score": 0.9,
    }


# ─── the four required event types ────────────────────────────────────────────

def test_record_assumption_created():
    store = InMemoryAuditStore()
    event = record_assumption_created(_assumption(), store=store)
    assert event["entity_type"] == "assumption"
    assert event["action"] == "created"
    assert event["before"] is None
    assert event["after"]["statement"] == "Vacant possession assumed."
    assert len(store) == 1


def test_record_assumption_overridden():
    store = InMemoryAuditStore()
    overridden = apply_override(_assumption(),
                                changes={"confidence_level": "High"},
                                rationale="Corroborated by two comparables",
                                actor="lead_valuer")
    event = record_assumption_overridden(overridden, store=store)
    assert event["action"] == "overridden"
    assert event["before"]["confidence_level"] == "Medium"
    assert event["after"]["confidence_level"] == "High"
    assert event["rationale"] == "Corroborated by two comparables"
    assert event["actor"] == "lead_valuer"
    assert event["explanation"]  # carried from the override


def test_record_comparable_assessed():
    store = InMemoryAuditStore()
    comp = _comparable()
    assessment = assess_comparable(comp, context={"subject_area": 100.0})
    event = record_comparable_assessed(comp, assessment, store=store)
    assert event["entity_type"] == "comparable"
    assert event["action"] == "assessed"
    assert event["entity_id"] == "C-1"
    assert "reliability_score" in event["after"]
    assert event["explanation"]


def test_record_inclusion_recommendation():
    store = InMemoryAuditStore()
    comp = _comparable()
    decision = assess_comparable(comp, context={"subject_area": 100.0})
    event = record_inclusion_recommendation(comp, decision, store=store)
    assert event["action"] == "inclusion_recommended"
    assert event["after"]["inclusion_decision"] in {"include", "review", "exclude"}
    assert event["after"]["auto_decision"] in {"include", "review", "exclude"}


# ─── append-only / immutability ───────────────────────────────────────────────

def test_append_only_and_immutability():
    store = InMemoryAuditStore()
    record_event("assumption", "A-1", "created", store=store)
    record_event("assumption", "A-2", "created", store=store)
    assert len(store) == 2
    # storage exposes no delete/update
    assert not hasattr(store, "delete")
    assert not hasattr(store, "update")
    # mutating a read-out copy must not affect the store
    events = store.list()
    events.clear()
    events_again = store.list()
    assert len(events_again) == 2


def test_before_after_snapshot_integrity():
    store = InMemoryAuditStore()
    before = {"confidence_level": "Low"}
    after = {"confidence_level": "High"}
    record_event("assumption", "A-9", "overridden",
                 before=before, after=after, store=store)
    # mutate the sources after recording
    before["confidence_level"] = "MUTATED"
    after["confidence_level"] = "MUTATED"
    recorded = store.list()[0]
    assert recorded["before"]["confidence_level"] == "Low"
    assert recorded["after"]["confidence_level"] == "High"


# ─── injectable storage ───────────────────────────────────────────────────────

def test_injectable_store_swap_does_not_touch_default():
    baseline = len(default_store)
    store = InMemoryAuditStore()
    record_event("comparable", "C-7", "assessed", store=store)
    assert len(store) == 1
    assert len(default_store) == baseline  # default untouched


def test_jsonl_store_roundtrip(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    store = JsonlAuditStore(path)
    record_event("assumption", "A-1", "created", rationale="r1", store=store)
    record_event("assumption", "A-2", "overridden", rationale="r2", store=store)
    assert len(store) == 2
    # file is genuine JSON Lines
    with open(path, encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert [e["entity_id"] for e in lines] == ["A-1", "A-2"]


# ─── event_id generation ──────────────────────────────────────────────────────

def test_event_id_autogenerated_when_absent():
    store = InMemoryAuditStore()
    event = record_event("assumption", "A-1", "created", store=store)
    assert event["event_id"].startswith("E-")


def test_event_id_respected_when_provided():
    store = InMemoryAuditStore()
    event = record_event("assumption", "A-1", "created",
                         event_id="E-custom", store=store)
    assert event["event_id"] == "E-custom"


def test_timestamp_autogenerated_when_absent():
    store = InMemoryAuditStore()
    event = record_event("assumption", "A-1", "created", store=store)
    assert event["timestamp"]


# ─── rationale / explanation preservation ─────────────────────────────────────

def test_rationale_and_explanation_preserved():
    store = InMemoryAuditStore()
    event = record_event("comparable", "C-1", "assessed",
                         rationale="because", explanation=["line1", "line2"],
                         store=store)
    assert event["rationale"] == "because"
    assert event["explanation"] == ["line1", "line2"]


# ─── injectable vocabulary (non-rigid) ────────────────────────────────────────

def test_unknown_action_rejected_by_default_vocabulary():
    store = InMemoryAuditStore()
    with pytest.raises(AuditError):
        record_event("assumption", "A-1", "teleported", store=store)


def test_empty_vocabulary_is_unrestricted():
    store = InMemoryAuditStore()
    config = AuditConfig(entity_types=(), actions=())
    event = record_event("anything", "X-1", "whatever",
                         store=store, config=config)
    assert event["action"] == "whatever"


# ─── contract ────────────────────────────────────────────────────────────────

def test_schema_is_valid_json():
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    assert schema["title"] == "AuditEvent"


def test_recorded_event_matches_schema_if_jsonschema_available():
    jsonschema = pytest.importorskip("jsonschema")
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    store = InMemoryAuditStore()
    event = record_assumption_created(_assumption(), store=store)
    jsonschema.validate(event, schema)
