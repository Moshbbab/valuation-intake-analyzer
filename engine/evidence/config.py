"""Default configuration for evidence-quality scoring.

Design principle: avoid rigid systems. Every number and mapping here is a
DEFAULT that callers can override at runtime by passing arguments to the
functions in ``engine.evidence.scoring``. Nothing in the scoring logic embeds
a magic constant — the constants all live here and are injectable. This keeps
the Evidence Registry configurable and supportive of professional judgment.
"""

from typing import Dict

# Relative importance of each quality factor. They need not sum to exactly 1.0;
# the weighted strategy normalises by the sum of the weights actually used, so
# an engagement can drop or re-weight factors freely.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "recency": 0.30,
    "location_proximity": 0.30,
    "source_quality": 0.25,
    "size_similarity": 0.15,
}

# Inclusion thresholds on the 0..1 reliability score. Tunable per engagement.
#   score >= include  -> "include"
#   score >= review   -> "review"
#   otherwise         -> "exclude"
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "include": 0.70,
    "review": 0.45,
}

# Confidence bands on the 0..1 reliability score.
#   score >= high   -> "High"
#   score >= medium -> "Medium"
#   otherwise       -> "Low"
DEFAULT_CONFIDENCE_BANDS: Dict[str, float] = {
    "high": 0.75,
    "medium": 0.50,
}

# Source-quality lookup (0..1). Unknown / unmapped sources fall back to
# DEFAULT_SOURCE_QUALITY. Matching is case-insensitive on the source label.
DEFAULT_SOURCE_QUALITY: float = 0.50
DEFAULT_SOURCE_QUALITY_MAP: Dict[str, float] = {
    "registry": 1.00,
    "official": 0.95,
    "valuer": 0.85,
    "broker": 0.70,
    "listing": 0.55,
    "asking": 0.40,
    "anecdotal": 0.25,
}

# Recency half-life in days: a comparable this old scores 0.5 on the recency
# factor; decay is exponential.
DEFAULT_RECENCY_HALF_LIFE_DAYS: int = 365

# Neutral fallback score used when a factor cannot be computed (missing input).
DEFAULT_NEUTRAL_SCORE: float = 0.50
