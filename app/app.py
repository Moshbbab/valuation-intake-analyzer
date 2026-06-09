"""Streamlit application — ValuationForge Intake Workflow.

Five-step workflow: Upload & Extract → Data Gate → Evidence Register
→ Assumptions Register → Risk & QA Summary.

The Data Gate (Step 2) is a human decision. Auto-detected status from
assess_data_gate() is presented as evidence only; the registered valuer
must make an explicit PASS / FAIL choice for each of the five items
before the gate closes.
"""

import json
import os
import tempfile
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from engine.intake_analyzer import (
    assess_data_gate,
    field_confidence,
    generate_report,
    parse_intake,
    read_file,
)

# ─── Constants ────────────────────────────────────────────────────────────────

STEPS: List[str] = [
    "Upload & Extract",
    "Data Gate",
    "Evidence Register",
    "Assumptions Register",
    "Risk & QA Summary",
]

# Map engine confidence labels to display terms that reflect the source type,
# not an implied quality ranking. "Extracted" means found verbatim; "Inferred"
# means present but required regex heuristics.
_CONFIDENCE_DISPLAY: Dict[str, str] = {
    "High": "Extracted",
    "Low": "Inferred",
    "Not found": "Not found",
}

# Fields surfaced in the Evidence Register (derived risk/readiness fields
# are shown in Step 5 only, not here).
_EVIDENCE_FIELDS: List[str] = [
    "property_type",
    "property_location",
    "valuation_purpose",
    "basis_of_value",
    "valuation_date",
    "client_name",
    "instruction_reference",
    "site_area",
    "intended_user",
    "available_documents",
    "missing_documents",
    "inspection_status",
    "market_evidence_count",
    "special_assumptions",
    "initial_assumptions",
]

_EVIDENCE_STATUSES: List[str] = ["Confirmed", "Queried", "Not found"]
_ASSUMPTION_TYPES: List[str] = ["General", "Special", "Extraordinary"]
_ASSUMPTION_STATUSES: List[str] = ["Pending", "Confirmed", "Flagged"]

# Caveats shown alongside specific derived fields in the Evidence Register.
_FIELD_CAVEATS: Dict[str, str] = {
    "market_evidence_count": (
        "Auto-count only — comparability and quality must be verified independently."
    ),
    "special_assumptions": (
        "Detected in document. Formal Special Assumptions per IVS 104 §200.4 "
        "must be agreed with the client and declared explicitly (Step 4)."
    ),
    "inspection_status": (
        "Status inferred from document text — confirm against actual inspection records."
    ),
}


# ─── Session state ────────────────────────────────────────────────────────────

def _init_session() -> None:
    """Initialise session state keys on first run."""
    defaults: Dict = {
        "step": 1,
        "raw_text": "",
        "data": {},
        "report": {},
        # gate_decisions: gate_id → "PASS" | "FAIL"  (human decision only)
        "gate_decisions": {},
        # evidence_status: field_key → one of _EVIDENCE_STATUSES
        "evidence_status": {},
        # assumptions: list of {Text, Type, Status}
        "assumptions": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _reset_downstream() -> None:
    """Clear gate, evidence, and assumption decisions when a new file is uploaded."""
    st.session_state.gate_decisions = {}
    st.session_state.evidence_status = {}
    st.session_state.assumptions = []


def _gate_result() -> str:
    """Return overall Data Gate outcome: PASS, FAIL, or INCOMPLETE."""
    decisions = st.session_state.gate_decisions
    if len(decisions) < 5:
        return "INCOMPLETE"
    if any(v == "FAIL" for v in decisions.values()):
        return "FAIL"
    return "PASS"


# ─── File I/O ─────────────────────────────────────────────────────────────────

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


# ─── Progress indicator ───────────────────────────────────────────────────────

def render_progress() -> None:
    """Render a step indicator across the top of the page."""
    current = st.session_state.step
    cols = st.columns(len(STEPS))
    for i, (col, label) in enumerate(zip(cols, STEPS), start=1):
        if i < current:
            col.success(f"✓ {i}. {label}")
        elif i == current:
            col.info(f"▶ {i}. {label}")
        else:
            col.markdown(
                f"<span style='color:#aaa'>{i}. {label}</span>",
                unsafe_allow_html=True,
            )
    st.divider()


# ─── Navigation ───────────────────────────────────────────────────────────────

def render_nav(can_proceed: bool = True, proceed_label: str = "Next →") -> None:
    """Render Previous / Next buttons."""
    col_prev, _, col_next = st.columns([1, 4, 1])
    at_first = st.session_state.step <= 1
    at_last = st.session_state.step >= len(STEPS)
    if col_prev.button("← Previous", disabled=at_first, key="nav_prev"):
        st.session_state.step -= 1
        st.rerun()
    if col_next.button(
        proceed_label,
        disabled=(not can_proceed) or at_last,
        key="nav_next",
    ):
        st.session_state.step += 1
        st.rerun()


# ─── Step 1: Upload & Extract ─────────────────────────────────────────────────

def render_step_1() -> None:
    """Upload a document and run intake extraction."""
    st.header("Step 1 — Upload & Extract")
    st.caption(
        "Upload a valuation instruction document (PDF, DOCX, or TXT). "
        "Fields are extracted automatically using keyword and pattern matching. "
        "No valuation opinions or pricing are generated."
    )

    uploaded_file = st.file_uploader(
        "Drag and drop a PDF, DOCX, or TXT file",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
    )

    if uploaded_file:
        with st.spinner("Extracting intake fields…"):
            filepath = save_uploaded_file(uploaded_file)
            if not filepath:
                st.error("Could not save uploaded file.")
                return
            raw_text = read_file(filepath)
            if not raw_text.strip():
                st.warning(
                    "Unable to extract text from this file. "
                    "Please check the format."
                )
                return
            data = parse_intake(raw_text)
            report = generate_report(data)

        st.session_state.raw_text = raw_text
        st.session_state.data = data
        st.session_state.report = report
        _reset_downstream()

        st.subheader("Extracted Fields")
        st.caption(
            "Source Type — **Extracted**: found verbatim in document. "
            "**Inferred**: present but required heuristic matching. "
            "**Not found**: absent from document."
        )
        rows = []
        for field in _EVIDENCE_FIELDS:
            if field not in data:
                continue
            conf = field_confidence(data[field])
            source_type = _CONFIDENCE_DISPLAY.get(conf, conf)
            caveat = _FIELD_CAVEATS.get(field, "")
            rows.append({
                "Field": field.replace("_", " ").title(),
                "Value": data[field]["value"],
                "Source Type": source_type,
                "Note": caveat,
            })
        st.dataframe(
            pd.DataFrame(rows), use_container_width=True, hide_index=True
        )

    can_proceed = bool(st.session_state.data)
    if not can_proceed:
        st.info("Upload a document to continue.")
    render_nav(can_proceed=can_proceed)


# ─── Step 2: Data Gate ────────────────────────────────────────────────────────

def render_step_2() -> None:
    """Data Gate: the valuer makes an explicit PASS / FAIL decision per item."""
    st.header("Step 2 — Data Gate")
    st.caption(
        "Review each gate item. The auto-detected status (based on document "
        "text) is shown as evidence only. **Your decision (PASS / FAIL) is the "
        "only one that counts.** All five items require an explicit choice."
    )
    st.info(
        "⚖️ **Ownership:** This gate records a professional decision by the "
        "registered valuer. Auto-detection does not constitute a determination "
        "under IVS 102 or RICS VPS 1. The audit trail will record your choices.",
        icon=None,
    )

    data = st.session_state.data
    gate_items = assess_data_gate(data)
    all_decided = True

    for item in gate_items:
        gid = item["id"]
        with st.expander(f"{gid} — {item['label']}", expanded=True):
            col_detect, col_decide = st.columns([2, 1])

            # Auto-detected evidence (read-only)
            auto = item["status"]
            if auto == "PASS":
                col_detect.success(f"Auto-detected: {item['detected']}")
            elif auto == "FAIL":
                col_detect.error(f"Auto-detected: {item['detected']}")
            else:
                col_detect.warning(
                    f"Auto-detected: {item['detected']} "
                    "(cannot verify from document text alone — confirm manually)"
                )

            # Human decision — no default (index=None forces explicit selection)
            stored = st.session_state.gate_decisions.get(gid)
            options = ["PASS", "FAIL"]
            default_idx = options.index(stored) if stored in options else None
            decision = col_decide.radio(
                "Your decision",
                options=options,
                index=default_idx,
                key=f"gate_{gid}",
                horizontal=True,
            )
            if decision:
                st.session_state.gate_decisions[gid] = decision
            else:
                all_decided = False

    st.divider()
    result = _gate_result()
    if result == "PASS":
        st.success("✓ Data Gate: PASS — all items confirmed. Proceed to evidence review.")
    elif result == "FAIL":
        st.error(
            "✗ Data Gate: FAIL — one or more items failed. "
            "Proceed only to document deficiencies. Do not issue a final valuation."
        )
    else:
        st.warning("All five items require an explicit decision before you can proceed.")
        all_decided = False

    render_nav(can_proceed=all_decided)


# ─── Step 3: Evidence Register ────────────────────────────────────────────────

def _build_evidence_df(data: dict) -> pd.DataFrame:
    """Build the initial evidence register DataFrame from extracted data."""
    rows = []
    for field in _EVIDENCE_FIELDS:
        if field not in data:
            continue
        conf = field_confidence(data[field])
        source_type = _CONFIDENCE_DISPLAY.get(conf, conf)
        # Pre-suggest status based on source type; user adjusts as needed.
        stored = st.session_state.evidence_status.get(field)
        if stored:
            status = stored
        elif source_type == "Extracted":
            status = "Confirmed"
        elif source_type == "Inferred":
            status = "Queried"
        else:
            status = "Not found"
        evidence_text = data[field].get("evidence", "") or "—"
        rows.append({
            "_key": field,
            "Field": field.replace("_", " ").title(),
            "Value": data[field]["value"],
            "Source Type": source_type,
            "Evidence": evidence_text,
            "Status": status,
        })
    return pd.DataFrame(rows)


def render_step_3() -> None:
    """Evidence Register: confirm, query, or flag each extracted field."""
    st.header("Step 3 — Evidence Register")
    st.caption(
        "Status is pre-suggested based on source type. "
        "**Confirmed** = you have verified this value against source documents. "
        "**Queried** = requires follow-up. "
        "**Not found** = information is absent. Adjust any row as needed."
    )

    data = st.session_state.data
    df = _build_evidence_df(data)

    display_df = df.drop(columns=["_key"])
    edited = st.data_editor(
        display_df,
        column_config={
            "Field": st.column_config.TextColumn("Field", disabled=True),
            "Value": st.column_config.TextColumn("Value", disabled=True),
            "Source Type": st.column_config.TextColumn("Source Type", disabled=True),
            "Evidence": st.column_config.TextColumn("Evidence", disabled=True),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=_EVIDENCE_STATUSES, required=True
            ),
        },
        use_container_width=True,
        hide_index=True,
        key="evidence_editor",
    )

    # Persist status decisions back to session state using original field keys
    keys = df["_key"].tolist()
    for i, field_key in enumerate(keys):
        if i < len(edited):
            status_val = edited.iloc[i]["Status"]
            if status_val:
                st.session_state.evidence_status[field_key] = status_val

    # Show field-specific caveats for sensitive fields
    for field, caveat in _FIELD_CAVEATS.items():
        if field in data and data[field]["value"] != "Not stated":
            st.caption(f"⚠️ **{field.replace('_', ' ').title()}**: {caveat}")

    queried_count = (edited["Status"] == "Queried").sum()
    if queried_count > 0:
        st.warning(
            f"{queried_count} field(s) marked Queried — "
            "follow up required before finalising the report."
        )

    render_nav(can_proceed=True)


# ─── Step 4: Assumptions Register ─────────────────────────────────────────────

def _seed_assumptions(data: dict) -> None:
    """Populate assumptions register from detected fields if not yet seeded."""
    if st.session_state.assumptions:
        return
    detected: List[Dict] = []
    for field, assumption_type in (
        ("initial_assumptions", "General"),
        ("special_assumptions", "Special"),
    ):
        value = data.get(field, {}).get("value", "None stated")
        if value != "None stated":
            for part in value.split(";"):
                text = part.strip()
                if text:
                    detected.append({
                        "Text": text,
                        "Type": assumption_type,
                        "Status": "Pending",
                    })
    st.session_state.assumptions = detected


def render_step_4() -> None:
    """Assumptions Register: confirm detected assumptions and add new ones."""
    st.header("Step 4 — Assumptions Register")
    st.caption(
        "Assumptions detected in the document are listed below. "
        "Confirm each one, flag it for review, or remove it if incorrect. "
        "Use the empty row at the bottom to add assumptions not captured automatically."
    )
    st.info(
        "📋 **IVS 104 \xa7200.4:** Special Assumptions must be formally agreed with "
        "the client and clearly disclosed in the report. Extraction from a document "
        "is not a substitute for that formal agreement.",
        icon=None,
    )

    data = st.session_state.data
    _seed_assumptions(data)

    assumptions_df = pd.DataFrame(
        st.session_state.assumptions or [],
        columns=["Text", "Type", "Status"],
    )

    edited = st.data_editor(
        assumptions_df,
        column_config={
            "Text": st.column_config.TextColumn(
                "Assumption Text", width="large", required=True
            ),
            "Type": st.column_config.SelectboxColumn(
                "Type", options=_ASSUMPTION_TYPES, required=True
            ),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=_ASSUMPTION_STATUSES, required=True
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="assumptions_editor",
    )

    st.session_state.assumptions = edited.to_dict("records")

    flagged_count = (edited["Status"] == "Flagged").sum()
    if flagged_count > 0:
        st.warning(
            f"{flagged_count} assumption(s) flagged — "
            "resolve before issuing the report."
        )

    render_nav(can_proceed=True)


# ─── Step 5: Risk & QA Summary ────────────────────────────────────────────────

def _render_export(report: dict) -> None:
    """Render the export section."""
    st.subheader("Export")
    export_payload = {
        "intake_fields": report,
        "data_gate_result": _gate_result(),
        "gate_decisions": st.session_state.gate_decisions,
        "evidence_status": st.session_state.evidence_status,
        "assumptions": st.session_state.assumptions,
    }
    st.download_button(
        label="Download Intake Report (JSON)",
        data=json.dumps(export_payload, indent=2),
        file_name="valuation_intake_report.json",
        mime="application/json",
    )
    st.caption("Word export (.docx) — available in a future release.")


def render_step_5() -> None:
    """Risk flags, readiness assessment, evidence summary, and export."""
    st.header("Step 5 — Risk & QA Summary")

    report = st.session_state.report
    gate_result = _gate_result()

    # Gate banner
    if gate_result == "PASS":
        st.success(f"Data Gate: {gate_result}")
    elif gate_result == "FAIL":
        st.error(
            f"Data Gate: {gate_result} — "
            "this file must not be issued as a final valuation report."
        )
    else:
        st.warning(f"Data Gate: {gate_result}")

    st.divider()

    # Risk flags
    st.subheader("Risk Flags")
    risk_value = report.get("initial_risk_flags", "None")
    if risk_value == "None":
        st.success("No risk flags detected.")
    else:
        for flag in risk_value.split(";"):
            flag = flag.strip()
            if flag:
                st.warning(f"⚠ {flag}")

    st.divider()

    # Readiness
    st.subheader("Readiness Assessment")
    readiness = report.get("readiness_assessment", "Unknown")
    if readiness == "Ready":
        st.success(f"**{readiness}**")
    elif readiness == "Partially Ready":
        st.warning(f"**{readiness}**")
    else:
        st.error(f"**{readiness}**")

    st.divider()

    # Evidence summary
    st.subheader("Evidence Status Summary")
    ev = st.session_state.evidence_status
    if ev:
        confirmed = sum(1 for v in ev.values() if v == "Confirmed")
        queried = sum(1 for v in ev.values() if v == "Queried")
        not_found = sum(1 for v in ev.values() if v == "Not found")
        c1, c2, c3 = st.columns(3)
        c1.metric("Confirmed", confirmed)
        c2.metric("Queried", queried)
        c3.metric("Not Found", not_found)
    else:
        st.info("No evidence status recorded — return to Step 3 to complete.")

    st.divider()

    # Assumptions
    st.subheader("Assumptions Register")
    assumptions = st.session_state.assumptions
    if assumptions:
        st.dataframe(
            pd.DataFrame(assumptions), use_container_width=True, hide_index=True
        )
        special_count = sum(
            1 for a in assumptions if a.get("Type") == "Special"
        )
        if special_count > 0:
            st.caption(
                f"⚠️ {special_count} Special Assumption(s) declared. "
                "Confirm client agreement per IVS 104 \xa7200.4 before signing."
            )
    else:
        st.info(
            "No assumptions recorded — return to Step 4 to complete."
        )

    st.divider()
    _render_export(report)

    # Previous-only navigation on last step
    if st.button("← Previous", key="nav_prev_5"):
        st.session_state.step -= 1
        st.rerun()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the ValuationForge intake workflow."""
    st.set_page_config(
        page_title="ValuationForge — Intake Analyzer", layout="wide"
    )
    st.title("ValuationForge — Valuation Intake Analyzer")

    _init_session()
    render_progress()

    step = st.session_state.step
    if step == 1:
        render_step_1()
    elif step == 2:
        render_step_2()
    elif step == 3:
        render_step_3()
    elif step == 4:
        render_step_4()
    elif step == 5:
        render_step_5()


if __name__ == "__main__":
    main()
