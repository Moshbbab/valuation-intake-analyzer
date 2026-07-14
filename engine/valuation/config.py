"""Injectable configuration for the comparable-approach calculation support.

Design principle: avoid rigid systems. The weighting strategy, the set of
inclusion decisions that count, and rounding are all injectable. There are no
caps, no hard-coded weighting formula and no forced single-point conclusion.
``weighting`` may be the built-in name or a callable that returns
``{comparable_id: weight}`` — an alternative calculation path the caller owns.
"""

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple, Union

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


@dataclass(frozen=True)
class SimilarityConfig:
    """Configuration injected into the similarity / weighting-intelligence funcs.

    Everything is injectable. ``scorers``/``dimensions``/``weights`` default to
    None so the module supplies replaceable defaults; pass your own to extend or
    replace them. ``aggregation`` and ``ranking`` accept a built-in name or a
    callable.

    ``blend_reliability`` is the only place evidence reliability may enter
    weighting. It is disabled by default (None) — similarity and reliability are
    distinct professional concepts and are not collapsed. When set to a fraction
    in [0, 1] it is applied explicitly and reported by ``confidence_contribution``.
    """

    dimensions: Optional[Tuple[str, ...]] = None
    scorers: Optional[Mapping] = None
    weights: Optional[Mapping] = None
    aggregation: Union[str, Callable] = "weighted_mean"
    ranking: Union[str, Callable] = "similarity"
    blend_reliability: Optional[float] = None
    included_decisions: Tuple[str, ...] = DEFAULT_INCLUDED_DECISIONS
    rounding: Optional[int] = None


# Convenience default instance (pure similarity; no reliability blend).
DEFAULT_SIMILARITY_CONFIG = SimilarityConfig()


@dataclass(frozen=True)
class NOIConfig:
    """Configuration injected into the NOI Builder.

    ``aggregation`` controls how line-item amounts are summed — the built-in
    name ``"sum"`` or a callable taking a list of amounts and returning a total.
    ``amount_field``/``name_field`` are the keys read from each line-item dict,
    so callers are not forced into fixed field names. There is no default
    vacancy rate, no fixed expense ratio and no reserve rule here.
    """

    aggregation: Union[str, Callable] = "sum"
    amount_field: str = "amount"
    name_field: str = "name"
    rounding: Optional[int] = None


# Convenience default instance.
DEFAULT_NOI_CONFIG = NOIConfig()


@dataclass(frozen=True)
class DirectCapConfig:
    """Configuration injected into the Direct Capitalization functions.

    There is no cap rate here — cap rates are always caller-supplied. The config
    carries only presentation/structural options: ``rounding`` and the
    ``sort_range`` toggle for ordering a value range (lower cap rate yields a
    higher value, so the range is sorted by default). No market default, no risk
    premium, no growth/exit assumption is encoded.
    """

    rounding: Optional[int] = None
    sort_range: bool = True


# Convenience default instance.
DEFAULT_DIRECT_CAP_CONFIG = DirectCapConfig()


@dataclass(frozen=True)
class DCFConfig:
    """Configuration injected into the DCF functions.

    There is no discount rate, exit cap rate, growth rate or horizon here — all
    are caller-supplied. The config carries only presentation/structural options
    plus an optional ``discount_factor`` callable (rate, period) -> factor for an
    alternative discounting convention. No market default or build-up is encoded.
    """

    rounding: Optional[int] = None
    discount_factor: Optional[Callable] = None


# Convenience default instance.
DEFAULT_DCF_CONFIG = DCFConfig()


@dataclass(frozen=True)
class ReconciliationConfig:
    """Configuration injected into cross-approach reconciliation.

    ``weights`` optionally maps approach name -> weight; per-indication weights
    override it. When no weights are supplied anywhere, reconciliation falls back
    to equal weights (a mixed/partial weight set is rejected, not guessed).
    ``aggregation`` is the built-in ``"weighted_mean"`` or a callable
    ``(approach_centrals, weights) -> central``. No default approach hierarchy
    and no adopted value are encoded.
    """

    weights: Optional[Mapping] = None
    aggregation: Union[str, Callable] = "weighted_mean"
    rounding: Optional[int] = None


# Convenience default instance.
DEFAULT_RECONCILIATION_CONFIG = ReconciliationConfig()


@dataclass(frozen=True)
class AgreementConfig:
    """Configuration injected into cross-approach agreement/dispersion metrics.

    ``normalize_against`` selects the central figure that percentage dispersion
    is expressed relative to — the built-in ``"weighted_mean"`` or ``"mean"``, or
    a callable ``(centrals, weights) -> base``. No confidence band, label or
    threshold is encoded: the module reports raw dispersion, not a verdict on it.
    """

    normalize_against: Union[str, Callable] = "weighted_mean"
    rounding: Optional[int] = None


# Convenience default instance.
DEFAULT_AGREEMENT_CONFIG = AgreementConfig()


# ─── Valuation production engines (market rate, land value, cap rate) ──────────

@dataclass(frozen=True)
class MarketRateConfig:
    """Configuration injected into the Comparable Market Engine.

    Produces an adopted land rate range from comparable transactions. Every knob
    is configurable: ``outlier_method`` ("iqr"/"none"/callable) with ``iqr_k``
    fence; ``central`` chooses the recommended base rate ("weighted_mean"/
    "median"/"mean"/callable); ``range_basis`` chooses the low/high bounds
    ("percentile"/"min_max") with ``low_pct``/``high_pct``. No fixed market rate
    is encoded — the rate is computed from the supplied evidence only.
    """

    outlier_method: Union[str, Callable] = "iqr"
    outlier_action: str = "flag"
    iqr_k: float = 1.5
    central: Union[str, Callable] = "weighted_mean"
    range_basis: str = "percentile"
    low_pct: float = 25.0
    high_pct: float = 75.0
    weight_field: str = "weight"
    rounding: Optional[int] = None


DEFAULT_MARKET_RATE_CONFIG = MarketRateConfig()


@dataclass(frozen=True)
class LandValueConfig:
    """Configuration injected into the Land Value Engine.

    Land value = area x rate, evaluated at the low/base/high points of an
    adopted rate range. ``rounding`` only affects presentation. No rate is
    assumed here — the rate range is always caller-supplied (typically from the
    Comparable Market Engine).
    """

    rounding: Optional[int] = None


DEFAULT_LAND_VALUE_CONFIG = LandValueConfig()


@dataclass(frozen=True)
class CapRateConfig:
    """Configuration injected into the Cap Rate Engine.

    Derives implied capitalisation rates (NOI / price) from market transactions
    and recommends an adopted cap-rate range. Mirrors the market-rate knobs:
    ``outlier_method``/``iqr_k``, ``central`` recommendation strategy,
    ``range_basis`` with percentiles. No market cap rate is encoded — rates are
    implied from the supplied evidence only.
    """

    outlier_method: Union[str, Callable] = "iqr"
    outlier_action: str = "flag"
    iqr_k: float = 1.5
    central: Union[str, Callable] = "weighted_mean"
    range_basis: str = "percentile"
    low_pct: float = 25.0
    high_pct: float = 75.0
    weight_field: str = "weight"
    rounding: Optional[int] = None


DEFAULT_CAP_RATE_CONFIG = CapRateConfig()


@dataclass(frozen=True)
class AdjustmentEngineConfig:
    """Configuration injected into the Comparable Adjustment Engine.

    Each adjustment dimension is driven by a caller-supplied sensitivity — the
    engine performs the mechanics; it assumes no market movement or coefficient.
    All sensitivities default to 0 (no adjustment) and the use map defaults to
    empty, so nothing is adjusted unless the caller supplies a coefficient.
    ``annual_market_trend`` is the market movement per year used for the time
    adjustment; ``combination`` is "multiplicative"/"additive" or a callable
    ``(base, pct_by_dim) -> adjusted``. No professional judgment is encoded.
    """

    annual_market_trend: float = 0.0
    valuation_date: Optional[str] = None
    date_field: str = "date"
    location_sensitivity: float = 0.0
    location_scale: float = 1.0
    size_sensitivity: float = 0.0
    frontage_sensitivity: float = 0.0
    use_adjustment_map: Optional[Mapping] = None
    combination: Union[str, Callable] = "multiplicative"
    rounding: Optional[int] = None


DEFAULT_ADJUSTMENT_ENGINE_CONFIG = AdjustmentEngineConfig()


@dataclass(frozen=True)
class ReconciliationEngineConfig:
    """Configuration injected into the Reconciliation Engine.

    ``agreement_basis`` selects the dispersion measure inverted into the 0..1
    agreement score — "coefficient_of_variation" (default) or "spread_pct".
    The engine compares approaches and suggests a range; it never adopts a
    final value.
    """

    agreement_basis: str = "coefficient_of_variation"
    rounding: Optional[int] = None


DEFAULT_RECONCILIATION_ENGINE_CONFIG = ReconciliationEngineConfig()
