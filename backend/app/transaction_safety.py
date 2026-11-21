"""
Kawad Swad ERP — Transaction Safety Core Primitives (Mission 51B-1)

Provides:
1. Canonical Transaction Lifecycle State Model (`TransactionState`).
2. Consistent Transaction Failure Classification (`FailureCategory`).
3. Deterministic payload normalization & SHA-256 fingerprinting for idempotency.
4. Secret/PII sanitization for structured transaction audit events.
5. Gateway transport exception classification (pre-transmission vs unknown outcome).
6. Explicit audit-log failure policy by mutation class.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import http.client
import json
import re
import socket
from typing import Any, Dict, FrozenSet, Tuple
import urllib.error


class TransactionState(str, Enum):
    """Canonical lifecycle state of every governed ERP mutation."""

    INITIATED = "INITIATED"
    VALIDATING = "VALIDATING"
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECONCILED = "RECONCILED"


class FailureCategory(str, Enum):
    """Consistent actionable transaction failure categories."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    WRITE_REJECTED = "WRITE_REJECTED"
    WRITE_FAILED_CONFIRMED = "WRITE_FAILED_CONFIRMED"
    WRITE_OUTCOME_UNKNOWN = "WRITE_OUTCOME_UNKNOWN"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Volatile per-attempt keys excluded from payload idempotency fingerprints so
# legitimate retries with regenerated timestamps/correlation IDs hash identically
# while every meaningful business field remains part of the fingerprint.
VOLATILE_FINGERPRINT_KEYS: FrozenSet[str] = frozenset({
    "timestamp",
    "correlation_id",
    "request_timestamp",
    "client_timestamp",
    "nonce",
    "idempotency_key",
    "submitted_at",
    "created_at",
    "updated_at",
    "decided_at",
    "reviewed_at",
    "executed_at",
    "payment_datetime",
    "txn_datetime",
    "event_datetime",
    "approval_datetime",
    "expense_datetime",
    "visit_datetime",
    "bill_datetime",
    "checked_at",
    "recorded_at",
    "logged_at",
    "posted_at",
    "verified_at",
    "completed_at",
    "approved_at",
    "cancelled_at",
    "reversed_at",
    "sale_datetime",
    "closing_datetime",
    "issued_at",
})

# Keys that MUST be redacted before writing structured audit telemetry or logs.
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|authorization|auth_header|cookie|"
    r"api_key|private_key|signature|hmac|salt|hash|pin|otp|cvv|"
    r"bank_account|account_number|ifsc|aadhaar|pan_number|ssn)",
    re.IGNORECASE,
)

# Strict plain decimal syntax — never coerces zero-padded codes ("0010") or
# scientific-notation lookalikes ("1E2").
_PLAIN_DECIMAL_RE = re.compile(r"^[+-]?(?:(?:0|[1-9]\d*)(?:\.\d+)?|\.\d+)$")

# ISO-8601 datetime string pattern (e.g. 2026-11-21T10:15:30Z or +00:00)
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def format_decimal_canonical(dec: Decimal) -> str:
    """
    Format a finite Decimal canonically without stripping meaningful integer zeroes.
    10 -> "10", 100 -> "100", 10.00 -> "10", 1.20 -> "1.2", 0.0 -> "0".
    """
    if dec == 0:
        return "0"
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def normalize_scalar_canonical(value: Any) -> str:
    """
    Deterministic scalar normalization for both idempotency fingerprinting and read-back:
    - bool / "true" / "false" -> "true" | "false" (never collides with 1 / 0)
    - None / "" / whitespace -> "" (never collides with 0 or false)
    - date / datetime -> canonical ISO-8601 UTC string (or YYYY-MM-DD for pure date)
    - int / float / Decimal / strict plain decimal string -> canonical Decimal string
    - other strings -> trimmed string
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if value.is_finite():
            return format_decimal_canonical(value)
        return str(value).strip()
    if isinstance(value, float):
        try:
            dec = Decimal(str(value))
            if dec.is_finite():
                return format_decimal_canonical(dec)
        except (InvalidOperation, ValueError):
            pass
        return str(value).strip()

    s = str(value).strip()
    if not s:
        return ""
    lower = s.lower()
    if lower in {"true", "false"}:
        return lower
    if _PLAIN_DECIMAL_RE.match(s):
        try:
            dec = Decimal(s)
            if dec.is_finite():
                return format_decimal_canonical(dec)
        except (InvalidOperation, ValueError):
            pass
    if _ISO_DATETIME_RE.match(s):
        try:
            iso_candidate = s.replace(" ", "T")
            if iso_candidate.endswith("Z"):
                iso_candidate = iso_candidate[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    return s


def normalize_payload_for_fingerprint(value: Any) -> Any:
    """
    Recursively normalize a payload structure for deterministic SHA-256 fingerprinting.

    Guarantees:
    - Object keys are sorted lexicographically.
    - Strictly volatile per-attempt metadata keys are omitted.
    - Empty/null values (`None`, `""`, whitespace) normalize identically to `""`.
    - Numeric equivalents (`10`, `10.0`, `"10.00"`, `Decimal("10")`) normalize identically
      while distinct integers (`10` vs `100`) never collide.
    - Booleans (`True`, `"true"`) normalize identically without colliding with `1`/`0`.
    - Array order is preserved because item/line ordering can be semantically meaningful.
    """
    if isinstance(value, dict):
        normalized_dict: Dict[str, Any] = {}
        for k in sorted(value.keys(), key=lambda x: str(x)):
            key_str = str(k).strip()
            if key_str in VOLATILE_FINGERPRINT_KEYS:
                continue
            norm_val = normalize_payload_for_fingerprint(value[k])
            normalized_dict[key_str] = norm_val
        return normalized_dict
    if isinstance(value, (list, tuple)):
        return [normalize_payload_for_fingerprint(item) for item in value]
    if isinstance(value, set):
        return sorted(
            [normalize_payload_for_fingerprint(item) for item in value],
            key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"), default=str),
        )
    if isinstance(value, str):
        stripped = value.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, (dict, list)):
                    return normalize_payload_for_fingerprint(parsed)
            except (ValueError, TypeError):
                pass
        return normalize_scalar_canonical(value)
    return normalize_scalar_canonical(value)


def compute_deterministic_payload_hash(
    *,
    action: str,
    target_tab: str,
    actor_user_id: str,
    actor_role: str,
    payload: Dict[str, Any],
) -> str:
    """
    Compute a deterministic SHA-256 fingerprint over the normalized logical operation.
    Excludes nonce and volatile timestamps so:
    - Same nonce + same logical business operation -> identical hash.
    - Same nonce + different business field/amount/item/action -> different hash (409 conflict).
    """
    normalized_envelope = {
        "action": str(action or "").strip().upper(),
        "target_tab": str(target_tab or "").strip(),
        "actor_user_id": str(actor_user_id or "").strip(),
        "actor_role": str(actor_role or "").strip().upper(),
        "payload": normalize_payload_for_fingerprint(payload if isinstance(payload, dict) else {}),
    }
    canonical = json.dumps(
        normalized_envelope,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sanitize_audit_metadata(data: Any, *, max_depth: int = 5) -> Any:
    """Recursively redact secrets, tokens, passwords, and sensitive auth headers for audit logs."""
    if max_depth <= 0:
        return "[TRUNCATED]"
    if isinstance(data, dict):
        clean: Dict[str, Any] = {}
        for k, v in data.items():
            key_s = str(k)
            if _SENSITIVE_KEY_RE.search(key_s):
                clean[key_s] = "[REDACTED]"
            else:
                clean[key_s] = sanitize_audit_metadata(v, max_depth=max_depth - 1)
        return clean
    if isinstance(data, (list, tuple)):
        return [sanitize_audit_metadata(x, max_depth=max_depth - 1) for x in data[:50]]
    if isinstance(data, str):
        # Prevent accidental bearer token / JWT leakage even inside free-text fields
        if data.strip().lower().startswith("bearer ") or data.count(".") == 2 and len(data) > 80:
            return "[REDACTED_TOKEN]"
        return data[:500]
    return data


def classify_gateway_exception(exc: Exception) -> Tuple[TransactionState, FailureCategory, str, int, str]:
    """
    Classify transport/parsing exceptions when communicating with the Apps Script gateway.

    Critical safety rule:
    - ONLY classify as `FAILED` / `DEPENDENCY_UNAVAILABLE` when failure occurred definitively
      BEFORE request transmission (e.g. DNS resolution failure or TCP ConnectionRefused).
    - Timeout, socket reset, incomplete read, remote disconnect, empty response, or malformed
      JSON after connection MUST remain `UNKNOWN` / `WRITE_OUTCOME_UNKNOWN` because the
      gateway may already have committed the mutation.

    Returns: `(tx_state, failure_category, error_code, http_status, user_message)`
    """
    reason = getattr(exc, "reason", None)
    inner = reason if isinstance(reason, BaseException) else exc

    # Definite pre-transmission failures: remote server never received HTTP request bytes
    if isinstance(inner, (ConnectionRefusedError, socket.gaierror)):
        return (
            TransactionState.FAILED,
            FailureCategory.DEPENDENCY_UNAVAILABLE,
            "APPS_SCRIPT_UNREACHABLE",
            503,
            "Write gateway could not be reached before transmission. Data was NOT SAVED; safe to retry once service is available.",
        )

    if isinstance(exc, urllib.error.URLError) and isinstance(reason, str):
        lower_reason = reason.lower()
        if any(tok in lower_reason for tok in ("name or service not known", "nodename nor servname", "connection refused", "getaddrinfo failed")):
            return (
                TransactionState.FAILED,
                FailureCategory.DEPENDENCY_UNAVAILABLE,
                "APPS_SCRIPT_UNREACHABLE",
                503,
                "Write gateway could not be reached before transmission. Data was NOT SAVED; safe to retry once service is available.",
            )

    # Ambiguous post-transmission / timeout / malformed response failures
    if isinstance(inner, (TimeoutError, socket.timeout)):
        return (
            TransactionState.UNKNOWN,
            FailureCategory.WRITE_OUTCOME_UNKNOWN,
            "APPS_SCRIPT_UNKNOWN_OUTCOME",
            504,
            "Status not confirmed (gateway timed out); do not submit a new transaction. Check transaction status before retrying with the same nonce.",
        )

    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError)):
        return (
            TransactionState.UNKNOWN,
            FailureCategory.WRITE_OUTCOME_UNKNOWN,
            "APPS_SCRIPT_MALFORMED_RESPONSE",
            504,
            "Status not confirmed (malformed gateway response); do not submit a new transaction. Check transaction status before retrying with the same nonce.",
        )

    if isinstance(inner, (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, http.client.IncompleteRead)):
        return (
            TransactionState.UNKNOWN,
            FailureCategory.WRITE_OUTCOME_UNKNOWN,
            "APPS_SCRIPT_CONNECTION_DROPPED",
            504,
            "Status not confirmed (connection dropped during write); do not submit a new transaction. Check transaction status before retrying with the same nonce.",
        )

    return (
        TransactionState.UNKNOWN,
        FailureCategory.WRITE_OUTCOME_UNKNOWN,
        "APPS_SCRIPT_UNKNOWN_OUTCOME",
        504,
        "Status not confirmed; do not submit a new transaction. Check transaction status before retrying with the same nonce.",
    )


def map_http_status_to_failure_category(http_status: int, error_code: str = "") -> FailureCategory:
    """Map an HTTP status + error code to a canonical FailureCategory."""
    code = str(error_code or "").strip().upper()
    if "RECOVERY_REQUIRED" in code or "PARTIAL" in code or "DUPLICATE_PRIMARY" in code:
        return FailureCategory.RECOVERY_REQUIRED
    if "IDEMPOTENCY" in code or "CONFLICT" in code and "NONCE" in code:
        return FailureCategory.IDEMPOTENCY_CONFLICT
    if "CONCURRENT_DUPLICATE" in code or "DUPLICATE_RECORD" in code or "CROSS_TABLE_ID_COLLISION" in code:
        return FailureCategory.DUPLICATE_REQUEST
    if "READ_BACK" in code or "VERIFICATION" in code or "ALLOCATED_ID" in code:
        return FailureCategory.VERIFICATION_FAILED
    if "UNKNOWN" in code or http_status == 504:
        return FailureCategory.WRITE_OUTCOME_UNKNOWN
    if "UNAVAILABLE" in code or "UNCONFIGURED" in code or "PENDING_OWNER" in code or http_status == 503:
        return FailureCategory.DEPENDENCY_UNAVAILABLE
    if http_status in {401, 403}:
        return FailureCategory.AUTHORIZATION_ERROR
    if http_status in {400, 422}:
        return FailureCategory.VALIDATION_ERROR
    if http_status == 409:
        return FailureCategory.DUPLICATE_REQUEST
    if http_status == 502:
        return FailureCategory.WRITE_REJECTED
    if http_status >= 500:
        return FailureCategory.INTERNAL_ERROR
    return FailureCategory.WRITE_REJECTED
