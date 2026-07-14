"""Append-only audit event recorder — the core.

``record_event`` builds an event, stamps it (auto ``event_id`` / ``timestamp``
when absent), validates ``entity_type`` / ``action`` against an injectable
vocabulary, and appends it to a store. It records only — no valuation logic, no
decisions, no enforced ordering. ``before``/``after`` are deep-copied so later
mutation of the source cannot alter the recorded event.
"""

import hashlib
import json
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
    _chain(event, store)
    store.append(event)
    return event


# ─── SHA-256 hash chain ────────────────────────────────────────────────────────

def _event_digest(event: Dict, prev_hash: Optional[str]) -> str:
    """SHA-256 over the canonical event payload linked to the previous hash."""
    payload = {key: value for key, value in event.items()
               if key not in ("event_hash", "prev_event_hash")}
    canonical = json.dumps(payload, sort_keys=True, default=str,
                           ensure_ascii=False)
    return hashlib.sha256(
        (prev_hash or "GENESIS").encode("utf-8") + canonical.encode("utf-8")
    ).hexdigest()


def _chain(event: Dict, store: Any) -> None:
    """Stamp the event with the store's hash chain (tamper-evident)."""
    prev_hash = getattr(store, "last_event_hash", None)
    event["prev_event_hash"] = prev_hash
    event["event_hash"] = _event_digest(event, prev_hash)
    try:
        store.last_event_hash = event["event_hash"]
    except AttributeError:
        pass  # read-only store: events still carry their own hashes


def verify_chain(events: List[Dict]) -> Dict:
    """Verify a recorded event sequence's SHA-256 chain integrity.

    Returns ``{"valid": bool, "checked": n, "first_invalid": event_id or None}``.
    Any mutation of a recorded event, or any removal/reordering, breaks the
    chain at the first affected event.
    """
    prev_hash = None
    for index, event in enumerate(events):
        expected = _event_digest(event, prev_hash)
        if event.get("event_hash") != expected \
                or event.get("prev_event_hash") != prev_hash:
            return {"valid": False, "checked": index + 1,
                    "first_invalid": event.get("event_id")}
        prev_hash = event["event_hash"]
    return {"valid": True, "checked": len(events), "first_invalid": None}
