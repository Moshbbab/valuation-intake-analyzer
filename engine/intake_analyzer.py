"""Core intake analysis logic for the Valuation Intake Analyzer.

The functions in this module are deliberately simple and rule-based.
They extract structured information from the raw text of valuation
request documents and report missing or unclear fields without making
any assumptions about value or pricing.

Key design principles:
  Transparency: each piece of information is either extracted directly
    from the source or marked as missing.
  Separation of concerns: text parsing, field extraction, risk assessment,
    and report assembly are kept in distinct functions to facilitate unit
    testing and future expansion.
  Extensibility: the simple heuristics can be replaced by more
    sophisticated NLP pipelines in future iterations without affecting
    the Streamlit UI.

This module does not depend on Streamlit and can be imported into other
contexts (e.g. command-line scripts or tests).
"""

import os
import re
from typing import Dict, List, Tuple

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
    except Exception:
        pass
    return " ".join(text_parts)


def read_docx(path: str) -> str:
    """Extract text from a Word .docx file using python-docx."""
    if Document is None:
        return ""
    try:
        doc = Document(path)
    except Exception:
        return ""
    paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(paragraphs)


def read_plain(path: str) -> str:
    """Read plain text from a file with UTF-8 or fallback encodings."""
    for encoding in ("utf-8", "latin-1", "windows-1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except Exception:
            continue
    return ""


def read_file(path: str) -> str:
    """Detect the file type by extension and return its textual contents."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".pdf":
        return read_pdf(path)
    elif ext in (".docx",):
        return read_docx(path)
    else:
        return read_plain(path)


def extract_field(
    patterns: List[str], text: str
) -> Tuple[str, str]:
    """Search for the first occurrence of any pattern and return the captured value."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group("value").strip()
            return value, match.group(0).strip()
    return "", ""


def parse_intake(text: str) -> Dict[str, Dict[str, str]]:
    """Parse the intake text and return a structured dictionary with extracted fields."""
    result: Dict[str, Dict[str, str]] = {}

    patterns_map: Dict[str, List[str]] = {
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
    }

    for field, patterns in patterns_map.items():
        value, evidence = extract_field(patterns, text)
        if value:
            result[field] = {"value": value, "evidence": evidence}
        else:
            result[field] = {"value": "Not stated", "evidence": ""}

    # Documents section
    documents_section = re.search(
        r"documents[\s\S]*?provided[^:\n]*:?([\s\S]*?)(?:\n\n|$)",
        text, re.IGNORECASE
    )
    documents: List[str] = []
    if documents_section:
        raw_section = documents_section.group(1).split("\n", 10)
        for item in re.split(r"[,;\n]", documents_section.group(0)):
            cleaned = item.strip(" -\t")
            if cleaned:
                documents.append(cleaned)
    result["available_documents"] = {
        "value": ", ".join(documents) if documents else "None stated",
        "evidence": documents_section.group(0).split("\n", 10)[0].strip() if documents_section else "",
    }

    # Missing documents
    missing_match = re.search(r"missing[\s_-]*documents?[:\s]+(?P<value>[^\n]+)", text, re.IGNORECASE)
    if missing_match:
        missing_docs = [d.strip() for d in re.split(r"[,;]", missing_match.group("value")) if d.strip()]
        missing_value = ", ".join(missing_docs)
        missing_evidence = missing_match.group(0).strip()
    else:
        missing_value = "None stated"
        missing_evidence = ""
    result["missing_documents"] = {"value": missing_value, "evidence": missing_evidence}

    # Assumptions
    assumptions: List[str] = []
    for match in re.finditer(r"assumptions?[:\s]+(?P<value>[^\n]+)", text, re.IGNORECASE):
        assumptions.append(match.group("value").strip())
    result["initial_assumptions"] = {
        "value": "; ".join(assumptions) if assumptions else "None stated",
        "evidence": "; ".join(m.group(0).strip() for m in re.finditer(r"assumptions?[:\s]+(?P<value>[^\n]+)", text, re.IGNORECASE)),
    }

    # Risk flags
    risk_flags: List[str] = []
    for field in ("property_type", "property_location", "valuation_purpose", "basis_of_value", "valuation_date"):
        if result[field]["value"] == "Not stated":
            risk_flags.append(f"{field.replace('_', ' ').title()} missing")
    if result["missing_documents"]["value"] != "None stated":
        risk_flags.append("Missing documents listed")
    result["initial_risk_flags"] = {
        "value": "; ".join(risk_flags) if risk_flags else "None",
        "evidence": "risk flags are derived, not directly evidenced",
    }

    # Readiness assessment
    if not risk_flags:
        readiness = "Ready"
    elif any(flag.endswith("missing") for flag in risk_flags):
        readiness = "Partially Ready"
    else:
        readiness = "Not Ready"
    result["readiness_assessment"] = {
        "value": readiness,
        "evidence": "Derived from missing fields and documents",
    }

    return result


def generate_report(data: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """Flatten the structured dictionary into a simpler dict for export."""
    return {key: value_dict["value"] for key, value_dict in data.items()}
