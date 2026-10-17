import os

SALES_GOOGLE_SPREADSHEET_ID = os.getenv("SALES_GOOGLE_SPREADSHEET_ID", "").strip()
SALES_GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/etc/secrets/sales-service-account.json"
).strip()
SALES_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SALES_CORS_ORIGINS = os.getenv(
    "SALES_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).strip()
SALES_TOKEN_HOURS = int(os.getenv("SALES_TOKEN_HOURS", "8"))
SALES_ENV = os.getenv("SALES_ENV", "development").strip().lower()

# Rejected if an operator pastes this historical placeholder back into the environment.
_INSECURE_SECRETS = {
    "",
    "changeme",
    "secret",
    "kawad-swad-sales-mgmt-secure-token-key-2026-prod-secret",
}


def jwt_secret() -> str:
    """Return the configured signing secret or raise. Never log the value."""
    secret = os.getenv("SALES_JWT_SECRET", "").strip()
    testing = os.getenv("SALES_TESTING", "").strip() == "1"
    if testing and not secret:
        return "test-only-secret-do-not-use-for-deployment-32"
    if secret in _INSECURE_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "SALES_JWT_SECRET must be set to a unique random value of at least 32 characters. "
            "The application will not start with a missing or known default secret."
        )
    return secret


def assert_runtime_config() -> None:
    secret_ok = True
    try:
        jwt_secret()
    except RuntimeError:
        secret_ok = False
    if not secret_ok:
        raise RuntimeError(
            "SALES_JWT_SECRET must be set to a unique random value of at least 32 characters."
        )
    origins = [o.strip() for o in SALES_CORS_ORIGINS.split(",") if o.strip()]
    if SALES_ENV == "production" and (not origins or "*" in origins):
        raise RuntimeError(
            "SALES_CORS_ORIGINS must list the real frontend origins when SALES_ENV=production. "
            "Wildcard CORS is not allowed."
        )
