"""Tests for cross-approach reconciliation calculation support.

Covers the reconciled range envelope, weighted central, weight resolution
(per-indication, config, equal fallback, mixed rejection), point/range bounds,
custom aggregation, optional non-blocking audit, and absence of adopted value.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.config import ReconciliationConfig  # noqa: E402
from engine.valuation.reconciliation import (  # noqa: E402
    ReconciliationError,
    normalize_approach_weights,
    reconcile,
)


# ─── weights ──────────────────────────────────────────────────────────────────

def test_equal_weight_fallback_when_none_supplied():
    inds = [{"approach": "comparable", "value": 1000000},
            {"approach": "income", "value": 1200000}]
    weights = normalize_approach_weights(inds)
    assert weights == {"comparable": 0.5, "income": 0.5}


def test_per_indication_weights_normalized():
    inds = [{"approach": "comparable", "value": 1000000, "weight": 3},
            {"approach": "income", "value": 1200000, "weight": 1}]
    weights = normalize_approach_weights(inds)
    assert weights["comparable"] == 0.75
    assert weights["income"] == 0.25


def test_config_weights_by_approach_name():
    inds = [{"approach": "comparable", "value": 1000000},
            {"approach": "income", "value": 1200000}]
    cfg = ReconciliationConfig(weights={"comparable": 1, "income": 3})
    weights = normalize_approach_weights(inds, config=cfg)
    assert weights["comparable"] == 0.25
    assert weights["income"] == 0.75


def test_per_indication_overrides_config():
    inds = [{"approach": "comparable", "value": 1000000, "weight": 1},
            {"approach": "income", "value": 1200000, "weight": 1}]
    cfg = ReconciliationConfig(weights={"comparable": 99})
    weights = normalize_approach_weights(inds, config=cfg)
    assert weights == {"comparable": 0.5, "income": 0.5}


def test_mixed_partial_weights_rejected():
    inds = [{"approach": "comparable", "value": 1000000, "weight": 2},
            {"approach": "income", "value": 1200000}]  # missing weight
    with pytest.raises(ReconciliationError):
        normalize_approach_weights(inds)


# ─── bounds (point / range) ───────────────────────────────────────────────────

def test_reconcile_points():
    result = reconcile([{"approach": "comparable", "value": 1000000},
                        {"approach": "income", "value": 1200000}])
    assert result["reconciled_range"] == {"low": 1000000, "high": 1200000}
    assert result["weighted_indication"] == 1100000  # equal weights


def test_reconcile_ranges_envelope():
    result = reconcile([
        {"approach": "comparable", "range": {"low": 900000, "high": 1100000}},
        {"approach": "income", "range": {"low": 1000000, "high": 1300000}},
    ])
    assert result["reconciled_range"] == {"low": 900000, "high": 1300000}
    # central of each range is its midpoint: 1,000,000 and 1,150,000
    assert result["weighted_indication"] == pytest.approx((1000000 + 1150000) / 2)


def test_value_plus_range_uses_value_as_central():
    result = reconcile([
        {"approach": "income", "value": 1180000,
         "range": {"low": 1000000, "high": 1300000}},
    ])
    assert result["reconciled_range"] == {"low": 1000000, "high": 1300000}
    assert result["weighted_indication"] == 1180000  # value, not midpoint


def test_indication_without_value_or_range_rejected():
    with pytest.raises(ReconciliationError):
        reconcile([{"approach": "comparable"}])


def test_indication_without_approach_rejected():
    with pytest.raises(ReconciliationError):
        reconcile([{"value": 1000000}])


def test_empty_indications_rejected():
    with pytest.raises(ReconciliationError):
        reconcile([])


# ─── weighting flows into central ─────────────────────────────────────────────

def test_weighted_indication_respects_weights():
    result = reconcile([
        {"approach": "comparable", "value": 1000000, "weight": 3},
        {"approach": "income", "value": 1200000, "weight": 1},
    ])
    # 0.75*1,000,000 + 0.25*1,200,000 = 1,050,000
    assert result["weighted_indication"] == 1050000


def test_custom_aggregation_callable():
    cfg = ReconciliationConfig(
        aggregation=lambda centrals, weights: min(centrals.values()))
    result = reconcile([{"approach": "comparable", "value": 1000000},
                        {"approach": "income", "value": 1200000}], config=cfg)
    assert result["weighted_indication"] == 1000000


def test_rounding_configurable():
    cfg = ReconciliationConfig(rounding=2)
    result = reconcile([{"approach": "a", "value": 1000000, "weight": 1},
                        {"approach": "b", "value": 1000001, "weight": 2}],
                       config=cfg)
    assert result["weighted_indication"] == round((1000000 + 2 * 1000001) / 3, 2)


# ─── audit (optional, non-blocking) ───────────────────────────────────────────

def test_audit_absent_by_default():
    result = reconcile([{"approach": "comparable", "value": 1000000}])
    assert result["weighted_indication"] == 1000000


def test_audit_records_event_when_store_given():
    store = InMemoryAuditStore()
    reconcile([{"approach": "comparable", "value": 1000000, "property_id": "P-1"},
               {"approach": "income", "value": 1200000}], audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["entity_type"] == "valuation"
    assert events[0]["action"] == "reconciled"


# ─── no adopted / concluded value output ──────────────────────────────────────

def test_no_adopted_or_concluded_value_output():
    result = reconcile([{"approach": "comparable", "value": 1000000}])
    for forbidden in ("adopted_value", "concluded_value", "final_value",
                      "opinion"):
        assert forbidden not in result
    assert "not an adopted value" in result["basis"]
