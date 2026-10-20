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

security = HTTPBearer(auto_error=False)
_PBKDF2_PREFIX = "pbkdf2:sha256:"


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
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=SALES_TOKEN_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except Exception:
        return None


def _auth_row_for(user_id: str):
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
    payload = decode_access_token(credentials.credentials)
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
        # Transient Google Sheets quota limit or network timeout.
        # Preserve the cryptographically signed, unexpired session token
        # instead of revoking valid sessions on rate-limit hiccups.
        return payload
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists. Session revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if str(row.get("active", "true")).lower() == "false":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = dict(payload)
    payload["role"] = row.get("role") or payload.get("role")
    payload["full_name"] = row.get("full_name") or payload.get("full_name")
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
