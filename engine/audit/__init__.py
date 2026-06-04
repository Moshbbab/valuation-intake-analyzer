"""HVOS Audit Trail — minimal append-only event recorder.

Records what happened, to which entity, by whom, when and why, with a
before/after snapshot. It records only: no valuation math, no decisions, no
workflow. Storage is injectable and append-only.
"""

from engine.audit.recorder import (
    AuditError,
    default_store,
    record_event,
)
from engine.audit.adapters import (
    record_adjustment_created,
    record_adjustment_overridden,
    record_assumption_created,
    record_assumption_overridden,
    record_comparable_assessed,
    record_inclusion_recommendation,
)
from engine.audit.storage import InMemoryAuditStore, JsonlAuditStore
from engine.audit.config import AuditConfig, DEFAULT_CONFIG

__all__ = [
    "AuditError",
    "AuditConfig",
    "DEFAULT_CONFIG",
    "default_store",
    "record_event",
    "record_assumption_created",
    "record_assumption_overridden",
    "record_comparable_assessed",
    "record_inclusion_recommendation",
    "record_adjustment_created",
    "record_adjustment_overridden",
    "InMemoryAuditStore",
    "JsonlAuditStore",
]
