"""Root application wrapper for cPanel and other WSGI servers."""

import sys
from pathlib import Path


# Make the src-layout package importable after installing requirements only.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slicing_dashboard.app import app as dash_app


# Expose the Flask WSGI callable using common hosting entry point names.
app = dash_app.server
server = app
application = app


if __name__ == "__main__":
    dash_app.run(debug=False)
