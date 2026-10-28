import os
import secrets
import logging

logger = logging.getLogger("kawad_swad.config")

SALES_GOOGLE_SPREADSHEET_ID = os.getenv("SALES_GOOGLE_SPREADSHEET_ID", "").strip()
SALES_GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/etc/secrets/sales-service-account.json"
).strip()
SALES_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SALES_CORS_ORIGINS = os.getenv(
    "SALES_CORS_ORIGINS",
    "https://kawad-swad-sales-frontend.onrender.com,http://localhost:3000,http://127.0.0.1:3000",
).strip()
SALES_TOKEN_HOURS = int(os.getenv("SALES_TOKEN_HOURS", "8"))
SALES_ENV = os.getenv("SALES_ENV", "development").strip().lower()

_EPHEMERAL_SECRET = secrets.token_hex(32)

_INSECURE_SECRETS = {
    "",
    "changeme",
    "secret",
    "kawad-swad-sales-mgmt-secure-token-key-2026-prod-secret",
}


def jwt_secret() -> str:
    """Return the configured signing secret or generate an ephemeral runtime secret in dev."""
    secret = os.getenv("SALES_JWT_SECRET", "").strip()
    testing = os.getenv("SALES_TESTING", "").strip() == "1"
    if testing and not secret:
        return "test-only-secret-do-not-use-for-deployment-32"
    if secret in _INSECURE_SECRETS or len(secret) < 32:
        if SALES_ENV == "production":
            raise RuntimeError(
                "SALES_JWT_SECRET is missing or under 32 characters in production. "
                "Production deployment must fail-closed to prevent session loss on restart. "
                "Configure a secure SALES_JWT_SECRET (>= 32 characters) in your environment variables."
            )
        logger.warning(
            "SALES_JWT_SECRET is missing or under 32 characters in environment. "
            "Using an ephemeral process secret in non-production. "
            "Please configure SALES_JWT_SECRET in your environment variables."
        )
        return _EPHEMERAL_SECRET
    return secret


def assert_runtime_config() -> None:
    _ = jwt_secret()
    origins = [o.strip() for o in SALES_CORS_ORIGINS.split(",") if o.strip()]
    if SALES_ENV == "production":
        if not origins or "*" in origins:
            raise RuntimeError(
                "SALES_CORS_ORIGINS must list the real frontend origins when SALES_ENV=production. "
                "Wildcard CORS is not allowed."
            )
        if not SALES_GOOGLE_SPREADSHEET_ID:
            raise RuntimeError(
                "SALES_GOOGLE_SPREADSHEET_ID is missing from environment in production. "
                "Production deployment must fail-closed to prevent data loss."
            )
        has_sa_file = bool(SALES_GOOGLE_SERVICE_ACCOUNT_FILE and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE))
        has_sa_json = bool(SALES_GOOGLE_SERVICE_ACCOUNT_JSON and len(SALES_GOOGLE_SERVICE_ACCOUNT_JSON.strip()) > 10)
        if not (has_sa_file or has_sa_json):
            raise RuntimeError(
                "Neither SALES_GOOGLE_SERVICE_ACCOUNT_FILE nor SALES_GOOGLE_SERVICE_ACCOUNT_JSON is configured or accessible in production. "
                "Production deployment must fail-closed to prevent data loss."
            )

