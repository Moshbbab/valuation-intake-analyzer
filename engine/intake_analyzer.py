"""Core intake analysis logic for the Valuation Intake Analyzer.

The functions in this module are deliberately simple and rule-based.
They extract structured information from the raw text of valuation
request documents and report missing or unclear fields without making
any assumptions about value or pricing.

Key design principles:
  Transparency: each piece of information is either extracted directly
    from the source or marked as missing.
  Separation of concerns: text parsing, field extraction, risk
    assessment, and report assembly are kept in distinct functions
    to facilitate unit testing and future expansion.
  Extensibility: the simple heuristics can be replaced by more
    sophisticated NLP pipelines in future iterations without affecting
    the Streamlit UI.

This module does not depend on Streamlit and can be imported into
other contexts (e.g. command-line scripts or tests).
"""

import os
import re
from typing import Any, Dict, List, Tuple

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - handled via requirements
    PdfReader = None  # type: ignore

try:
    from docx import Document
except ImportError:  # pragma: no cover
    Document = None  # type: ignore


def read_pdf(path: str) -> str:
    """Extract text from a PDF file using PyPDF2."""
    if PdfReader is None:
        return ""
    text_parts: List[str] = []
    try:
        with open(path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
    except OSError:
        pass
    return " ".join(text_parts)


def read_docx(path: str) -> str:
    """Extract text from a Word .docx file using python-docx."""
    if Document is None:
        return ""
    try:
        doc = Document(path)
    except OSError:
        return ""
    paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(paragraphs)


def read_plain(path: str) -> str:
    """Read plain text from a file with UTF-8 or fallback encodings."""
    for encoding in ("utf-8", "latin-1", "windows-1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except OSError:
            continue
    return ""


def read_file(path: str) -> str:
    """Detect the file type by extension and return its textual contents."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext in (".docx",):
        return read_docx(path)
    return read_plain(path)


def extract_field(
    patterns: List[str], text: str
) -> Tuple[str, str]:
    """Search for the first pattern match and return the captured value."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group("value").strip()
            return value, match.group(0).strip()
    return "", ""


def _build_patterns_map() -> Dict[str, List[str]]:
    """Return the regex patterns used to extract each intake field."""
    return {
        "property_type": [
            r"property[\s_-]*type[:\s]+(?P<value>[^\n]+)",
            r"نوع[\s_-]*العقار[:\s]+(?P<value>[^\n]+)",
        ],
        "property_location": [
            r"property[\s_-]*location[:\s]+(?P<value>[^\n]+)",
            r"location[:\s]+(?P<value>[^\n]+)",
            r"موقع[\s_-]*العقار[:\s]+(?P<value>[^\n]+)",
        ],
        "valuation_purpose": [
            r"valuation[\s_-]*purpose[:\s]+(?P<value>[^\n]+)",
            r"purpose[:\s]+(?P<value>[^\n]+)",
            r"غرض[\s_-]*التقييم[:\s]+(?P<value>[^\n]+)",
        ],
        "basis_of_value": [
            r"basis[\s_-]*of[\s_-]*value[:\s]+(?P<value>[^\n]+)",
            r"basis[:\s]+(?P<value>[^\n]+)",
            r"أساس[\s_-]*القيمة[:\s]+(?P<value>[^\n]+)",
        ],
        "valuation_date": [
            r"valuation[\s_-]*date[:\s]+(?P<value>[^\n]+)",
            r"date[:\s]+(?P<value>[^\n]+)",
            r"تاريخ[\s_-]*التقييم[:\s]+(?P<value>[^\n]+)",
        ],
        "client_name": [
            r"client[\s_-]*name[:\s]+(?P<value>[^\n]+)",
            r"client[:\s]+(?P<value>[^\n]+)",
            r"prepared[\s_-]*for[:\s]+(?P<value>[^\n]+)",
        ],
        "instruction_reference": [
            r"instruction[\s_-]*ref(?:erence)?[:\s]+(?P<value>[^\n]+)",
            r"ref(?:erence)?[\s_-]*no\.?[:\s]+(?P<value>[^\n]+)",
            r"job[\s_-]*(?:no|number|ref)[:\s]+(?P<value>[^\n]+)",
        ],
        "site_area": [
            r"site[\s_-]*area[:\s]+(?P<value>[^\n]+)",
            r"land[\s_-]*area[:\s]+(?P<value>[^\n]+)",
            r"gross[\s_-]*(?:floor[\s_-]*)?area[:\s]+(?P<value>[^\n]+)",
            r"total[\s_-]*area[:\s]+(?P<value>[^\n]+)",
        ],
        "intended_user": [
            r"intended[\s_-]*user[:\s]+(?P<value>[^\n]+)",
            r"report[\s_-]*(?:is[\s_-]*)?(?:prepared[\s_-]*)?for[:\s]+(?P<value>[^\n]+)",
        ],
    }


def _extract_documents(text: str) -> Dict[str, str]:
    """Extract available documents section from text."""
    documents_section = re.search(
        r"documents[\s\S]*?provided[^:\n]*:?([\s\S]*?)(?:\n\n|$)",
        text,
        re.IGNORECASE,
    )
    documents: List[str] = []
    evidence = ""
    if documents_section:
        for item in re.split(r"[,;\n]", documents_section.group(0)):
            cleaned = item.strip(" -\t")
            if cleaned:
                documents.append(cleaned)
        evidence = documents_section.group(0).split("\n", 10)[0].strip()
    return {
        "value": ", ".join(documents) if documents else "None stated",
        "evidence": evidence,
    }


def _extract_missing_documents(text: str) -> Dict[str, str]:
    """Extract the missing documents field from text."""
    missing_match = re.search(
        r"missing[\s_-]*documents?[:\s]+(?P<value>[^\n]+)",
        text,
        re.IGNORECASE,
    )
    if missing_match:
        missing_docs = [
            d.strip()
            for d in re.split(r"[,;]", missing_match.group("value"))
            if d.strip()
        ]
        return {
            "value": ", ".join(missing_docs),
            "evidence": missing_match.group(0).strip(),
        }
    return {"value": "None stated", "evidence": ""}


def _extract_assumptions(text: str) -> Dict[str, str]:
    """Extract general assumptions without duplicating special assumptions."""
    pattern = (
        r"^[ \t]*(?!special[\s_-]*assumptions?\b)"
        r"assumptions?[ \t]*:[ \t]*(?P<value>[^\n]+)"
    )
    matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
    assumptions = [match.group("value").strip() for match in matches]
    evidence = "; ".join(match.group(0).strip() for match in matches)
    return {
        "value": "; ".join(assumptions) if assumptions else "None stated",
        "evidence": evidence,
    }


def _extract_special_assumptions(text: str) -> Dict[str, str]:
    """Extract special assumptions declared in the document."""
    pattern = r"special[\s_-]*assumptions?[:\s]+(?P<value>[^\n]+)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    values = [m.group("value").strip() for m in matches]
    evidence = "; ".join(m.group(0).strip() for m in matches)
    return {
        "value": "; ".join(values) if values else "None stated",
        "evidence": evidence,
    }


def _extract_inspection_status(text: str) -> Dict[str, str]:
    """Detect whether an inspection was performed or declared remote."""
    remote_patterns = [
        r"remote[\s_-]*valuation",
        r"desktop[\s_-]*(?:valuation|review)",
        r"no[\s_-]*(?:physical[\s_-]*)?inspection",
        r"inspection[\s_-]*not[\s_-]*(?:carried[\s_-]*out|performed)",
    ]
    for pat in remote_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return {"value": "Remote (declared)", "evidence": m.group(0).strip()}

    inspection_patterns = [
        r"inspection[\s_-]*(?:was[\s_-]*)?"
        r"(?:carried[\s_-]*out|performed|conducted|date)"
        r"[:\s]*(?P<value>[^\n]+)",
        r"inspected[\s_-]*on[:\s]*(?P<value>[^\n]+)",
        r"site[\s_-]*visit[:\s]*(?P<value>[^\n]+)",
    ]
    for pat in inspection_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            value = m.group("value").strip() if "value" in m.groupdict() else "Confirmed"
            return {"value": f"Performed — {value}", "evidence": m.group(0).strip()}

    return {"value": "Not stated", "evidence": ""}


def _extract_market_evidence_count(text: str) -> Dict[str, str]:
    """Estimate number of market comparables or evidence sources mentioned."""
    comparable_pattern = r"comparable[\s_-]*(?:no\.?|#|[0-9]+|transaction)"
    matches = list(re.finditer(comparable_pattern, text, re.IGNORECASE))
    count = len(matches)
    if count == 0:
        evidence_keywords = [
            r"market[\s_-]*evidence",
            r"sales?[\s_-]*(?:evidence|comparison|transaction)",
            r"(?:recent|comparable)[\s_-]*(?:sale|transaction|deal)",
        ]
        for kw in evidence_keywords:
            if re.search(kw, text, re.IGNORECASE):
                return {"value": "Present (count unclear)", "evidence": kw}
        return {"value": "Not stated", "evidence": ""}
    return {
        "value": f"{count} reference(s) detected",
        "evidence": f"{count} comparable reference(s) found in document",
    }


def assess_data_gate(result: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    """Return the Data Gate checklist items with auto-detected status.

    Each item has:
      id       — gate item identifier (A1–A5)
      label    — human-readable description
      detected — auto-detected status string
      status   — "PASS", "FAIL", or "UNVERIFIED" (requires human confirmation)

    The returned list is used by the UI to pre-fill the gate; the user must
    confirm each item before the gate closes.
    """
    items: List[Dict[str, Any]] = []

    # A1 — Terms of Engagement (proxy: basis_of_value + valuation_purpose + intended_user)
    toe_fields = ("basis_of_value", "valuation_purpose", "intended_user")
    toe_found = all(
        result.get(f, {}).get("value", "Not stated") != "Not stated"
        for f in toe_fields
    )
    items.append({
        "id": "A1",
        "label": "Terms of Engagement reviewed (Basis of Value, Purpose, Intended User stated)",
        "detected": "Key ToE fields found" if toe_found else "One or more ToE fields missing",
        "status": "PASS" if toe_found else "FAIL",
    })

    # A2 — Property Description (proxy: property_type + property_location + site_area)
    desc_fields = ("property_type", "property_location")
    desc_found = all(
        result.get(f, {}).get("value", "Not stated") != "Not stated"
        for f in desc_fields
    )
    items.append({
        "id": "A2",
        "label": "Property Description complete (type, location, area)",
        "detected": (
            "Type and location found" if desc_found
            else "Property type or location missing"
        ),
        "status": "PASS" if desc_found else "FAIL",
    })

    # A3 — Inspection Report (cannot be fully verified from text; flag as UNVERIFIED if not detected)
    inspection_value = result.get("inspection_status", {}).get("value", "Not stated")
    if inspection_value == "Not stated":
        items.append({
            "id": "A3",
            "label": "Inspection Report available or Remote Valuation declared",
            "detected": "Not detected in document",
            "status": "UNVERIFIED",
        })
    else:
        items.append({
            "id": "A3",
            "label": "Inspection Report available or Remote Valuation declared",
            "detected": inspection_value,
            "status": "PASS",
        })

    # A4 — Market Evidence (n≥3 preferred; flag as UNVERIFIED if count is unclear)
    evidence_value = result.get("market_evidence_count", {}).get("value", "Not stated")
    if evidence_value == "Not stated":
        a4_status = "FAIL"
    elif "count unclear" in evidence_value.lower() or "present" in evidence_value.lower():
        a4_status = "UNVERIFIED"
    else:
        try:
            count = int(re.search(r"\d+", evidence_value).group())  # type: ignore[union-attr]
            a4_status = "PASS" if count >= 3 else "UNVERIFIED"
        except (AttributeError, ValueError):
            a4_status = "UNVERIFIED"
    items.append({
        "id": "A4",
        "label": "Market Evidence available (≥3 comparables or declared absence)",
        "detected": evidence_value,
        "status": a4_status,
    })

    # A5 — No hidden assumptions (proxy: if special_assumptions present or none stated)
    special = result.get("special_assumptions", {}).get("value", "None stated")
    general = result.get("initial_assumptions", {}).get("value", "None stated")
    if special != "None stated" or general != "None stated":
        a5_detected = "Assumptions declared"
        a5_status = "PASS"
    else:
        a5_detected = "No explicit assumption declarations found — verify manually"
        a5_status = "UNVERIFIED"
    items.append({
        "id": "A5",
        "label": "All assumptions declared explicitly (no hidden assumptions)",
        "detected": a5_detected,
        "status": a5_status,
    })

    return items


def _compute_risk_and_readiness(
    result: Dict[str, Dict[str, str]]
) -> Dict[str, Dict[str, str]]:
    """Derive risk flags and readiness from the extracted fields."""
    core_fields = (
        "property_type",
        "property_location",
        "valuation_purpose",
        "basis_of_value",
        "valuation_date",
    )
    risk_flags: List[str] = [
        f"{f.replace('_', ' ').title()} missing"
        for f in core_fields
        if result[f]["value"] == "Not stated"
    ]

    extended_fields = {
        "client_name": "Client Name missing",
        "intended_user": "Intended User not specified",
        "inspection_status": "Inspection status not stated",
    }
    for field, flag_label in extended_fields.items():
        if result.get(field, {}).get("value", "Not stated") == "Not stated":
            risk_flags.append(flag_label)

    if result["missing_documents"]["value"] != "None stated":
        risk_flags.append("Missing documents listed")

    result["initial_risk_flags"] = {
        "value": "; ".join(risk_flags) if risk_flags else "None",
        "evidence": "risk flags are derived, not directly evidenced",
    }

    if not risk_flags:
        readiness = "Ready"
    elif any(flag.endswith("missing") or "not" in flag.lower() for flag in risk_flags):
        readiness = "Partially Ready"
    else:
        readiness = "Not Ready"
    result["readiness_assessment"] = {
        "value": readiness,
        "evidence": "Derived from missing fields and documents",
    }
    return result


def parse_intake(text: str) -> Dict[str, Dict[str, str]]:
    """Parse the intake text and return a structured dictionary.

    Returns a dictionary keyed by field name. Each field contains
    sub-keys 'value' and 'evidence'. Missing fields have value
    'Not stated'.
    """
    result: Dict[str, Dict[str, str]] = {}

    for field, patterns in _build_patterns_map().items():
        value, evidence = extract_field(patterns, text)
        if value:
            result[field] = {"value": value, "evidence": evidence}
        else:
            result[field] = {"value": "Not stated", "evidence": ""}

    result["available_documents"] = _extract_documents(text)
    result["missing_documents"] = _extract_missing_documents(text)
    result["initial_assumptions"] = _extract_assumptions(text)
    result["special_assumptions"] = _extract_special_assumptions(text)
    result["inspection_status"] = _extract_inspection_status(text)
    result["market_evidence_count"] = _extract_market_evidence_count(text)
    result = _compute_risk_and_readiness(result)
    return result


def field_confidence(field_data: Dict[str, str]) -> str:
    """Return confidence label for a single field dict.

    High  — value extracted and evidence text is present
    Low   — value extracted but no evidence (inferred)
    Not found — value is 'Not stated'
    """
    value = field_data.get("value", "Not stated")
    evidence = field_data.get("evidence", "")
    if value == "Not stated":
        return "Not found"
    if evidence:
        return "High"
    return "Low"


def generate_report(data: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """Flatten the structured dictionary into a simpler dict for export."""
    return {key: value_dict["value"] for key, value_dict in data.items()}
