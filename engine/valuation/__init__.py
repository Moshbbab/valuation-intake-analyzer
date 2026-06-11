"""HVOS valuation calculation support.

Computation capabilities that compose the existing foundations (Evidence,
Adjustments, Assumptions, Audit) into valuation-relevant output. This is not a
new foundation/registry/contract layer — it produces calculation support, never
a final valuation opinion.
"""

from engine.valuation.config import (
    AgreementConfig,
    ComparableApproachConfig,
    DCFConfig,
    AdjustmentEngineConfig,
    CapRateConfig,
    DEFAULT_ADJUSTMENT_ENGINE_CONFIG,
    DEFAULT_AGREEMENT_CONFIG,
    DEFAULT_CAP_RATE_CONFIG,
    DEFAULT_CONFIG,
    DEFAULT_DCF_CONFIG,
    DEFAULT_DIRECT_CAP_CONFIG,
    DEFAULT_LAND_VALUE_CONFIG,
    DEFAULT_MARKET_RATE_CONFIG,
    DEFAULT_NOI_CONFIG,
    DEFAULT_RECONCILIATION_CONFIG,
    DEFAULT_RECONCILIATION_ENGINE_CONFIG,
    DEFAULT_SIMILARITY_CONFIG,
    DirectCapConfig,
    LandValueConfig,
    MarketRateConfig,
    NOIConfig,
    ReconciliationConfig,
    ReconciliationEngineConfig,
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
from engine.valuation.agreement import (
    approach_dispersion,
)
from engine.valuation.market_rate import adopted_market_rate
from engine.valuation.land_value import land_value, land_value_from_comparables
from engine.valuation.cap_rate import adopted_cap_rate, market_derived_cap_rate
from engine.valuation.comparable_adjustment import (
    adjust_comparable,
    adjustment_grid,
)
from engine.valuation.reconciliation_engine import reconcile_approaches
from engine.valuation.valuation_run import run_valuation

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
    "AgreementConfig",
    "DEFAULT_AGREEMENT_CONFIG",
    "MarketRateConfig",
    "DEFAULT_MARKET_RATE_CONFIG",
    "LandValueConfig",
    "DEFAULT_LAND_VALUE_CONFIG",
    "CapRateConfig",
    "DEFAULT_CAP_RATE_CONFIG",
    "AdjustmentEngineConfig",
    "DEFAULT_ADJUSTMENT_ENGINE_CONFIG",
    "ReconciliationEngineConfig",
    "DEFAULT_RECONCILIATION_ENGINE_CONFIG",
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
    "approach_dispersion",
    "adopted_market_rate",
    "land_value",
    "land_value_from_comparables",
    "adopted_cap_rate",
    "market_derived_cap_rate",
    "adjust_comparable",
    "adjustment_grid",
    "reconcile_approaches",
    "run_valuation",
]
