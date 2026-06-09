"""CIL-1 — Extended evidence-quality dimensions.

Adds four *numeric* quality factor scorers that plug directly into the existing
``engine.evidence.scoring.score_evidence`` via its ``factor_scorers`` argument:

* ``data_completeness``      — fraction of configurable required fields present;
* ``transaction_reliability``— arms-length / verified / sale-condition signals;
* ``market_relevance``       — categorical alignment to the subject;
* ``adjustment_burden``      — inverse of the gross relative adjustment applied.

Scoring is a *supporting* signal only (explainability-first): every output is an
advisory envelope whose reasoning is the headline and whose numbers are nested,
indicative and never determinative. Similarity is deliberately NOT a quality
factor — similarity and reliability are kept distinct and combined only later in
ranking (CIL-6). This module makes no admission/governance decision and produces
no value.
"""

from typing import Dict, Mapping, Optional

from engine.comparable_intelligence import config as cfg
from engine.comparable_intelligence.common import build_envelope, clamp, is_number
from engine.evidence import config as ecfg
from engine.evidence.scoring import DEFAULT_FACTOR_SCORERS, score_evidence
from engine.valuation.comparable_approach import parse_adjustment_value


# ─── Extended factor scorers (signature-compatible with evidence.scoring) ──────

def score_data_completeness(comparable: Mapping, context: Mapping) -> float:
    """Fraction of the configurable ``required_fields`` present and non-empty."""
    required = context.get("required_fields", cfg.DEFAULT_REQUIRED_FIELDS)
    if not required:
        return context.get("neutral_score", ecfg.DEFAULT_NEUTRAL_SCORE)
    present = sum(1 for field in required
                  if comparable.get(field) not in (None, ""))
    return clamp(present / len(required))


def score_transaction_reliability(comparable: Mapping, context: Mapping) -> float:
    """Blend available transaction signals; neutral when none are present.

    Each of arms-length, verified and sale-conditions contributes only when the
    comparable carries it, so a missing signal is *not computable* rather than a
    penalty. The mean of the available signals is returned.
    """
    neutral = context.get("neutral_score", ecfg.DEFAULT_NEUTRAL_SCORE)
    signals = []

    arms_length = comparable.get("arms_length")
    if isinstance(arms_length, bool):
        signals.append(1.0 if arms_length else 0.0)

    verified = comparable.get("verified")
    if isinstance(verified, bool):
        signals.append(1.0 if verified
                       else context.get("unverified_score",
                                        cfg.DEFAULT_UNVERIFIED_SCORE))

    conditions = comparable.get("sale_conditions")
    if conditions is not None:
        condition_map = context.get("sale_condition_map",
                                    cfg.DEFAULT_SALE_CONDITION_MAP)
        signals.append(clamp(condition_map.get(
            str(conditions).strip().lower(), neutral)))

    if not signals:
        return neutral
    return clamp(sum(signals) / len(signals))


def score_market_relevance(comparable: Mapping, context: Mapping) -> float:
    """Categorical alignment to the subject over configurable attributes.

    Each attribute is compared against ``context['subject_<attr>']``; attributes
    missing on either side are skipped. Returns the fraction matching, or the
    neutral score when nothing is comparable. Time/recency is intentionally
    excluded here — it is covered by the separate recency factor.
    """
    attrs = context.get("market_relevance_attrs",
                        cfg.DEFAULT_MARKET_RELEVANCE_ATTRS)
    neutral = context.get("neutral_score", ecfg.DEFAULT_NEUTRAL_SCORE)
    matches = []
    for attr in attrs:
        subject_value = context.get(f"subject_{attr}")
        comp_value = comparable.get(attr)
        if subject_value is None or comp_value is None:
            continue
        matches.append(1.0 if str(subject_value).strip().lower()
                       == str(comp_value).strip().lower() else 0.0)
    if not matches:
        return neutral
    return clamp(sum(matches) / len(matches))


def _relative_magnitude(adj_value: Mapping, base) -> Optional[float]:
    """Relative size of one normalised adjustment, or None when uncomputable."""
    value_type = adj_value["type"]
    value = adj_value["value"]
    if value_type == "percentage":
        return abs(value) / 100.0
    if value_type == "absolute":
        if is_number(base) and base > 0:
            return abs(value) / base
        return None
    midpoint = (abs(value["low"]) + abs(value["high"])) / 2.0
    if value_type == "range_percentage":
        return midpoint / 100.0
    if is_number(base) and base > 0:
        return midpoint / base
    return None


def score_adjustment_burden(comparable: Mapping, context: Mapping) -> float:
    """Inverse of the gross relative adjustment; neutral when none computable.

    Reads only the machine-readable ``adjustment_value`` of each adjustment (via
    the existing parser). A heavier total adjustment yields a lower score; the
    cap at which the score reaches 0 is configurable.
    """
    neutral = context.get("neutral_score", ecfg.DEFAULT_NEUTRAL_SCORE)
    cap = context.get("adjustment_burden_cap", cfg.DEFAULT_ADJUSTMENT_BURDEN_CAP)
    base = comparable.get("unit_rate")

    magnitudes = []
    for adjustment in comparable.get("adjustments", []) or []:
        parsed = parse_adjustment_value(adjustment)
        if parsed is None:
            continue
        magnitude = _relative_magnitude(parsed, base)
        if magnitude is not None:
            magnitudes.append(magnitude)

    if not magnitudes or cap <= 0:
        return neutral
    return clamp(1.0 - sum(magnitudes) / cap)


EXTENDED_FACTOR_SCORERS: Dict = {
    "data_completeness": score_data_completeness,
    "transaction_reliability": score_transaction_reliability,
    "market_relevance": score_market_relevance,
    "adjustment_burden": score_adjustment_burden,
}

# Base evidence factors plus the CIL-1 extensions.
ALL_FACTOR_SCORERS: Dict = {**DEFAULT_FACTOR_SCORERS, **EXTENDED_FACTOR_SCORERS}


# ─── Public API ────────────────────────────────────────────────────────────────

def _direction(score: float, neutral: float) -> str:
    if score > neutral:
        return "supports"
    if score < neutral:
        return "detracts"
    return "neutral"


def score_quality(comparable: Mapping, *,
                  config: Optional[cfg.QualityConfig] = None,
                  context: Optional[Mapping] = None) -> Dict:
    """Score one comparable's evidence quality as an advisory envelope.

    Returns the tri-part envelope ``{result, explanation, assumptions_used,
    advisory, basis}``: ``result`` holds the (subordinate) numeric metrics,
    ``explanation`` leads with reasoning, and ``assumptions_used`` records the
    weights, strategy, bands and per-factor tunables that produced it — so the
    score is reproducible and never mistaken for a determinative judgment.
    """
    config = config or cfg.DEFAULT_QUALITY_CONFIG
    neutral = ecfg.DEFAULT_NEUTRAL_SCORE
    effective_context = {**(config.context_defaults or {}), **(context or {})}

    scorers = dict(config.factor_scorers) if config.factor_scorers \
        else dict(ALL_FACTOR_SCORERS)
    weights = dict(config.weights) if config.weights \
        else {**ecfg.DEFAULT_WEIGHTS, **cfg.EXTENDED_DEFAULT_WEIGHTS}
    bands = dict(config.confidence_bands) if config.confidence_bands \
        else dict(ecfg.DEFAULT_CONFIDENCE_BANDS)

    scored = score_evidence(
        comparable,
        weights=weights,
        factor_scorers=scorers,
        context=effective_context,
        strategy=config.strategy,
        confidence_bands=bands,
    )
    factor_scores = scored["factor_scores"]

    explanation = [
        "Evidence quality is a supporting indicator only; professional "
        "judgment remains the final authority and no value is implied.",
        f"reliability_score={scored['reliability_score']} (indicative, not "
        f"determinative); confidence_level={scored['confidence_level']}",
    ]
    for name in scorers:
        score = factor_scores.get(name)
        if score is None:
            continue
        explanation.append(f"{name}: {score} (weight {weights.get(name)}) — "
                           f"{_direction(score, neutral)}")

    assumptions_used = {
        "factors": list(scorers.keys()),
        "weights": weights,
        "strategy": scored["strategy"],
        "confidence_bands": bands,
        "required_fields": list(effective_context.get(
            "required_fields", cfg.DEFAULT_REQUIRED_FIELDS)),
        "market_relevance_attrs": list(effective_context.get(
            "market_relevance_attrs", cfg.DEFAULT_MARKET_RELEVANCE_ATTRS)),
        "adjustment_burden_cap": effective_context.get(
            "adjustment_burden_cap", cfg.DEFAULT_ADJUSTMENT_BURDEN_CAP),
        "sale_condition_map": dict(effective_context.get(
            "sale_condition_map", cfg.DEFAULT_SALE_CONDITION_MAP)),
        "neutral_score": neutral,
    }

    result = {
        "comparable_id": comparable.get("comparable_id"),
        "reliability_score": scored["reliability_score"],
        "factor_scores": factor_scores,
        "confidence_level": scored["confidence_level"],
        "strategy": scored["strategy"],
    }

    return build_envelope(
        result=result,
        explanation=explanation,
        assumptions_used=assumptions_used,
        basis=("evidence quality score — supporting/indicative, not "
               "determinative; not an admission decision and not a value"),
    )
