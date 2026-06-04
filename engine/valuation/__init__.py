"""HVOS valuation calculation support.

Computation capabilities that compose the existing foundations (Evidence,
Adjustments, Assumptions, Audit) into valuation-relevant output. This is not a
new foundation/registry/contract layer — it produces calculation support, never
a final valuation opinion.
"""

from engine.valuation.config import (
    ComparableApproachConfig,
    DEFAULT_CONFIG,
)
from engine.valuation.comparable_approach import (
    adjusted_unit_rate,
    apply_adjustment_to_rate,
    indicated_range,
    normalize_weights,
    parse_adjustment_value,
    run_comparable_approach,
)

__all__ = [
    "ComparableApproachConfig",
    "DEFAULT_CONFIG",
    "parse_adjustment_value",
    "apply_adjustment_to_rate",
    "adjusted_unit_rate",
    "normalize_weights",
    "indicated_range",
    "run_comparable_approach",
]
