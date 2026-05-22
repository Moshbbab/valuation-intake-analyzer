"""Basic unit tests for the intake analyzer engine."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.intake_analyzer import (  # noqa: E402
    parse_intake,
    generate_report,
    extract_field,
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
    """Readiness is Ready when all key fields are present."""
    sample = """
    Property Type: Villa
    Property Location: Jeddah
    Valuation Purpose: Sale
    Basis of Value: Market Value
    Valuation Date: 2025-01-01
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
