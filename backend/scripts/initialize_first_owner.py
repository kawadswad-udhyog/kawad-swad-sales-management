#!/usr/bin/env python3
"""
Kawad Swad ERP — Governed First-Owner Initialization Utility (Single-Write-Owner Safe)

Architecture & Security Guarantees:
- Zero direct Google Sheets imports or writes (never imports `gspread` or `app.sheets`).
- Calls ONLY the gated FastAPI endpoint `POST /api/auth/bootstrap-owner`, which hashes
  the password server-side with PBKDF2-SHA256 and delegates the governed mutation to
  Google Apps Script (`BOOTSTRAP_FIRST_OWNER`).
- Prompts interactively with masked input (`getpass`) so neither the Owner password
  nor the one-time bootstrap secret ever enters shell history or process argv.
- Generates and prints a deterministic `X-KS-Idempotency-Key` BEFORE transmission so
  an interrupted network call can be retried safely with `--idempotency-key`.
- Enforces HTTPS for all non-local backend URLs.
- Never prints passwords, password hashes, or bootstrap tokens.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Dict, Tuple


_USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")
_CONFIRM_PHRASE = "INITIALIZE FIRST OWNER"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_backend_url(raw_url: str) -> str:
    cleaned = str(raw_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("Backend URL must be a valid https:// URL (e.g. https://erp-api.example.com).")
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme != "https" and host not in _LOCAL_HOSTS:
        raise ValueError(
            "Refusing insecure http:// transport for non-local host. "
            "Use https:// for staging/production servers."
        )
    if parsed.query or parsed.fragment:
        raise ValueError("Backend URL must not contain query parameters or fragments.")
    return cleaned


def _prompt_non_empty(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if not val and default:
            return default
        if val:
            return val
        print("Value is required.", file=sys.stderr)


def _prompt_username() -> str:
    while True:
        val = input("Owner username (3-50 lowercase letters, numbers, ., _, -): ").strip().lower()
        if _USERNAME_RE.fullmatch(val):
            return val
        print("Invalid username format. Use 3-50 chars from [a-z0-9._-].", file=sys.stderr)


def _prompt_password() -> str:
    while True:
        pw1 = getpass.getpass("Owner password (min 12 chars, hidden): ")
        if len(pw1) < 12 or len(pw1) > 128:
            print("Password must be between 12 and 128 characters.", file=sys.stderr)
            continue
        pw2 = getpass.getpass("Confirm Owner password (hidden): ")
        if pw1 != pw2:
            print("Passwords do not match. Please try again.", file=sys.stderr)
            continue
        return pw1


def _prompt_bootstrap_token() -> str:
    while True:
        tok = getpass.getpass("One-time bootstrap token (>= 32 chars, hidden): ").strip()
        if len(tok) >= 32:
            return tok
        print("Bootstrap token must be at least 32 characters.", file=sys.stderr)


def submit_bootstrap_request(
    *,
    base_url: str,
    username: str,
    full_name: str,
    password: str,
    bootstrap_token: str,
    idempotency_key: str,
    email: str = "",
    mobile: str = "",
    notes: str = "",
    timeout_seconds: int = 35,
) -> Tuple[int, Dict[str, object]]:
    endpoint = f"{_validate_backend_url(base_url)}/api/auth/bootstrap-owner"
    payload = {
        "username": username.strip().lower(),
        "full_name": full_name.strip(),
        "password": password,
        "email": email.strip(),
        "mobile": mobile.strip(),
        "notes": notes.strip(),
    }
    body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body_bytes,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-KS-Bootstrap-Token": bootstrap_token.strip(),
            "X-KS-Idempotency-Key": idempotency_key.strip(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status_code = getattr(resp, "status", 200)
            return int(status_code), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace") if err.fp else ""
        try:
            parsed = json.loads(raw) if raw else {"detail": err.reason}
        except Exception:
            parsed = {"detail": raw or str(err.reason)}
        return int(err.code), parsed
    finally:
        payload["password"] = ""
        body_bytes = b""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Kawad Swad ERP — Governed One-Time First-Owner Initialization Utility. "
            "Never writes directly to Google Sheets; delegates exclusively via FastAPI -> Apps Script."
        )
    )
    parser.add_argument(
        "--url",
        dest="base_url",
        default="",
        help="Backend base URL (https://... for staging/production; http://localhost:... for local dev).",
    )
    parser.add_argument(
        "--idempotency-key",
        dest="idempotency_key",
        default="",
        help="Optional existing X-KS-Idempotency-Key when recovering from an interrupted attempt.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=int,
        default=35,
        help="HTTPS request timeout in seconds (default: 35).",
    )
    args = parser.parse_args()

    print("=== Kawad Swad ERP — One-Time First-Owner Initialization ===")
    print("Note: Google Sheets writes occur strictly via FastAPI -> Apps Script.")
    print("      Both Users and AuthUsers must contain zero rows before initialization.\n")

    password = ""
    bootstrap_token = ""
    try:
        raw_url = args.base_url or _prompt_non_empty("Backend API URL (https://...)")
        base_url = _validate_backend_url(raw_url)

        username = _prompt_username()
        full_name = _prompt_non_empty("Owner full name")
        email = input("Owner email (optional): ").strip()
        mobile = input("Owner mobile (optional): ").strip()
        notes = input("Bootstrap notes (optional): ").strip()

        password = _prompt_password()
        bootstrap_token = _prompt_bootstrap_token()

        idempotency_key = (
            args.idempotency_key.strip()
            if args.idempotency_key and args.idempotency_key.strip()
            else f"BOOTSTRAP-OWNER-{uuid.uuid4().hex.upper()}"
        )

        print(f"\nTarget Endpoint  : {base_url}/api/auth/bootstrap-owner")
        print(f"Owner Username   : {username}")
        print(f"Owner Full Name  : {full_name}")
        print("Role (forced)    : OWNER_ADMIN (UI role: OWNER)")
        print("Password Policy  : must_change_password = false")
        print(f"Idempotency Key  : {idempotency_key}")
        print("(Save this Idempotency Key in case of network timeout so retries reuse the same key.)\n")

        confirm = input(f"Type '{_CONFIRM_PHRASE}' to execute governed initialization: ").strip()
        if confirm != _CONFIRM_PHRASE:
            print("Aborted by operator. No request was sent.")
            return 1

        status_code, body = submit_bootstrap_request(
            base_url=base_url,
            username=username,
            full_name=full_name,
            password=password,
            bootstrap_token=bootstrap_token,
            idempotency_key=idempotency_key,
            email=email,
            mobile=mobile,
            notes=notes,
            timeout_seconds=args.timeout_seconds,
        )
    except KeyboardInterrupt:
        print("\nAborted by operator.", file=sys.stderr)
        return 130
    except ValueError as val_err:
        print(f"Input validation error: {val_err}", file=sys.stderr)
        return 2
    except urllib.error.URLError as net_err:
        print(
            f"\nNetwork/transport error ({net_err.reason}). Outcome may be UNKNOWN.\n"
            f"Do NOT generate a new key; retry with the exact same --idempotency-key once connectivity returns.",
            file=sys.stderr,
        )
        return 3
    finally:
        password = ""
        bootstrap_token = ""

    if status_code in (200, 201) and body.get("success"):
        print("\n=== FIRST-OWNER INITIALIZATION CONFIRMED ===")
        print(f"User ID          : {body.get('user_id')}")
        print(f"Username         : {body.get('username')}")
        print(f"Full Name        : {body.get('full_name')}")
        print(f"Role             : {body.get('role')} ({body.get('canonical_role')})")
        print(f"Must Change Pass : {body.get('must_change_password')}")
        print(f"Transaction ID   : {body.get('transaction_id')}")
        print(f"Correlation ID   : {body.get('correlation_id')}")
        print(f"Nonce            : {body.get('nonce')}")
        print(f"Idempotent Replay: {body.get('is_replay')}")
        print("\nMANDATORY POST-BOOTSTRAP CLEANUP:")
        print("1. Immediately unset SALES_OWNER_BOOTSTRAP_ENABLED, SALES_OWNER_BOOTSTRAP_SECRET, and SALES_OWNER_BOOTSTRAP_EXPIRES_AT on the backend host.")
        print("2. Remove KS_OWNER_BOOTSTRAP_TOKEN_HASH and KS_OWNER_BOOTSTRAP_EXPIRES_AT from Apps Script Script Properties (keep KS_OWNER_BOOTSTRAP_COMPLETED=true permanently).")
        print("3. Sign in via the standard ERP Login screen using the configured username and password.")
        return 0

    print(f"\nInitialization FAILED (HTTP {status_code}).", file=sys.stderr)
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        safe_detail = {
            k: v
            for k, v in detail.items()
            if not any(s in str(k).lower() for s in ("password", "secret", "token", "hash"))
        }
        print(json.dumps(safe_detail, indent=2), file=sys.stderr)
    else:
        print(str(detail), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
