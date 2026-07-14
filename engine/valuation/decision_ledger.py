"""Evidence Decision Ledger — the single policy seam (Path-3 restructuring).

The ratified diagnosis found one root cause behind the critical findings:
policy decisions (include/exclude, weights, thresholds) were scattered inside
the calculation engines and duplicated across subsystems. The ledger fixes the
root: ALL evidence-set policy is resolved in ONE explicit, human-ratifiable
``DecisionRecord``; the calculation engines then run as pure functions over
(evidence, decision) and perform no policy of their own.

A ``DecisionRecord`` carries: the included/excluded ids each with ``decided_by``
(default / auto-policy / manual override) and a reason; the weights; the outlier
flags (signals only — flagged evidence stays included unless a human or an
explicitly configured policy excludes it); a mandatory gate (record count,
outlier count, warnings); and an ``assumptions_used`` snapshot for
reproducibility. Every decision transition can be written to the SHA-256
audit chain.
"""

from typing import Dict, Iterable, List, Mapping, Optional

from engine.audit.config import UNRESTRICTED_CONFIG
from engine.audit.recorder import record_event
from engine.valuation._rate_support import detect_outliers


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_decision_record(entries: Iterable[Mapping], *,
                          outlier_method="iqr", iqr_k: float = 1.5,
                          outlier_action: str = "flag",
                          overrides: Optional[Mapping] = None,
                          weights: Optional[Mapping] = None,
                          audit_store=None, audit_config=None) -> Dict:
    """Build the single evidence decision record for one calculation run.

    ``entries`` is ``[{id, value, weight?}]`` (typically adjusted rates).
    Outliers are DETECTED and FLAGGED; they are excluded only when
    ``outlier_action="exclude"`` is explicitly chosen or a documented manual
    override says so. ``overrides`` is ``{force_include, force_exclude,
    rationale, actor}`` and always wins, with the automatic treatment retained.
    ``weights`` optionally overrides per-id weights (appraiser judgment).
    """
    entries = list(entries)
    items = [{"id": e["id"], "value": float(e["value"]),
              "weight": float(e.get("weight", 1.0))}
             for e in entries if _is_number(e.get("value"))]
    skipped = [e.get("id") for e in entries if not _is_number(e.get("value"))]

    flagged, notes = detect_outliers(items, outlier_method, iqr_k)
    overrides = overrides or {}
    force_include = set(overrides.get("force_include", ()))
    force_exclude = set(overrides.get("force_exclude", ()))

    warnings: List[str] = [f"note: {n}" for n in notes]
    if flagged and outlier_action == "flag":
        warnings.append(f"{len(flagged)} outlier(s) flagged, NOT excluded: "
                        f"{flagged} — exclusion is the appraiser's decision")

    decisions: List[Dict] = []
    weight_map = dict(weights or {})
    for item in items:
        cid = item["id"]
        if cid in force_exclude:
            status, decided_by, reason = ("excluded", "manual_override",
                                          overrides.get("rationale"))
        elif cid in force_include:
            status, decided_by, reason = ("included", "manual_override",
                                          overrides.get("rationale"))
        elif cid in flagged and outlier_action == "exclude":
            status, decided_by = "excluded", "configured_policy"
            reason = f"outlier beyond IQR fence (k={iqr_k}); excluded by " \
                     f"explicit outlier_action='exclude'"
        else:
            status, decided_by = "included", "default"
            reason = ("outlier flag raised — retained pending appraiser "
                      "decision" if cid in flagged else "no objection")
        decisions.append({"id": cid, "status": status,
                          "decided_by": decided_by, "reason": reason,
                          "outlier_flag": cid in flagged,
                          "value": item["value"],
                          "weight": float(weight_map.get(cid, item["weight"]))})

    excluded_ids = [d["id"] for d in decisions if d["status"] == "excluded"]
    if excluded_ids and outlier_action == "exclude":
        warnings.append(f"{len(excluded_ids)} item(s) excluded by explicit "
                        f"configuration: {excluded_ids}")
    if force_include or force_exclude:
        warnings.append(
            f"manual override applied by {overrides.get('actor')!r}: "
            f"+{sorted(force_include)} -{sorted(force_exclude)} "
            f"(rationale: {overrides.get('rationale')!r})")
    included = [d for d in decisions if d["status"] == "included"]
    if not included:
        warnings.append("ZERO OUTPUT: no included evidence after decisions — "
                        "review exclusions/overrides before relying on this")

    record = {
        "decisions": decisions,
        "included_ids": [d["id"] for d in included],
        "excluded_ids": excluded_ids,
        "weights": {d["id"]: d["weight"] for d in included},
        "outlier_flags": flagged,
        "skipped": skipped,
        "gate": {"record_count": len(entries),
                 "included_count": len(included),
                 "outlier_count": len(flagged),
                 "warnings": warnings,
                 "warning_count": len(warnings)},
        "assumptions_used": {
            "outlier_method": getattr(outlier_method, "__name__",
                                      outlier_method),
            "outlier_action": outlier_action,
            "iqr_k": iqr_k,
            "overrides": dict(overrides) if overrides else {},
            "weight_overrides": weight_map,
        },
        "basis": ("evidence decision record — the single policy seam; "
                  "calculation engines apply it verbatim and decide nothing"),
    }

    if audit_store is not None:
        record_event(
            "evidence", None, "decision_record_built",
            before=None,
            after={"included": record["included_ids"],
                   "excluded": record["excluded_ids"],
                   "outlier_flags": flagged,
                   "assumptions_used": record["assumptions_used"]},
            rationale=overrides.get("rationale")
            or "evidence decision record for calculation run",
            actor=overrides.get("actor"),
            store=audit_store, config=audit_config or UNRESTRICTED_CONFIG)

    return record


def apply_decision(entries: Iterable[Mapping], decision: Mapping) -> List[Dict]:
    """Return the calculation-ready items dictated by a decision record.

    Pure selection: engines receiving this list perform no policy. Ids absent
    from the decision record are dropped (they were never ratified).
    """
    weights = decision.get("weights", {})
    included = set(decision.get("included_ids", ()))
    return [{"id": e["id"], "value": float(e["value"]),
             "weight": float(weights.get(e["id"], e.get("weight", 1.0)))}
            for e in entries
            if e.get("id") in included and _is_number(e.get("value"))]
