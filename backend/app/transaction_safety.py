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

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import http.client
import json
import os
import re
import socket
import tempfile
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
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


# ===========================================================================
# TX-AUDIT-01: Single Authoritative Transaction State-Transition Policy
# ===========================================================================


class TransitionAuthority(str, Enum):
    """Explicit authority classes governing transaction state transitions."""

    ORDINARY = "ORDINARY"
    RETRY = "RETRY"
    RECOVERY = "RECOVERY"
    SECONDARY_QUARANTINE = "SECONDARY_QUARANTINE"
    RECONCILIATION = "RECONCILIATION"


@dataclass(frozen=True)
class TransitionRule:
    """Single legal transition entry in the authoritative state-transition matrix."""

    source: TransactionState
    destination: TransactionState
    allowed_authorities: FrozenSet[TransitionAuthority]
    requires_cas: bool = True
    requires_evidence: bool = False
    requires_recovery_authority: bool = False
    requires_lease_owner: bool = False
    destination_is_terminal: bool = False
    description: str = ""


TERMINAL_STATES: FrozenSet[TransactionState] = frozenset({
    TransactionState.COMMITTED,
    TransactionState.RECONCILED,
})

PROTECTED_STATES: FrozenSet[TransactionState] = frozenset({
    TransactionState.COMMITTED,
    TransactionState.RECONCILED,
    TransactionState.RECOVERY_REQUIRED,
})


class InvalidStateTransitionError(ValueError):
    """
    Raised when a transaction state mutation violates the authoritative transition matrix,
    fails atomic compare-and-swap (CAS), originates from a stale worker/lease, or attempts
    to overwrite a protected terminal state.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID_STATE_TRANSITION",
        nonce: str = "",
        current_state: Optional[str] = None,
        target_state: Optional[str] = None,
        authority: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.nonce = nonce
        self.current_state = current_state
        self.target_state = target_state
        self.authority = authority


def _rule(
    source: TransactionState,
    destination: TransactionState,
    authorities: Tuple[TransitionAuthority, ...],
    *,
    requires_cas: bool = True,
    requires_evidence: bool = False,
    requires_recovery_authority: bool = False,
    requires_lease_owner: bool = False,
    destination_is_terminal: bool = False,
    description: str = "",
) -> Tuple[Tuple[TransactionState, TransactionState], TransitionRule]:
    return (
        (source, destination),
        TransitionRule(
            source=source,
            destination=destination,
            allowed_authorities=frozenset(authorities),
            requires_cas=requires_cas,
            requires_evidence=requires_evidence,
            requires_recovery_authority=requires_recovery_authority,
            requires_lease_owner=requires_lease_owner,
            destination_is_terminal=destination_is_terminal,
            description=description,
        ),
    )


LEGAL_TRANSITION_MATRIX: Dict[Tuple[TransactionState, TransactionState], TransitionRule] = dict([
    # From INITIATED
    _rule(
        TransactionState.INITIATED,
        TransactionState.VALIDATING,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Begin pre-write validation for initiated intent.",
    ),
    _rule(
        TransactionState.INITIATED,
        TransactionState.EXECUTING,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Advance initiated intent directly into active execution with lease.",
    ),
    _rule(
        TransactionState.INITIATED,
        TransactionState.FAILED,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Pre-execution validation or setup failed cleanly before remote write.",
    ),
    _rule(
        TransactionState.INITIATED,
        TransactionState.UNKNOWN,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Stale lease expired while in INITIATED state.",
    ),
    # From VALIDATING
    _rule(
        TransactionState.VALIDATING,
        TransactionState.EXECUTING,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Validation passed; begin governed write execution.",
    ),
    _rule(
        TransactionState.VALIDATING,
        TransactionState.FAILED,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Validation rejected mutation before gateway transmission.",
    ),
    _rule(
        TransactionState.VALIDATING,
        TransactionState.UNKNOWN,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Stale lease expired while in VALIDATING state.",
    ),
    # From PENDING (verified absent in Google Sheets; awaiting safe retry)
    _rule(
        TransactionState.PENDING,
        TransactionState.EXECUTING,
        (TransitionAuthority.RETRY,),
        description="Controlled same-nonce retry after recovery verified zero side effects.",
    ),
    _rule(
        TransactionState.PENDING,
        TransactionState.FAILED,
        (TransitionAuthority.ORDINARY, TransitionAuthority.RECOVERY),
        description="Pending intent aborted cleanly before remote execution.",
    ),
    _rule(
        TransactionState.PENDING,
        TransactionState.RECOVERY_REQUIRED,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Evidence later revealed partial side effects for pending intent.",
    ),
    _rule(
        TransactionState.PENDING,
        TransactionState.RECONCILED,
        (TransitionAuthority.RECONCILIATION,),
        requires_evidence=True,
        requires_recovery_authority=True,
        destination_is_terminal=True,
        description="Owner manually reconciled pending intent.",
    ),
    # From EXECUTING (active lease-holding worker)
    _rule(
        TransactionState.EXECUTING,
        TransactionState.COMMITTED,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        destination_is_terminal=True,
        description="Gateway confirmed write and read-back verification succeeded.",
    ),
    _rule(
        TransactionState.EXECUTING,
        TransactionState.FAILED,
        (TransitionAuthority.ORDINARY,),
        requires_lease_owner=True,
        description="Definitive pre-transmission refusal or explicit 4xx/redirect rejection.",
    ),
    _rule(
        TransactionState.EXECUTING,
        TransactionState.UNKNOWN,
        (TransitionAuthority.ORDINARY, TransitionAuthority.RECOVERY),
        requires_lease_owner=True,
        description="Ambiguous gateway timeout/disconnect/malformed response or stale lease expiry.",
    ),
    _rule(
        TransactionState.EXECUTING,
        TransactionState.RECOVERY_REQUIRED,
        (TransitionAuthority.ORDINARY, TransitionAuthority.RECOVERY),
        requires_evidence=True,
        requires_lease_owner=True,
        description="Partial, imbalanced, or duplicate side effects detected during read-back.",
    ),
    # From FAILED (definitively confirmed zero-effect failure)
    _rule(
        TransactionState.FAILED,
        TransactionState.EXECUTING,
        (TransitionAuthority.RETRY,),
        description="Explicit controlled retry with incremented attempt_count and fresh lease.",
    ),
    # From UNKNOWN (ambiguous outcome; recovery authority required)
    _rule(
        TransactionState.UNKNOWN,
        TransactionState.COMMITTED,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        destination_is_terminal=True,
        description="Evidence-based Sheets inspection verified complete uncorrupted commit.",
    ),
    _rule(
        TransactionState.UNKNOWN,
        TransactionState.PENDING,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Evidence-based Sheets inspection confirmed zero side effects; retry permitted.",
    ),
    _rule(
        TransactionState.UNKNOWN,
        TransactionState.RECOVERY_REQUIRED,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Evidence-based Sheets inspection detected orphan allocation or partial/duplicate rows.",
    ),
    _rule(
        TransactionState.UNKNOWN,
        TransactionState.UNKNOWN,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description="Recovery deferred because authoritative Google Sheets status tables are unreachable.",
    ),
    _rule(
        TransactionState.UNKNOWN,
        TransactionState.RECONCILED,
        (TransitionAuthority.RECONCILIATION,),
        requires_evidence=True,
        requires_recovery_authority=True,
        destination_is_terminal=True,
        description="Owner manually reconciled unknown-outcome transaction after inspecting Sheets.",
    ),
    # From RECOVERY_REQUIRED (quarantined; ordinary execution & retry STRICTLY forbidden)
    _rule(
        TransactionState.RECOVERY_REQUIRED,
        TransactionState.COMMITTED,
        (TransitionAuthority.RECOVERY,),
        requires_evidence=True,
        requires_recovery_authority=True,
        destination_is_terminal=True,
        description="Evidence-based Sheets inspection verified all required primary & child rows intact.",
    ),
    _rule(
        TransactionState.RECOVERY_REQUIRED,
        TransactionState.RECONCILED,
        (TransitionAuthority.RECONCILIATION,),
        requires_evidence=True,
        requires_recovery_authority=True,
        destination_is_terminal=True,
        description="Owner manually reconciled quarantined transaction with recorded notes and audit trail.",
    ),
    # From COMMITTED (protected terminal state — ONLY constrained secondary-side-effect quarantine allowed;
    # COMMITTED -> FAILED / INITIATED / VALIDATING / PENDING / EXECUTING / UNKNOWN / RECONCILED are ALWAYS FORBIDDEN)
    _rule(
        TransactionState.COMMITTED,
        TransactionState.RECOVERY_REQUIRED,
        (TransitionAuthority.SECONDARY_QUARANTINE,),
        requires_evidence=True,
        requires_recovery_authority=True,
        description=(
            "Constrained post-commit quarantine when primary business record committed in Sheets "
            "but mandatory secondary side effect (e.g. accounting journal) failed."
        ),
    ),
    # From RECONCILED: ZERO outgoing transitions. RECONCILED is strictly immutable.
])


def _coerce_state(value: Any) -> TransactionState:
    if isinstance(value, TransactionState):
        return value
    raw = str(value or "").strip().upper()
    try:
        return TransactionState(raw)
    except ValueError as exc:
        raise InvalidStateTransitionError(
            f"Unknown transaction lifecycle state '{value}'.",
            code="UNKNOWN_TRANSACTION_STATE",
            target_state=raw,
        ) from exc


def _coerce_authority(value: Any) -> TransitionAuthority:
    if isinstance(value, TransitionAuthority):
        return value
    raw = str(value or "").strip().upper()
    try:
        return TransitionAuthority(raw)
    except ValueError as exc:
        raise InvalidStateTransitionError(
            f"Unknown transition authority '{value}'.",
            code="UNKNOWN_TRANSITION_AUTHORITY",
            authority=raw,
        ) from exc


def validate_state_transition(
    current_state: Any,
    target_state: Any,
    authority: Any = TransitionAuthority.ORDINARY,
    *,
    nonce: str = "",
    reason: Optional[str] = None,
    evidence: Optional[Any] = None,
    actor: Optional[str] = None,
) -> TransitionRule:
    """
    Validate a proposed transaction state transition against the single authoritative
    `LEGAL_TRANSITION_MATRIX`. Raises `InvalidStateTransitionError` on any violation.
    """
    src = _coerce_state(current_state)
    dst = _coerce_state(target_state)
    auth = _coerce_authority(authority)

    # Strict immutability of RECONCILED
    if src == TransactionState.RECONCILED:
        raise InvalidStateTransitionError(
            f"Terminal state violation: RECONCILED transaction '{nonce}' cannot transition to '{dst.value}'.",
            code="TERMINAL_STATE_IMMUTABLE",
            nonce=nonce,
            current_state=src.value,
            target_state=dst.value,
            authority=auth.value,
        )

    rule = LEGAL_TRANSITION_MATRIX.get((src, dst))
    if rule is None:
        code = "TERMINAL_STATE_PROTECTED" if src in TERMINAL_STATES else "ILLEGAL_STATE_TRANSITION"
        raise InvalidStateTransitionError(
            f"Illegal state transition {src.value} -> {dst.value} (authority={auth.value}) for nonce '{nonce}'.",
            code=code,
            nonce=nonce,
            current_state=src.value,
            target_state=dst.value,
            authority=auth.value,
        )

    if auth not in rule.allowed_authorities:
        allowed_str = ", ".join(sorted(a.value for a in rule.allowed_authorities))
        code = (
            "TERMINAL_STATE_PROTECTED"
            if src in TERMINAL_STATES
            else "INSUFFICIENT_TRANSITION_AUTHORITY"
        )
        raise InvalidStateTransitionError(
            f"Unauthorized transition {src.value} -> {dst.value} using authority '{auth.value}' "
            f"(allowed: {allowed_str}) for nonce '{nonce}'.",
            code=code,
            nonce=nonce,
            current_state=src.value,
            target_state=dst.value,
            authority=auth.value,
        )

    if rule.requires_evidence:
        has_reason = bool(str(reason or "").strip())
        has_evidence = evidence is not None and (
            not isinstance(evidence, (str, dict, list, tuple, set)) or len(evidence) > 0
        )
        if not (has_reason or has_evidence):
            raise InvalidStateTransitionError(
                f"Transition {src.value} -> {dst.value} (authority={auth.value}) requires explicit reason or evidence.",
                code="TRANSITION_EVIDENCE_REQUIRED",
                nonce=nonce,
                current_state=src.value,
                target_state=dst.value,
                authority=auth.value,
            )

    if rule.requires_recovery_authority and auth in {
        TransitionAuthority.RECONCILIATION,
        TransitionAuthority.SECONDARY_QUARANTINE,
    }:
        if not str(actor or "").strip():
            raise InvalidStateTransitionError(
                f"Transition {src.value} -> {dst.value} (authority={auth.value}) requires explicit actor identity.",
                code="TRANSITION_ACTOR_REQUIRED",
                nonce=nonce,
                current_state=src.value,
                target_state=dst.value,
                authority=auth.value,
            )

    return rule


def get_legal_transition_matrix_summary() -> List[Dict[str, Any]]:
    """Return a deterministic audit representation of the authoritative transition matrix."""
    rows: List[Dict[str, Any]] = []
    for (src, dst), rule in sorted(
        LEGAL_TRANSITION_MATRIX.items(),
        key=lambda item: (item[0][0].value, item[0][1].value),
    ):
        rows.append({
            "source": src.value,
            "destination": dst.value,
            "allowed_authorities": sorted(a.value for a in rule.allowed_authorities),
            "requires_cas": rule.requires_cas,
            "requires_evidence": rule.requires_evidence,
            "requires_recovery_authority": rule.requires_recovery_authority,
            "requires_lease_owner": rule.requires_lease_owner,
            "destination_is_terminal": rule.destination_is_terminal,
            "description": rule.description,
        })
    return rows


# ===========================================================================
# TX-AUDIT-02: Transaction Coordinator Durability & Scaling Validation
# ===========================================================================


class CoordinatorDurabilityMode(str, Enum):
    """Explicit classification of local transaction coordinator durability."""

    PERSISTENT = "PERSISTENT"
    VOLATILE_TEST = "VOLATILE_TEST"
    DEV_LOCAL = "DEV_LOCAL"
    MISCONFIGURED = "MISCONFIGURED"
    UNAVAILABLE = "UNAVAILABLE"


class CoordinatorDurabilityError(RuntimeError):
    """Raised fail-closed when required coordinator durability is misconfigured or unavailable."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        mode: CoordinatorDurabilityMode,
        db_path: str = "",
    ):
        super().__init__(message)
        self.error_code = error_code
        self.mode = mode
        self.db_path = db_path


def _is_volatile_db_path(path: str) -> bool:
    raw = str(path or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    if raw == ":memory:" or lower.startswith("file::memory:") or "mode=memory" in lower:
        return True
    norm = os.path.normpath(os.path.abspath(raw))
    volatile_roots = {
        "/tmp",
        "/var/tmp",
        "/dev/shm",
        os.path.normpath(os.path.abspath(tempfile.gettempdir())),
    }
    for root in volatile_roots:
        if norm == root or norm.startswith(root + os.sep):
            return True
    return False


def validate_coordinator_durability(
    *,
    db_path: Optional[str] = None,
    env: Optional[str] = None,
    testing: Optional[bool] = None,
    allow_volatile_in_test: Optional[bool] = None,
    instance_count: Optional[int] = None,
    create_dir_in_nonprod: bool = False,
) -> Dict[str, Any]:
    """
    Validate transaction coordinator SQLite durability and single-host scaling constraints.

    Rules (fail-closed):
    - NEVER silently falls back to `/tmp` when `SALES_ENV=production` (non-testing).
    - Production MUST explicitly configure `TRANSACTION_DB_PATH` on a non-volatile,
      mounted, writable persistent volume (e.g. Render persistent disk `/var/data/kawad_swad/...`).
    - Multi-instance horizontal scaling (`RENDER_INSTANCE_COUNT` / `SALES_INSTANCE_COUNT` > 1)
      is explicitly rejected because host-local SQLite WAL + fcntl.flock does NOT provide
      cross-container distributed coordination.
    - Isolated testing (`SALES_TESTING=1`) or explicit local development allows volatile/temp paths
      while still failing closed if an explicitly configured directory is missing or unwritable.
    """
    resolved_env = (env if env is not None else os.getenv("SALES_ENV", "development")).strip().lower()
    is_testing = (
        bool(testing)
        if testing is not None
        else (os.getenv("SALES_TESTING", "").strip() == "1")
    )
    volatile_flag = (
        bool(allow_volatile_in_test)
        if allow_volatile_in_test is not None
        else (os.getenv("SALES_TX_ALLOW_VOLATILE_COORD", "false").strip().lower() in {"1", "true", "yes"})
    )
    raw_instances = (
        instance_count
        if instance_count is not None
        else int(
            os.getenv("SALES_INSTANCE_COUNT")
            or os.getenv("RENDER_INSTANCE_COUNT")
            or "1"
        )
    )
    if raw_instances > 1 and not is_testing:
        raise CoordinatorDurabilityError(
            f"Unsupported horizontal scaling detected (instance_count={raw_instances}). "
            "Host-local SQLite WAL transaction coordination is single-instance only; "
            "keep instance count = 1 until distributed coordination / verified Apps Script LockService is deployed.",
            error_code="COORDINATOR_MULTI_INSTANCE_UNSUPPORTED",
            mode=CoordinatorDurabilityMode.MISCONFIGURED,
            db_path=str(db_path or ""),
        )

    explicit_env_path = os.getenv("TRANSACTION_DB_PATH", "").strip()
    configured_path = str(db_path).strip() if db_path is not None else explicit_env_path

    if resolved_env == "production" and not is_testing:
        if not configured_path:
            raise CoordinatorDurabilityError(
                "TRANSACTION_DB_PATH is not configured in production. "
                "Refusing silent fallback to volatile /tmp storage; mount a persistent disk "
                "(e.g. /var/data/kawad_swad/kawad_swad_tx_coord.db).",
                error_code="COORDINATOR_PATH_UNCONFIGURED",
                mode=CoordinatorDurabilityMode.MISCONFIGURED,
                db_path="",
            )
        if _is_volatile_db_path(configured_path):
            raise CoordinatorDurabilityError(
                f"TRANSACTION_DB_PATH='{configured_path}' points to volatile storage (/tmp or memory) "
                "in production mode. Production requires a persistent mounted directory.",
                error_code="COORDINATOR_VOLATILE_PATH_IN_PRODUCTION",
                mode=CoordinatorDurabilityMode.MISCONFIGURED,
                db_path=configured_path,
            )
        abs_path = os.path.normpath(os.path.abspath(configured_path))
        parent_dir = os.path.dirname(abs_path)
        if not parent_dir or not os.path.isdir(parent_dir):
            raise CoordinatorDurabilityError(
                f"Persistent coordinator directory '{parent_dir}' does not exist or is not mounted.",
                error_code="COORDINATOR_DIRECTORY_UNAVAILABLE",
                mode=CoordinatorDurabilityMode.UNAVAILABLE,
                db_path=abs_path,
            )
        if not os.access(parent_dir, os.R_OK | os.W_OK | os.X_OK):
            raise CoordinatorDurabilityError(
                f"Persistent coordinator directory '{parent_dir}' is not writable.",
                error_code="COORDINATOR_DIRECTORY_NOT_WRITABLE",
                mode=CoordinatorDurabilityMode.UNAVAILABLE,
                db_path=abs_path,
            )
        return {
            "mode": CoordinatorDurabilityMode.PERSISTENT.value,
            "db_path": abs_path,
            "parent_dir": parent_dir,
            "env": resolved_env,
            "testing": False,
            "persistent": True,
            "single_host_only": True,
            "instance_count": raw_instances,
        }

    # Non-production / isolated testing mode
    effective_path = configured_path or os.path.join(tempfile.gettempdir(), "kawad_swad_tx_coord.db")
    if effective_path == ":memory:" or effective_path.lower().startswith("file::memory:"):
        if not (is_testing or volatile_flag):
            raise CoordinatorDurabilityError(
                "In-memory SQLite coordinator is only permitted in explicit test/volatile mode.",
                error_code="COORDINATOR_MEMORY_FORBIDDEN",
                mode=CoordinatorDurabilityMode.MISCONFIGURED,
                db_path=effective_path,
            )
        return {
            "mode": CoordinatorDurabilityMode.VOLATILE_TEST.value,
            "db_path": effective_path,
            "parent_dir": "",
            "env": resolved_env,
            "testing": is_testing,
            "persistent": False,
            "single_host_only": True,
            "instance_count": raw_instances,
        }

    abs_path = os.path.normpath(os.path.abspath(effective_path))
    parent_dir = os.path.dirname(abs_path)
    if parent_dir and not os.path.isdir(parent_dir):
        if create_dir_in_nonprod:
            try:
                os.makedirs(parent_dir, mode=0o700, exist_ok=True)
            except OSError as exc:
                raise CoordinatorDurabilityError(
                    f"Coordinator directory '{parent_dir}' could not be created: {exc}",
                    error_code="COORDINATOR_DIRECTORY_UNAVAILABLE",
                    mode=CoordinatorDurabilityMode.UNAVAILABLE,
                    db_path=abs_path,
                ) from exc
        else:
            raise CoordinatorDurabilityError(
                f"Coordinator directory '{parent_dir}' does not exist.",
                error_code="COORDINATOR_DIRECTORY_UNAVAILABLE",
                mode=CoordinatorDurabilityMode.UNAVAILABLE,
                db_path=abs_path,
            )

    if parent_dir and not os.access(parent_dir, os.R_OK | os.W_OK | os.X_OK):
        raise CoordinatorDurabilityError(
            f"Coordinator directory '{parent_dir}' is not writable.",
            error_code="COORDINATOR_DIRECTORY_NOT_WRITABLE",
            mode=CoordinatorDurabilityMode.UNAVAILABLE,
            db_path=abs_path,
        )

    is_volatile = _is_volatile_db_path(abs_path)
    mode = (
        CoordinatorDurabilityMode.VOLATILE_TEST
        if (is_testing or (is_volatile and volatile_flag))
        else (CoordinatorDurabilityMode.DEV_LOCAL if is_volatile else CoordinatorDurabilityMode.PERSISTENT)
    )
    return {
        "mode": mode.value,
        "db_path": abs_path,
        "parent_dir": parent_dir,
        "env": resolved_env,
        "testing": is_testing,
        "persistent": not is_volatile,
        "single_host_only": True,
        "instance_count": raw_instances,
    }
