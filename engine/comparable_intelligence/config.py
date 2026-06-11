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


# ─── CIL-2: Evidence Quality Governance defaults ──────────────────────────────
# Governance establishes *appropriateness/eligibility* of evidence — distinct
# from numeric quality scoring (CIL-1) and from admission (later). Every mapping
# below is a DEFAULT policy expressed as data: fully replaceable, never a
# hard-coded rule in logic, and never a numeric sufficiency/count threshold.

# Raw source label (case-insensitive) -> source class. Unknown labels map to
# ``DEFAULT_UNKNOWN_SOURCE_CLASS``.
DEFAULT_SOURCE_TAXONOMY: Dict[str, str] = {
    "registry": "registry",
    "land_registry": "registry",
    "official": "official_record",
    "official_record": "official_record",
    "valuer": "valuer_confirmed",
    "valuer_confirmed": "valuer_confirmed",
    "broker": "broker_supplied",
    "broker_supplied": "broker_supplied",
    "agent": "broker_supplied",
    "listing": "advertised",
    "asking": "advertised",
    "advertised": "advertised",
    "inferred": "inferred",
    "anecdotal": "anecdotal",
}
DEFAULT_UNKNOWN_SOURCE_CLASS: str = "unknown"

# Source class -> evidence directness.
DEFAULT_EVIDENCE_TYPE_MAP: Dict[str, str] = {
    "registry": "direct",
    "official_record": "direct",
    "valuer_confirmed": "direct",
    "broker_supplied": "indirect",
    "advertised": "indirect",
    "unknown": "indirect",
    "inferred": "inferred",
    "anecdotal": "inferred",
}

# Default reliability hierarchy (most appropriate first). This is governance
# POLICY expressed as ordered data — callers may replace it completely; nothing
# in the logic depends on this particular order.
DEFAULT_RELIABILITY_HIERARCHY: Tuple[str, ...] = (
    "registry",
    "official_record",
    "valuer_confirmed",
    "broker_supplied",
    "advertised",
    "inferred",
    "anecdotal",
)

# Source class -> default admissibility role (before weak-evidence handling).
# Per approved decision: advertised/asking and inferred/anecdotal evidence is
# corroborating-only by default — never "supporting".
DEFAULT_ADMISSIBILITY_BY_CLASS: Dict[str, str] = {
    "registry": "primary",
    "official_record": "primary",
    "valuer_confirmed": "supporting",
    "broker_supplied": "supporting",
    "advertised": "corroborating_only",
    "inferred": "corroborating_only",
    "anecdotal": "corroborating_only",
    "unknown": "corroborating_only",
}

# Ordering of admissibility roles from strongest to weakest; downgrades move
# rightward only. Extensible — supply your own order with custom roles.
DEFAULT_ADMISSIBILITY_ORDER: Tuple[str, ...] = (
    "primary", "supporting", "corroborating_only", "inadmissible",
)

# Source classes that always require verification by default (decision: the
# advertised/asking family), in addition to any unverified/unverifiable status.
DEFAULT_VERIFICATION_REQUIRED_CLASSES: Tuple[str, ...] = (
    "advertised", "inferred", "anecdotal", "unknown",
)

# Role a weak-evidence downgrade falls to (at most) by default.
DEFAULT_WEAK_EVIDENCE_MAX_ROLE: str = "corroborating_only"


@dataclass(frozen=True)
class GovernanceConfig:
    """Configuration injected into ``governance`` functions.

    Every field is optional and falls back to the module defaults above.
    ``admissibility_policy`` may be a callable ``(classification, verification,
    config) -> {admissibility, requires_verification, caveats}`` replacing the
    default policy entirely; ``verification_resolver`` may be a callable
    ``(comparable) -> {status, method, by, on}``. ``weak_evidence_rules`` maps
    rule name -> callable ``(comparable, classification, verification) ->
    Optional[{caveats, requires_verification, max_role}]``. No numeric
    sufficiency threshold and no admission state exists here.
    """

    source_taxonomy: Optional[Mapping] = None
    unknown_source_class: str = DEFAULT_UNKNOWN_SOURCE_CLASS
    evidence_type_map: Optional[Mapping] = None
    reliability_hierarchy: Optional[Tuple[str, ...]] = None
    admissibility_by_class: Optional[Mapping] = None
    admissibility_order: Optional[Tuple[str, ...]] = None
    admissibility_policy: Optional[Callable] = None
    verification_required_classes: Optional[Tuple[str, ...]] = None
    verification_resolver: Optional[Callable] = None
    weak_evidence_rules: Optional[Mapping] = None
    weak_evidence_max_role: str = DEFAULT_WEAK_EVIDENCE_MAX_ROLE
    required_fields: Tuple[str, ...] = DEFAULT_REQUIRED_FIELDS


# Convenience default instance.
DEFAULT_GOVERNANCE_CONFIG = GovernanceConfig()


# ─── CIL-3: Outlier detection defaults ────────────────────────────────────────
# Outlier detection CLASSIFIES only — it never removes a comparable. Severity
# tiers map to advisory classes via ``DEFAULT_OUTLIER_CLASS_BY_SEVERITY`` and
# ``auto_exclude`` is False by default (and even when enabled it only flags ids
# for human confirmation).

# Statistical methods applied by default; "zscore" and "mad" are also built in,
# and any entry may be a callable (values_by_id, config) -> {id: severity 0..3}.
DEFAULT_OUTLIER_METHODS: Tuple[str, ...] = ("iqr",)

# Tiered fences per built-in method: (mild, severe, extreme) -> severity 1/2/3.
DEFAULT_IQR_FENCES: Tuple[float, float, float] = (1.5, 3.0, 4.5)
DEFAULT_ZSCORE_FENCES: Tuple[float, float, float] = (2.5, 3.5, 4.5)
DEFAULT_MAD_FENCES: Tuple[float, float, float] = (3.0, 4.5, 6.0)

# Severity (max across methods) -> advisory outlier class. 0 -> "none".
DEFAULT_OUTLIER_CLASS_BY_SEVERITY: Dict[int, str] = {
    1: "warning",
    2: "review_required",
    3: "exclude_candidate",
}

# Professional outlier rule: gross relative adjustment above this cap marks the
# comparable severity-2 (review_required) by default. None disables the rule.
DEFAULT_PROFESSIONAL_BURDEN_CAP: float = 1.0
DEFAULT_PROFESSIONAL_SEVERITY: int = 2


@dataclass(frozen=True)
class OutlierConfig:
    """Configuration injected into ``outliers.classify_outliers``.

    ``methods`` lists built-in names ("iqr", "zscore", "mad") and/or callables
    ``(values_by_id, config) -> {id: severity}``. Fences are tiered (mild,
    severe, extreme). ``class_by_severity`` maps severity to advisory class.
    ``professional_burden_cap`` None disables the professional rule.
    ``auto_exclude`` defaults to False — classification is advisory and nothing
    is ever removed.
    """

    methods: Optional[Tuple] = None
    iqr_fences: Tuple[float, float, float] = DEFAULT_IQR_FENCES
    zscore_fences: Tuple[float, float, float] = DEFAULT_ZSCORE_FENCES
    mad_fences: Tuple[float, float, float] = DEFAULT_MAD_FENCES
    class_by_severity: Optional[Mapping] = None
    professional_burden_cap: Optional[float] = DEFAULT_PROFESSIONAL_BURDEN_CAP
    professional_severity: int = DEFAULT_PROFESSIONAL_SEVERITY
    auto_exclude: bool = False
    rounding: Optional[int] = None


# Convenience default instance.
DEFAULT_OUTLIER_CONFIG = OutlierConfig()


# ─── CIL-4: Admission Framework defaults ──────────────────────────────────────
# NOT a fixed state machine: states are data, rules are data/callables, conflict
# resolution is a named strategy or callable, and the no-match default state is
# configurable. The framework recommends — it never admits or rejects by itself.

# Suggested state set. Callers may add or remove states freely; no state is
# privileged in logic.
DEFAULT_ADMISSION_STATES: Tuple[str, ...] = (
    "admit", "admit_conditional", "flag", "review", "reject",
)

# State recommended when no rule matches.
DEFAULT_ADMISSION_DEFAULT_STATE: str = "review"

# Reliability thresholds referenced by the suggested default rules; both are
# engagement policy and fully overridable (they mirror evidence defaults).
DEFAULT_ADMISSION_STRONG_RELIABILITY: float = 0.70
DEFAULT_ADMISSION_WEAK_RELIABILITY: float = 0.45


@dataclass(frozen=True)
class AdmissionConfig:
    """Configuration injected into the Admission Framework.

    ``states`` is the extensible state vocabulary. ``rules`` is an ordered
    tuple of rule mappings ``{name, predicate(context)->bool, state,
    conditions, rationale, priority}`` — None selects the suggested default
    set. ``conflict_resolution`` is ``"first_match"`` (configured order),
    ``"highest_priority"`` or a callable receiving the matched rules and
    returning the governing one. ``allowed_transitions`` (state -> tuple of
    states) is open when None. No mandatory path is encoded anywhere.
    """

    states: Tuple[str, ...] = DEFAULT_ADMISSION_STATES
    rules: Optional[Tuple] = None
    conflict_resolution: Union[str, Callable] = "first_match"
    default_state: str = DEFAULT_ADMISSION_DEFAULT_STATE
    allowed_transitions: Optional[Mapping] = None
    strong_reliability: float = DEFAULT_ADMISSION_STRONG_RELIABILITY
    weak_reliability: float = DEFAULT_ADMISSION_WEAK_RELIABILITY


# Convenience default instance.
DEFAULT_ADMISSION_CONFIG = AdmissionConfig()
