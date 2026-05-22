# Valuation Intake Analyzer

[![Pylint](https://github.com/Moshbbab/valuation-intake-analyzer/actions/workflows/pylint.yml/badge.svg)](https://github.com/Moshbbab/valuation-intake-analyzer/actions/workflows/pylint.yml)
[![Python application](https://github.com/Moshbbab/valuation-intake-analyzer/actions/workflows/python-app.yml/badge.svg)](https://github.com/Moshbbab/valuation-intake-analyzer/actions/workflows/python-app.yml)

A minimal internal tool designed to help real estate valuation teams quickly assess the completeness of incoming valuation requests.

The application accepts simple files such as PDFs, Word documents, or plain text and extracts key intake information to produce a structured readiness and risk summary. It focuses strictly on intake analysis and **does not perform any valuation calculations or pricing**.

---

## What It Does

Upload a valuation request in PDF, Word (.docx), or plain text format. The tool will:

1. Parse the document and identify key intake fields:
   - Property Type
   - Property Location
   - Valuation Purpose
   - Basis of Value
   - Valuation Date
   - Available Documents
   - Missing Documents
   - Initial Assumptions
   - Initial Risk Flags
   - Readiness Assessment (Ready / Partially Ready / Not Ready)

2. Display a structured summary panel showing facts, assumptions, and inferences separately.
3. Provide a download button for the generated report as a JSON file.

---

## What It Does Not Do

- It does not compute or opine on property values.
- It does not make judgments about market conditions, pricing, or valuation methodology beyond listing the basis of value.
- It does not over-engineer the architecture — this is an MVP intended to be clear, maintainable, and easy to extend.

---

## Directory Structure

```
valuation-intake-analyzer/
├── app/
│   └── app.py                  # Streamlit user interface
├── engine/
│   ├── __init__.py
│   └── intake_analyzer.py      # Core extraction and analysis logic
├── templates/
│   └── README.md               # Placeholder for future report templates
├── tests/
│   └── test_intake_analyzer.py # Unit tests for engine
├── .github/
│   └── workflows/
│       ├── pylint.yml            # Code quality check
│       └── python-app.yml        # Build and test
├── README.md                   # This file
└── requirements.txt            # Python dependencies
```

---

## Installation

1. Clone the repository or copy the folder into your environment.
2. Install dependencies. Create a virtual environment if desired, then run:

```bash
pip install -r requirements.txt
```

3. Run the application:

```bash
streamlit run app/app.py
```

---

## Usage

1. Open the web interface (usually at `http://localhost:8501`).
2. Drag and drop a PDF, Word document, or text file into the upload area.
3. The tool will parse the file and display a structured summary.
4. Review the Facts, Assumptions, and Inferences sections. Missing or unclear fields are explicitly labeled.
5. Download the summary report as JSON if desired.

---

## Running Tests

```bash
pip install pytest
pytest tests/
```

---

## Current Limitations

- The extraction logic relies on simple keyword and regex matching — it may miss information if the document uses unusual phrasing.
- Only basic file formats (PDF, DOCX, plain text) are supported.
- Complex email formats or scanned images are out of scope for this MVP.
- The tool does not cross-validate data against external databases.

---

## Next Steps

- Improve NLP extraction using more sophisticated libraries (e.g. spaCy or ML models).
- Add support for scanned documents using OCR.
- Implement user authentication and multi-user work queues.
- Add more automated unit tests under `tests/`.
