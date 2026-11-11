"""
Database package for Kawad Swad ERP.
Exports PostgresDatabase and get_postgres_db for transactional row-level locking.
"""

from .postgres_database import PostgresDatabase, get_postgres_db

__all__ = [
    "PostgresDatabase",
    "get_postgres_db",
]
