"""Tests for CIL-4 Admission Framework (configurable rules over states).

Covers the suggested default rules (governance/outlier/quality driven), the
no-match default state, conflict resolution (first_match / highest_priority /
callable), custom rule sets and custom states, envelope-or-bare-result inputs,
manual override (wins + auto retained), open and mapped transitions, the
tri-part envelope, optional audit, and the AVM-risk invariants (advisory only,
nothing admitted/rejected automatically, no value keys).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.comparable_intelligence.admission import (  # noqa: E402
    check_transition,
    default_admission_rules,
    recommend_admission,
)
from engine.comparable_intelligence.config import AdmissionConfig  # noqa: E402


def _context(reliability=None, admissibility=None, requires_verification=None,
             outlier=None, comparable=None):
    context = {"comparable": comparable or {"comparable_id": "C-1"}}
    if reliability is not None:
        context["quality"] = {"reliability_score": reliability}
    governance = {}
    if admissibility is not None:
        governance["admissibility"] = admissibility
    if requires_verification is not None:
        governance["requires_verification"] = requires_verification
    if governance:
        context["governance"] = governance
    if outlier is not None:
        context["outlier"] = {"classification": outlier}
    return context


# ─── default rules ────────────────────────────────────────────────────────────

def test_inadmissible_recommends_reject():
    env = recommend_admission(_context(admissibility="inadmissible"))
    assert env["result"]["recommended_state"] == "reject"
    assert env["result"]["governing_rule"] == "governance_inadmissible"


def test_requires_verification_recommends_conditional():
    env = recommend_admission(_context(admissibility="corroborating_only",
                                       requires_verification=True))
    result = env["result"]
    assert result["recommended_state"] == "admit_conditional"
    assert "verify evidence before reliance" in result["conditions"]


def test_strong_evidence_recommends_admit():
    env = recommend_admission(_context(reliability=0.85,
                                       admissibility="primary",
                                       requires_verification=False))
    assert env["result"]["recommended_state"] == "admit"
    assert env["result"]["governing_rule"] == "strong_evidence"


def test_weak_reliability_recommends_review():
    env = recommend_admission(_context(reliability=0.30))
    assert env["result"]["recommended_state"] == "review"
    assert env["result"]["governing_rule"] == "weak_reliability"


def test_outlier_classes_drive_states():
    assert recommend_admission(_context(outlier="warning"))["result"][
        "recommended_state"] == "flag"
    assert recommend_admission(_context(outlier="review_required"))["result"][
        "recommended_state"] == "review"
    assert recommend_admission(_context(outlier="exclude_candidate"))["result"][
        "recommended_state"] == "review"


def test_no_match_falls_to_default_state():
    env = recommend_admission(_context())
    assert env["result"]["recommended_state"] == "review"
    assert env["result"]["governing_rule"] is None
    assert env["result"]["matched_rules"] == []


def test_default_state_configurable():
    config = AdmissionConfig(default_state="flag")
    env = recommend_admission(_context(), config=config)
    assert env["result"]["recommended_state"] == "flag"


# ─── conflict resolution ──────────────────────────────────────────────────────

def test_first_match_uses_configured_order():
    # both requires_verification (prio 80) and outlier_warning (prio 50) match;
    # default rules are ordered by priority so first_match == requires_verif.
    env = recommend_admission(_context(requires_verification=True,
                                       outlier="warning"))
    assert env["result"]["governing_rule"] == "requires_verification"
    assert set(env["result"]["matched_rules"]) == {"requires_verification",
                                                   "outlier_warning"}


def test_highest_priority_resolution():
    rules = (
        {"name": "low", "predicate": lambda ctx, cfg: True, "state": "flag",
         "conditions": [], "rationale": "", "priority": 1},
        {"name": "high", "predicate": lambda ctx, cfg: True, "state": "review",
         "conditions": [], "rationale": "", "priority": 99},
    )
    config = AdmissionConfig(rules=rules,
                             conflict_resolution="highest_priority")
    env = recommend_admission(_context(), config=config)
    assert env["result"]["governing_rule"] == "high"


def test_callable_resolution():
    rules = (
        {"name": "a", "predicate": lambda ctx, cfg: True, "state": "admit",
         "conditions": [], "rationale": "", "priority": 1},
        {"name": "b", "predicate": lambda ctx, cfg: True, "state": "reject",
         "conditions": [], "rationale": "", "priority": 2},
    )
    config = AdmissionConfig(rules=rules,
                             conflict_resolution=lambda matched: matched[-1])
    env = recommend_admission(_context(), config=config)
    assert env["result"]["governing_rule"] == "b"


def test_unknown_resolution_rejected():
    config = AdmissionConfig(conflict_resolution="nope")
    with pytest.raises(ValueError):
        recommend_admission(_context(outlier="warning"), config=config)


# ─── extensibility ────────────────────────────────────────────────────────────

def test_custom_rules_and_custom_state():
    rules = (
        {"name": "needs_site_visit",
         "predicate": lambda ctx, cfg: ctx["comparable"].get("remote") is True,
         "state": "admit_with_site_visit",
         "conditions": ["site visit required"],
         "rationale": "remote comparable", "priority": 10},
    )
    config = AdmissionConfig(
        states=("admit", "admit_with_site_visit", "review"),
        rules=rules)
    env = recommend_admission(
        {"comparable": {"comparable_id": "C-7", "remote": True}},
        config=config)
    assert env["result"]["recommended_state"] == "admit_with_site_visit"
    assert env["assumptions_used"]["rule_set"] == "custom"


def test_accepts_envelope_or_bare_result_inputs():
    bare = recommend_admission(
        {"comparable": {"comparable_id": "C-1"},
         "governance": {"admissibility": "inadmissible"}})
    wrapped = recommend_admission(
        {"comparable": {"comparable_id": "C-1"},
         "governance": {"result": {"admissibility": "inadmissible"},
                        "explanation": [], "assumptions_used": {},
                        "advisory": True, "basis": "x"}})
    assert bare["result"]["recommended_state"] == "reject"
    assert wrapped["result"]["recommended_state"] == "reject"


# ─── manual override ──────────────────────────────────────────────────────────

def test_override_wins_and_auto_retained():
    env = recommend_admission(_context(
        admissibility="inadmissible",
        comparable={"comparable_id": "C-1",
                    "manual_override": {"decision": "admit",
                                        "rationale": "verified at source",
                                        "actor": "appraiser-2"}}))
    result = env["result"]
    assert result["recommended_state"] == "admit"
    assert result["decided_by"] == "manual_override"
    assert result["auto_recommendation"] == "reject"
    assert result["actor"] == "appraiser-2"


# ─── transitions ──────────────────────────────────────────────────────────────

def test_transitions_open_by_default():
    out = check_transition("review", "admit")
    assert out["allowed"] is True


def test_transitions_respect_configured_map():
    config = AdmissionConfig(
        allowed_transitions={"review": ("admit", "reject")})
    assert check_transition("review", "admit", config=config)["allowed"] is True
    assert check_transition("admit", "review", config=config)["allowed"] is False


# ─── envelope / audit / invariants ────────────────────────────────────────────

def test_envelope_shape_and_advisory():
    env = recommend_admission(_context(outlier="warning"))
    assert set(env) == {"result", "explanation", "assumptions_used",
                        "advisory", "basis"}
    assert env["advisory"] is True
    assert "advisory recommendation" in env["explanation"][0]
    assert "appraiser" in env["explanation"][0]


def test_assumptions_record_framework_provenance():
    env = recommend_admission(_context())
    used = env["assumptions_used"]
    assert used["rule_set"] == "default"
    assert used["conflict_resolution"] == "first_match"
    assert used["default_state"] == "review"
    assert used["allowed_transitions"] == "open"
    assert "governance_inadmissible" in used["rules"]


def test_audit_records_event_when_store_given():
    store = InMemoryAuditStore()
    recommend_admission(_context(outlier="warning"), audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["action"] == "admission_recommended"


def test_no_value_keys_and_default_rules_exposed():
    env = recommend_admission(_context(reliability=0.9, admissibility="primary"))
    for forbidden in ("value", "adopted_value", "final_value", "price",
                      "opinion", "excluded"):
        assert forbidden not in env["result"]
    assert "no value is implied" in env["basis"]
    assert len(default_admission_rules()) == 7
