"""Tests for CIL-3 outlier detection (classify only, advisory).

Covers the tiered IQR default, z-score/MAD selection, custom method callables,
small-sample honesty (not assessable, never guessed), the professional
adjustment-burden rule, classification mapping overrides, auto_exclude off by
default (and flag-only when enabled), the tri-part envelope, and the AVM-risk
invariants (never removes, no value/admission keys).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.comparable_intelligence.config import OutlierConfig  # noqa: E402
from engine.comparable_intelligence.outliers import (  # noqa: E402
    classify_outliers,
    gross_adjustment_burden,
)


def _entries(values):
    return [{"comparable_id": f"C-{i}", "value": v}
            for i, v in enumerate(values, start=1)]


# Tight cluster + one far point: 8 values around 1000, one at 5000.
CLUSTER = [990, 995, 1000, 1002, 1005, 1008, 1010, 1015, 5000]


# ─── statistical methods ──────────────────────────────────────────────────────

def test_iqr_flags_extreme_outlier():
    env = classify_outliers(_entries(CLUSTER))
    items = env["result"]["items"]
    assert items["C-9"]["classification"] == "exclude_candidate"
    assert items["C-9"]["severity"] == 3
    assert all(items[f"C-{i}"]["classification"] == "none" for i in range(1, 9))


def test_iqr_tiers_warning_vs_review():
    config = OutlierConfig(iqr_fences=(1.5, 3.0, 4.5))
    # value just beyond the mild fence -> warning, far beyond severe -> higher.
    values = [100, 101, 102, 103, 104, 105, 106, 115]
    env = classify_outliers(_entries(values), config=config)
    item = env["result"]["items"]["C-8"]
    assert item["classification"] in ("warning", "review_required")
    assert item["severity"] >= 1


def test_zscore_and_mad_methods_selectable():
    # z-score is bounded at (n-1)/sqrt(n) ~= 2.67 for n=9, so the extreme point
    # tiers at severity 1 there; MAD is robust and reaches the top tier.
    for method, min_severity in (("zscore", 1), ("mad", 3)):
        env = classify_outliers(_entries(CLUSTER),
                                config=OutlierConfig(methods=(method,)))
        assert env["result"]["items"]["C-9"]["severity"] >= min_severity
        assert env["assumptions_used"]["methods"] == [method]


def test_multiple_methods_max_severity():
    env = classify_outliers(_entries(CLUSTER),
                            config=OutlierConfig(methods=("iqr", "mad")))
    item = env["result"]["items"]["C-9"]
    assert set(item["method_severities"]) == {"iqr", "mad"}
    assert item["severity"] == max(item["method_severities"].values())


def test_custom_method_callable():
    def always_extreme(values_by_id, config):
        return {cid: 3 for cid in values_by_id}

    env = classify_outliers(_entries([1, 2, 3]),
                            config=OutlierConfig(methods=(always_extreme,)))
    assert all(item["classification"] == "exclude_candidate"
               for item in env["result"]["items"].values())
    assert env["assumptions_used"]["methods"] == ["always_extreme"]


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        classify_outliers(_entries(CLUSTER),
                          config=OutlierConfig(methods=("nope",)))


# ─── small samples / degenerate data ──────────────────────────────────────────

def test_small_sample_not_assessable_not_guessed():
    env = classify_outliers(_entries([100, 5000]))
    items = env["result"]["items"]
    assert all(item["classification"] == "none" for item in items.values())
    assert any("not assessable" in note
               for note in env["result"]["not_assessable_notes"])


def test_identical_values_not_assessable():
    env = classify_outliers(_entries([100] * 6))
    assert all(item["classification"] == "none"
               for item in env["result"]["items"].values())


def test_non_numeric_values_skipped():
    entries = _entries(CLUSTER) + [{"comparable_id": "C-X", "value": None}]
    env = classify_outliers(entries)
    assert "C-X" in env["result"]["skipped"]
    assert env["result"]["items"]["C-X"]["classification"] == "none"


# ─── professional rule ────────────────────────────────────────────────────────

def _heavy_comparable():
    return {"comparable_id": "C-1", "unit_rate": 1000, "adjustments": [
        {"adjustment_value": {"type": "percentage", "value": 80,
                              "direction": "upward"}},
        {"adjustment_value": {"type": "percentage", "value": 40,
                              "direction": "downward"}},
    ]}


def test_gross_adjustment_burden():
    assert gross_adjustment_burden(_heavy_comparable()) == pytest.approx(1.2)
    assert gross_adjustment_burden({"unit_rate": 1000}) is None


def test_professional_rule_fires_above_cap():
    entries = [{"comparable_id": "C-1", "value": 1000,
                "comparable": _heavy_comparable()},
               {"comparable_id": "C-2", "value": 1001}]
    env = classify_outliers(entries)
    item = env["result"]["items"]["C-1"]
    assert item["classification"] == "review_required"
    assert any("professional" in reason for reason in item["reasons"])


def test_professional_rule_disabled_with_none_cap():
    entries = [{"comparable_id": "C-1", "value": 1000,
                "comparable": _heavy_comparable()}]
    env = classify_outliers(entries,
                            config=OutlierConfig(professional_burden_cap=None))
    assert env["result"]["items"]["C-1"]["classification"] == "none"


# ─── classification mapping / auto_exclude ────────────────────────────────────

def test_class_mapping_override():
    config = OutlierConfig(class_by_severity={1: "warning", 2: "warning",
                                              3: "review_required"})
    env = classify_outliers(_entries(CLUSTER), config=config)
    assert env["result"]["items"]["C-9"]["classification"] == "review_required"


def test_auto_exclude_off_by_default():
    env = classify_outliers(_entries(CLUSTER))
    assert env["result"]["exclude_candidates"] == []
    assert env["assumptions_used"]["auto_exclude"] is False


def test_auto_exclude_enabled_flags_only_never_removes():
    env = classify_outliers(_entries(CLUSTER),
                            config=OutlierConfig(auto_exclude=True))
    assert env["result"]["exclude_candidates"] == ["C-9"]
    # every input id is still present and classified — nothing removed.
    assert len(env["result"]["items"]) == len(CLUSTER)


# ─── envelope / invariants ────────────────────────────────────────────────────

def test_envelope_shape_and_advisory():
    env = classify_outliers(_entries(CLUSTER))
    assert set(env) == {"result", "explanation", "assumptions_used",
                        "advisory", "basis"}
    assert env["advisory"] is True
    assert "advisory" in env["explanation"][0]
    assert "human decision" in env["explanation"][0]


def test_assumptions_record_fences_and_methods():
    env = classify_outliers(_entries(CLUSTER))
    used = env["assumptions_used"]
    assert used["iqr_fences"] == [1.5, 3.0, 4.5]
    assert used["methods"] == ["iqr"]
    assert used["professional_burden_cap"] == 1.0


def test_no_value_or_admission_keys():
    env = classify_outliers(_entries(CLUSTER))
    for forbidden in ("value", "adopted_value", "final_value", "price",
                      "inclusion_decision", "admission_state", "excluded"):
        assert forbidden not in env["result"]
    assert "not a value" in env["basis"]
