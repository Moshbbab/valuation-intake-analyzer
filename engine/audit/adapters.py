"""Thin adapters mapping producer outputs into audit events.

Each adapter only reads existing keys from an Assumptions Foundation or Evidence
Registry output and forwards them to ``record_event``. They add no valuation
logic, do not modify producer outputs, and enforce no ordering — recording any
one is independent of the others.
"""

from typing import Any, Dict, Mapping, Optional

from engine.audit.recorder import record_event


def record_assumption_created(assumption: Mapping, *,
                              store: Any = None,
                              config: Any = None,
                              actor: Optional[str] = None) -> Dict:
    """Map a ``create_assumption()`` output to an 'assumption created' event."""
    return record_event(
        "assumption", assumption.get("assumption_id"), "created",
        before=None,
        after=dict(assumption),
        rationale=assumption.get("rationale"),
        actor=actor or assumption.get("actor"),
        store=store, config=config,
    )


def record_assumption_overridden(assumption: Mapping, *,
                                 store: Any = None,
                                 config: Any = None) -> Dict:
    """Map an ``apply_override()`` output to an 'assumption overridden' event.

    ``before`` is the override's ``previous`` snapshot; ``after`` is the new
    value of each changed field, taken from the ``changes`` diff.
    """
    override = assumption.get("manual_override") or {}
    changes = override.get("changes") or {}
    after = {field: change.get("to") for field, change in changes.items()}
    return record_event(
        "assumption", assumption.get("assumption_id"), "overridden",
        before=override.get("previous"),
        after=after,
        rationale=override.get("rationale"),
        explanation=override.get("explanation"),
        actor=override.get("actor"),
        timestamp=override.get("timestamp"),
        store=store, config=config,
    )


def record_comparable_assessed(comparable: Mapping, assessment: Mapping, *,
                               store: Any = None,
                               config: Any = None,
                               actor: Optional[str] = None) -> Dict:
    """Map a ``score_evidence()`` / ``assess_comparable()`` output to an event."""
    return record_event(
        "comparable", comparable.get("comparable_id"), "assessed",
        before=None,
        after={
            "reliability_score": assessment.get("reliability_score"),
            "factor_scores": assessment.get("factor_scores"),
            "confidence_level": assessment.get("confidence_level"),
        },
        explanation=assessment.get("explanation"),
        actor=actor,
        store=store, config=config,
    )


def record_inclusion_recommendation(comparable: Mapping, decision: Mapping, *,
                                    store: Any = None,
                                    config: Any = None) -> Dict:
    """Map a ``decide_inclusion()`` / ``assess_comparable()`` output to an event."""
    return record_event(
        "comparable", comparable.get("comparable_id"), "inclusion_recommended",
        before=None,
        after={
            "inclusion_decision": decision.get("inclusion_decision"),
            "auto_decision": decision.get("auto_decision"),
            "decided_by": decision.get("decided_by"),
        },
        rationale=decision.get("rationale"),
        actor=decision.get("actor"),
        store=store, config=config,
    )


def record_adjustment_created(adjustment: Mapping, *,
                              store: Any = None,
                              config: Any = None,
                              actor: Optional[str] = None) -> Dict:
    """Map a ``create_adjustment()`` output to an 'adjustment created' event."""
    return record_event(
        "adjustment", adjustment.get("adjustment_id"), "created",
        before=None,
        after=dict(adjustment),
        rationale=adjustment.get("rationale"),
        actor=actor or adjustment.get("actor"),
        store=store, config=config,
    )


def record_adjustment_overridden(adjustment: Mapping, *,
                                 store: Any = None,
                                 config: Any = None) -> Dict:
    """Map an ``apply_override()`` output to an 'adjustment overridden' event.

    ``before`` is the override's ``previous`` snapshot; ``after`` is the new
    value of each changed field, taken from the ``changes`` diff.
    """
    override = adjustment.get("manual_override") or {}
    changes = override.get("changes") or {}
    after = {field: change.get("to") for field, change in changes.items()}
    return record_event(
        "adjustment", adjustment.get("adjustment_id"), "overridden",
        before=override.get("previous"),
        after=after,
        rationale=override.get("rationale"),
        explanation=override.get("explanation"),
        actor=override.get("actor"),
        timestamp=override.get("timestamp"),
        store=store, config=config,
    )
