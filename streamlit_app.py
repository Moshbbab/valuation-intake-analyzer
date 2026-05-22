"""Entry point for Streamlit Cloud deployment.

Streamlit Cloud looks for the app file in the repository root.
This file simply imports and runs the main application from the app module.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.app import main  # noqa: E402

if __name__ == "__main__":
    main()
else:
    main()
