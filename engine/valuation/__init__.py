"""HVOS valuation calculation support.

Computation capabilities that compose the existing foundations (Evidence,
Adjustments, Assumptions, Audit) into valuation-relevant output. This is not a
new foundation/registry/contract layer — it produces calculation support, never
a final valuation opinion.
"""

from engine.valuation.config import (
    ComparableApproachConfig,
    DEFAULT_CONFIG,
    DEFAULT_SIMILARITY_CONFIG,
    SimilarityConfig,
)
from engine.valuation.comparable_approach import (
    adjusted_unit_rate,
    apply_adjustment_to_rate,
    indicated_range,
    normalize_weights,
    parse_adjustment_value,
    run_comparable_approach,
)
from engine.valuation.similarity import (
    as_weighting_strategy,
    confidence_contribution,
    rank_comparables,
    score_similarity,
    similarity_weights,
)

__all__ = [
    "ComparableApproachConfig",
    "DEFAULT_CONFIG",
    "SimilarityConfig",
    "DEFAULT_SIMILARITY_CONFIG",
    "parse_adjustment_value",
    "apply_adjustment_to_rate",
    "adjusted_unit_rate",
    "normalize_weights",
    "indicated_range",
    "run_comparable_approach",
    "score_similarity",
    "rank_comparables",
    "similarity_weights",
    "confidence_contribution",
    "as_weighting_strategy",
]
