"""CIL-4 — Admission Framework (configurable rules over configurable states).

NOT a fixed state machine. Admission is a rule engine evaluated over an
extensible state vocabulary: states are data, each rule is a mapping with a
predicate (declarative callable), a recommended state, optional conditions and
a priority; conflict resolution is a named strategy or a callable; the no-match
default state is configurable; transitions are open unless a map is supplied.

The framework consumes the advisory outputs of the earlier CIL stages —
quality (CIL-1), governance (CIL-2) and outliers (CIL-3) — plus the comparable
itself, and produces an advisory *recommendation*: it never admits, rejects or
mutates anything. A ``manual_override`` always wins, with the automated
recommendation retained (``auto_recommendation``) for auditability. Every
output uses the tri-part envelope (result / explanation / assumptions_used).
"""

from typing import Dict, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.comparable_intelligence import config as cfg
from engine.comparable_intelligence.common import build_envelope


# ─── Context helpers ───────────────────────────────────────────────────────────

def _unwrap(block) -> Mapping:
    """Accept either a tri-part envelope or its bare ``result`` mapping."""
    if isinstance(block, Mapping) and "result" in block \
            and isinstance(block["result"], Mapping):
        return block["result"]
    return block if isinstance(block, Mapping) else {}


def _ctx_value(context: Mapping, section: str, key: str, default=None):
    return _unwrap(context.get(section)).get(key, default)


# ─── Suggested default rules (data — fully replaceable) ───────────────────────

def _rule_governance_inadmissible(context, _config):
    return _ctx_value(context, "governance", "admissibility") == "inadmissible"


def _rule_outlier_exclude_candidate(context, _config):
    return _ctx_value(context, "outlier", "classification") \
        == "exclude_candidate"


def _rule_requires_verification(context, _config):
    return _ctx_value(context, "governance", "requires_verification") is True


def _rule_outlier_review(context, _config):
    return _ctx_value(context, "outlier", "classification") == "review_required"


def _rule_weak_reliability(context, config):
    score = _ctx_value(context, "quality", "reliability_score")
    return score is not None and score < config.weak_reliability


def _rule_outlier_warning(context, _config):
    return _ctx_value(context, "outlier", "classification") == "warning"


def _rule_strong_evidence(context, config):
    score = _ctx_value(context, "quality", "reliability_score")
    admissibility = _ctx_value(context, "governance", "admissibility")
    return (score is not None and score >= config.strong_reliability
            and admissibility in ("primary", "supporting"))


def default_admission_rules() -> tuple:
    """The suggested rule set — ordered data, fully replaceable via config."""
    return (
        {"name": "governance_inadmissible",
         "predicate": _rule_governance_inadmissible, "state": "reject",
         "conditions": [],
         "rationale": "governance classified the evidence inadmissible",
         "priority": 100},
        {"name": "outlier_exclude_candidate",
         "predicate": _rule_outlier_exclude_candidate, "state": "review",
         "conditions": ["resolve exclude-candidate outlier before reliance"],
         "rationale": "outlier classification is exclude_candidate",
         "priority": 90},
        {"name": "requires_verification",
         "predicate": _rule_requires_verification, "state": "admit_conditional",
         "conditions": ["verify evidence before reliance"],
         "rationale": "governance flagged the evidence as requiring "
                      "verification",
         "priority": 80},
        {"name": "outlier_review",
         "predicate": _rule_outlier_review, "state": "review",
         "conditions": ["review outlier classification"],
         "rationale": "outlier classification is review_required",
         "priority": 70},
        {"name": "weak_reliability",
         "predicate": _rule_weak_reliability, "state": "review",
         "conditions": ["assess whether evidence quality supports reliance"],
         "rationale": "reliability score below the configured weak threshold",
         "priority": 60},
        {"name": "outlier_warning",
         "predicate": _rule_outlier_warning, "state": "flag",
         "conditions": [],
         "rationale": "outlier classification is warning",
         "priority": 50},
        {"name": "strong_evidence",
         "predicate": _rule_strong_evidence, "state": "admit",
         "conditions": [],
         "rationale": "reliability at/above the strong threshold and "
                      "governance role primary/supporting",
         "priority": 40},
    )


# ─── Framework engine ──────────────────────────────────────────────────────────

def _resolve_conflict(matched: List[Mapping], config: cfg.AdmissionConfig):
    """Pick the governing rule among matches per the configured strategy."""
    if callable(config.conflict_resolution):
        return config.conflict_resolution(matched)
    if config.conflict_resolution == "first_match":
        return matched[0]
    if config.conflict_resolution == "highest_priority":
        return max(matched, key=lambda rule: rule.get("priority", 0))
    raise ValueError(
        f"Unknown conflict resolution: {config.conflict_resolution!r}")


def check_transition(current: str, proposed: str, *,
                     config: Optional[cfg.AdmissionConfig] = None) -> Dict:
    """Advisory transition check; open (allowed) when no map is configured."""
    config = config or cfg.DEFAULT_ADMISSION_CONFIG
    if config.allowed_transitions is None:
        return {"allowed": True, "reason": "transitions are open (no map "
                                           "configured)"}
    allowed = proposed in config.allowed_transitions.get(current, ())
    reason = (f"transition {current} -> {proposed} "
              f"{'is' if allowed else 'is not'} in the configured map")
    return {"allowed": allowed, "reason": reason}


def recommend_admission(context: Mapping, *,
                        config: Optional[cfg.AdmissionConfig] = None,
                        audit_store=None, audit_config=None) -> Dict:
    """Produce an advisory admission recommendation for one comparable.

    ``context`` carries ``comparable`` plus any of ``quality`` / ``governance``
    / ``outlier`` (each a tri-part envelope or its bare result; all optional —
    rules simply don't fire on absent inputs). Returns the tri-part envelope:
    the governing rule's state is ``recommended_state``, every matched rule is
    reported, conditions are the union of matched rules' conditions, and a
    ``manual_override`` (``{"decision", "rationale", "actor"}``) wins with the
    automated recommendation retained. Optionally records a non-blocking
    ``admission_recommended`` audit event.
    """
    config = config or cfg.DEFAULT_ADMISSION_CONFIG
    rules = config.rules if config.rules is not None \
        else default_admission_rules()
    comparable = context.get("comparable") or {}

    matched = [rule for rule in rules if rule["predicate"](context, config)]
    if matched:
        governing = _resolve_conflict(matched, config)
        auto_state = governing["state"]
        auto_rationale = governing.get("rationale", governing["name"])
    else:
        governing = None
        auto_state = config.default_state
        auto_rationale = "no rule matched; configured default state applies"

    conditions: List[str] = []
    for rule in matched:
        for condition in rule.get("conditions", []):
            if condition not in conditions:
                conditions.append(condition)

    override = comparable.get("manual_override")
    if isinstance(override, Mapping) and override.get("decision"):
        recommended_state = override["decision"]
        decided_by = "manual_override"
        actor = override.get("actor")
        rationale = override.get("rationale", "")
    else:
        recommended_state = auto_state
        decided_by = "auto"
        actor = None
        rationale = auto_rationale

    result = {
        "comparable_id": comparable.get("comparable_id"),
        "recommended_state": recommended_state,
        "matched_rules": [rule["name"] for rule in matched],
        "governing_rule": governing["name"] if governing else None,
        "conditions": conditions,
        "auto_recommendation": auto_state,
        "decided_by": decided_by,
        "actor": actor,
        "rationale": rationale,
    }

    explanation = [
        "Admission is an advisory recommendation only — the appraiser makes "
        "the final admit/reject decision; nothing is admitted or rejected "
        "automatically.",
        f"recommended state: {recommended_state}"
        + (f" (manual override; auto recommendation was {auto_state})"
           if decided_by == "manual_override" else ""),
    ]
    for rule in matched:
        explanation.append(
            f"rule '{rule['name']}' matched -> {rule['state']}: "
            f"{rule.get('rationale', '')}")
    if not matched:
        explanation.append(
            f"no rule matched; default state '{config.default_state}' applies")
    if conditions:
        explanation.append(f"conditions attached: {conditions}")

    assumptions_used = {
        "states": list(config.states),
        "rules": [rule["name"] for rule in rules],
        "conflict_resolution": (config.conflict_resolution
                                if isinstance(config.conflict_resolution, str)
                                else "custom_callable"),
        "default_state": config.default_state,
        "strong_reliability": config.strong_reliability,
        "weak_reliability": config.weak_reliability,
        "allowed_transitions": (dict(config.allowed_transitions)
                                if config.allowed_transitions is not None
                                else "open"),
        "rule_set": "default" if config.rules is None else "custom",
    }

    envelope = build_envelope(
        result=result,
        explanation=explanation,
        assumptions_used=assumptions_used,
        basis=("admission framework — advisory state recommendation; the "
               "final admit/reject decision is human and no value is "
               "implied"),
    )

    if audit_store is not None:
        record_event(
            "comparable", comparable.get("comparable_id"),
            "admission_recommended",
            before=None,
            after={"recommended_state": recommended_state,
                   "auto_recommendation": auto_state,
                   "decided_by": decided_by,
                   "matched_rules": result["matched_rules"]},
            rationale=rationale or auto_rationale,
            actor=actor,
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG,
        )

    return envelope
