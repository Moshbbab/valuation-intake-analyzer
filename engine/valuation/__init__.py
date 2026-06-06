"""HVOS valuation calculation support.

Computation capabilities that compose the existing foundations (Evidence,
Adjustments, Assumptions, Audit) into valuation-relevant output. This is not a
new foundation/registry/contract layer — it produces calculation support, never
a final valuation opinion.
"""

from engine.valuation.config import (
    ComparableApproachConfig,
    DCFConfig,
    DEFAULT_CONFIG,
    DEFAULT_DCF_CONFIG,
    DEFAULT_DIRECT_CAP_CONFIG,
    DEFAULT_NOI_CONFIG,
    DEFAULT_RECONCILIATION_CONFIG,
    DEFAULT_SIMILARITY_CONFIG,
    DirectCapConfig,
    NOIConfig,
    ReconciliationConfig,
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
from engine.valuation.noi import (
    build_noi,
    effective_gross_income,
    potential_gross_income,
    total_operating_expenses,
)
from engine.valuation.direct_capitalization import (
    capitalize,
    direct_capitalization,
    sensitivity_grid,
    value_from_cap_rate_range,
)
from engine.valuation.dcf import (
    dcf_sensitivity,
    discount_factor,
    discounted_cash_flow,
    present_value,
    reversion_value,
)
from engine.valuation.reconciliation import (
    normalize_approach_weights,
    reconcile,
)

__all__ = [
    "ComparableApproachConfig",
    "DEFAULT_CONFIG",
    "SimilarityConfig",
    "DEFAULT_SIMILARITY_CONFIG",
    "NOIConfig",
    "DEFAULT_NOI_CONFIG",
    "DirectCapConfig",
    "DEFAULT_DIRECT_CAP_CONFIG",
    "DCFConfig",
    "DEFAULT_DCF_CONFIG",
    "ReconciliationConfig",
    "DEFAULT_RECONCILIATION_CONFIG",
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
    "potential_gross_income",
    "effective_gross_income",
    "total_operating_expenses",
    "build_noi",
    "capitalize",
    "value_from_cap_rate_range",
    "sensitivity_grid",
    "direct_capitalization",
    "discount_factor",
    "present_value",
    "reversion_value",
    "discounted_cash_flow",
    "dcf_sensitivity",
    "normalize_approach_weights",
    "reconcile",
]
