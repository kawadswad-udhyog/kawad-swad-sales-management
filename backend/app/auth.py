import os
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import jwt_secret, SALES_TOKEN_HOURS
from app.permissions import (
    is_owner,
    is_manager,
    is_salesman,
    is_factory_worker,
    is_recognized_role,
    require_owner,
    require_manager,
)

import logging
import uuid
import time
from typing import Optional, Dict, Any, Set, Tuple

logger = logging.getLogger("kawad_swad.auth")
security = HTTPBearer(auto_error=False)
_PBKDF2_PREFIX = "pbkdf2:sha256:"

# In-memory revocation cache for instant sub-millisecond lookups across requests
_REVOKED_TOKENS: Set[str] = set()
_USER_REVOKED_AT: Dict[str, float] = {}


class RevocationVerificationError(RuntimeError):
    """Raised when token revocation status cannot be safely verified (fail-closed)."""
    pass


_EXPLICIT_ACTIVE_STRINGS: Set[str] = {"true", "1", "yes", "active"}


def is_account_active(active_value: Any) -> bool:
    """
    Fail-closed account active-status predicate (AUTH-03).
    Returns True ONLY for explicit active representations (bool True, int 1, or
    case-insensitive string in {'true', '1', 'yes', 'active'}).
    Missing, None, blank, False, 0, 'false', 'inactive', 'suspended', or any
    malformed/unrecognized value fails closed (returns False).
    """
    if isinstance(active_value, bool):
        return active_value
    if isinstance(active_value, int):
        return active_value == 1
    if isinstance(active_value, str):
        return active_value.strip().lower() in _EXPLICIT_ACTIVE_STRINGS
    return False


def is_account_deactivated(active_value: Any) -> bool:
    """Consistent fail-closed account deactivation predicate shared by login and token verification."""
    return not is_account_active(active_value)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 100000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    dk_b64 = base64.b64encode(dk).decode("utf-8")
    return f"pbkdf2:sha256:{iterations}${salt_b64}${dk_b64}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Accept only PBKDF2-SHA256. Plaintext and raw SHA-256 are never valid."""
    if not hashed_password or not str(hashed_password).startswith(_PBKDF2_PREFIX):
        return False
    try:
        parts = str(hashed_password).split("$")
        if len(parts) != 3:
            return False
        iterations = int(parts[0].split(":")[2])
        if iterations < 10000 or iterations > 2000000:
            return False
        salt = base64.b64decode(parts[1])
        expected_dk = base64.b64decode(parts[2])
        calc_dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected_dk, calc_dk)
    except Exception:
        return False


def password_needs_reset(hashed_password: str) -> bool:
    return not str(hashed_password or "").startswith(_PBKDF2_PREFIX)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    now_utc = datetime.now(timezone.utc)
    to_encode = data.copy()
    expire = now_utc + (expires_delta or timedelta(hours=SALES_TOKEN_HOURS))
    to_encode.update({
        "exp": expire,
        "iat": int(now_utc.timestamp()),
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(to_encode, jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except Exception:
        return None


def _token_identifier(token: str, payload: Optional[Dict[str, Any]] = None) -> str:
    """Compute a stable hash or extract jti for token revocation."""
    if payload and payload.get("jti"):
        return str(payload["jti"])
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def revoke_token(token: str, user_id: str, reason: str = "Logout", raise_on_failure: bool = False) -> bool:
    """Revoke a single active JWT token (in-memory + Apps Script governed persistence)."""
    payload = decode_access_token(token)
    token_id = _token_identifier(token, payload)
    _REVOKED_TOKENS.add(token_id)
    if token:
        _REVOKED_TOKENS.add(token)

    now_iso_str = datetime.now(timezone.utc).isoformat()
    exp_iso = ""
    if payload and payload.get("exp"):
        exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()

    from app.apps_script_bridge import apps_script_bridge

    try:
        res = apps_script_bridge.execute_governed_write(
            action="REVOKE_TOKEN",
            target_tab="RevokedTokens",
            payload={
                "jti": token_id,
                "user_id": user_id,
                "revoked_at": now_iso_str,
                "expires_at": exp_iso,
                "reason": reason,
            },
            nonce=f"RVK-{token_id[:24]}",
            actor_user_id=user_id,
            actor_role="AUTH",
            invalidate_tabs=["RevokedTokens"],
        )
        if res.status != "CONFIRMED" and raise_on_failure:
            raise HTTPException(
                status_code=res.http_status,
                detail={
                    "status": res.status,
                    "error_code": res.error_code,
                    "dependency": res.dependency,
                    "message": res.message,
                    "correlation_id": res.correlation_id,
                    "nonce": res.nonce,
                    "retryable": res.retryable,
                },
            )
        return res.status == "CONFIRMED"
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delegate token revocation for user %s: %s", user_id, exc)
        if raise_on_failure:
            raise
        return False


def revoke_all_user_sessions(
    user_id: str,
    reason: str = "Security revocation",
    raise_on_failure: bool = False,
    nonce: Optional[str] = None,
) -> bool:
    """Invalidate all active sessions across all devices via Apps Script governed write."""
    clean_id = str(user_id or "").strip().lower()
    now_epoch = time.time()
    now_iso_str = datetime.now(timezone.utc).isoformat()
    _USER_REVOKED_AT[clean_id] = now_epoch
    reason_hash = hashlib.sha256(str(reason or "").encode("utf-8")).hexdigest()[:8].upper()
    stable_nonce = str(nonce or "").strip() or f"REVOKE-SESS-{user_id}-{reason_hash}-{now_iso_str[:16]}"

    from app.apps_script_bridge import apps_script_bridge

    try:
        res = apps_script_bridge.execute_governed_write(
            action="REVOKE_USER_SESSIONS",
            target_tab="AuthUsers",
            payload={
                "user_id": user_id,
                "sessions_revoked_at": now_iso_str,
                "reason": reason,
            },
            nonce=stable_nonce,
            actor_user_id=user_id,
            actor_role="AUTH",
            invalidate_tabs=["AuthUsers"],
        )
        if res.status != "CONFIRMED" and raise_on_failure:
            raise HTTPException(
                status_code=res.http_status,
                detail={
                    "status": res.status,
                    "error_code": res.error_code,
                    "dependency": res.dependency,
                    "message": res.message,
                    "correlation_id": res.correlation_id,
                    "nonce": res.nonce,
                    "retryable": res.retryable,
                },
            )
        return res.status == "CONFIRMED"
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delegate user-wide revocation for %s: %s", user_id, exc)
        if raise_on_failure:
            raise
        return False


def check_token_revocation(
    token: str,
    payload: Dict[str, Any],
    *,
    fresh: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a token is revoked in memory or in the persisted RevokedTokens sheet.
    Returns (is_revoked, error_code) so callers can clearly distinguish a confirmed
    non-revoked token from a revocation-source outage or malformed response (P1.5-003).
    """
    jti = payload.get("jti")
    token_id = _token_identifier(token, payload)
    if token_id in _REVOKED_TOKENS or (jti and jti in _REVOKED_TOKENS) or token in _REVOKED_TOKENS:
        return True, None

    # Check user-level revocation in memory
    user_id = str(payload.get("user_id") or payload.get("sub") or "").strip().lower()
    iat = float(payload.get("iat") or 0)
    if user_id in _USER_REVOKED_AT and iat <= _USER_REVOKED_AT[user_id]:
        return True, None

    # Check persisted RevokedTokens tab (fail closed on missing sheet, read error, or malformed response)
    from app.sheets import db
    try:
        revoked_rows = db.get_records("RevokedTokens", fresh=fresh)
    except Exception as exc:
        logger.error(
            "Token revocation lookup failed for user=%s (%s); denying access fail-closed.",
            user_id or "unknown",
            type(exc).__name__,
        )
        return False, "REVOCATION_STORE_UNAVAILABLE"

    if not isinstance(revoked_rows, list):
        logger.error(
            "Malformed RevokedTokens response type=%s for user=%s; denying access fail-closed.",
            type(revoked_rows).__name__,
            user_id or "unknown",
        )
        return False, "REVOCATION_DATA_MALFORMED"

    for row in revoked_rows:
        if not isinstance(row, dict):
            logger.error(
                "Malformed row entry in RevokedTokens (type=%s); denying access fail-closed.",
                type(row).__name__,
            )
            return False, "REVOCATION_DATA_MALFORMED"
        r_jti = str(row.get("jti") or "").strip()
        if r_jti and (r_jti == token_id or (jti and r_jti == jti)):
            _REVOKED_TOKENS.add(token_id)
            return True, None

    return False, None


def is_token_revoked(token: str, payload: Dict[str, Any], *, fresh: bool = True) -> bool:
    """
    Fail-closed token revocation check.
    Returns True if revoked, False ONLY when confirmed non-revoked.
    Raises RevocationVerificationError if the revocation store cannot be safely verified.
    """
    revoked, error_code = check_token_revocation(token, payload, fresh=fresh)
    if error_code is not None:
        raise RevocationVerificationError(
            f"Unable to verify token revocation status ({error_code})."
        )
    return revoked


def _auth_row_for(user_id: str, *, fresh: bool = True) -> Tuple[Optional[dict], Optional[str]]:
    """
    Lookup authoritative AuthUsers row.
    Returns (row, error_code) where error_code is None on unambiguous lookup (row or not found),
    or a fail-closed code ('AUTH_STORE_UNAVAILABLE', 'AUTH_DATA_MALFORMED', 'AMBIGUOUS_IDENTITY')
    when identity cannot be safely verified.
    """
    from app.sheets import db
    clean_id = str(user_id or "").strip().lower()
    if not clean_id:
        return None, None
    try:
        records = db.get_records("AuthUsers", fresh=fresh)
    except Exception as exc:
        logger.error(
            "AuthUsers lookup failed for user=%s (%s); denying access fail-closed.",
            clean_id,
            type(exc).__name__,
        )
        return None, "AUTH_STORE_UNAVAILABLE"
    if not isinstance(records, list):
        logger.error("Malformed AuthUsers response type=%s; denying access fail-closed.", type(records).__name__)
        return None, "AUTH_DATA_MALFORMED"

    matches = []
    for row in records:
        if not isinstance(row, dict):
            logger.error("Malformed row entry in AuthUsers (type=%s); denying access fail-closed.", type(row).__name__)
            return None, "AUTH_DATA_MALFORMED"
        r_uid = str(row.get("user_id", "")).strip().lower()
        r_uname = str(row.get("username", "")).strip().lower()
        if (r_uid and r_uid == clean_id) or (r_uname and r_uname == clean_id):
            matches.append(row)

    if len(matches) > 1:
        logger.error("Ambiguous AuthUsers identity for user=%s (%d matching rows); denying access fail-closed.", clean_id, len(matches))
        return None, "AMBIGUOUS_IDENTITY"
    return (matches[0] if matches else None), None


def _validate_authoritative_role(raw_role: Any, user_id: str) -> str:
    """
    Validate that the authoritative AuthUsers role is non-empty and belongs to either
    a recognized canonical/legacy system role or an active CustomRoles entry.
    Fails closed (403 on missing/unknown role, 503 if CustomRoles cannot be read).
    """
    clean_role = str(raw_role or "").strip()
    if not clean_role:
        logger.warning("Authorization rejected for user=%s: missing/blank role in AuthUsers.", user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role is missing or unassigned. Access denied.",
        )
    if is_recognized_role(clean_role):
        return clean_role

    from app.sheets import db
    try:
        custom_roles = db.get_records("CustomRoles", fresh=True)
    except Exception as exc:
        logger.error(
            "CustomRoles lookup failed while validating role for user=%s (%s); denying access fail-closed.",
            user_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify custom role authorization state. Please retry.",
        )
    if not isinstance(custom_roles, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Custom role authorization store returned malformed data. Access denied.",
        )
    if not is_recognized_role(clean_role, custom_roles=custom_roles):
        logger.warning("Authorization rejected for user=%s: unrecognized or inactive role '%s'.", user_id, clean_role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role is not recognized or has been disabled. Access denied.",
        )
    return clean_role


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token = credentials.credentials
    payload = decode_access_token(raw_token)
    uid = payload.get("user_id") or payload.get("sub") or payload.get("username") if payload else None
    if not payload or not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(uid).strip()
    payload = dict(payload)
    payload["user_id"] = user_id

    # Always read fresh AuthUsers state (AUTH-04); never fall back to cached rows or JWT claims.
    row, auth_error = _auth_row_for(user_id, fresh=True)
    if auth_error == "AMBIGUOUS_IDENTITY":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account identity is ambiguous in AuthUsers. Access denied until resolved by Owner.",
        )
    if auth_error:
        # Fail closed: NEVER fall back to stale JWT permissions when AuthUsers cannot be verified.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sheets is currently unreachable. Cannot verify current account permissions. Please retry.",
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists. Session revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Fail-closed active validation (AUTH-03): missing, blank, or malformed active status denies access.
    if not is_account_active(row.get("active")):
        logger.warning("Session rejected for user=%s: account is inactive or has invalid active status.", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated or inactive. Session revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fail-closed server-side revocation check (P1.5-003):
    # Never swallow RevokedTokens lookup errors or malformed responses into non-revoked access.
    revoked, rev_error = check_token_revocation(raw_token, payload, fresh=True)
    if rev_error is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "REJECTED",
                "error_code": rev_error,
                "message": "Unable to verify session revocation status. Access denied for security; please retry.",
                "retryable": True,
            },
        )
    if revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been logged out and revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check persistent user-level session revocation timestamp from AuthUsers sheet (fail-closed on malformed timestamp)
    revoked_at_str = str(row.get("sessions_revoked_at", "")).strip()
    if revoked_at_str:
        try:
            rev_dt = datetime.fromisoformat(revoked_at_str.replace("Z", "+00:00"))
            rev_epoch = rev_dt.timestamp()
            token_iat = float(payload.get("iat") or 0)
        except (ValueError, TypeError):
            logger.error(
                "Malformed sessions_revoked_at timestamp for user=%s; rejecting session fail-closed.",
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revocation state could not be verified. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if token_iat <= rev_epoch:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked due to password reset, role change, or security policy. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Authoritative role validation (AUTH-01 / AUTH-02):
    # Role MUST come exclusively from AuthUsers; NEVER fall back to JWT role claim or implicit default.
    authoritative_role = _validate_authoritative_role(row.get("role"), user_id)
    authoritative_uid = str(row.get("user_id") or user_id).strip()
    authoritative_username = str(row.get("username") or "").strip()
    authoritative_full_name = str(row.get("full_name") or authoritative_username or authoritative_uid).strip()

    payload["user_id"] = authoritative_uid
    payload["role"] = authoritative_role
    payload["full_name"] = authoritative_full_name
    payload["username"] = authoritative_username
    payload["must_change_password"] = str(row.get("must_change_password", "false")).strip().lower() == "true"
    return payload


async def require_sheets_connection() -> bool:
    from app.config import SALES_GOOGLE_SPREADSHEET_ID, SALES_ENV
    from app.sheets import db
    if SALES_ENV == "production" and not SALES_GOOGLE_SPREADSHEET_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sheets spreadsheet ID is not configured in production. No transaction was saved.",
        )
    if SALES_GOOGLE_SPREADSHEET_ID and (not getattr(db, "is_connected", False) or getattr(db, "spreadsheet", None) is None):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sheets is disconnected. No transaction was saved. Reconnect Sheets before retrying.",
        )
    return True
