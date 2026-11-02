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
    require_owner,
    require_manager,
)

import uuid
import time
from typing import Optional, Dict, Any, Set, Tuple

security = HTTPBearer(auto_error=False)
_PBKDF2_PREFIX = "pbkdf2:sha256:"

# In-memory revocation cache for instant sub-millisecond lookups across requests
_REVOKED_TOKENS: Set[str] = set()
_USER_REVOKED_AT: Dict[str, float] = {}


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
    """Revoke a single active JWT token (both in-memory and persisted)."""
    payload = decode_access_token(token)
    token_id = _token_identifier(token, payload)
    _REVOKED_TOKENS.add(token_id)
    if token:
        _REVOKED_TOKENS.add(token)

    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = ""
    if payload and payload.get("exp"):
        exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()

    from app.sheets import db
    try:
        rev_id = db.generate_id("RevokedTokens")
        persisted = db.append_record("RevokedTokens", {
            "token_id": rev_id,
            "jti": token_id,
            "user_id": user_id,
            "revoked_at": now_iso,
            "expires_at": exp_iso,
            "reason": reason,
        }, raise_on_error=raise_on_failure)
        return bool(persisted)
    except Exception as exc:
        logger.error(f"Failed to persist token revocation for user {user_id}: {exc}")
        if raise_on_failure:
            raise
        return False


def revoke_all_user_sessions(user_id: str, reason: str = "Security revocation", raise_on_failure: bool = False) -> bool:
    """Invalidate all active sessions across all devices for a user immediately."""
    clean_id = str(user_id or "").strip().lower()
    now_epoch = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    _USER_REVOKED_AT[clean_id] = now_epoch

    from app.sheets import db
    try:
        updated = db.update_record("AuthUsers", "user_id", user_id, {
            "sessions_revoked_at": now_iso
        }, raise_on_error=raise_on_failure)
        return bool(updated)
    except Exception as exc:
        logger.error(f"Failed to persist user-wide revocation for {user_id}: {exc}")
        if raise_on_failure:
            raise
        return False


def is_token_revoked(token: str, payload: Dict[str, Any]) -> bool:
    """Check if token was revoked explicitly or via user-wide revocation."""
    jti = payload.get("jti")
    token_id = _token_identifier(token, payload)
    if token_id in _REVOKED_TOKENS or (jti and jti in _REVOKED_TOKENS) or token in _REVOKED_TOKENS:
        return True

    # Check user-level revocation in memory
    user_id = str(payload.get("user_id") or payload.get("sub") or "").strip().lower()
    iat = float(payload.get("iat") or 0)
    if user_id in _USER_REVOKED_AT and iat <= _USER_REVOKED_AT[user_id]:
        return True

    # Check persisted RevokedTokens tab
    from app.sheets import db
    try:
        revoked_rows = db.get_records("RevokedTokens", fresh=False)
        for r in revoked_rows:
            r_jti = str(r.get("jti") or "").strip()
            if r_jti and (r_jti == token_id or (jti and r_jti == jti)):
                _REVOKED_TOKENS.add(token_id)
                return True
    except Exception:
        pass

    return False


def _auth_row_for(user_id: str) -> Tuple[Optional[dict], bool]:
    """Lookup AuthUsers row. Returns (row, error_occurred_flag)."""
    from app.sheets import db
    clean_id = str(user_id or "").strip().lower()
    if not clean_id:
        return None, False
    try:
        records = db.get_records("AuthUsers", fresh=False)
    except Exception:
        # Sheet read failed or quota exceeded
        return None, True
    for row in records:
        r_uid = str(row.get("user_id", "")).strip().lower()
        r_uname = str(row.get("username", "")).strip().lower()
        if (r_uid and r_uid == clean_id) or (r_uname and r_uname == clean_id):
            return row, False
    return None, False


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

    row, sheet_error = _auth_row_for(user_id)
    if sheet_error:
        # User System Audit Rule: Do NOT fall back to stale JWT permissions when Sheets cannot be read!
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
    if str(row.get("active", "true")).lower() in {"false", "0", "no"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated. Session revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check server-side revocation
    if is_token_revoked(raw_token, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been logged out and revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check persistent user-level session revocation timestamp from AuthUsers sheet
    revoked_at_str = str(row.get("sessions_revoked_at", "")).strip()
    if revoked_at_str:
        try:
            rev_dt = datetime.fromisoformat(revoked_at_str.replace("Z", "+00:00"))
            rev_epoch = rev_dt.timestamp()
            token_iat = float(payload.get("iat") or 0)
            if token_iat <= rev_epoch:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session revoked due to password reset, role change, or security policy. Please sign in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except (ValueError, TypeError):
            pass

    # Ensure authoritative permissions and details always come from fresh sheet record
    payload["role"] = row.get("role") or payload.get("role")
    payload["full_name"] = row.get("full_name") or payload.get("full_name")
    payload["username"] = row.get("username") or payload.get("username")
    payload["must_change_password"] = str(row.get("must_change_password", "false")).lower() == "true"
    return payload


async def require_sheets_connection() -> bool:
    from app.config import SALES_GOOGLE_SPREADSHEET_ID
    from app.sheets import db
    if SALES_GOOGLE_SPREADSHEET_ID and (not getattr(db, "is_connected", False) or getattr(db, "spreadsheet", None) is None):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sheets is disconnected. No transaction was saved. Reconnect Sheets before retrying.",
        )
    return True
