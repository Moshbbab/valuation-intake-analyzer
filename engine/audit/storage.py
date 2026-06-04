"""Append-only storage backends for audit events.

Both backends expose only ``append`` and read access (``list`` / iteration /
``len``) — there is no update or delete, which is what makes the trail
append-only. Reads return deep copies so stored events cannot be mutated in
place by a caller. Backends are duck-typed: anything with a compatible
``append`` is accepted by the recorder, so new backends need no recorder change.
"""

import json
import os
from copy import deepcopy
from typing import Dict, Iterator, List


class InMemoryAuditStore:
    """In-memory append-only store (the default)."""

    def __init__(self) -> None:
        self._events: List[Dict] = []

    def append(self, event: Dict) -> Dict:
        """Append a copy of ``event`` to the trail."""
        self._events.append(deepcopy(dict(event)))
        return event

    def list(self) -> List[Dict]:
        """Return a deep copy of all events (mutating it cannot affect the store)."""
        return deepcopy(self._events)

    def __iter__(self) -> Iterator[Dict]:
        return iter(self.list())

    def __len__(self) -> int:
        return len(self._events)


class JsonlAuditStore:
    """Append-only JSON Lines store: one event per line.

    Intentionally minimal — no rotation, locking or retention. Each append is a
    single line write; reads parse the file. Missing file reads as empty.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def append(self, event: Dict) -> Dict:
        """Append ``event`` as one JSON line."""
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def list(self) -> List[Dict]:
        """Return all events, or an empty list if the file does not exist yet."""
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def __iter__(self) -> Iterator[Dict]:
        return iter(self.list())

    def __len__(self) -> int:
        return len(self.list())
