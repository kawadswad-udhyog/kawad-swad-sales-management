import os, hashlib, hmac, base64, secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def _secret():
    secret = os.getenv("SALES_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("Set SALES_JWT_SECRET to a random secret of at least 32 characters in Render.")
    return secret

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 310000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, expected = encoded.split("$")
        if scheme != "pbkdf2_sha256": return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except Exception:
        return False

def create_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user["user_id"], "role": user["role"], "name": user["full_name"],
               "iat": now, "exp": now + timedelta(hours=int(os.getenv("SALES_TOKEN_HOURS", "8")))}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired login. Please sign in again.")

def current_user(token: str = Depends(oauth2_scheme)):
    return decode_token(token)

def require_roles(*roles):
    def checker(user=Depends(current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Your account is not permitted to perform this action.")
        return user
    return checker
