"""Tests for CIL-2 Evidence Quality Governance.

Covers source classification (taxonomy + unknown fallback), verification
resolution (default + custom resolver), the reliability hierarchy (default +
complete override + not-in-hierarchy caveat), admissibility (decision-2
defaults, custom policy callable, role downgrades), weak-evidence handling per
type, manual override (wins + auto retained), the tri-part advisory envelope,
optional audit, and the AVM-risk invariants (no value / no score / no admission
state, never excludes evidence).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.comparable_intelligence import config as cfg  # noqa: E402
from engine.comparable_intelligence.governance import (  # noqa: E402
    assess_admissibility,
    classify_source,
    govern_evidence,
    hierarchy_rank,
    resolve_verification,
)


def _comp(**kwargs):
    base = {"comparable_id": "C-1"}
    base.update(kwargs)
    return base


# ─── classify_source ──────────────────────────────────────────────────────────

def test_classify_known_labels():
    assert classify_source(_comp(source="Registry"))["source_class"] == "registry"
    assert classify_source(_comp(source="listing"))["source_class"] == "advertised"
    assert classify_source(_comp(source="asking"))["source_class"] == "advertised"
    assert classify_source(_comp(source="broker"))["source_class"] == "broker_supplied"


def test_classify_unknown_falls_back():
    out = classify_source(_comp(source="carrier-pigeon"))
    assert out["source_class"] == "unknown"
    assert out["evidence_type"] == "indirect"


def test_classify_evidence_types():
    assert classify_source(_comp(source="registry"))["evidence_type"] == "direct"
    assert classify_source(_comp(source="broker"))["evidence_type"] == "indirect"
    assert classify_source(_comp(source="anecdotal"))["evidence_type"] == "inferred"


def test_classify_custom_taxonomy():
    config = cfg.GovernanceConfig(
        source_taxonomy={"oracle": "registry"},
        evidence_type_map={"registry": "direct"})
    assert classify_source(_comp(source="oracle"),
                           config=config)["source_class"] == "registry"


# ─── resolve_verification ─────────────────────────────────────────────────────

def test_verification_default_mapping():
    assert resolve_verification(_comp(verified=True,
                                      verification_method="deed"))["status"] \
        == "verified"
    assert resolve_verification(_comp(verified=True))["status"] \
        == "partially_verified"
    assert resolve_verification(_comp(verified=False))["status"] == "unverified"
    assert resolve_verification(_comp())["status"] == "unverifiable"


def test_verification_custom_resolver():
    config = cfg.GovernanceConfig(
        verification_resolver=lambda c: {"status": "verified", "method": "x",
                                         "by": None, "on": None})
    assert resolve_verification(_comp(), config=config)["status"] == "verified"


# ─── hierarchy_rank ───────────────────────────────────────────────────────────

def test_hierarchy_default_order():
    assert hierarchy_rank("registry") == 1
    assert hierarchy_rank("advertised") == 5
    assert hierarchy_rank("not-a-class") is None


def test_hierarchy_complete_override():
    config = cfg.GovernanceConfig(
        reliability_hierarchy=("advertised", "registry"))
    assert hierarchy_rank("advertised", config=config) == 1
    assert hierarchy_rank("registry", config=config) == 2
    assert hierarchy_rank("valuer_confirmed", config=config) is None


# ─── admissibility (decision-2 defaults) ──────────────────────────────────────

def test_advertised_is_corroborating_only_and_requires_verification():
    env = govern_evidence(_comp(source="asking", verified=True,
                                verification_method="call"))
    result = env["result"]
    assert result["admissibility"] == "corroborating_only"
    assert result["requires_verification"] is True


def test_unverified_evidence_downgraded_and_requires_verification():
    env = govern_evidence(_comp(source="broker", verified=False))
    result = env["result"]
    assert result["admissibility"] == "corroborating_only"  # supporting -> down
    assert result["requires_verification"] is True


def test_verified_registry_is_primary():
    env = govern_evidence(_comp(source="registry", verified=True,
                                verification_method="title_deed"))
    result = env["result"]
    assert result["admissibility"] == "primary"
    assert result["requires_verification"] is False


def test_verified_broker_is_supporting_with_caveat():
    env = govern_evidence(_comp(source="broker", verified=True,
                                verification_method="contract"))
    result = env["result"]
    assert result["admissibility"] == "supporting"
    assert any("broker-supplied" in c for c in result["caveats"])


def test_custom_admissibility_policy_replaces_default():
    config = cfg.GovernanceConfig(
        admissibility_policy=lambda cls, ver, conf: {
            "admissibility": "primary", "requires_verification": False,
            "caveats": ["custom policy"], "rules_fired": []})
    env = govern_evidence(_comp(source="asking"), config=config)
    assert env["result"]["admissibility"] == "primary"
    assert env["assumptions_used"]["policy"] == "custom_callable"


def test_custom_admissibility_by_class():
    config = cfg.GovernanceConfig(
        admissibility_by_class={"advertised": "inadmissible",
                                "unknown": "corroborating_only"})
    out = assess_admissibility({"source_class": "advertised",
                                "evidence_type": "indirect"},
                               {"status": "verified"}, config=config)
    assert out["admissibility"] == "inadmissible"


# ─── weak-evidence handling ───────────────────────────────────────────────────

def test_incomplete_evidence_caveat():
    env = govern_evidence(_comp(source="registry", verified=True,
                                verification_method="deed"))
    # default required fields largely missing on this minimal comparable.
    assert any("incomplete evidence record" in c
               for c in env["result"]["caveats"])


def test_indirect_evidence_caveat():
    env = govern_evidence(_comp(source="broker", verified=True,
                                verification_method="contract"))
    assert any("indirect evidence" in c for c in env["result"]["caveats"])


def test_unknown_class_not_in_hierarchy_caveat():
    env = govern_evidence(_comp(source="mystery"))
    assert env["result"]["hierarchy_rank"] is None
    assert any("not in the configured reliability hierarchy" in c
               for c in env["result"]["caveats"])


def test_custom_weak_evidence_rules():
    config = cfg.GovernanceConfig(weak_evidence_rules={
        "always": lambda comp, cls, ver: {"caveats": ["custom caveat"],
                                          "max_role": "inadmissible"}})
    env = govern_evidence(_comp(source="registry", verified=True,
                                verification_method="deed"), config=config)
    assert env["result"]["admissibility"] == "inadmissible"
    assert env["result"]["caveats"] == ["custom caveat"]


# ─── manual override ──────────────────────────────────────────────────────────

def test_manual_override_wins_and_auto_retained():
    env = govern_evidence(_comp(
        source="asking",
        manual_override={"admissibility": "supporting",
                         "rationale": "verified directly with vendor",
                         "actor": "appraiser-1"}))
    result = env["result"]
    assert result["admissibility"] == "supporting"
    assert result["decided_by"] == "manual_override"
    assert result["actor"] == "appraiser-1"
    assert result["auto_admissibility"] == "corroborating_only"


# ─── envelope / explainability-first ──────────────────────────────────────────

def test_envelope_shape_and_advisory():
    env = govern_evidence(_comp(source="broker"))
    assert set(env) == {"result", "explanation", "assumptions_used",
                        "advisory", "basis"}
    assert env["advisory"] is True
    assert "advisory" in env["explanation"][0]
    assert "human judgment" in env["explanation"][0].lower()


def test_assumptions_used_records_policy_provenance():
    env = govern_evidence(_comp(source="broker"))
    used = env["assumptions_used"]
    assert used["reliability_hierarchy"] == list(cfg.DEFAULT_RELIABILITY_HIERARCHY)
    assert used["admissibility_by_class"] == dict(cfg.DEFAULT_ADMISSIBILITY_BY_CLASS)
    assert used["policy"] == "default"
    assert "unverified" in used["weak_evidence_rules"]


def test_assumptions_capture_hierarchy_override():
    config = cfg.GovernanceConfig(reliability_hierarchy=("broker_supplied",))
    env = govern_evidence(_comp(source="broker"), config=config)
    assert env["assumptions_used"]["reliability_hierarchy"] == ["broker_supplied"]
    assert env["result"]["hierarchy_rank"] == 1


# ─── audit (optional, non-blocking) ───────────────────────────────────────────

def test_audit_absent_by_default():
    env = govern_evidence(_comp(source="broker"))
    assert env["result"]["source_class"] == "broker_supplied"


def test_audit_records_governed_event():
    store = InMemoryAuditStore()
    govern_evidence(_comp(source="broker"), audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["entity_type"] == "evidence"
    assert events[0]["action"] == "governed"


# ─── AVM-risk invariants ──────────────────────────────────────────────────────

def test_no_value_score_or_admission_keys():
    env = govern_evidence(_comp(source="asking", verified=False))
    result = env["result"]
    for forbidden in ("value", "adopted_value", "final_value", "price",
                      "reliability_score", "inclusion_decision",
                      "admission_state", "excluded"):
        assert forbidden not in result
    assert "not a value" in env["basis"]


def test_governance_never_excludes_evidence():
    # even the weakest evidence gets a classification, not removal.
    env = govern_evidence(_comp(source="anecdotal", verified=False))
    assert env["result"]["admissibility"] == "corroborating_only"
    assert env["result"]["comparable_id"] == "C-1"
