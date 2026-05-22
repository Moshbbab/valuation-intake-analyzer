"""Streamlit application for the Valuation Intake Analyzer.

This script provides a minimal user interface for uploading valuation
request documents, running the intake analysis, and viewing the results.
"""

import json
import os
import tempfile
from typing import Optional

import pandas as pd
import streamlit as st

from engine.intake_analyzer import read_file, parse_intake, generate_report


def save_uploaded_file(uploaded_file) -> Optional[str]:
    """Save uploaded file to a temporary location and return the path."""
    if uploaded_file is None:
        return None

    uploads_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, dir=uploads_dir
    ) as tmp:
        tmp.write(uploaded_file.getbuffer())
        return tmp.name


def render_intake_summary(data: dict, report: dict) -> None:
    """Render the structured intake summary and detailed evidence."""
    st.subheader("Structured Intake Summary")
    df = pd.DataFrame(
        [report],
        columns=list(report.keys()),
    )
    st.table(df)

    st.subheader("Detailed Evidence and Notes")
    for field, info in data.items():
        with st.expander(field.replace("_", " ").title()):
            st.write("**Value:**", info["value"])
            if info.get("evidence"):
                st.write("**Evidence:**", info["evidence"])
            else:
                st.write("_No direct evidence — value inferred or not stated._")


def main() -> None:
    """Run the Streamlit application."""
    st.set_page_config(page_title="Valuation Intake Analyzer", layout="wide")
    st.title("Valuation Intake Analyzer")
    st.markdown(
        "Upload a valuation request (PDF, Word document, or plain text) "
        "and this tool will extract key intake information and highlight "
        "missing elements. It does not provide valuation opinions or "
        "pricing \u2014 it purely assesses document completeness and "
        "initial risk."
    )

    uploaded_file = st.file_uploader(
        "Drag and drop a PDF, DOCX, or TXT file",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
    )

    if uploaded_file:
        with st.spinner("Processing document..."):
            filepath = save_uploaded_file(uploaded_file)
            if not filepath:
                st.error("Could not save uploaded file.")
                return

            raw_text = read_file(filepath)
            if not raw_text.strip():
                st.warning(
                    "Unable to extract text from the file. "
                    "Please check the file format."
                )
                return

            data = parse_intake(raw_text)
            report = generate_report(data)

        render_intake_summary(data, report)

        json_data = json.dumps(report, indent=2)
        st.download_button(
            label="Download Report as JSON",
            data=json_data,
            file_name="valuation_intake_report.json",
            mime="application/json",
        )


if __name__ == "__main__":
    main()
