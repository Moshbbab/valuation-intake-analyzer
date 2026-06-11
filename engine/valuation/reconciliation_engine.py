"""Reconciliation Engine — approach comparison + agreement + suggested range.

Composes the existing cross-approach reconciliation (range + weighted
indication) and dispersion metrics into one engine that compares approach
indications, scores their agreement, and suggests a valuation range.

It explicitly does NOT adopt a final value: the reconciled figure is a
*suggestion* for the appraiser, who performs the final reconciliation. The
agreement score is the inverse of a dispersion measure, surfaced as a number,
not a verdict.
"""

from typing import Dict, Iterable, List, Mapping, Optional

from engine.valuation.agreement import approach_dispersion
from engine.valuation.config import (
    DEFAULT_RECONCILIATION_ENGINE_CONFIG,
    ReconciliationEngineConfig,
)
from engine.valuation.reconciliation import reconcile


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _round(value, config: ReconciliationEngineConfig):
    if config.rounding is not None and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        return round(value, config.rounding)
    return value


def reconcile_approaches(indications: Iterable[Mapping], *,
                         config: Optional[ReconciliationEngineConfig] = None,
                         recon_config=None) -> Dict:
    """Compare valuation approaches and suggest a range (no final adoption).

    ``indications`` is the reconciliation contract — a list of
    ``{approach, value? , range?, weight?}``. Returns the per-approach
    ``comparison`` (central, range, weight, deviation from the weighted
    indication), ``dispersion`` metrics, a 0..1 ``agreement_score``, and a
    ``suggested_range`` ({low, high, weighted_indication}). No final value is
    adopted.
    """
    config = config or DEFAULT_RECONCILIATION_ENGINE_CONFIG
    indications = list(indications)

    recon = reconcile(indications, config=recon_config)
    dispersion = approach_dispersion(indications)

    if config.agreement_basis not in ("coefficient_of_variation", "spread_pct"):
        raise ValueError(f"Unknown agreement_basis: {config.agreement_basis!r}")
    measure = dispersion.get(config.agreement_basis)
    agreement_score = _clamp(1.0 - measure) if measure is not None else None

    deviations = dispersion["deviations"]
    comparison: List[Dict] = []
    for row in recon["approaches"]:
        approach = row["approach"]
        comparison.append({
            "approach": approach,
            "central": row["central"],
            "low": row["low"],
            "high": row["high"],
            "weight": row["weight"],
            "deviation_from_weighted": _round(deviations.get(approach), config),
        })

    suggested_range = {
        "low": recon["reconciled_range"]["low"],
        "high": recon["reconciled_range"]["high"],
        "weighted_indication": recon["weighted_indication"],
    }

    return {
        "comparison": comparison,
        "dispersion": dispersion,
        "agreement_score": _round(agreement_score, config),
        "agreement_basis": config.agreement_basis,
        "suggested_range": suggested_range,
        "deliverable": "suggested valuation range with approach agreement",
        "basis": ("reconciliation engine — approach comparison, dispersion, "
                  "agreement score and a SUGGESTED range; the appraiser adopts "
                  "the final value, which is not produced here"),
    }
