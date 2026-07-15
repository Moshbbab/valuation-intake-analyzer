"""Basic unit tests for the intake analyzer engine."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.intake_analyzer import (  # noqa: E402
    parse_intake,
    generate_report,
    extract_field,
    assess_data_gate,
    field_confidence,
)


def test_parse_intake_all_fields_present():
    """All key fields are correctly extracted from a well-formed document."""
    sample = """
    Property Type: Commercial Office
    Property Location: Riyadh, King Fahd Road
    Valuation Purpose: Mortgage Financing
    Basis of Value: Market Value
    Valuation Date: 01 June 2025
    Documents Provided: Title Deed, Survey Plan
    """
    result = parse_intake(sample)
    assert result["property_type"]["value"] == "Commercial Office"
    assert result["property_location"]["value"] != "Not stated"
    assert result["valuation_purpose"]["value"] != "Not stated"
    assert result["basis_of_value"]["value"] != "Not stated"
    assert result["valuation_date"]["value"] != "Not stated"


def test_parse_intake_missing_fields():
    """Missing fields are reported as 'Not stated'."""
    result = parse_intake("This is a document with no structured fields.")
    assert result["property_type"]["value"] == "Not stated"
    assert result["property_location"]["value"] == "Not stated"
    assert result["valuation_purpose"]["value"] == "Not stated"


def test_readiness_when_all_missing():
    """Readiness is Partially Ready or Not Ready when fields are missing."""
    result = parse_intake("No fields here.")
    assert result["readiness_assessment"]["value"] in (
        "Partially Ready",
        "Not Ready",
    )


def test_readiness_ready_when_all_present():
    """Readiness is Ready when all core and extended fields are present."""
    sample = """
    Property Type: Villa
    Property Location: Jeddah
    Valuation Purpose: Sale
    Basis of Value: Market Value
    Valuation Date: 2025-01-01
    Client Name: Smith Family Trust
    Intended User: Smith Family Trust (mortgage purposes)
    Inspection was carried out on 01 June 2025.
    """
    result = parse_intake(sample)
    assert result["readiness_assessment"]["value"] == "Ready"


def test_generate_report_flattens_data():
    """generate_report returns a flat dict of string values."""
    sample = "Property Type: Land\nValuation Date: 2025-05-01"
    data = parse_intake(sample)
    report = generate_report(data)
    assert isinstance(report, dict)
    for val in report.values():
        assert isinstance(val, str)


def test_extract_field_no_match():
    """extract_field returns empty strings when no pattern matches."""
    value, evidence = extract_field(
        [r"nonexistent[:\s]+(?P<value>[^\n]+)"], "hello world"
    )
    assert value == ""
    assert evidence == ""


# ─── New field extraction ────────────────────────────────────────────────────

def test_new_fields_extracted():
    """New fields client_name, instruction_reference, site_area, intended_user are extracted."""
    sample = """
    Client Name: ABC Asset Management
    Instruction Reference: REF-2025-001
    Site Area: 5,000 sqm
    Intended User: ABC Asset Management (for internal reporting only)
    Property Type: Commercial Office
    Property Location: Riyadh
    Valuation Purpose: Financial Reporting
    Basis of Value: Fair Value
    Valuation Date: 01 June 2025
    """
    result = parse_intake(sample)
    assert result["client_name"]["value"] == "ABC Asset Management"
    assert result["instruction_reference"]["value"] == "REF-2025-001"
    assert result["site_area"]["value"] == "5,000 sqm"
    assert result["intended_user"]["value"] != "Not stated"


def test_special_assumptions_extracted():
    """Special assumptions are extracted when declared."""
    sample = "Special Assumptions: Vacant possession assumed\nProperty Type: Land"
    result = parse_intake(sample)
    assert result["special_assumptions"]["value"] != "None stated"
    assert "vacant" in result["special_assumptions"]["value"].lower()


def test_special_assumptions_do_not_leak_into_general_assumptions():
    """A special assumption must not be duplicated as a general assumption."""
    sample = "Special Assumptions: Vacant possession assumed\nProperty Type: Land"
    result = parse_intake(sample)
    assert result["special_assumptions"]["value"] == "Vacant possession assumed"
    assert result["initial_assumptions"]["value"] == "None stated"


def test_general_and_special_assumptions_remain_separate():
    """General and special assumptions retain their own evidence and values."""
    sample = (
        "Assumptions: Title is free from encumbrances\n"
        "Special Assumptions: Vacant possession assumed\n"
    )
    result = parse_intake(sample)
    assert result["initial_assumptions"]["value"] == "Title is free from encumbrances"
    assert result["special_assumptions"]["value"] == "Vacant possession assumed"


def test_special_assumptions_none():
    """Special assumptions are None stated when absent."""
    result = parse_intake("Property Type: Office\nValuation Date: 2025-01-01")
    assert result["special_assumptions"]["value"] == "None stated"


def test_inspection_status_remote():
    """Remote valuation is detected when declared."""
    sample = "Remote Valuation — no physical inspection was carried out."
    result = parse_intake(sample)
    assert "remote" in result["inspection_status"]["value"].lower()


def test_inspection_status_performed():
    """Physical inspection is detected when referenced."""
    sample = "Inspection was carried out on 15 May 2025."
    result = parse_intake(sample)
    assert result["inspection_status"]["value"] != "Not stated"
    assert "performed" in result["inspection_status"]["value"].lower()


def test_inspection_status_not_stated():
    """Inspection status is Not stated when no reference found."""
    result = parse_intake("Property Type: Villa\nLocation: Jeddah")
    assert result["inspection_status"]["value"] == "Not stated"


def test_market_evidence_count_detected():
    """Market comparables are counted when referenced."""
    sample = (
        "Comparable No. 1: sold for SAR 2M\n"
        "Comparable No. 2: sold for SAR 2.1M\n"
        "Comparable No. 3: sold for SAR 1.9M\n"
    )
    result = parse_intake(sample)
    assert result["market_evidence_count"]["value"] != "Not stated"


def test_market_evidence_count_not_stated():
    """Market evidence count is Not stated when no references found."""
    result = parse_intake("Property Type: Office")
    assert result["market_evidence_count"]["value"] == "Not stated"


# ─── Data Gate ───────────────────────────────────────────────────────────────

def test_data_gate_returns_five_items():
    """assess_data_gate always returns exactly 5 items (A1–A5)."""
    result = parse_intake("Property Type: Office\nLocation: Riyadh")
    gate = assess_data_gate(result)
    assert len(gate) == 5
    ids = [item["id"] for item in gate]
    assert ids == ["A1", "A2", "A3", "A4", "A5"]


def test_data_gate_pass_when_complete():
    """Data Gate A1 and A2 are PASS when all ToE and property fields are present."""
    sample = """
    Property Type: Commercial Office
    Property Location: Riyadh
    Valuation Purpose: Financial Reporting
    Basis of Value: Fair Value
    Intended User: ABC Bank
    Valuation Date: 01 June 2025
    """
    result = parse_intake(sample)
    gate = assess_data_gate(result)
    a1 = next(i for i in gate if i["id"] == "A1")
    a2 = next(i for i in gate if i["id"] == "A2")
    assert a1["status"] == "PASS"
    assert a2["status"] == "PASS"


def test_data_gate_fail_when_missing():
    """Data Gate A1 is FAIL when basis_of_value, valuation_purpose, intended_user are absent."""
    result = parse_intake("This document has no structured fields.")
    gate = assess_data_gate(result)
    a1 = next(i for i in gate if i["id"] == "A1")
    assert a1["status"] == "FAIL"


def test_data_gate_a3_unverified_when_not_stated():
    """Data Gate A3 is UNVERIFIED when no inspection reference is found."""
    result = parse_intake("Property Type: Office\nLocation: Riyadh")
    gate = assess_data_gate(result)
    a3 = next(i for i in gate if i["id"] == "A3")
    assert a3["status"] == "UNVERIFIED"


def test_data_gate_a3_pass_when_remote():
    """Data Gate A3 is PASS when remote valuation is declared."""
    sample = "Property Type: Office\nRemote Valuation — no site visit conducted."
    result = parse_intake(sample)
    gate = assess_data_gate(result)
    a3 = next(i for i in gate if i["id"] == "A3")
    assert a3["status"] == "PASS"


# ─── field_confidence ────────────────────────────────────────────────────────

def test_field_confidence_high():
    """field_confidence returns High when value and evidence are present."""
    assert field_confidence({"value": "Office", "evidence": "Property type: Office"}) == "High"


def test_field_confidence_low():
    """field_confidence returns Low when value is present but evidence is empty."""
    assert field_confidence({"value": "Office", "evidence": ""}) == "Low"


def test_field_confidence_not_found():
    """field_confidence returns Not found when value is Not stated."""
    assert field_confidence({"value": "Not stated", "evidence": ""}) == "Not found"
