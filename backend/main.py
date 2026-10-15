"""
Kawad Swad Sales Management - Root Entrypoint
Allows running both:
  - uvicorn app.main:app
  - uvicorn main:app
"""
from app.main import app, db

__all__ = ["app", "db"]
