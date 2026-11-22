"""
Isolated non-volatile test fixture helpers (Mission 51B-1 Round 3.1 / TX-AUDIT-07).

When an independent audit extracts the release archive into a volatile directory such as
`/tmp/audit_extract/...`, paths derived from `REPO_ROOT` or `backend_dir` fall under `/tmp`
and are rightly rejected by production durability validation (`COORDINATOR_VOLATILE_PATH_IN_PRODUCTION`).

These helpers locate a genuinely non-volatile writable directory on the host filesystem
(never under `/tmp`, `/var/tmp`, `/dev/shm`, or `tempfile.gettempdir()`) to create isolated
per-test directories that callers always remove in `finally` blocks — preserving 100% of
production durability checks with zero weakening or `/tmp` whitelisting.
"""

import os
import tempfile
import uuid
from typing import Optional

from app.transaction_safety import _is_volatile_db_path

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))


def find_nonvolatile_writable_root(preferred_root: Optional[str] = None) -> str:
    """
    Return an existing, writable, genuinely non-volatile directory root
    (`not _is_volatile_db_path(root)`).
    """
    candidates = []
    if preferred_root:
        candidates.append(preferred_root)
    candidates.extend([
        _REPO_ROOT,
        os.path.expanduser("~"),
        "/var/data",
        os.getcwd(),
    ])
    seen = set()
    for cand in candidates:
        if not cand:
            continue
        norm = os.path.normpath(os.path.abspath(cand))
        if norm in seen:
            continue
        seen.add(norm)
        if _is_volatile_db_path(norm):
            continue
        if os.path.isdir(norm) and os.access(norm, os.R_OK | os.W_OK | os.X_OK):
            return norm
    raise RuntimeError(
        "No non-volatile writable directory found for production durability test fixture. "
        "Checked repository root, user home, /var/data, and current working directory."
    )


def make_nonvolatile_test_dir(prefix: str = "ks_nonvolatile_test", preferred_root: Optional[str] = None) -> str:
    """Create a unique, isolated, genuinely non-volatile directory for a single test."""
    base = find_nonvolatile_writable_root(preferred_root=preferred_root)
    created = tempfile.mkdtemp(prefix=f".{prefix}_", dir=base)
    if _is_volatile_db_path(created):
        raise AssertionError(f"Fixture directory unexpectedly resolved to volatile path: {created}")
    return created


def nonexistent_nonvolatile_db_path(tag: str = "nonexistent") -> str:
    """
    Return an absolute DB file path whose parent directory is guaranteed to be BOTH
    genuinely non-volatile (never under /tmp, /var/tmp, /dev/shm, or tempdir) AND non-existent.
    """
    unique = f"kawad_swad_nonexistent_{tag}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    candidate = os.path.normpath(os.path.join("/var/data", unique, "coord.db"))
    if _is_volatile_db_path(candidate):
        raise AssertionError(f"Non-existent fixture path unexpectedly volatile: {candidate}")
    return candidate
