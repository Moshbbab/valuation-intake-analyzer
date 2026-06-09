"""Comparable Intelligence Layer (CIL) for HVOS.

An evidence-assisted *support* layer that composes the existing foundations
(Evidence, Adjustments, Assumptions, Audit) and valuation engines. It is not a
new foundation/registry/contract and never an AVM: every output is advisory,
human judgment is the final authority, and no component produces, infers or
recommends an adopted/final value.

Three concerns are kept architecturally distinct: evidence *scoring* (how good —
CIL-1, here), evidence *governance* (is it appropriate — CIL-2), and *admission*
(what to recommend — later). Every output exposes ``result``, ``explanation``
and ``assumptions_used`` for auditability and reproducibility.

Phase A exposes CIL-1 (extended quality dimensions) only.
"""

from engine.comparable_intelligence.common import build_envelope, clamp, is_number
from engine.comparable_intelligence.config import (
    DEFAULT_ADJUSTMENT_BURDEN_CAP,
    DEFAULT_MARKET_RELEVANCE_ATTRS,
    DEFAULT_QUALITY_CONFIG,
    DEFAULT_REQUIRED_FIELDS,
    DEFAULT_SALE_CONDITION_MAP,
    DEFAULT_UNVERIFIED_SCORE,
    EXTENDED_DEFAULT_WEIGHTS,
    QualityConfig,
)
from engine.comparable_intelligence.quality import (
    ALL_FACTOR_SCORERS,
    EXTENDED_FACTOR_SCORERS,
    score_adjustment_burden,
    score_data_completeness,
    score_market_relevance,
    score_quality,
    score_transaction_reliability,
)

__all__ = [
    "build_envelope",
    "clamp",
    "is_number",
    "QualityConfig",
    "DEFAULT_QUALITY_CONFIG",
    "EXTENDED_DEFAULT_WEIGHTS",
    "DEFAULT_REQUIRED_FIELDS",
    "DEFAULT_SALE_CONDITION_MAP",
    "DEFAULT_MARKET_RELEVANCE_ATTRS",
    "DEFAULT_ADJUSTMENT_BURDEN_CAP",
    "DEFAULT_UNVERIFIED_SCORE",
    "score_quality",
    "score_data_completeness",
    "score_transaction_reliability",
    "score_market_relevance",
    "score_adjustment_burden",
    "EXTENDED_FACTOR_SCORERS",
    "ALL_FACTOR_SCORERS",
]
