"""Configurable evidence-quality scoring for the HVOS Evidence Registry.

Design principle: avoid rigid systems. This module never forces a single
outcome. Concretely:

* weights, thresholds and confidence bands are arguments with sane defaults
  (configurable assumptions);
* factor scorers are pluggable callables and the combination strategy can be a
  built-in name or a custom callable (alternative calculation paths);
* a ``manual_override`` always wins over the computed decision, yet the
  automated decision is still recorded (override mechanism + auditability);
* every result carries a per-factor breakdown and a human-readable explanation
  (explainable decisions), and confidence is banded rather than binary
  (confidence levels).
"""

from datetime import date, datetime
from typing import Callable, Dict, List, Mapping, Optional, Union

from engine.evidence import config as cfg

# A factor scorer maps (comparable, context) -> raw factor score in 0..1.
FactorScorer = Callable[[Mapping, Mapping], float]
# A combination strategy is either a known name or a callable.
Strategy = Union[str, Callable[[Mapping, Mapping], float]]


def _clamp(value: float) -> float:
    """Constrain a score to the 0..1 range."""
    return max(0.0, min(1.0, float(value)))


def _as_date(value) -> Optional[date]:
    """Best-effort parse of an ISO date string / date / datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


# ─── Built-in factor scorers (all overridable) ────────────────────────────────

def score_recency(comparable: Mapping, context: Mapping) -> float:
    """Exponential decay by age using a configurable half-life."""
    comp_date = _as_date(comparable.get("date"))
    if comp_date is None:
        return context.get("missing_recency_score", cfg.DEFAULT_NEUTRAL_SCORE)
    ref_date = _as_date(context.get("valuation_date")) or date.today()
    half_life = context.get("recency_half_life_days",
                            cfg.DEFAULT_RECENCY_HALF_LIFE_DAYS)
    age_days = max(0, (ref_date - comp_date).days)
    return _clamp(0.5 ** (age_days / float(half_life)))


def score_location_proximity(comparable: Mapping, context: Mapping) -> float:
    """Use a provided location_score; accept 0..1 or 0..100 scales."""
    raw = comparable.get("location_score")
    if raw is None:
        return cfg.DEFAULT_NEUTRAL_SCORE
    val = float(raw)
    if val > 1.0:
        val = val / 100.0
    return _clamp(val)


def score_source_quality(comparable: Mapping, context: Mapping) -> float:
    """Map a free-form source label to a quality score via a configurable map."""
    mapping = context.get("source_quality_map", cfg.DEFAULT_SOURCE_QUALITY_MAP)
    default = context.get("default_source_quality", cfg.DEFAULT_SOURCE_QUALITY)
    source = str(comparable.get("source", "")).strip().lower()
    return _clamp(mapping.get(source, default))


def score_size_similarity(comparable: Mapping, context: Mapping) -> float:
    """Ratio of smaller/larger area against the subject; neutral if unknown."""
    subject_area = context.get("subject_area")
    comp_area = comparable.get("area")
    if not subject_area or not comp_area:
        return cfg.DEFAULT_NEUTRAL_SCORE
    smaller, larger = sorted((float(comp_area), float(subject_area)))
    if larger <= 0:
        return cfg.DEFAULT_NEUTRAL_SCORE
    return _clamp(smaller / larger)


DEFAULT_FACTOR_SCORERS: Dict[str, FactorScorer] = {
    "recency": score_recency,
    "location_proximity": score_location_proximity,
    "source_quality": score_source_quality,
    "size_similarity": score_size_similarity,
}


# ─── Combination strategies ───────────────────────────────────────────────────

def _combine(factor_scores: Mapping, weights: Mapping, strategy: Strategy) -> float:
    """Combine per-factor scores into one reliability score.

    Built-in strategies: "weighted" (weight-normalised mean) and "min"
    (conservative, worst-factor). A callable strategy receives
    (factor_scores, weights) and returns a 0..1 score — an alternative
    calculation path the caller fully controls.
    """
    if callable(strategy):
        return _clamp(strategy(factor_scores, weights))
    if not factor_scores:
        return 0.0
    if strategy == "min":
        return _clamp(min(factor_scores.values()))
    if strategy == "weighted":
        total_w = sum(weights.get(name, 0.0) for name in factor_scores)
        if total_w <= 0:
            return 0.0
        weighted = sum(score * weights.get(name, 0.0)
                       for name, score in factor_scores.items())
        return _clamp(weighted / total_w)
    raise ValueError(f"Unknown combination strategy: {strategy!r}")


def _confidence_level(score: float, bands: Mapping) -> str:
    """Band a 0..1 score into High / Medium / Low using configurable edges."""
    if score >= bands.get("high", cfg.DEFAULT_CONFIDENCE_BANDS["high"]):
        return "High"
    if score >= bands.get("medium", cfg.DEFAULT_CONFIDENCE_BANDS["medium"]):
        return "Medium"
    return "Low"


def _explain(factor_scores: Mapping, weights: Mapping,
             strategy: Strategy, reliability: float) -> List[str]:
    """Produce a human-readable, auditable breakdown of the score."""
    label = strategy if isinstance(strategy, str) else "custom"
    lines = [f"strategy={label}", f"reliability={round(reliability, 4)}"]
    for name, score in factor_scores.items():
        weight = weights.get(name, "n/a")
        lines.append(f"{name}: score={round(float(score), 4)} weight={weight}")
    return lines


# ─── Public API ───────────────────────────────────────────────────────────────

def score_evidence(comparable: Mapping, *,
                   weights: Optional[Mapping] = None,
                   factor_scorers: Optional[Mapping] = None,
                   context: Optional[Mapping] = None,
                   strategy: Strategy = "weighted",
                   confidence_bands: Optional[Mapping] = None) -> Dict:
    """Score one comparable's evidence quality.

    All of weights, factor_scorers, context, strategy and confidence_bands are
    optional overrides; with no arguments the configurable defaults apply.

    Returns a dict with ``reliability_score`` (0..1), per-factor
    ``factor_scores``, a banded ``confidence_level``, the ``strategy`` used and
    an ``explanation`` list.
    """
    weights = dict(weights or cfg.DEFAULT_WEIGHTS)
    scorers = dict(factor_scorers or DEFAULT_FACTOR_SCORERS)
    context = dict(context or {})
    bands = dict(confidence_bands or cfg.DEFAULT_CONFIDENCE_BANDS)

    factor_scores = {
        name: _clamp(scorer(comparable, context))
        for name, scorer in scorers.items()
    }
    reliability = _combine(factor_scores, weights, strategy)

    return {
        "reliability_score": round(reliability, 4),
        "factor_scores": {k: round(v, 4) for k, v in factor_scores.items()},
        "confidence_level": _confidence_level(reliability, bands),
        "strategy": strategy if isinstance(strategy, str) else "custom",
        "explanation": _explain(factor_scores, weights, strategy, reliability),
    }


def _auto_decision(score: float, thresholds: Mapping) -> str:
    """Map a reliability score to include / review / exclude."""
    if score >= thresholds.get("include", cfg.DEFAULT_THRESHOLDS["include"]):
        return "include"
    if score >= thresholds.get("review", cfg.DEFAULT_THRESHOLDS["review"]):
        return "review"
    return "exclude"


def decide_inclusion(reliability_score: float, *,
                     thresholds: Optional[Mapping] = None,
                     manual_override: Optional[Mapping] = None) -> Dict:
    """Decide inclusion from a reliability score, honouring manual overrides.

    A ``manual_override`` (``{"decision": ..., "rationale": ..., "actor": ...}``)
    always wins, but the automated decision is still computed and returned as
    ``auto_decision`` so the override remains explainable and auditable.
    """
    thresholds = dict(thresholds or cfg.DEFAULT_THRESHOLDS)
    auto = _auto_decision(reliability_score, thresholds)

    if manual_override is not None:
        return {
            "inclusion_decision": manual_override.get("decision"),
            "decided_by": "manual_override",
            "actor": manual_override.get("actor"),
            "rationale": manual_override.get("rationale", ""),
            "auto_decision": auto,
        }

    return {
        "inclusion_decision": auto,
        "decided_by": "auto",
        "actor": None,
        "rationale": (f"reliability_score={round(reliability_score, 4)} "
                      f"vs thresholds {thresholds}"),
        "auto_decision": auto,
    }


def assess_comparable(comparable: Mapping, **kwargs) -> Dict:
    """Convenience: score a comparable and decide inclusion in one call.

    Accepts the same overrides as ``score_evidence`` plus ``thresholds``. A
    ``manual_override`` taken from the comparable (or passed explicitly) is
    respected.
    """
    thresholds = kwargs.pop("thresholds", None)
    override = kwargs.pop("manual_override", comparable.get("manual_override"))
    scored = score_evidence(comparable, **kwargs)
    decision = decide_inclusion(scored["reliability_score"],
                                thresholds=thresholds,
                                manual_override=override)
    return {**scored, **decision}
