"""Injectable vocabulary for the Audit Trail.

Design principle: avoid rigid systems. ``entity_type`` and ``action`` are not
fixed enums; they are validated against the tuples below, which are passed in
via an ``AuditConfig``. An empty tuple means "unrestricted" for that field, so
a caller can disable validation entirely without touching the recorder.
"""

from dataclasses import dataclass
from typing import Tuple

# Default vocabulary covering the four currently-wired event types. Replaceable
# or extendable per engagement; an empty tuple disables validation.
DEFAULT_ENTITY_TYPES: Tuple[str, ...] = ("assumption", "comparable", "adjustment")
DEFAULT_ACTIONS: Tuple[str, ...] = (
    "created",
    "overridden",
    "assessed",
    "inclusion_recommended",
)


@dataclass(frozen=True)
class AuditConfig:
    """Configuration injected into the recorder.

    An empty tuple for either field means that field is not validated, keeping
    the recorder open rather than rigid.
    """

    entity_types: Tuple[str, ...] = DEFAULT_ENTITY_TYPES
    actions: Tuple[str, ...] = DEFAULT_ACTIONS


# Convenience default instance.
DEFAULT_CONFIG = AuditConfig()

# An explicitly unrestricted config (no vocabulary validation).
UNRESTRICTED_CONFIG = AuditConfig(entity_types=(), actions=())
