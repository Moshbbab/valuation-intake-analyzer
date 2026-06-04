"""Tests for the NOI Builder calculation support.

Verifies the income/expense build-up, vacancy as rate vs absolute, optional
other income and reserves, configurable aggregation, optional non-blocking
audit, and that no cap rate / value is produced.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.audit.storage import InMemoryAuditStore  # noqa: E402
from engine.valuation.config import NOIConfig  # noqa: E402
from engine.valuation.noi import (  # noqa: E402
    build_noi,
    effective_gross_income,
    potential_gross_income,
    total_operating_expenses,
)


def _income():
    return [{"name": "base rent", "amount": 90000},
            {"name": "parking", "amount": 10000}]


def _expenses():
    return [{"name": "management", "amount": 8000},
            {"name": "insurance", "amount": 4000}]


# ─── PGI / expenses ───────────────────────────────────────────────────────────

def test_pgi_from_multiple_income_lines():
    assert potential_gross_income(_income()) == 100000


def test_operating_expenses_summed():
    assert total_operating_expenses(_expenses()) == 12000


# ─── vacancy ──────────────────────────────────────────────────────────────────

def test_vacancy_as_rate():
    egi = effective_gross_income(_income(),
                                 vacancy={"type": "rate", "value": 0.05})
    assert egi == 100000 - 5000  # 5% of PGI


def test_vacancy_as_absolute():
    egi = effective_gross_income(_income(),
                                 vacancy={"type": "absolute", "value": 4000})
    assert egi == 100000 - 4000


def test_no_default_vacancy_magic_rate():
    # vacancy omitted -> zero loss, never an implicit default rate
    assert effective_gross_income(_income()) == 100000


def test_other_income_included():
    egi = effective_gross_income(_income(), other_income=2500)
    assert egi == 102500


def test_other_income_as_line_items():
    egi = effective_gross_income(
        _income(), other_income=[{"amount": 1500}, {"amount": 500}])
    assert egi == 102000


# ─── build_noi ────────────────────────────────────────────────────────────────

def test_build_noi_basic():
    result = build_noi({"income_items": _income(),
                        "vacancy": {"type": "rate", "value": 0.05},
                        "expense_items": _expenses()})
    assert result["potential_gross_income"] == 100000
    assert result["vacancy_loss"] == 5000
    assert result["effective_gross_income"] == 95000
    assert result["operating_expenses"] == 12000
    assert result["noi"] == 95000 - 12000
    assert "not an adopted NOI" in result["basis"]


def test_reserves_included_only_if_provided():
    base = build_noi({"income_items": _income(), "expense_items": _expenses()})
    assert base["reserves"] == 0.0
    assert base["breakdown"]["reserves_provided"] is False
    assert base["noi"] == 100000 - 12000

    with_res = build_noi({"income_items": _income(),
                          "expense_items": _expenses(), "reserves": 3000})
    assert with_res["reserves"] == 3000
    assert with_res["breakdown"]["reserves_provided"] is True
    assert with_res["noi"] == 100000 - 12000 - 3000


def test_breakdown_lists_line_items():
    result = build_noi({"income_items": _income(), "expense_items": _expenses()})
    names = [row["name"] for row in result["breakdown"]["income_items"]]
    assert names == ["base rent", "parking"]


# ─── configurable aggregation ─────────────────────────────────────────────────

def test_custom_aggregation_callable():
    # sum only the largest line as a (contrived) custom aggregation
    config = NOIConfig(aggregation=lambda amounts: max(amounts) if amounts else 0)
    assert potential_gross_income(_income(), config=config) == 90000


def test_custom_amount_field():
    config = NOIConfig(amount_field="value")
    items = [{"name": "rent", "value": 50000}, {"name": "x", "value": 25000}]
    assert potential_gross_income(items, config=config) == 75000


def test_rounding_configurable():
    config = NOIConfig(rounding=2)
    result = build_noi({"income_items": [{"amount": 100000}],
                        "vacancy": {"type": "rate", "value": 0.0333},
                        "expense_items": []}, config=config)
    assert result["vacancy_loss"] == 3330.0


# ─── audit (optional, non-blocking) ───────────────────────────────────────────

def test_audit_optional_absent_by_default():
    # no store -> no error, no audit
    result = build_noi({"income_items": _income(), "expense_items": _expenses()})
    assert result["noi"] == 88000


def test_audit_records_event_when_store_given():
    store = InMemoryAuditStore()
    build_noi({"property_id": "P-1", "income_items": _income(),
               "expense_items": _expenses()}, audit_store=store)
    events = store.list()
    assert len(events) == 1
    assert events[0]["entity_type"] == "noi"
    assert events[0]["action"] == "noi_built"
    assert events[0]["after"]["noi"] == 88000


# ─── no value / cap-rate output ───────────────────────────────────────────────

def test_no_cap_rate_or_value_output():
    result = build_noi({"income_items": _income(), "expense_items": _expenses()})
    for forbidden in ("cap_rate", "value", "indicated_value", "adopted_noi"):
        assert forbidden not in result
