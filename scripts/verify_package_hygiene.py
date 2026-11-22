#!/usr/bin/env python3
"""
Kawad Swad ERP — Mission 51B-1 Round 2 Package Hygiene & Integrity Verifier.

Validates a release ZIP archive (and/or workspace root) for:
1. ZIP structural integrity (`testzip() is None`).
2. Complete absence of forbidden artifacts:
   - Accidental AI Studio prompt uploads (`public/assets/aistudio/`, `Paste_*`)
   - Local `.env` files (except `.env.example`), secrets, private keys, service accounts
   - Runtime SQLite DB / WAL / SHM files (`*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite*`)
   - Caches, build outputs, temp locks (`__pycache__`, `*.pyc`, `node_modules`, `dist`, `.pytest_cache`)
   - Nested archives (`*.zip`, `*.tar*`) and `.git/`
3. Presence of mandatory Round 2 source, config, test, and report files.
4. Deterministic SHA-256 checksum, byte size, file count, and UTC timestamp.

Usage:
  python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round2_Audit_Package.zip
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import sys
import zipfile
from datetime import datetime, timezone
from typing import Dict, List, Tuple

REQUIRED_ROUND2_FILES = [
    "backend/app/transaction_safety.py",
    "backend/app/accounting/transaction_coordinator.py",
    "backend/app/apps_script_bridge.py",
    "backend/app/config.py",
    "backend/app/routers/sales.py",
    "backend/app/routers/v2_erp.py",
    "backend/tests/test_mission51b1_transaction_safety.py",
    "backend/tests/test_mission51b1_round2_integrity.py",
    "scripts/verify_package_hygiene.py",
    "render.yaml",
    ".env.example",
    "docs/MISSION_51B1_ROUND2_REPAIR_REPORT.md",
    "docs/MISSION_51B1_ROUND2_README.md",
]

REQUIRED_ROUND3_FILES = REQUIRED_ROUND2_FILES + [
    "backend/tests/test_mission51b1_round3_lease_enforcement.py",
    "docs/MISSION_51B1_ROUND3_REPAIR_REPORT.md",
    "docs/MISSION_51B1_ROUND3_README.md",
]

REQUIRED_ROUND31_FILES = REQUIRED_ROUND3_FILES + [
    "backend/tests/_durability_test_helpers.py",
    "backend/tests/test_mission51b1_round31_repairs.py",
    "docs/MISSION_51B1_ROUND31_REPAIR_REPORT.md",
    "docs/MISSION_51B1_ROUND31_README.md",
]

ROOT_LAYOUT_ANCHORS = (
    "backend/app/main.py",
    "render.yaml",
    ".env.example",
    "package.json",
)

FORBIDDEN_PATH_SEGMENTS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    ".venv",
    "venv",
    "aistudio",
}

FORBIDDEN_EXTENSIONS = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".zip",
    ".tar",
    ".gz",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)

FORBIDDEN_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".DS_Store",
    "Thumbs.db",
}

FORBIDDEN_NAME_PATTERNS = [
    re.compile(r"^Paste_", re.IGNORECASE),
    re.compile(r"service[-_]?account.*\.json$", re.IGNORECASE),
    re.compile(r"credentials.*\.json$", re.IGNORECASE),
    re.compile(r"\.env\.(?!example$)", re.IGNORECASE),
]

# Detect real leaked private key bodies (must contain actual base64 body lines, not regex/placeholder strings)
PRIVATE_KEY_LEAK_RE = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{24,}"
)


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_member_path(member_path: str) -> str:
    norm = posixpath.normpath(member_path.replace("\\", "/"))
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.lstrip("/")
    return norm


def check_member_hygiene(member_path: str) -> List[str]:
    """Return list of hygiene violation reasons for a normalized POSIX path inside archive/tree."""
    norm = _normalize_member_path(member_path)
    if not norm or norm == ".":
        return []
    violations: List[str] = []
    parts = [p for p in norm.split("/") if p]
    base = parts[-1] if parts else norm

    for seg in parts:
        if seg in FORBIDDEN_PATH_SEGMENTS:
            violations.append(f"forbidden_directory_segment:{seg} ({norm})")
            break

    if base in FORBIDDEN_BASENAMES:
        violations.append(f"forbidden_basename:{base} ({norm})")

    lower_base = base.lower()
    for ext in FORBIDDEN_EXTENSIONS:
        if lower_base.endswith(ext):
            violations.append(f"forbidden_extension:{ext} ({norm})")
            break

    for pat in FORBIDDEN_NAME_PATTERNS:
        if pat.search(base):
            violations.append(f"forbidden_name_pattern:{pat.pattern} ({norm})")
            break

    return violations


def audit_zip_archive(
    zip_path: str,
    *,
    require_round2_files: bool = True,
    require_round3_files: bool = False,
    require_round31_files: bool = False,
) -> Tuple[bool, Dict[str, object]]:
    """
    Independently verify ZIP integrity, forbidden-file hygiene, leaked-key absence,
    repository-root layout, required Round 2 / Round 3 / Round 3.1 files, and final SHA-256 digest.
    """
    if not os.path.isfile(zip_path):
        return False, {"error": f"Archive not found: {zip_path}"}

    violations: List[str] = []
    members: List[str] = []
    bad_member = None

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad_member = zf.testzip()
        if bad_member is not None:
            violations.append(f"corrupt_zip_member:{bad_member}")
        for info in zf.infolist():
            if info.is_dir():
                continue
            norm_name = _normalize_member_path(info.filename)
            members.append(norm_name)
            violations.extend(check_member_hygiene(norm_name))
            # Scan reasonably sized text/json/env/yaml files for real private key material
            if info.file_size <= 2 * 1024 * 1024:
                raw = zf.read(info.filename)
                if PRIVATE_KEY_LEAK_RE.search(raw):
                    violations.append(f"private_key_material_detected:{norm_name}")

    member_set = set(members)
    missing_required: List[str] = []
    if require_round31_files:
        required_list = REQUIRED_ROUND31_FILES
    elif require_round3_files:
        required_list = REQUIRED_ROUND3_FILES
    elif require_round2_files:
        required_list = REQUIRED_ROUND2_FILES
    else:
        required_list = []

    for req in required_list:
        if req not in member_set:
            missing_required.append(req)
            violations.append(f"missing_required_file:{req}")

    top_level_entries = sorted({m.split("/", 1)[0] for m in members if m})
    is_repo_root = all(anchor in member_set for anchor in ROOT_LAYOUT_ANCHORS)
    if require_round2_files or require_round3_files or require_round31_files:
        if not is_repo_root:
            violations.append(
                f"invalid_root_layout:expected_repository_root_anchors ({', '.join(ROOT_LAYOUT_ANCHORS)})"
            )
        if len(top_level_entries) == 1:
            violations.append(f"wrapped_root_directory_detected:{top_level_entries[0]}")

    stat = os.stat(zip_path)
    sha256_hex = compute_sha256(zip_path)
    mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    report: Dict[str, object] = {
        "archive_path": os.path.abspath(zip_path),
        "archive_name": os.path.basename(zip_path),
        "size_bytes": stat.st_size,
        "file_count": len(members),
        "testzip_bad_member": bad_member,
        "root_layout": "REPOSITORY_ROOT" if is_repo_root and len(top_level_entries) > 1 else "NON_STANDARD",
        "timestamp_utc": mtime_utc,
        "sha256": sha256_hex,
        "missing_required": missing_required,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }
    return len(violations) == 0, report


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python3 scripts/verify_package_hygiene.py <archive.zip>", file=sys.stderr)
        return 2
    zip_path = argv[1]
    ok, report = audit_zip_archive(
        zip_path,
        require_round2_files=True,
        require_round3_files=True,
        require_round31_files=True,
    )
    for k in (
        "archive_name",
        "size_bytes",
        "file_count",
        "testzip_bad_member",
        "root_layout",
        "timestamp_utc",
        "sha256",
        "status",
    ):
        print(f"{k.upper()}={report.get(k)}")
    if not ok:
        print("VIOLATIONS:", file=sys.stderr)
        for v in report.get("violations", []):
            print(f"  - {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
