"""Injectable configuration for the comparable-approach calculation support.

Design principle: avoid rigid systems. The weighting strategy, the set of
inclusion decisions that count, and rounding are all injectable. There are no
caps, no hard-coded weighting formula and no forced single-point conclusion.
``weighting`` may be the built-in name or a callable that returns
``{comparable_id: weight}`` — an alternative calculation path the caller owns.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Union

# Inclusion decisions that count toward the indicated value by default. Note
# "review" is deliberately excluded so a review comparable is never auto-used.
DEFAULT_INCLUDED_DECISIONS: Tuple[str, ...] = ("include",)

# A weighting strategy is either the built-in name or a callable.
Weighting = Union[str, Callable]


@dataclass(frozen=True)
class ComparableApproachConfig:
    """Configuration injected into the comparable-approach functions."""

    weighting: Weighting = "reliability_normalized"
    included_decisions: Tuple[str, ...] = DEFAULT_INCLUDED_DECISIONS
    rounding: Optional[int] = None


# Convenience default instance.
DEFAULT_CONFIG = ComparableApproachConfig()
