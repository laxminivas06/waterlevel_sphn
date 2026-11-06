"""
wsgi.py - PythonAnywhere WSGI Application Entrypoint

Exposes PEP 3333 'application' callable with absolute path resolution
to avoid PythonAnywhere '/var/www' or '/home/<user>' working directory traps.
"""

import os
import sys

# Compute project root directory absolutely
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# Ensure project root is first in sys.path
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app

# PythonAnywhere looks for the WSGI callable named 'application'
application = create_app()

if __name__ == "__main__":
    # Local development server execution
    application.run(host="127.0.0.1", port=5000, debug=False)
