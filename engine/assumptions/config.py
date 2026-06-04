"""Injectable configuration for the Assumptions Foundation.

Design principle: avoid rigid systems. The allowed assumption categories and
confidence levels live here as DEFAULTS and are passed into the registry
functions via an ``AssumptionConfig``. Nothing downstream hard-codes these
sets, so an engagement can supply its own categories/levels (e.g. an
IVS/RICS-specific taxonomy) without touching the logic or the schema.
"""

from dataclasses import dataclass
from typing import Tuple

# Default categories. "special" and "extraordinary" mirror common IVS/RICS
# usage; the list is intentionally replaceable, not authoritative.
DEFAULT_CATEGORIES: Tuple[str, ...] = (
    "general",
    "special",
    "extraordinary",
    "market",
    "physical",
    "legal",
)

# Default stated-confidence labels. Replaceable per engagement.
DEFAULT_CONFIDENCE_LEVELS: Tuple[str, ...] = ("High", "Medium", "Low")


@dataclass(frozen=True)
class AssumptionConfig:
    """Configuration injected into the registry functions.

    Both fields default to the module defaults but can be overridden entirely,
    which is how callers extend or replace the allowed sets.
    """

    categories: Tuple[str, ...] = DEFAULT_CATEGORIES
    confidence_levels: Tuple[str, ...] = DEFAULT_CONFIDENCE_LEVELS


# Convenience default instance.
DEFAULT_CONFIG = AssumptionConfig()
