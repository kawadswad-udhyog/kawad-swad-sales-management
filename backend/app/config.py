import os

SALES_GOOGLE_SPREADSHEET_ID = os.getenv("SALES_GOOGLE_SPREADSHEET_ID", "").strip()
SALES_GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/etc/secrets/sales-service-account.json").strip()
SALES_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SALES_JWT_SECRET = os.getenv("SALES_JWT_SECRET", "kawad-swad-sales-mgmt-secure-token-key-2026-prod-secret").strip()
SALES_CORS_ORIGINS = os.getenv("SALES_CORS_ORIGINS", "*").strip()
SALES_TOKEN_HOURS = int(os.getenv("SALES_TOKEN_HOURS", "8"))
SALES_OWNER_SETUP_SECRET = os.getenv("SALES_OWNER_SETUP_SECRET", "").strip()
