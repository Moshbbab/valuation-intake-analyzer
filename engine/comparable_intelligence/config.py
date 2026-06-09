"""Injectable configuration for the Comparable Intelligence Layer — Phase A.

Avoid rigid systems: every weight, field set, mapping and scale here is a
DEFAULT that callers may override at runtime (via ``QualityConfig`` or the
per-call ``context``). Nothing embeds professional judgment, a fixed workflow,
or a value conclusion. CIL-1 covers evidence *quality scoring* only — governance
(CIL-2) and the later capabilities are intentionally absent.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Tuple, Union

# Default weights for the four CIL-1 quality factors. These are merged on top of
# the existing evidence base-factor weights; the weighted strategy normalises by
# the sum of the weights actually used, so callers can drop or re-weight freely.
EXTENDED_DEFAULT_WEIGHTS: Dict[str, float] = {
    "data_completeness": 0.10,
    "transaction_reliability": 0.20,
    "market_relevance": 0.15,
    "adjustment_burden": 0.15,
}

# Fields whose presence counts toward the data-completeness factor.
DEFAULT_REQUIRED_FIELDS: Tuple[str, ...] = (
    "unit_rate", "area", "date", "location_score", "source", "use",
)

# Sale-condition label -> 0..1 transaction-quality contribution (case-insensitive,
# unknown labels fall back to the neutral score). Fully overridable.
DEFAULT_SALE_CONDITION_MAP: Dict[str, float] = {
    "open_market": 1.00,
    "arms_length": 1.00,
    "private_treaty": 0.85,
    "auction": 0.80,
    "part_exchange": 0.40,
    "distressed": 0.20,
    "forced_sale": 0.15,
    "related_party": 0.15,
}

# Categorical attributes compared against the subject for market relevance.
DEFAULT_MARKET_RELEVANCE_ATTRS: Tuple[str, ...] = ("use", "zoning", "market_segment")

# Gross relative adjustment at/above which the adjustment-burden factor reaches 0
# (e.g. 1.0 == 100% total adjustment). Heavier adjustments -> lower quality.
DEFAULT_ADJUSTMENT_BURDEN_CAP: float = 1.0

# Score applied to the ``verified`` signal when a comparable is explicitly
# unverified (False). Unknown/None is treated as "no signal", not penalised.
DEFAULT_UNVERIFIED_SCORE: float = 0.50


@dataclass(frozen=True)
class QualityConfig:
    """Configuration injected into ``quality.score_quality``.

    All fields are optional. ``weights``/``factor_scorers``/``confidence_bands``
    default to the merged base+extended sets when None. ``strategy`` is the
    built-in ``"weighted"``/``"min"`` or a callable (alternative calculation
    path). ``context_defaults`` supplies per-factor tunables (required fields,
    sale-condition map, relevance attrs, burden cap) without threading a context
    through every call. No value or judgment is encoded.
    """

    weights: Optional[Mapping] = None
    factor_scorers: Optional[Mapping] = None
    strategy: Union[str, Callable] = "weighted"
    confidence_bands: Optional[Mapping] = None
    context_defaults: Optional[Mapping] = None


# Convenience default instance.
DEFAULT_QUALITY_CONFIG = QualityConfig()
