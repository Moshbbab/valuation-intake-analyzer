"""Comparable similarity & weighting intelligence — decision support.

Scores how comparable each sale is to the subject across *configurable*
dimensions, then turns that into ranking and weighting *suggestions* plus a
confidence-contribution view. It produces support only: no value, no adopted
figure, no auto acceptance/rejection of comparables, no forced ranking method.

Distinct from Evidence reliability: reliability measures evidence quality;
similarity measures comparability to the subject. They are kept separate —
``similarity_weights`` uses pure similarity by default and only blends
reliability when ``SimilarityConfig.blend_reliability`` is explicitly set.

Everything is injectable: the dimension set, each dimension's scorer, the
dimension weights, the aggregation strategy and the ranking strategy may all be
replaced (a callable is accepted where a strategy is expected). The default
dimension scorers below are illustrative and fully replaceable — they are not a
fixed similarity model or hierarchy.
"""

from typing import Callable, Dict, Iterable, List, Mapping, Optional

from engine.valuation.config import (
    DEFAULT_SIMILARITY_CONFIG,
    SimilarityConfig,
)

# A dimension scorer maps (subject, comparable) -> similarity in [0, 1] or None
# (None = not computable for this pair, skipped safely).
DimensionScorer = Callable[[Mapping, Mapping], Optional[float]]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _numeric_similarity(subject_value, comparable_value) -> Optional[float]:
    """1 minus the relative difference; None when either value is missing."""
    if not _is_number(subject_value) or not _is_number(comparable_value):
        return None
    scale = max(abs(subject_value), abs(comparable_value))
    if scale == 0:
        return 1.0
    return _clamp(1 - abs(subject_value - comparable_value) / scale)


def _ratio_similarity(subject_value, comparable_value) -> Optional[float]:
    """Smaller/larger ratio (good for areas); None when missing/non-positive."""
    if (not _is_number(subject_value) or not _is_number(comparable_value)
            or subject_value <= 0 or comparable_value <= 0):
        return None
    return _clamp(min(subject_value, comparable_value)
                  / max(subject_value, comparable_value))


def _categorical_similarity(subject_value, comparable_value) -> Optional[float]:
    """1.0 when the labels match (case-insensitive), else 0.0; None if missing."""
    if subject_value is None or comparable_value is None:
        return None
    return 1.0 if (str(subject_value).strip().lower()
                   == str(comparable_value).strip().lower()) else 0.0


# ─── Default, fully-replaceable dimension scorers ─────────────────────────────

def score_location(subject: Mapping, comparable: Mapping) -> Optional[float]:
    """Similarity of a 0..1 (or 0..100) location_score."""
    sub = subject.get("location_score")
    comp = comparable.get("location_score")
    if _is_number(sub) and sub > 1:
        sub = sub / 100.0
    if _is_number(comp) and comp > 1:
        comp = comp / 100.0
    return _numeric_similarity(sub, comp)


def score_area(subject: Mapping, comparable: Mapping) -> Optional[float]:
    return _ratio_similarity(subject.get("area"), comparable.get("area"))


def score_age(subject: Mapping, comparable: Mapping) -> Optional[float]:
    return _numeric_similarity(subject.get("age"), comparable.get("age"))


def score_use(subject: Mapping, comparable: Mapping) -> Optional[float]:
    return _categorical_similarity(subject.get("use"), comparable.get("use"))


def score_zoning(subject: Mapping, comparable: Mapping) -> Optional[float]:
    return _categorical_similarity(subject.get("zoning"), comparable.get("zoning"))


DEFAULT_DIMENSION_SCORERS: Dict[str, DimensionScorer] = {
    "location": score_location,
    "area": score_area,
    "age": score_age,
    "use": score_use,
    "zoning": score_zoning,
}


# ─── Resolution helpers ───────────────────────────────────────────────────────

def _resolve(config: Optional[SimilarityConfig]):
    config = config or DEFAULT_SIMILARITY_CONFIG
    scorers = dict(config.scorers) if config.scorers is not None \
        else dict(DEFAULT_DIMENSION_SCORERS)
    dimensions = tuple(config.dimensions) if config.dimensions is not None \
        else tuple(scorers.keys())
    return config, scorers, dimensions


def _aggregate(components: Mapping, weights: Mapping,
               aggregation) -> Optional[float]:
    """Combine per-dimension scores; built-in 'weighted_mean' or a callable."""
    available = {dim: score for dim, score in components.items()
                 if score is not None}
    if not available:
        return None
    if callable(aggregation):
        return aggregation(available, weights)
    if aggregation == "weighted_mean":
        total_w = sum(weights.get(dim, 1.0) for dim in available)
        if total_w <= 0:
            return None
        return sum(score * weights.get(dim, 1.0)
                   for dim, score in available.items()) / total_w
    raise ValueError(f"Unknown aggregation strategy: {aggregation!r}")


# ─── Public API ───────────────────────────────────────────────────────────────

def score_similarity(subject: Mapping, comparable: Mapping, *,
                     config: Optional[SimilarityConfig] = None) -> Dict:
    """Score one comparable's similarity to the subject.

    Returns the aggregate ``similarity`` (or None when nothing is computable),
    the per-dimension ``components``, the normalized ``weights_used`` over
    available dimensions, the list of ``missing_dimensions`` and an
    ``explanation``. No value or judgment is produced.
    """
    config, scorers, dimensions = _resolve(config)
    weights = dict(config.weights) if config.weights is not None else {}

    components: Dict[str, Optional[float]] = {}
    for dim in dimensions:
        scorer = scorers.get(dim)
        components[dim] = scorer(subject, comparable) if scorer else None

    missing = [dim for dim, score in components.items() if score is None]
    similarity = _aggregate(components, weights, config.aggregation)
    if config.rounding is not None and similarity is not None:
        similarity = round(similarity, config.rounding)

    available = [dim for dim, score in components.items() if score is not None]
    total_w = sum(weights.get(dim, 1.0) for dim in available) or 1.0
    weights_used = {dim: weights.get(dim, 1.0) / total_w for dim in available}

    explanation = [f"aggregation={config.aggregation if isinstance(config.aggregation, str) else 'custom'}",
                   f"similarity={similarity}"]
    for dim in dimensions:
        explanation.append(f"{dim}: score={components[dim]} "
                           f"weight={weights_used.get(dim)}")
    if missing:
        explanation.append(f"missing_dimensions={missing}")

    return {
        "comparable_id": comparable.get("comparable_id"),
        "similarity": similarity,
        "components": components,
        "weights_used": weights_used,
        "missing_dimensions": missing,
        "explanation": explanation,
    }


def rank_comparables(subject: Mapping, assessed: Iterable[Mapping], *,
                     config: Optional[SimilarityConfig] = None) -> List[Dict]:
    """Rank comparables by similarity (support only — no selection forced).

    Each entry in ``assessed`` carries a ``comparable``. Returns scored rows
    ordered by the ranking strategy (built-in 'similarity' descending, or a
    callable that receives and returns the list of scored rows). Comparables
    with no computable similarity sort last under the built-in strategy.
    """
    config, _, _ = _resolve(config)
    scored = [score_similarity(subject, entry["comparable"], config=config)
              for entry in assessed]

    if callable(config.ranking):
        ordered = list(config.ranking(scored))
    elif config.ranking == "similarity":
        ordered = sorted(
            scored,
            key=lambda row: (row["similarity"] is not None, row["similarity"]
                             if row["similarity"] is not None else 0.0),
            reverse=True,
        )
    else:
        raise ValueError(f"Unknown ranking strategy: {config.ranking!r}")

    for position, row in enumerate(ordered, start=1):
        row["rank"] = position
    return ordered


def _reliability_norm(included: List[Mapping]) -> Dict:
    total = sum(e["assessment"].get("reliability_score", 0.0) for e in included)
    if total <= 0:
        count = len(included)
        equal = (1.0 / count) if count else 0.0
        return {e["comparable"]["comparable_id"]: equal for e in included}
    return {e["comparable"]["comparable_id"]:
            e["assessment"].get("reliability_score", 0.0) / total
            for e in included}


def similarity_weights(subject: Mapping, assessed: Iterable[Mapping], *,
                       config: Optional[SimilarityConfig] = None) -> Dict:
    """Suggest ``{comparable_id: weight}`` from similarity (a suggestion only).

    Only comparables whose ``inclusion_decision`` is in
    ``config.included_decisions`` are weighted, so a 'review' comparable is never
    auto-included. By default weights are pure similarity, normalized to sum to
    1. Reliability is blended *only* when ``config.blend_reliability`` is set,
    in which case ``weight = (1-b)*similarity_norm + b*reliability_norm`` and the
    blend is reported by ``confidence_contribution``.
    """
    config, _, _ = _resolve(config)
    included = [e for e in assessed
                if e["assessment"].get("inclusion_decision")
                in config.included_decisions]
    if not included:
        return {}

    sims = {e["comparable"]["comparable_id"]:
            (score_similarity(subject, e["comparable"], config=config)["similarity"] or 0.0)
            for e in included}
    sim_total = sum(sims.values())
    if sim_total <= 0:
        count = len(included)
        sim_norm = {cid: (1.0 / count) for cid in sims}
    else:
        sim_norm = {cid: value / sim_total for cid, value in sims.items()}

    blend = config.blend_reliability
    if blend is None:
        weights = sim_norm
    else:
        blend = _clamp(blend)
        rel_norm = _reliability_norm(included)
        combined = {cid: (1 - blend) * sim_norm.get(cid, 0.0)
                    + blend * rel_norm.get(cid, 0.0) for cid in sims}
        combined_total = sum(combined.values()) or 1.0
        weights = {cid: value / combined_total for cid, value in combined.items()}

    if config.rounding is not None:
        weights = {cid: round(value, config.rounding)
                   for cid, value in weights.items()}
    return weights


def confidence_contribution(assessed: Iterable[Mapping], weights: Mapping, *,
                            config: Optional[SimilarityConfig] = None) -> Dict:
    """Analyse how each weighted comparable contributes to overall confidence.

    Contribution = weight * reliability_score. Reports the weighting ``mode``
    (pure similarity vs explicit reliability blend) so any blend is transparent.
    Support only — no value or adopted figure.
    """
    config, _, _ = _resolve(config)
    by_id = {e["comparable"]["comparable_id"]: e for e in assessed}

    mode = ("pure_similarity" if config.blend_reliability is None
            else f"blended(reliability={_clamp(config.blend_reliability)})")

    contributions: Dict[str, Dict] = {}
    overall = 0.0
    for comparable_id, weight in weights.items():
        entry = by_id.get(comparable_id, {})
        assessment = entry.get("assessment", {})
        reliability = assessment.get("reliability_score", 0.0)
        contribution = weight * reliability
        overall += contribution
        contributions[comparable_id] = {
            "weight": weight,
            "reliability_score": reliability,
            "confidence_level": assessment.get("confidence_level"),
            "contribution": contribution,
        }

    if config.rounding is not None:
        overall = round(overall, config.rounding)
        for row in contributions.values():
            row["contribution"] = round(row["contribution"], config.rounding)

    return {
        "mode": mode,
        "overall_confidence_index": overall,
        "contributions": contributions,
        "explanation": [f"weighting_mode={mode}",
                        f"overall_confidence_index={overall}"],
    }


def as_weighting_strategy(subject: Mapping, *,
                          config: Optional[SimilarityConfig] = None) -> Callable:
    """Return a callable suitable for ``ComparableApproachConfig.weighting``.

    The returned callable takes the ``assessed`` list and returns
    ``{comparable_id: weight}`` from ``similarity_weights`` — so similarity can
    drive the existing comparable-approach calculation with no change to it.
    """
    def strategy(assessed):
        return similarity_weights(subject, assessed, config=config)
    return strategy
