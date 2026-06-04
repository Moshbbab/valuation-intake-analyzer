"""Injectable configuration for the Adjustment Foundation.

Design principle: avoid rigid systems. The allowed adjustment factors,
directions and confidence levels live here as DEFAULTS and are passed into the
registry functions via an ``AdjustmentConfig``. Nothing downstream hard-codes
these sets, so an engagement can supply its own vocabulary without touching the
logic or the schema. An empty tuple for any field means "unrestricted" for that
field — validation is then skipped, keeping the foundation open rather than
rigid. No percentage limits or factor hierarchy are encoded anywhere.
"""

from dataclasses import dataclass
from typing import Tuple

# Default adjustment factors. Intentionally illustrative and replaceable, not
# authoritative — there is no fixed factor list or hierarchy in HVOS.
DEFAULT_FACTORS: Tuple[str, ...] = (
    "location",
    "time",
    "size",
    "condition",
    "use",
    "tenure",
)

# Default directions. Replaceable per engagement.
DEFAULT_DIRECTIONS: Tuple[str, ...] = ("upward", "downward", "neutral")

# Default stated-confidence labels. Replaceable per engagement.
DEFAULT_CONFIDENCE_LEVELS: Tuple[str, ...] = ("High", "Medium", "Low")


@dataclass(frozen=True)
class AdjustmentConfig:
    """Configuration injected into the registry functions.

    Each field defaults to the module defaults but can be overridden entirely.
    An empty tuple disables validation for that field (unrestricted), which is
    how a caller opts out of any vocabulary constraint.
    """

    factors: Tuple[str, ...] = DEFAULT_FACTORS
    directions: Tuple[str, ...] = DEFAULT_DIRECTIONS
    confidence_levels: Tuple[str, ...] = DEFAULT_CONFIDENCE_LEVELS


# Convenience default instance.
DEFAULT_CONFIG = AdjustmentConfig()

# An explicitly unrestricted config (no vocabulary validation at all).
UNRESTRICTED_CONFIG = AdjustmentConfig(factors=(), directions=(),
                                       confidence_levels=())
