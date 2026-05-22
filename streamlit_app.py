"""Entry point for Streamlit Cloud deployment.

Streamlit Cloud looks for the app file in the repository root.
This file imports and runs the main application from the app module.
"""
from app.app import main  # pylint: disable=import-error

main()
