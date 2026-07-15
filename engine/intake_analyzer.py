"""Core intake analysis logic for the Valuation Intake Analyzer."""

import os
import re
from typing import Any, Dict, List, Tuple

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover
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
        with open(path, "rb") as file_obj:
            reader = PdfReader(file_obj)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
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
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def read_plain(path: str) -> str:
    """Read plain text from a file with UTF-8 or fallback encodings."""
    for encoding in ("utf-8", "latin-1", "windows-1252"):
        try:
            with open(path, "r", encoding=encoding) as file_obj:
                return file_obj.read()
        except OSError:
            continue
    return ""


def read_file(path: str) -> str:
    """Detect the file type by extension and return its textual contents."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".docx":
        return read_docx(path)
    return read_plain(path)


def extract_field(patterns: List[str], text: str) -> Tuple[str, str]:
    """Search for the first pattern match and return the captured value."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group("value").strip()
            return value, match.group(0).strip()
    return "", ""


def _build_patterns_map() -> Dict[str, List[str]]:
    """Return regex patterns used to extract each intake field."""
    return {
        "property_type": [r"property[\s_-]*type[:\s]+(?P<value>[^\n]+)"],
        "property_location": [
            r"property[\s_-]*location[:\s]+(?P<value>[^\n]+)",
            r"location[:\s]+(?P<value>[^\n]+)",
        ],
        "valuation_purpose": [
            r"valuation[\s_-]*purpose[:\s]+(?P<value>[^\n]+)",
            r"purpose[:\s]+(?P<value>[^\n]+)",
        ],
        "basis_of_value": [
            r"basis[\s_-]*of[\s_-]*value[:\s]+(?P<value>[^\n]+)",
            r"basis[:\s]+(?P<value>[^\n]+)",
        ],
        "valuation_date": [
            r"valuation[\s_-]*date[:\s]+(?P<value>[^\n]+)",
            r"date[:\s]+(?P<value>[^\n]+)",
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
    return {"value": ", ".join(documents) if documents else "None stated", "evidence": evidence}


def _extract_missing_documents(text: str) -> Dict[str, str]:
    match = re.search(r"missing[\s_-]*documents?[:\s]+(?P<value>[^\n]+)", text, re.IGNORECASE)
    if not match:
        return {"value": "None stated", "evidence": ""}
    docs = [item.strip() for item in re.split(r"[,;]", match.group("value")) if item.strip()]
    return {"value": ", ".join(docs), "evidence": match.group(0).strip()}


def _extract_assumptions(text: str) -> Dict[str, str]:
    """Extract general assumptions without duplicating special assumptions."""
    pattern = r"^[ \t]*(?!special[\s_-]*assumptions?\b)assumptions?[ \t]*:[ \t]*(?P<value>[^\n]+)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
    return {
        "value": "; ".join(m.group("value").strip() for m in matches) if matches else "None stated",
        "evidence": "; ".join(m.group(0).strip() for m in matches),
    }


def _extract_special_assumptions(text: str) -> Dict[str, str]:
    pattern = r"special[\s_-]*assumptions?[:\s]+(?P<value>[^\n]+)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    return {
        "value": "; ".join(m.group("value").strip() for m in matches) if matches else "None stated",
        "evidence": "; ".join(m.group(0).strip() for m in matches),
    }


def _extract_inspection_status(text: str) -> Dict[str, str]:
    for pattern in (
        r"remote[\s_-]*valuation",
        r"desktop[\s_-]*(?:valuation|review)",
        r"no[\s_-]*(?:physical[\s_-]*)?inspection",
        r"inspection[\s_-]*not[\s_-]*(?:carried[\s_-]*out|performed)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return {"value": "Remote (declared)", "evidence": match.group(0).strip()}
    for pattern in (
        r"inspection[\s_-]*(?:was[\s_-]*)?(?:carried[\s_-]*out|performed|conducted|date)[:\s]*(?P<value>[^\n]+)",
        r"inspected[\s_-]*on[:\s]*(?P<value>[^\n]+)",
        r"site[\s_-]*visit[:\s]*(?P<value>[^\n]+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return {"value": f"Performed — {match.group('value').strip()}", "evidence": match.group(0).strip()}
    return {"value": "Not stated", "evidence": ""}


def _extract_market_evidence_count(text: str) -> Dict[str, str]:
    matches = list(re.finditer(r"comparable[\s_-]*(?:no\.?|#|[0-9]+|transaction)", text, re.IGNORECASE))
    if matches:
        count = len(matches)
        return {"value": f"{count} reference(s) detected", "evidence": f"{count} comparable reference(s) found in document"}
    for keyword in (
        r"market[\s_-]*evidence",
        r"sales?[\s_-]*(?:evidence|comparison|transaction)",
        r"(?:recent|comparable)[\s_-]*(?:sale|transaction|deal)",
    ):
        if re.search(keyword, text, re.IGNORECASE):
            return {"value": "Present (count unclear)", "evidence": keyword}
    return {"value": "Not stated", "evidence": ""}


def assess_data_gate(result: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    """Return Data Gate items with explicit PASS/FAIL/UNVERIFIED states."""
    items: List[Dict[str, Any]] = []

    toe_fields = ("basis_of_value", "valuation_purpose", "intended_user")
    toe_found = all(result.get(field, {}).get("value", "Not stated") != "Not stated" for field in toe_fields)
    items.append({
        "id": "A1",
        "label": "Terms of Engagement reviewed (Basis of Value, Purpose, Intended User stated)",
        "detected": "Key ToE fields found" if toe_found else "One or more ToE fields missing",
        "status": "PASS" if toe_found else "FAIL",
    })

    desc_fields = ("property_type", "property_location")
    desc_found = all(
        result.get(field, {}).get("value", "Not stated") != "Not stated"
        for field in desc_fields
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

    inspection_value = result.get("inspection_status", {}).get("value", "Not stated")
    items.append({
        "id": "A3",
        "label": "Inspection Report available or Remote Valuation declared",
        "detected": "Not detected in document" if inspection_value == "Not stated" else inspection_value,
        "status": "UNVERIFIED" if inspection_value == "Not stated" else "PASS",
    })

    evidence_value = result.get("market_evidence_count", {}).get("value", "Not stated")
    if evidence_value == "Not stated":
        a4_status = "FAIL"
    elif "count unclear" in evidence_value.lower() or "present" in evidence_value.lower():
        a4_status = "UNVERIFIED"
    else:
        match = re.search(r"\d+", evidence_value)
        a4_status = "PASS" if match and int(match.group()) >= 3 else "UNVERIFIED"
    items.append({
        "id": "A4",
        "label": "Market Evidence available (≥3 comparables or declared absence)",
        "detected": evidence_value,
        "status": a4_status,
    })

    special = result.get("special_assumptions", {}).get("value", "None stated")
    general = result.get("initial_assumptions", {}).get("value", "None stated")
    assumptions_declared = special != "None stated" or general != "None stated"
    items.append({
        "id": "A5",
        "label": "All assumptions declared explicitly (no hidden assumptions)",
        "detected": "Assumptions declared" if assumptions_declared else "No explicit assumption declarations found — verify manually",
        "status": "PASS" if assumptions_declared else "UNVERIFIED",
    })
    return items


def _compute_risk_and_readiness(result: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    core_fields = ("property_type", "property_location", "valuation_purpose", "basis_of_value", "valuation_date")
    risk_flags = [
        f"{field.replace('_', ' ').title()} missing"
        for field in core_fields
        if result[field]["value"] == "Not stated"
    ]
    extended_fields = {
        "client_name": "Client Name missing",
        "intended_user": "Intended User not specified",
        "inspection_status": "Inspection status not stated",
    }
    for field, label in extended_fields.items():
        if result.get(field, {}).get("value", "Not stated") == "Not stated":
            risk_flags.append(label)
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
    """Parse intake text into structured values and source evidence."""
    result: Dict[str, Dict[str, str]] = {}
    for field, patterns in _build_patterns_map().items():
        value, evidence = extract_field(patterns, text)
        result[field] = {"value": value or "Not stated", "evidence": evidence}
    result["available_documents"] = _extract_documents(text)
    result["missing_documents"] = _extract_missing_documents(text)
    result["initial_assumptions"] = _extract_assumptions(text)
    result["special_assumptions"] = _extract_special_assumptions(text)
    result["inspection_status"] = _extract_inspection_status(text)
    result["market_evidence_count"] = _extract_market_evidence_count(text)
    return _compute_risk_and_readiness(result)


def field_confidence(field_data: Dict[str, str]) -> str:
    value = field_data.get("value", "Not stated")
    evidence = field_data.get("evidence", "")
    if value == "Not stated":
        return "Not found"
    return "High" if evidence else "Low"


def generate_report(data: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    return {key: value_dict["value"] for key, value_dict in data.items()}
