"""CIL-2 — Evidence Quality Governance.

Establishes whether comparable evidence is *appropriate/eligible* for valuation
use — a concern kept architecturally distinct from numeric quality scoring
(CIL-1) and from admission recommendations (later CIL stages). Governance
classifies provenance, resolves verification status, ranks evidence against a
fully-overridable reliability hierarchy, assesses an advisory *admissibility
role*, and attaches caveats for weak (unverified, indirect, broker-supplied,
advertised, inferred, incomplete) evidence.

Advisory only: governance returns a role recommendation and caveats. It never
excludes evidence, never produces a numeric reliability score, never makes an
admission decision and never produces a value. Manual overrides win, with the
automated classification retained for auditability. Every output uses the
tri-part envelope (result / explanation / assumptions_used) so a reader can see
what the classification was, why, and which policy/configuration produced it.
"""

from typing import Dict, List, Mapping, Optional, Tuple

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.comparable_intelligence import config as cfg
from engine.comparable_intelligence.common import build_envelope


# ─── Resolution helpers ────────────────────────────────────────────────────────

def _taxonomy(config: cfg.GovernanceConfig) -> Mapping:
    return config.source_taxonomy if config.source_taxonomy is not None \
        else cfg.DEFAULT_SOURCE_TAXONOMY


def _type_map(config: cfg.GovernanceConfig) -> Mapping:
    return config.evidence_type_map if config.evidence_type_map is not None \
        else cfg.DEFAULT_EVIDENCE_TYPE_MAP


def _hierarchy(config: cfg.GovernanceConfig) -> Tuple[str, ...]:
    return config.reliability_hierarchy \
        if config.reliability_hierarchy is not None \
        else cfg.DEFAULT_RELIABILITY_HIERARCHY


def _by_class(config: cfg.GovernanceConfig) -> Mapping:
    return config.admissibility_by_class \
        if config.admissibility_by_class is not None \
        else cfg.DEFAULT_ADMISSIBILITY_BY_CLASS


def _order(config: cfg.GovernanceConfig) -> Tuple[str, ...]:
    return config.admissibility_order \
        if config.admissibility_order is not None \
        else cfg.DEFAULT_ADMISSIBILITY_ORDER


def _verification_required(config: cfg.GovernanceConfig) -> Tuple[str, ...]:
    return config.verification_required_classes \
        if config.verification_required_classes is not None \
        else cfg.DEFAULT_VERIFICATION_REQUIRED_CLASSES


def _weakest(role_a: str, role_b: str, order: Tuple[str, ...]) -> str:
    """Return the weaker of two roles under ``order`` (rightward = weaker)."""
    try:
        return role_a if order.index(role_a) >= order.index(role_b) else role_b
    except ValueError:
        return role_b  # unknown role labels are left to the configured policy


# ─── Public API ────────────────────────────────────────────────────────────────

def classify_source(comparable: Mapping, *,
                    config: Optional[cfg.GovernanceConfig] = None) -> Dict:
    """Classify a comparable's provenance into source class + evidence type."""
    config = config or cfg.DEFAULT_GOVERNANCE_CONFIG
    taxonomy = _taxonomy(config)
    label = str(comparable.get("source", "")).strip().lower()
    source_class = taxonomy.get(label, config.unknown_source_class)
    evidence_type = _type_map(config).get(source_class, "indirect")
    return {"source_class": source_class, "evidence_type": evidence_type,
            "source_label": label or None}


def resolve_verification(comparable: Mapping, *,
                         config: Optional[cfg.GovernanceConfig] = None) -> Dict:
    """Resolve a verification status from the comparable's signals.

    Default mapping: ``verified=True`` with a method -> ``verified``; without a
    method -> ``partially_verified``; ``verified=False`` -> ``unverified``; no
    signal -> ``unverifiable``. A configured resolver callable replaces this.
    """
    config = config or cfg.DEFAULT_GOVERNANCE_CONFIG
    if config.verification_resolver is not None:
        return dict(config.verification_resolver(comparable))

    verified = comparable.get("verified")
    method = comparable.get("verification_method")
    if verified is True:
        status = "verified" if method else "partially_verified"
    elif verified is False:
        status = "unverified"
    else:
        status = "unverifiable"
    return {"status": status, "method": method,
            "by": comparable.get("verified_by"),
            "on": comparable.get("verified_on")}


def hierarchy_rank(source_class: str, *,
                   config: Optional[cfg.GovernanceConfig] = None) -> Optional[int]:
    """1-based rank of a source class in the configured hierarchy, or None."""
    config = config or cfg.DEFAULT_GOVERNANCE_CONFIG
    hierarchy = _hierarchy(config)
    if source_class in hierarchy:
        return hierarchy.index(source_class) + 1
    return None


def _rule_unverified(_comparable, _classification, verification):
    """Default rule: unverified/unverifiable evidence is downgraded + flagged."""
    if verification["status"] in ("unverified", "unverifiable"):
        return {"caveats": [f"evidence is {verification['status']}; "
                            "independent verification recommended"],
                "requires_verification": True, "downgrade": True}
    return None


def _rule_advertised(_comparable, classification, _verification):
    """Default rule: advertised/asking evidence is corroborating-only."""
    if classification["source_class"] == "advertised":
        return {"caveats": ["advertised/asking evidence — not a completed "
                            "transaction"],
                "requires_verification": True, "downgrade": True}
    return None


def _rule_broker_supplied(_comparable, classification, _verification):
    """Default rule: broker-supplied evidence carries a corroboration caveat."""
    if classification["source_class"] == "broker_supplied":
        return {"caveats": ["broker-supplied evidence — corroborate "
                            "independently where possible"]}
    return None


def _rule_indirect_or_inferred(_comparable, classification, _verification):
    """Default rule: indirect/inferred evidence carries a directness caveat."""
    if classification["evidence_type"] in ("indirect", "inferred"):
        return {"caveats": [f"{classification['evidence_type']} evidence — "
                            "not a directly evidenced transaction"]}
    return None


def _rule_incomplete(comparable, classification, _verification):
    """Default rule: missing configured fields flag an incomplete record."""
    config = classification.get("_config") or cfg.DEFAULT_GOVERNANCE_CONFIG
    missing = [field for field in config.required_fields
               if comparable.get(field) in (None, "")]
    if missing:
        return {"caveats": [f"incomplete evidence record — missing {missing}"]}
    return None


def _default_weak_evidence_rules() -> Dict:
    """Built-in weak-evidence handling rules — each fully replaceable."""
    return {"unverified": _rule_unverified,
            "advertised": _rule_advertised,
            "broker_supplied": _rule_broker_supplied,
            "indirect_or_inferred": _rule_indirect_or_inferred,
            "incomplete": _rule_incomplete}


def assess_admissibility(classification: Mapping, verification: Mapping, *,
                         comparable: Optional[Mapping] = None,
                         config: Optional[cfg.GovernanceConfig] = None) -> Dict:
    """Assess an advisory admissibility role for classified evidence.

    Default policy: the class's configured base role, downgraded to at most
    ``weak_evidence_max_role`` (never below per the configured order) whenever a
    weak-evidence rule fires with ``downgrade``; ``requires_verification`` is
    set for the configured class family and for unverified/unverifiable status.
    A configured ``admissibility_policy`` callable replaces all of this.
    """
    config = config or cfg.DEFAULT_GOVERNANCE_CONFIG
    comparable = comparable or {}

    if config.admissibility_policy is not None:
        return dict(config.admissibility_policy(classification, verification,
                                                config))

    by_class = _by_class(config)
    order = _order(config)
    source_class = classification["source_class"]
    role = by_class.get(source_class,
                        by_class.get(config.unknown_source_class,
                                     config.weak_evidence_max_role))
    requires_verification = source_class in _verification_required(config)

    rules = config.weak_evidence_rules if config.weak_evidence_rules is not None \
        else _default_weak_evidence_rules()
    classification_with_cfg = {**classification, "_config": config}

    caveats: List[str] = []
    fired: List[str] = []
    for name, rule in rules.items():
        outcome = rule(comparable, classification_with_cfg, verification)
        if not outcome:
            continue
        fired.append(name)
        caveats.extend(outcome.get("caveats", []))
        if outcome.get("requires_verification"):
            requires_verification = True
        if outcome.get("downgrade"):
            role = _weakest(role, config.weak_evidence_max_role, order)
        if outcome.get("max_role"):
            role = _weakest(role, outcome["max_role"], order)

    return {"admissibility": role,
            "requires_verification": requires_verification,
            "caveats": caveats, "rules_fired": fired}


def govern_evidence(comparable: Mapping, *,
                    config: Optional[cfg.GovernanceConfig] = None,
                    audit_store=None, audit_config=None) -> Dict:
    """Produce one comparable's advisory governance record (tri-part envelope).

    Composes classification, verification, hierarchy rank and admissibility. A
    ``manual_override`` (``{"admissibility", "rationale", "actor"}``) wins, yet
    the automated classification is retained as ``auto_admissibility``. Records
    a non-blocking ``governed`` audit event only when ``audit_store`` is given;
    the result is computed before the audit call.
    """
    config = config or cfg.DEFAULT_GOVERNANCE_CONFIG

    classification = classify_source(comparable, config=config)
    verification = resolve_verification(comparable, config=config)
    rank = hierarchy_rank(classification["source_class"], config=config)
    assessed = assess_admissibility(classification, verification,
                                    comparable=comparable, config=config)

    caveats = list(assessed["caveats"])
    if rank is None:
        caveats.append(f"source class '{classification['source_class']}' is "
                       "not in the configured reliability hierarchy")

    override = comparable.get("manual_override")
    if isinstance(override, Mapping) and override.get("admissibility"):
        admissibility = override["admissibility"]
        decided_by = "manual_override"
        actor = override.get("actor")
        rationale = override.get("rationale", "")
    else:
        admissibility = assessed["admissibility"]
        decided_by = "auto"
        actor = None
        rationale = None

    result = {
        "comparable_id": comparable.get("comparable_id"),
        "source_class": classification["source_class"],
        "evidence_type": classification["evidence_type"],
        "verification_status": verification["status"],
        "hierarchy_rank": rank,
        "admissibility": admissibility,
        "requires_verification": assessed["requires_verification"],
        "caveats": caveats,
        "decided_by": decided_by,
        "actor": actor,
        "override_rationale": rationale,
        "auto_admissibility": assessed["admissibility"],
    }

    explanation = [
        "Evidence governance is an advisory appropriateness classification; "
        "human judgment remains the final authority and no evidence is "
        "excluded automatically.",
        f"source '{classification['source_label']}' classified as "
        f"{classification['source_class']} ({classification['evidence_type']} "
        f"evidence), hierarchy rank {rank}",
        f"verification status: {verification['status']}",
        f"admissibility recommendation: {admissibility}"
        + (" (manual override; auto recommendation was "
           f"{assessed['admissibility']})" if decided_by == "manual_override"
           else "")
        + (", verification required" if assessed["requires_verification"]
           else ""),
    ]
    explanation.extend(f"caveat: {caveat}" for caveat in caveats)
    if assessed["rules_fired"]:
        explanation.append(f"weak-evidence rules applied: "
                           f"{assessed['rules_fired']}")

    assumptions_used = {
        "source_taxonomy": dict(_taxonomy(config)),
        "evidence_type_map": dict(_type_map(config)),
        "reliability_hierarchy": list(_hierarchy(config)),
        "admissibility_by_class": dict(_by_class(config)),
        "admissibility_order": list(_order(config)),
        "verification_required_classes": list(_verification_required(config)),
        "weak_evidence_max_role": config.weak_evidence_max_role,
        "weak_evidence_rules": list(
            (config.weak_evidence_rules
             if config.weak_evidence_rules is not None
             else _default_weak_evidence_rules()).keys()),
        "required_fields": list(config.required_fields),
        "policy": "custom_callable" if config.admissibility_policy else "default",
        "verification_resolver": ("custom_callable"
                                  if config.verification_resolver else "default"),
    }

    envelope = build_envelope(
        result=result,
        explanation=explanation,
        assumptions_used=assumptions_used,
        basis=("evidence governance — advisory appropriateness/eligibility "
               "classification; not a quality score, not an admission "
               "decision and not a value"),
    )

    if audit_store is not None:
        record_event(
            "evidence", comparable.get("comparable_id"), "governed",
            before=None,
            after={"admissibility": admissibility,
                   "auto_admissibility": assessed["admissibility"],
                   "decided_by": decided_by,
                   "requires_verification": assessed["requires_verification"]},
            rationale=rationale or "evidence governance classification",
            actor=actor,
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return envelope
