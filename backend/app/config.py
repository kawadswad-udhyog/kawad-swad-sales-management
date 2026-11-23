import os
import secrets
import logging
from typing import Optional

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

# Blueprint v2.1 Apps Script Single-Write-Owner Bridge Configuration
SALES_APPS_SCRIPT_ENABLED = os.getenv("SALES_APPS_SCRIPT_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
SALES_APPS_SCRIPT_WEBAPP_URL = os.getenv("SALES_APPS_SCRIPT_WEBAPP_URL", "").strip()
SALES_APPS_SCRIPT_SHARED_SECRET = os.getenv("SALES_APPS_SCRIPT_SHARED_SECRET", "").strip()
try:
    _raw_as_timeout = float(os.getenv("SALES_APPS_SCRIPT_TIMEOUT_SECONDS", "15"))
    SALES_APPS_SCRIPT_TIMEOUT_SECONDS = max(3.0, min(_raw_as_timeout, 30.0))
except (TypeError, ValueError):
    SALES_APPS_SCRIPT_TIMEOUT_SECONDS = 15.0

SALES_CA_POLICY_CONFIG_JSON = os.getenv("SALES_CA_POLICY_CONFIG_JSON", "").strip()
SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON = os.getenv(
    "SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON", ""
).strip()

# Authentication lockout configuration (consistent across code, messages, and tests)
try:
    SALES_LOGIN_MAX_ATTEMPTS = max(1, int(os.getenv("SALES_LOGIN_MAX_ATTEMPTS", "5")))
except (TypeError, ValueError):
    SALES_LOGIN_MAX_ATTEMPTS = 5

try:
    SALES_LOGIN_LOCKOUT_SECONDS = max(1.0, float(os.getenv("SALES_LOGIN_LOCKOUT_SECONDS", "300")))
except (TypeError, ValueError):
    SALES_LOGIN_LOCKOUT_SECONDS = 300.0

# Explicit opt-in gate for offline CLI schema migration tools (disabled by default)
SALES_ALLOW_OFFLINE_SHEETS_MIGRATION = (
    os.getenv("SALES_ALLOW_OFFLINE_SHEETS_MIGRATION", "false").strip().lower() in {"1", "true", "yes"}
)

_EPHEMERAL_SECRET = secrets.token_hex(32)
TEST_ONLY_JWT_SECRET = "test-only-secret-do-not-use-for-deployment-32"

_INSECURE_SECRETS = {
    "",
    "changeme",
    "secret",
    "kawad-swad-sales-mgmt-secure-token-key-2026-prod-secret",
    TEST_ONLY_JWT_SECRET,
}

_TRUTHY_TESTING_VALUES = frozenset({"1", "true", "yes", "on"})


class ProductionTestModeConflictError(RuntimeError):
    """Raised fail-closed when production environment is combined with testing mode."""

    error_code = "PRODUCTION_TEST_MODE_CONFLICT"


def get_effective_env(env: Optional[str] = None) -> str:
    """
    Resolve effective runtime environment fail-closed.
    If an explicit `env` argument is omitted, production takes absolute precedence
    whenever either module-level `SALES_ENV` or live process `SALES_ENV` is 'production'.
    """
    if env is not None:
        return str(env).strip().lower()
    live_env = str(os.getenv("SALES_ENV", "") or "").strip().lower()
    mod_env = str(SALES_ENV or "").strip().lower()
    if mod_env == "production" or live_env == "production":
        return "production"
    return live_env or mod_env or "development"


def is_production_env(env: Optional[str] = None) -> bool:
    """Return True when the effective runtime environment is production."""
    return get_effective_env(env=env) == "production"


def is_testing_flag_enabled(testing: Optional[bool] = None) -> bool:
    """Return True when SALES_TESTING (or explicit override) activates test mode."""
    if testing is not None:
        return bool(testing)
    return str(os.getenv("SALES_TESTING", "") or "").strip().lower() in _TRUTHY_TESTING_VALUES


def assert_production_test_isolation(
    *,
    env: Optional[str] = None,
    testing: Optional[bool] = None,
) -> None:
    """
    Centralized fail-closed guard enforcing absolute production/test isolation (M19-001).
    Production configuration takes absolute precedence over all test flags:
    SALES_ENV=production combined with SALES_TESTING=1 (or any truthy test flag)
    is rejected deterministically before dependent components initialize.
    """
    if is_production_env(env=env) and is_testing_flag_enabled(testing=testing):
        raise ProductionTestModeConflictError(
            "FATAL CONFIGURATION CONFLICT [PRODUCTION_TEST_MODE_CONFLICT]: "
            "SALES_TESTING cannot be enabled when SALES_ENV=production. "
            "Production configuration takes absolute precedence over test flags; "
            "unset SALES_TESTING (or set SALES_TESTING=0) before starting the application."
        )


def is_isolated_testing_mode(
    *,
    env: Optional[str] = None,
    testing: Optional[bool] = None,
) -> bool:
    """
    Return True ONLY when testing mode is enabled in a non-production environment.
    Fails closed with ProductionTestModeConflictError if production and testing mode
    are simultaneously active.
    """
    assert_production_test_isolation(env=env, testing=testing)
    return is_testing_flag_enabled(testing=testing)


def jwt_secret() -> str:
    """Return the configured signing secret or generate an ephemeral runtime secret in dev."""
    assert_production_test_isolation()
    secret = str(os.getenv("SALES_JWT_SECRET", "") or "").strip()

    if is_production_env():
        if secret in _INSECURE_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "SALES_JWT_SECRET is missing, insecure, or under 32 characters in production. "
                "Production deployment must fail-closed to prevent session loss or forged tokens. "
                "Configure a secure SALES_JWT_SECRET (>= 32 characters) in your environment variables."
            )
        return secret

    if is_isolated_testing_mode():
        if not secret or secret == TEST_ONLY_JWT_SECRET:
            return TEST_ONLY_JWT_SECRET

    if secret in _INSECURE_SECRETS or len(secret) < 32:
        logger.warning(
            "SALES_JWT_SECRET is missing, insecure, or under 32 characters in environment. "
            "Using an ephemeral process secret in non-production. "
            "Please configure SALES_JWT_SECRET in your environment variables."
        )
        return _EPHEMERAL_SECRET
    return secret


def assert_runtime_config() -> None:
    assert_production_test_isolation()
    _ = jwt_secret()
    origins = [o.strip() for o in SALES_CORS_ORIGINS.split(",") if o.strip()]
    if is_production_env():
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
        # TX-AUDIT-02: Production MUST fail closed if transaction coordinator persistence
        # is missing, volatile (/tmp), unmounted, unwritable, or horizontally scaled (>1 instance).
        from app.transaction_safety import validate_coordinator_durability
        validate_coordinator_durability(env="production", testing=is_testing_flag_enabled())


# Fail-closed startup ordering guard: reject production + test-mode conflict immediately
# on config module import before storage, auth, coordinator, or API setup can run.
assert_production_test_isolation()



