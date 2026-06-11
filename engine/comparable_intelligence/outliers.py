"""CIL-3 — Outlier detection (classify only, advisory).

Identifies statistical outliers (tiered IQR / z-score / MAD fences, or custom
callables) and professional outliers (gross adjustment burden above a
configurable cap) across a comparable set's metric values — typically the
adjusted unit rates already produced by the comparable approach.

Classification is advisory: ``none``, ``warning``, ``review_required`` or
``exclude_candidate`` (mapping configurable). Nothing is ever removed.
``auto_exclude`` defaults to False, and even when explicitly enabled it only
lists candidate ids for human confirmation — the input set is never mutated.
Small samples are reported as not statistically assessable rather than guessed.

Every output uses the tri-part envelope (result / explanation /
assumptions_used) and carries no value, score-verdict or admission state.
"""

from statistics import mean, median, pstdev, quantiles
from typing import Dict, List, Mapping, Optional, Tuple

from engine.comparable_intelligence import config as cfg
from engine.comparable_intelligence.common import build_envelope, is_number
from engine.valuation.comparable_approach import parse_adjustment_value


# ─── Tier helper ───────────────────────────────────────────────────────────────

def _tier(measure: float, fences: Tuple[float, float, float]) -> int:
    """Severity 0..3 from a deviation measure against tiered fences."""
    severity = 0
    for index, fence in enumerate(fences, start=1):
        if measure > fence:
            severity = index
    return severity


# ─── Built-in statistical methods ──────────────────────────────────────────────

def _method_iqr(values_by_id: Mapping, config: cfg.OutlierConfig) -> Dict:
    """Tukey-style tiered IQR fences; needs >= 4 observations."""
    values = list(values_by_id.values())
    if len(values) < 4:
        return {"_note": f"iqr not assessable with n={len(values)} (<4)"}
    q1, _, q3 = quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    if iqr == 0:
        return {"_note": "iqr is zero (identical quartiles); not assessable"}
    out = {}
    for cid, value in values_by_id.items():
        distance = max(q1 - value, value - q3, 0.0) / iqr
        out[cid] = _tier(distance, config.iqr_fences)
    return out


def _method_zscore(values_by_id: Mapping, config: cfg.OutlierConfig) -> Dict:
    """Tiered standard-score fences; needs >= 3 observations and spread."""
    values = list(values_by_id.values())
    if len(values) < 3:
        return {"_note": f"zscore not assessable with n={len(values)} (<3)"}
    centre = mean(values)
    spread = pstdev(values)
    if spread == 0:
        return {"_note": "zscore spread is zero; not assessable"}
    return {cid: _tier(abs(value - centre) / spread, config.zscore_fences)
            for cid, value in values_by_id.items()}


def _method_mad(values_by_id: Mapping, config: cfg.OutlierConfig) -> Dict:
    """Tiered modified z-score (median absolute deviation) fences."""
    values = list(values_by_id.values())
    if len(values) < 3:
        return {"_note": f"mad not assessable with n={len(values)} (<3)"}
    centre = median(values)
    mad = median(abs(value - centre) for value in values)
    if mad == 0:
        return {"_note": "median absolute deviation is zero; not assessable"}
    return {cid: _tier(0.6745 * abs(value - centre) / mad, config.mad_fences)
            for cid, value in values_by_id.items()}


BUILTIN_METHODS = {"iqr": _method_iqr, "zscore": _method_zscore,
                   "mad": _method_mad}


# ─── Professional rule ─────────────────────────────────────────────────────────

def gross_adjustment_burden(comparable: Mapping) -> Optional[float]:
    """Gross relative adjustment from machine-readable adjustments, or None."""
    base = comparable.get("unit_rate")
    magnitudes: List[float] = []
    for adjustment in comparable.get("adjustments", []) or []:
        parsed = parse_adjustment_value(adjustment)
        if parsed is None:
            continue
        value_type, value = parsed["type"], parsed["value"]
        if value_type == "percentage":
            magnitudes.append(abs(value) / 100.0)
        elif value_type == "range_percentage":
            magnitudes.append((abs(value["low"]) + abs(value["high"])) / 200.0)
        elif is_number(base) and base > 0:
            if value_type == "absolute":
                magnitudes.append(abs(value) / base)
            else:  # range_absolute
                magnitudes.append(
                    (abs(value["low"]) + abs(value["high"])) / (2.0 * base))
    if not magnitudes:
        return None
    return sum(magnitudes)


# ─── Internal pipeline steps ───────────────────────────────────────────────────

def _run_methods(methods, values_by_id: Mapping,
                 config: cfg.OutlierConfig) -> Tuple[Dict, List[str]]:
    """Run each configured method; collect per-id severities and any notes."""
    method_results: Dict[str, Dict] = {}
    notes: List[str] = []
    for method in methods:
        if callable(method):
            name = getattr(method, "__name__", "custom")
            outcome = method(values_by_id, config)
        else:
            name = method
            builtin = BUILTIN_METHODS.get(method)
            if builtin is None:
                raise ValueError(f"Unknown outlier method: {method!r}")
            outcome = builtin(values_by_id, config)
        if "_note" in outcome:
            notes.append(outcome["_note"])
            outcome = {k: v for k, v in outcome.items() if k != "_note"}
        method_results[name] = outcome
    return method_results, notes


def _classify_item(entry: Mapping, method_results: Mapping, class_map: Mapping,
                   config: cfg.OutlierConfig) -> Dict:
    """Combine statistical + professional severities into one classification."""
    cid = entry["comparable_id"]
    severities = {name: result.get(cid, 0)
                  for name, result in method_results.items()}
    statistical = max(severities.values(), default=0)

    professional = None
    burden = None
    if config.professional_burden_cap is not None \
            and entry.get("comparable") is not None:
        burden = gross_adjustment_burden(entry["comparable"])
        if burden is not None and burden > config.professional_burden_cap:
            professional = config.professional_severity

    severity = max(statistical, professional or 0)
    classification = class_map.get(severity, "none") if severity else "none"

    reasons = [f"{name}: severity {level}"
               for name, level in severities.items() if level]
    if professional:
        reasons.append(f"professional: gross adjustment burden "
                       f"{round(burden, 4)} exceeds cap "
                       f"{config.professional_burden_cap}")

    return {"classification": classification, "severity": severity,
            "method_severities": severities,
            "adjustment_burden": (round(burden, 4) if burden is not None
                                  else None),
            "reasons": reasons}


# ─── Public API ────────────────────────────────────────────────────────────────

def classify_outliers(entries: List[Mapping], *,
                      config: Optional[cfg.OutlierConfig] = None) -> Dict:
    """Classify outliers across a comparable set (advisory; never removes).

    Each entry is ``{"comparable_id", "value", "comparable"?}`` — ``value`` is
    the metric tested (typically the adjusted unit rate) and the optional
    ``comparable`` enables the professional adjustment-burden rule. Returns the
    tri-part envelope whose ``result.items`` maps every input id to its
    classification, per-method severities and reasons; ``result.summary``
    counts classes. ``exclude_candidates`` is informational; with
    ``auto_exclude`` False (default) it is empty.
    """
    config = config or cfg.DEFAULT_OUTLIER_CONFIG
    entries = list(entries)
    class_map = dict(config.class_by_severity
                     if config.class_by_severity is not None
                     else cfg.DEFAULT_OUTLIER_CLASS_BY_SEVERITY)
    methods = config.methods if config.methods is not None \
        else cfg.DEFAULT_OUTLIER_METHODS

    values_by_id = {e["comparable_id"]: float(e["value"]) for e in entries
                    if is_number(e.get("value"))}
    skipped = [e.get("comparable_id") for e in entries
               if not is_number(e.get("value"))]

    method_results, notes = _run_methods(methods, values_by_id, config)

    items: Dict = {}
    for entry in entries:
        items[entry["comparable_id"]] = _classify_item(
            entry, method_results, class_map, config)

    summary: Dict[str, int] = {}
    for item in items.values():
        summary[item["classification"]] = \
            summary.get(item["classification"], 0) + 1

    exclude_candidates = [cid for cid, item in items.items()
                          if item["classification"] == "exclude_candidate"] \
        if config.auto_exclude else []

    explanation = [
        "Outlier detection is advisory classification only — no comparable is "
        "removed, and any exclusion is a human decision.",
        f"assessed {len(values_by_id)} of {len(entries)} comparables "
        f"with methods {[getattr(m, '__name__', m) for m in methods]}",
        f"summary: {summary}",
    ]
    explanation.extend(f"note: {note}" for note in notes)
    if skipped:
        explanation.append(f"skipped (non-numeric value): {skipped}")
    for cid, item in items.items():
        if item["classification"] != "none":
            explanation.append(
                f"{cid}: {item['classification']} — {'; '.join(item['reasons'])}")
    if config.auto_exclude:
        explanation.append(
            f"auto_exclude is enabled by configuration: candidates "
            f"{exclude_candidates} are flagged for human confirmation only")

    assumptions_used = {
        "methods": [getattr(m, "__name__", m) for m in methods],
        "iqr_fences": list(config.iqr_fences),
        "zscore_fences": list(config.zscore_fences),
        "mad_fences": list(config.mad_fences),
        "class_by_severity": {str(k): v for k, v in class_map.items()},
        "professional_burden_cap": config.professional_burden_cap,
        "professional_severity": config.professional_severity,
        "auto_exclude": config.auto_exclude,
        "quartile_method": "inclusive",
    }

    return build_envelope(
        result={"items": items, "summary": summary,
                "exclude_candidates": exclude_candidates,
                "not_assessable_notes": notes, "skipped": skipped},
        explanation=explanation,
        assumptions_used=assumptions_used,
        basis=("outlier classification — advisory warning/review/"
               "exclude-candidate flags; not an exclusion, not an admission "
               "decision and not a value"),
    )
