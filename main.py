"""
Kawad Swad Sales Management - Root Entrypoint Fallback
Allows Render web service to build and run seamlessly regardless of whether
'Root Directory' in Render dashboard is set to 'backend' or left blank.
"""
import sys
import os

backend_path = os.path.join(os.path.dirname(__file__), "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.main import app, db  # noqa: F401

__all__ = ["app", "db"]
