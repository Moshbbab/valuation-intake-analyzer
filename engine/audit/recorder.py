"""Append-only audit event recorder — the core.

``record_event`` builds an event, stamps it (auto ``event_id`` / ``timestamp``
when absent), validates ``entity_type`` / ``action`` against an injectable
vocabulary, and appends it to a store. It records only — no valuation logic, no
decisions, no enforced ordering. ``before``/``after`` are deep-copied so later
mutation of the source cannot alter the recorded event.
"""

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.audit.config import AuditConfig, DEFAULT_CONFIG
from engine.audit.storage import InMemoryAuditStore

# Process-wide default in-memory store, used when no store is injected.
default_store = InMemoryAuditStore()


class AuditError(ValueError):
    """Raised when an audit event is invalid."""


def _now() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _validate_vocabulary(entity_type: str, action: str,
                         config: AuditConfig) -> None:
    """Validate against the injectable vocabulary; empty tuple = unrestricted."""
    if config.entity_types and entity_type not in config.entity_types:
        raise AuditError(
            f"entity_type '{entity_type}' is not in configured vocabulary "
            f"{config.entity_types}"
        )
    if config.actions and action not in config.actions:
        raise AuditError(
            f"action '{action}' is not in configured vocabulary {config.actions}"
        )


def record_event(entity_type: str, entity_id: Optional[str], action: str, *,
                 before: Any = None,
                 after: Any = None,
                 rationale: Optional[str] = None,
                 explanation: Optional[List[str]] = None,
                 actor: Optional[str] = None,
                 timestamp: Optional[str] = None,
                 event_id: Optional[str] = None,
                 store: Any = None,
                 config: Optional[AuditConfig] = None) -> Dict:
    """Record one audit event and append it to ``store``.

    ``event_id`` and ``timestamp`` are auto-generated when not supplied.
    ``before``/``after`` are snapshotted (deep-copied). Returns the recorded
    event. When ``store`` is None the module-level ``default_store`` is used.
    """
    config = config or DEFAULT_CONFIG
    if store is None:
        store = default_store

    _validate_vocabulary(entity_type, action, config)

    event = {
        "event_id": event_id or f"E-{uuid.uuid4().hex[:8]}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor": actor,
        "timestamp": timestamp or _now(),
        "before": deepcopy(before),
        "after": deepcopy(after),
        "rationale": rationale,
        "explanation": deepcopy(explanation),
    }
    store.append(event)
    return event
