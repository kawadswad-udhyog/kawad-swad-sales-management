import os
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.config import (
    SALES_GOOGLE_SPREADSHEET_ID,
    SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
    SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
)

logger = logging.getLogger("kawad_swad.sheets")

ID_PREFIXES = {
    "Users": "USR",
    "Products": "PRD",
    "Customers": "CUS",
    "Sales": "SALE",
    "SaleItems": "ITEM",
    "Payments": "PAY",
    "SalesmanStockLedger": "STK",
    "CashLedger": "CSH",
    "Expenses": "EXP",
    "ShopVisits": "VIS",
    "DailyClosing": "CLOSE",
    "SalaryIncentives": "SAL",
    "AuditLog": "AUD",
}

class SheetsDatabase:
    """Manages connection to Google Sheets or in-memory fallback."""

    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self.is_connected = False
        # Short-lived per-tab cache prevents dashboard and list endpoints from
        # repeatedly reading the same Google worksheet during one refresh.
        # All backend writes invalidate the affected tab immediately.
        self._records_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._records_cache_ttl_seconds = 10.0
        self.memory_store: Dict[str, List[Dict[str, Any]]] = {
            "AuthUsers": [],
            "Users": [],
            "Products": [],
            "Customers": [],
            "Sales": [],
            "SaleItems": [],
            "Payments": [],
            "SalesmanStockLedger": [],
            "CashLedger": [],
            "Expenses": [],
            "ShopVisits": [],
            "DailyClosing": [],
            "SalaryIncentives": [],
            "AuditLog": [],
            "Settings": [],
        }
        self.init_connection()

    def init_connection(self):
        if not SALES_GOOGLE_SPREADSHEET_ID:
            logger.warning("SALES_GOOGLE_SPREADSHEET_ID not provided. Using in-memory fallback.")
            return

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            creds = None
            if SALES_GOOGLE_SERVICE_ACCOUNT_JSON:
                try:
                    info = json.loads(SALES_GOOGLE_SERVICE_ACCOUNT_JSON)
                    creds = Credentials.from_service_account_info(info, scopes=scopes)
                except Exception as ex:
                    logger.error(f"Error parsing SALES_GOOGLE_SERVICE_ACCOUNT_JSON: {ex}")

            if not creds and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE):
                creds = Credentials.from_service_account_file(
                    SALES_GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes
                )

            if creds:
                self.client = gspread.authorize(creds)
                self.spreadsheet = self.client.open_by_key(SALES_GOOGLE_SPREADSHEET_ID)
                self.is_connected = True
                logger.info(f"Successfully connected to Google Sheet ID: {SALES_GOOGLE_SPREADSHEET_ID}")
            else:
                logger.warning("No valid Google service account credentials found. Operating in-memory.")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}. Falling back to in-memory.")

    def _invalidate_records_cache(self, tab_name: str) -> None:
        self._records_cache.pop(tab_name, None)

    def get_records(self, tab_name: str) -> List[Dict[str, Any]]:
        """Fetch worksheet rows with a short cache for repeated dashboard reads."""
        now = time.monotonic()
        # Cache only live Google Sheets reads. Test and in-memory mode must
        # always reflect direct fixture updates immediately.
        if self.is_connected and self.spreadsheet:
            cached = self._records_cache.get(tab_name)
            if cached and now - cached[0] < self._records_cache_ttl_seconds:
                return [dict(row) for row in cached[1]]
            try:
                worksheet = self.spreadsheet.worksheet(tab_name)
                records = worksheet.get_all_records()
                safe_records = [dict(row) for row in records]
                self._records_cache[tab_name] = (now, safe_records)
                return [dict(row) for row in safe_records]
            except Exception as e:
                logger.warning(f"Error reading {tab_name} from sheet: {e}")
                return [dict(row) for row in self.memory_store.get(tab_name, [])]
        return [dict(row) for row in self.memory_store.get(tab_name, [])]

    def append_record(self, tab_name: str, record: Dict[str, Any], raise_on_error: bool = False) -> bool:
        """Append a record to a worksheet. Returns True on success, False or raises on failure."""
        self._invalidate_records_cache(tab_name)
        self.memory_store.setdefault(tab_name, []).append(record)

        if self.is_connected and self.spreadsheet:
            try:
                worksheet = self.spreadsheet.worksheet(tab_name)
                headers = worksheet.row_values(1)
                if not headers:
                    headers = list(record.keys())
                    worksheet.append_row(headers)
                row = [record.get(h, "") for h in headers]
                worksheet.append_row(row)
                return True
            except Exception as e:
                logger.error(f"Error appending to {tab_name} in Google Sheet: {e}")
                if raise_on_error:
                    raise e
                return False
        return True

    def delete_record(self, tab_name: str, id_field: str, id_value: str) -> bool:
        """Delete a record from memory store and Google Sheets (used for rollback/recovery)."""
        self._invalidate_records_cache(tab_name)
        found = False
        items = self.memory_store.get(tab_name, [])
        initial_len = len(items)
        self.memory_store[tab_name] = [
            item for item in items if str(item.get(id_field)) != str(id_value)
        ]
        if len(self.memory_store[tab_name]) < initial_len:
            found = True

        if self.is_connected and self.spreadsheet:
            try:
                worksheet = self.spreadsheet.worksheet(tab_name)
                records = worksheet.get_all_records()
                for idx, r in enumerate(records, start=2):
                    if str(r.get(id_field)) == str(id_value):
                        worksheet.delete_rows(idx)
                        return True
            except Exception as e:
                logger.error(f"Error deleting record in {tab_name}: {e}")

        return found

    def update_record(self, tab_name: str, id_field: str, id_value: str, updates: Dict[str, Any]) -> bool:
        """Update a record in the memory store and in Google Sheets if connected."""
        self._invalidate_records_cache(tab_name)
        found = False
        items = self.memory_store.get(tab_name, [])
        for item in items:
            val = item.get(id_field)
            if val is None:
                for ik, iv in item.items():
                    if str(ik).strip().lower() == str(id_field).strip().lower():
                        val = iv
                        break
            if str(val) == str(id_value):
                item.update(updates)
                found = True
                break

        if self.is_connected and self.spreadsheet:
            try:
                worksheet = self.spreadsheet.worksheet(tab_name)
                records = worksheet.get_all_records()
                headers = worksheet.row_values(1)
                header_map = {str(h).strip().lower(): i + 1 for i, h in enumerate(headers)}
                for idx, r in enumerate(records, start=2):
                    val = r.get(id_field)
                    if val is None:
                        for ik, iv in r.items():
                            if str(ik).strip().lower() == str(id_field).strip().lower():
                                val = iv
                                break
                    if str(val) == str(id_value):
                        for k, v in updates.items():
                            k_lower = str(k).strip().lower()
                            if k_lower in header_map:
                                col_idx = header_map[k_lower]
                                worksheet.update_cell(idx, col_idx, v)
                        return True
            except Exception as e:
                logger.error(f"Error updating record in {tab_name}: {e}")

        return found

    def generate_id(self, tab_name: str) -> str:
        """Generate human-readable sequential ID (e.g. SALE-000001)."""
        prefix = ID_PREFIXES.get(tab_name, tab_name[:3].upper())
        records = self.get_records(tab_name)
        seq = len(records) + 1
        return f"{prefix}-{str(seq).zfill(6)}"

    def log_audit(self, actor: str, action: str, entity_type: str, entity_id: str,
                  field_changed: str = "", old_val: str = "", new_val: str = "",
                  reason: str = "", approved_by: str = "", related_id: str = ""):
        """Append an entry to the AuditLog."""
        audit_id = self.generate_id("AuditLog")
        record = {
            "audit_id": audit_id,
            "event_datetime": datetime.utcnow().isoformat(),
            "actor_user_id": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_changed": field_changed,
            "old_value": str(old_val),
            "new_value": str(new_val),
            "reason": reason,
            "approved_by_user_id": approved_by,
            "related_record_id": related_id,
        }
        self.append_record("AuditLog", record)

db = SheetsDatabase()
