import hmac
import re
import asyncio
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Header
from app.models import (
    LoginRequest,
    TokenResponse,
    UserProfile,
    OwnerSetupRequest,
    OwnerSetupResponse,
)
from app.sheets import db
from app.auth import verify_password, create_access_token, get_current_user, hash_password
from app.config import SALES_OWNER_SETUP_SECRET

logger = logging.getLogger("kawad_swad.auth")
_owner_setup_lock = asyncio.Lock()

router = APIRouter(tags=["Authentication"])


def _validate_owner_setup_fields(req: OwnerSetupRequest) -> None:
    username = req.username.strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username cannot be empty or whitespace only.",
        )
    if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must contain only letters, numbers, underscores, dots, or hyphens.",
        )
    if len(username) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must be at least 3 characters long.",
        )

    full_name = req.full_name.strip()
    if not full_name or len(full_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Full name must be at least 2 characters long.",
        )

    password = req.password
    if len(password) < 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 12 characters long.",
        )
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)

    if not (has_upper and has_lower and (has_digit or has_special)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must include uppercase, lowercase, and at least one digit or special character.",
        )


def _verify_setup_secret(setup_secret: Optional[str]) -> None:
    if not SALES_OWNER_SETUP_SECRET or not SALES_OWNER_SETUP_SECRET.strip():
        logger.error("Owner setup attempt blocked: SALES_OWNER_SETUP_SECRET is not configured on this server.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Initial owner setup is disabled or unconfigured on this server.",
        )

    if not setup_secret or not setup_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required setup secret header (X-Setup-Secret).",
        )

    supplied_bytes = setup_secret.strip().encode("utf-8")
    configured_bytes = SALES_OWNER_SETUP_SECRET.strip().encode("utf-8")
    if not hmac.compare_digest(supplied_bytes, configured_bytes):
        logger.warning("Owner setup attempt failed: Invalid setup secret provided.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid setup secret.",
        )


@router.post("/api/auth/setup-owner", response_model=OwnerSetupResponse, tags=["Authentication"])
@router.post("/auth/setup-owner", response_model=OwnerSetupResponse, tags=["Authentication"])
async def setup_owner(
    req: OwnerSetupRequest,
    x_setup_secret: Optional[str] = Header(None, alias="X-Setup-Secret"),
):
    """
    Secure, one-time initial OWNER account setup endpoint.
    Guarded by SALES_OWNER_SETUP_SECRET header and concurrency lock.
    Permanently locks once the first OWNER account exists.
    """
    # 1. Verify secret timing-safely; fails closed if unconfigured
    _verify_setup_secret(x_setup_secret)

    # 2. Validate input fields and password strength
    _validate_owner_setup_fields(req)

    clean_username = req.username.strip()
    clean_full_name = req.full_name.strip()

    # 3. Synchronize via lock to prevent concurrent duplicate creation
    async with _owner_setup_lock:
        auth_records = db.get_records("AuthUsers")
        users_records = db.get_records("Users")

        # Check if an OWNER or OWNER_ADMIN already exists in either table
        for auth in auth_records:
            if str(auth.get("role", "")).upper() in ["OWNER", "OWNER_ADMIN"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An Owner account already exists in AuthUsers. Initial setup is permanently locked.",
                )
        for user in users_records:
            if str(user.get("role", "")).upper() in ["OWNER", "OWNER_ADMIN"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An Owner account already exists in Users. Initial setup is permanently locked.",
                )

        # Check if username or user_id is already registered
        norm_username = clean_username.lower()
        for auth in auth_records:
            if str(auth.get("username", "")).strip().lower() == norm_username:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Username '{clean_username}' is already in use.",
                )
        for user in users_records:
            if (
                str(user.get("user_id", "")).strip().lower() == norm_username
                or str(user.get("full_name", "")).strip().lower() == norm_username
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User identifier '{clean_username}' is already in use.",
                )

        # Generate IDs
        user_id = db.generate_id("Users")
        auth_id = db.generate_id("AuthUsers")
        now_iso = datetime.utcnow().isoformat()

        user_record = {
            "user_id": user_id,
            "full_name": clean_full_name,
            "role": "OWNER",
            "mobile": "",
            "email": "",
            "active": "true",
            "created_at": now_iso,
            "notes": "Initial Owner account created via secure setup endpoint",
        }

        hashed_pw = hash_password(req.password)
        auth_record = {
            "auth_id": auth_id,
            "user_id": user_id,
            "username": clean_username,
            "password_hash": hashed_pw,
            "role": "OWNER",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
        }

        # Step 4: Write Users record with atomic fallback
        try:
            db.append_record("Users", user_record, raise_on_error=True)
        except Exception as e:
            logger.error(f"Failed to append Users record during initial setup: {e}")
            db.delete_record("Users", "user_id", user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to write Users record to database. Setup aborted safely without modifying state.",
            )

        # Step 5: Write AuthUsers record with atomic rollback of Users if it fails
        try:
            db.append_record("AuthUsers", auth_record, raise_on_error=True)
        except Exception as e:
            logger.critical(f"Failed to append AuthUsers record after Users write. Executing rollback: {e}")
            rollback_ok = db.delete_record("Users", "user_id", user_id)
            db.log_audit(
                actor="SYSTEM",
                action="SETUP_OWNER_ROLLBACK",
                entity_type="Users",
                entity_id=user_id,
                reason=f"AuthUsers append failed; Users rollback status: {'SUCCESS' if rollback_ok else 'FAILED'}",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write AuthUsers record. Rollback of Users was {'completed successfully' if rollback_ok else 'incomplete - check sheet'}. Setup aborted.",
            )

        # Step 6: Audit log successful setup (never log plaintext password or secret)
        db.log_audit(
            actor=user_id,
            action="BOOTSTRAP_OWNER_CREATED",
            entity_type="Users",
            entity_id=user_id,
            reason=f"Initial Owner {clean_username} successfully created via secure setup endpoint",
        )

        logger.info(f"Initial Owner account {clean_username} ({user_id}) successfully created.")

        return OwnerSetupResponse(
            success=True,
            message="Initial Owner account successfully created. You can now log in.",
            user_id=user_id,
            username=clean_username,
            full_name=clean_full_name,
            role="OWNER",
            created_at=now_iso,
        )


@router.post("/api/auth/login", response_model=TokenResponse)
@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    auth_records = db.get_records("AuthUsers")
    user_match = None

    for auth in auth_records:
        if auth.get("username", "").strip().lower() == req.username.strip().lower():
            if str(auth.get("active", "true")).lower() == "false":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
            if verify_password(req.password, auth.get("password_hash", "")):
                user_match = auth
                break

    if not user_match:
        # Check standard Users tab for development fallback
        users = db.get_records("Users")
        for u in users:
            if u.get("user_id", "").strip().lower() == req.username.strip().lower() or \
               u.get("full_name", "").strip().lower() == req.username.strip().lower():
                # Allow dev login if no AuthUsers records exist yet
                if len(auth_records) == 0:
                    user_match = {
                        "user_id": u.get("user_id"),
                        "username": req.username,
                        "full_name": u.get("full_name"),
                        "role": u.get("role", "SALESMAN"),
                    }
                    break

    if not user_match:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    user_id = user_match.get("user_id")
    role = user_match.get("role", "SALESMAN")
    full_name = user_match.get("full_name", user_id)

    token_data = {
        "sub": user_id,
        "user_id": user_id,
        "full_name": full_name,
        "role": role,
    }
    access_token = create_access_token(token_data)

    db.log_audit(
        actor=user_id,
        action="LOGIN",
        entity_type="AuthUsers",
        entity_id=user_id,
        reason="User successfully authenticated"
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        full_name=full_name,
        role=role,
    )

@router.get("/api/auth/me")
@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user.get("user_id"),
        "full_name": current_user.get("full_name"),
        "role": current_user.get("role"),
    }
