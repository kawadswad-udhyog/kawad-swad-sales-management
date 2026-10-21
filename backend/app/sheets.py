import os
import json
import logging
import re
import threading
import uuid
from typing import Dict, List, Any, Optional

from app.config import (
    SALES_GOOGLE_SPREADSHEET_ID,
    SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
    SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
)
from app.timeutil import now_iso

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
    "AuthUsers": "AUTH",
    "Workers": "WRK",
    "WorkerAttendance": "ATT",
    "Recipes": "RCP",
    "ProductionBatches": "PRB",
    "PackagingBatches": "PKG",
    "ProductionStockLedger": "PST",
    "ProductionDispatches": "DSP",
    "RawMaterialLedger": "RML",
    "RawMaterials": "RWM",
    "IdAllocations": "ALC",
    "StockDiscrepancies": "DSC",
    "IncompleteTransactions": "TXN",
    "RevokedTokens": "RVK",
    "ApprovalRequests": "REQ",
}

REQUIRED_TABS = {
    "IdAllocations": ["allocation_id", "tab_name", "allocated_id", "nonce", "created_at"],
    "RevokedTokens": ["token_id", "jti", "user_id", "revoked_at", "expires_at", "reason"],
    "ApprovalRequests": ["request_id", "request_type", "target_user_id", "requested_by", "requested_at", "payload_json", "status", "decided_by", "decided_at", "decision_notes", "execution_error", "executed_at"],
    "AuthUsers": ["auth_id", "user_id", "username", "password_hash", "role", "active", "created_at", "must_change_password", "sessions_revoked_at"],
    "Users": ["user_id", "full_name", "username", "role", "mobile", "email", "active", "created_at", "notes"],
    "Products": ["product_id", "sku", "product_name", "category", "variant", "pack_weight_g", "selling_unit", "retail_pack_only", "active", "notes"],
    "Customers": ["customer_id", "customer_type", "shop_name", "shopkeeper_name", "mobile", "alternate_mobile", "address", "locality_area", "city", "gstin", "map_location", "active", "created_at"],
    "Sales": [
        "sale_id", "bill_number", "idempotency_key", "txn_status", "sale_datetime", "sales_type",
        "customer_id", "customer_name_snapshot", "customer_mobile", "customer_gstin",
        "entered_by_user_id", "salesman_user_id", "delivery_status", "payment_status",
        "payment_method", "payment_reference", "subtotal", "discount_amount", "tax_amount",
        "bill_total", "bill_status", "created_at", "notes",
    ],
    "SaleItems": [
        "sale_item_id", "sale_id", "product_id", "product_name_snapshot", "sku_snapshot",
        "pack_weight_g", "unit", "quantity", "actual_unit_price", "discount_amount",
        "line_total", "qualifying_kg", "created_at", "notes",
    ],
    "Payments": [
        "payment_id", "sale_id", "payment_datetime", "payment_method", "amount",
        "reference_number", "received_by_user_id", "payment_status", "notes",
    ],
    "SalesmanStockLedger": [
        "stock_txn_id", "txn_datetime", "salesman_user_id", "product_id", "sku_snapshot",
        "txn_type", "quantity", "unit", "pack_weight_g", "related_sale_id",
        "issued_by_user_id", "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes",
    ],
    "CashLedger": [
        "cash_txn_id", "txn_datetime", "salesman_user_id", "txn_type", "amount",
        "payment_method", "related_sale_id", "related_expense_id", "issued_by_user_id",
        "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes",
    ],
    "Expenses": [
        "expense_id", "expense_datetime", "salesman_user_id", "category", "amount",
        "payment_mode", "description", "receipt_image_url", "approval_status",
        "approved_by_user_id", "approved_datetime", "rejection_reason", "created_at", "notes",
    ],
    "ShopVisits": [
        "visit_id", "visit_datetime", "salesman_user_id", "customer_id", "customer_name_snapshot",
        "purpose", "outcome", "notes", "created_at",
    ],
    "DailyClosing": [
        "closing_id", "closing_date", "salesman_user_id", "opening_cash", "cash_collected",
        "approved_cash_expenses", "expected_cash_return", "physical_cash_returned", "cash_difference",
        "opening_stock_reference", "stock_discrepancy_flag", "closing_status", "submitted_at",
        "reviewed_by_user_id", "reviewed_at", "notes", "upi_collected", "bank_collected", "other_collected",
    ],
    "SalaryIncentives": [
        "incentive_id", "period_month", "salesman_user_id", "salesman_name", "qualifying_kg_sold",
        "base_rate_per_kg", "incentive_amount", "approved_by_user_id", "status", "paid_at", "notes", "created_at",
    ],
    "AuditLog": [
        "audit_id", "event_datetime", "actor_user_id", "action", "entity_type", "entity_id",
        "field_changed", "old_value", "new_value", "reason", "approved_by_user_id", "related_record_id",
    ],
    "Recipes": [
        "recipe_id", "product_id", "product_name_snapshot", "product_family", "version",
        "approved", "expected_yield_kg", "items_json", "notes", "created_at", "created_by",
        "approved_by", "approved_at",
    ],
    "RawMaterials": [
        "raw_material_id", "material_name", "current_stock", "unit", "rate_per_unit",
        "rate_status", "category", "created_at", "created_by",
    ],
    "ProductionBatches": [
        "production_id", "production_date", "product_id", "product_name_snapshot",
        "quantity_kg", "wastage_kg", "net_quantity_kg", "flour_base_used_kg",
        "benchmark_yield_kg", "actual_yield_ratio", "yield_variance_kg", "recipe_id",
        "status", "notes", "created_at", "created_by", "approved_by", "approved_at",
        "approval_notes",
    ],
    "PackagingBatches": [
        "packaging_id", "packaging_date", "product_id", "product_name_snapshot",
        "bulk_kg_used", "packets_200g", "packets_500g", "packets_1000g", "total_packets",
        "expected_kg", "difference_kg", "difference_status", "status", "notes",
        "created_at", "created_by",
    ],
    "ProductionStockLedger": [
        "movement_id", "txn_datetime", "movement_type", "product_id", "bulk_product_key",
        "product_name_snapshot", "sku_snapshot", "pack_weight_g", "quantity_kg",
        "quantity_packets", "channel", "reference_id", "destination", "created_by", "notes",
    ],
    "ProductionDispatches": [
        "dispatch_id", "dispatch_datetime", "product_id", "product_name_snapshot",
        "channel", "destination", "quantity_packets", "reference", "status",
        "created_by", "notes",
    ],
    "RawMaterialLedger": [
        "raw_material_txn_id", "txn_datetime", "material_name", "raw_material_id",
        "movement_type", "quantity", "unit", "production_id", "created_by", "notes",
    ],
    "Workers": [
        "worker_id", "worker_name", "mobile", "daily_wage", "active", "notes", "created_at",
    ],
    "WorkerAttendance": [
        "attendance_id", "worker_id", "worker_name_snapshot", "attendance_date",
        "status", "daily_wage_snapshot", "wage_accrued", "notes", "created_at", "created_by",
    ],
    "StockDiscrepancies": [
        "discrepancy_id", "discrepancy_date", "location", "product_id", "product_name_snapshot",
        "expected_stock", "physical_count", "difference", "reason", "counted_by_user_id",
        "reviewed_by_user_id", "status", "approved_adjustment", "created_at",
    ],
    "IncompleteTransactions": [
        "transaction_id", "transaction_type", "idempotency_key", "status", "payload_json",
        "error_details", "created_at", "updated_at", "resolved_by", "resolved_at",
    ],
}


class SheetsDatabase:
    """Google Sheets adapter with persistent write enforcement and isolated testing support."""

    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self.is_connected = False
        self.last_connection_error: Optional[str] = None
        self.allow_in_memory_fallback = os.getenv("SALES_TESTING", "").strip() == "1"
        self._records_cache: Dict[str, tuple] = {}
        self._records_cache_ttl_seconds = 30.0
        self._worksheets: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._inflight: Dict[str, threading.Event] = {}
        self._fail_once: Dict[str, int] = {}
        self.memory_store: Dict[str, List[Dict[str, Any]]] = {name: [] for name in list(ID_PREFIXES) + ["Settings"]}
        self._last_conn_attempt_time: float = 0.0
        self.init_connection()

    def init_connection(self) -> bool:
        """Attempt to connect to Google Sheets using configured service account credentials."""
        import time
        self._last_conn_attempt_time = time.monotonic()
        self.is_connected = False
        self.last_connection_error = None

        if not SALES_GOOGLE_SPREADSHEET_ID:
            self.last_connection_error = (
                "SALES_GOOGLE_SPREADSHEET_ID is not configured in environment. "
                "Persistent storage cannot initialize."
            )
            if self.allow_in_memory_fallback:
                logger.warning("%s Operating in-memory for testing.", self.last_connection_error)
            else:
                logger.error("%s Business writes are disabled to prevent data loss.", self.last_connection_error)
            return False

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
            ]
            creds = None
            if SALES_GOOGLE_SERVICE_ACCOUNT_JSON:
                try:
                    info = json.loads(SALES_GOOGLE_SERVICE_ACCOUNT_JSON)
                    creds = Credentials.from_service_account_info(info, scopes=scopes)
                except Exception as exc:
                    self.last_connection_error = f"Invalid SALES_GOOGLE_SERVICE_ACCOUNT_JSON format: {exc}"
                    logger.error(self.last_connection_error)
                    return False

            if not creds and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE):
                try:
                    creds = Credentials.from_service_account_file(SALES_GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
                except Exception as exc:
                    self.last_connection_error = f"Failed to load service account file {SALES_GOOGLE_SERVICE_ACCOUNT_FILE}: {exc}"
                    logger.error(self.last_connection_error)
                    return False

            if not creds:
                self.last_connection_error = (
                    "No Google service account credentials found. "
                    "Configure SALES_GOOGLE_SERVICE_ACCOUNT_JSON or SALES_GOOGLE_SERVICE_ACCOUNT_FILE."
                )
                if self.allow_in_memory_fallback:
                    logger.warning("%s Operating in-memory for testing.", self.last_connection_error)
                else:
                    logger.error("%s Business writes are disabled to prevent data loss.", self.last_connection_error)
                return False

            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(SALES_GOOGLE_SPREADSHEET_ID)
            self.is_connected = True
            self.last_connection_error = None
            logger.info("Connected to configured Google Spreadsheet.")
            self.ensure_required_tabs()
            return True
        except Exception as exc:
            self.is_connected = False
            self.spreadsheet = None
            self.last_connection_error = f"Failed to connect to Google Sheets: {exc}"
            logger.error("%s. Persistent writes disabled.", self.last_connection_error)
            return False

    def reconnect(self) -> bool:
        """Trigger re-initialization of Google Sheets connection and clear caches."""
        with self._lock:
            self._worksheets.clear()
            self._records_cache.clear()
        return self.init_connection()

    def verify_tabs_accessibility(self) -> Dict[str, Any]:
        """Verify that every required sheet can be read and written successfully."""
        if not (self.is_connected and self.spreadsheet):
            return {
                "connected": False,
                "all_tabs_accessible": False,
                "error": self.last_connection_error or "Google Sheets not connected",
                "tabs": {},
            }
        results = {}
        for tab in REQUIRED_TABS:
            try:
                ws = self._get_worksheet(tab)
                row1 = ws.row_values(1)
                results[tab] = {"status": "ok", "columns": len(row1)}
            except Exception as exc:
                results[tab] = {"status": "error", "error": str(exc)}
        all_ok = all(r.get("status") == "ok" for r in results.values())
        return {
            "connected": True,
            "all_tabs_accessible": all_ok,
            "tabs": results,
        }

    def ensure_required_tabs(self):
        """Create missing bookkeeping tabs and append missing headers. Never clears rows."""
        if not (self.is_connected and self.spreadsheet):
            return
        try:
            # Single API call to retrieve all existing worksheets at once
            existing_ws = {ws.title: ws for ws in self.spreadsheet.worksheets()}
            with self._lock:
                for title, ws in existing_ws.items():
                    self._worksheets[title] = ws
        except Exception as exc:
            logger.warning("Could not list worksheets in bulk: %s", exc)
            existing_ws = {}

        for tab, headers in REQUIRED_TABS.items():
            try:
                worksheet = existing_ws.get(tab)
                if worksheet is None:
                    worksheet = self.spreadsheet.add_worksheet(title=tab, rows=1000, cols=max(26, len(headers) + 2))
                    worksheet.update("A1", [headers])
                    with self._lock:
                        self._worksheets[tab] = worksheet
            except Exception as exc:
                logger.error("Could not ensure tab %s: %s", tab, exc)

    def _ensure_headers(self, worksheet, headers: List[str]):
        current = worksheet.row_values(1)
        if not current:
            worksheet.update("A1", [headers])
            return
        missing = [h for h in headers if h not in current]
        if missing:
            start = len(current) + 1
            end = start + len(missing) - 1
            worksheet.update(self._a1(start, 1, end), [missing])

    @staticmethod
    def _a1(start_col: int, row: int, end_col: int) -> str:
        def col_name(index: int) -> str:
            name = ""
            while index:
                index, rem = divmod(index - 1, 26)
                name = chr(65 + rem) + name
            return name
        return f"{col_name(start_col)}{row}:{col_name(end_col)}{row}"

    def _invalidate_records_cache(self, tab_name: str) -> None:
        with self._lock:
            self._records_cache.pop(tab_name, None)

    def _get_worksheet(self, tab_name: str):
        with self._lock:
            ws = self._worksheets.get(tab_name)
        if ws is not None:
            return ws
        try:
            ws = self.spreadsheet.worksheet(tab_name)
        except Exception as exc:
            # If worksheet is not found, automatically create it with required headers if it's in REQUIRED_TABS
            if tab_name in REQUIRED_TABS:
                headers = REQUIRED_TABS[tab_name]
                logger.info("Worksheet '%s' not found. Creating worksheet with default headers.", tab_name)
                ws = self.spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=max(26, len(headers) + 2))
                self._ensure_headers(ws, headers)
            else:
                raise exc
        with self._lock:
            self._worksheets[tab_name] = ws
        return ws

    def get_records(self, tab_name: str, fresh: bool = False) -> List[Dict[str, Any]]:
        import time
        now = time.monotonic()

        # If disconnected but configured, attempt lazy self-healing reconnect after a cooldown
        if not (self.is_connected and self.spreadsheet) and SALES_GOOGLE_SPREADSHEET_ID:
            if not self.allow_in_memory_fallback and (now - self._last_conn_attempt_time > 15.0):
                logger.info("Attempting automatic reconnection to Google Sheets for '%s'...", tab_name)
                self.init_connection()

        if not (self.is_connected and self.spreadsheet):
            if self.allow_in_memory_fallback:
                return [dict(row) for row in self.memory_store.get(tab_name, [])]
            err_msg = (
                f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                f"Cannot retrieve records for '{tab_name}'."
            )
            logger.error(err_msg)
            raise RuntimeError(err_msg)

        import time
        now = time.monotonic()
        with self._lock:
            cached = self._records_cache.get(tab_name)
        if not fresh:
            if cached and now - cached[0] < self._records_cache_ttl_seconds:
                return [dict(row) for row in cached[1]]
            with self._lock:
                event = self._inflight.get(tab_name)
                if event is None:
                    event = threading.Event()
                    self._inflight[tab_name] = event
                    leader = True
                else:
                    leader = False
            if not leader:
                event.wait(timeout=30)
                with self._lock:
                    cached = self._records_cache.get(tab_name)
                    if cached:
                        return [dict(row) for row in cached[1]]

        # Read from Google Sheets with retry on 429 quota errors
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                worksheet = self._get_worksheet(tab_name)
                records = worksheet.get_all_records()
                safe_records = [dict(row) for row in records]
                with self._lock:
                    self._records_cache[tab_name] = (time.monotonic(), safe_records)
                return [dict(row) for row in safe_records]
            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                is_quota_error = "429" in err_str or "quota" in err_str or "rate limit" in err_str
                if is_quota_error:
                    logger.warning(
                        "Google Sheets rate limit/429 for %s (attempt %d/%d): %s",
                        tab_name, attempt + 1, max_retries + 1, exc
                    )
                    # ONLY serve cached data when fresh=False was requested!
                    if not fresh and cached and cached[1]:
                        logger.info("Serving stale cached records for %s due to Google Sheets rate limit", tab_name)
                        return [dict(row) for row in cached[1]]
                    if attempt < max_retries:
                        sleep_time = 0.01 if os.getenv("SALES_TESTING", "").strip() == "1" else (2 ** attempt) * 1.5 + 0.5
                        time.sleep(sleep_time)
                        continue
                else:
                    with self._lock:
                        self._worksheets.pop(tab_name, None)
                    break
            finally:
                if not fresh:
                    with self._lock:
                        event = self._inflight.pop(tab_name, None)
                        if event:
                            event.set()

        err_str = str(last_exc).lower() if last_exc else ""
        if "429" in err_str or "quota" in err_str:
            if not fresh and cached and cached[1]:
                return [dict(row) for row in cached[1]]
            logger.error("Exhausted retries on 429 quota error for %s: %s", tab_name, last_exc)
            raise RuntimeError(f"Google Sheets API quota temporarily exceeded for {tab_name}. Please retry in a few seconds.") from last_exc

        logger.warning("Error reading %s from sheet: %s", tab_name, last_exc)
        raise RuntimeError(f"Could not read {tab_name} from Google Sheets.") from last_exc

    def append_record(self, tab_name: str, record: Dict[str, Any], raise_on_error: bool = False) -> bool:
        self._invalidate_records_cache(tab_name)
        failures = self._fail_once.get(tab_name, 0)
        if failures > 0:
            self._fail_once[tab_name] = failures - 1
            logger.error("Injected write failure for %s", tab_name)
            if raise_on_error:
                raise RuntimeError(f"Injected failure writing {tab_name}")
            return False

        if self.is_connected and self.spreadsheet:
            try:
                worksheet = self._get_worksheet(tab_name)
                headers = worksheet.row_values(1)
                if not headers:
                    headers = list(record.keys())
                    worksheet.update("A1", [headers])
                else:
                    missing = [k for k in record.keys() if k not in headers]
                    if missing:
                        self._ensure_headers(worksheet, headers + missing)
                        headers = headers + missing
                row = [record.get(h, "") for h in headers]
                worksheet.append_row(row, value_input_option="USER_ENTERED")
                self.memory_store.setdefault(tab_name, []).append(dict(record))
                return True
            except Exception as exc:
                logger.error("Error appending to %s in Google Sheet: %s", tab_name, exc)
                if raise_on_error:
                    raise RuntimeError(f"Persistent write failed for {tab_name}: {exc}") from exc
                return False

        # Disconnected state:
        if self.allow_in_memory_fallback:
            self.memory_store.setdefault(tab_name, []).append(dict(record))
            return True

        err_msg = (
            f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
            f"Business write for '{tab_name}' was blocked to prevent data loss."
        )
        logger.error(err_msg)
        if raise_on_error:
            raise RuntimeError(err_msg)
        return False

    def update_record(self, tab_name: str, id_field: str, id_value: str, updates: Dict[str, Any], raise_on_error: bool = False) -> bool:
        self._invalidate_records_cache(tab_name)
        failures = self._fail_once.get(tab_name, 0)
        if failures > 0:
            self._fail_once[tab_name] = failures - 1
            logger.error("Injected update failure for %s", tab_name)
            if raise_on_error:
                raise RuntimeError(f"Injected failure updating {tab_name}")
            return False
        if not (self.is_connected and self.spreadsheet):
            if self.allow_in_memory_fallback:
                found = False
                for item in self.memory_store.get(tab_name, []):
                    if str(item.get(id_field)) == str(id_value):
                        item.update(updates)
                        found = True
                        break
                return found
            err_msg = (
                f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                f"Business update for '{tab_name}' record {id_value} was blocked to prevent data loss."
            )
            logger.error(err_msg)
            if raise_on_error:
                raise RuntimeError(err_msg)
            return False

        try:
            worksheet = self._get_worksheet(tab_name)
            records = worksheet.get_all_records()
            headers = worksheet.row_values(1)
            header_map = {str(h).strip(): i + 1 for i, h in enumerate(headers)}
            missing = [k for k in updates if k not in header_map]
            if missing:
                self._ensure_headers(worksheet, headers + missing)
                headers = headers + missing
                header_map = {str(h).strip(): i + 1 for i, h in enumerate(headers)}
            for idx, row in enumerate(records, start=2):
                if str(row.get(id_field)) != str(id_value):
                    continue
                cells = []
                for key, value in updates.items():
                    col = header_map.get(key)
                    if col:
                        cells.append({"range": self._a1(col, idx, col), "values": [[value]]})
                if cells:
                    worksheet.batch_update([{"range": c["range"], "values": c["values"]} for c in cells])
                for item in self.memory_store.get(tab_name, []):
                    if str(item.get(id_field)) == str(id_value):
                        item.update(updates)
                        break
                return True
            return False
        except Exception as exc:
            logger.error("Error updating record in %s: %s", tab_name, exc)
            if raise_on_error:
                raise RuntimeError(f"Persistent update failed for {tab_name}: {exc}") from exc
            return False

    def delete_record(self, tab_name: str, id_field: str, id_value: str, raise_on_error: bool = False) -> bool:
        self._invalidate_records_cache(tab_name)
        if not (self.is_connected and self.spreadsheet):
            if self.allow_in_memory_fallback:
                prev_len = len(self.memory_store.get(tab_name, []))
                self.memory_store[tab_name] = [item for item in self.memory_store.get(tab_name, []) if str(item.get(id_field)) != str(id_value)]
                return len(self.memory_store[tab_name]) < prev_len
            err_msg = (
                f"Persistent storage is unavailable: Google Sheets is disconnected ({self.last_connection_error or 'not connected'}). "
                f"Business delete for '{tab_name}' record {id_value} was blocked to prevent data loss."
            )
            logger.error(err_msg)
            if raise_on_error:
                raise RuntimeError(err_msg)
            return False

        try:
            worksheet = self._get_worksheet(tab_name)
            records = worksheet.get_all_records()
            for idx, row in enumerate(records, start=2):
                if str(row.get(id_field)) == str(id_value):
                    worksheet.delete_rows(idx)
                    self.memory_store[tab_name] = [item for item in self.memory_store.get(tab_name, []) if str(item.get(id_field)) != str(id_value)]
                    return True
            return False
        except Exception as exc:
            logger.error("Error deleting record in %s: %s", tab_name, exc)
            if raise_on_error:
                raise RuntimeError(f"Persistent delete failed for {tab_name}: {exc}") from exc
            return False

    def _max_sequence(self, tab_name: str, prefix: str) -> int:
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        highest = 0
        sources = list(self.get_records(tab_name, fresh=True))
        try:
            sources.extend(self.get_records("IdAllocations", fresh=True))
        except Exception:
            sources.extend(self.memory_store.get("IdAllocations", []))
        for row in sources:
            values = [row.get("allocated_id", "")] if row.get("tab_name") else row.values()
            if row.get("tab_name") and str(row.get("tab_name")) != tab_name:
                continue
            for value in values:
                match = pattern.match(str(value).strip())
                if match:
                    highest = max(highest, int(match.group(1)))
        return highest

    def generate_id(self, tab_name: str) -> str:
        """Allocate PREFIX-000001 from the highest existing value, claimed before use.

        Two servers can request the same next number. Each appends a claim. The
        earliest claim for that exact id wins; the other caller retries.
        Existing historical ids are never renumbered.
        """
        prefix = ID_PREFIXES.get(tab_name, "ID")
        for _ in range(12):
            candidate = f"{prefix}-{self._max_sequence(tab_name, prefix) + 1:06d}"
            nonce = uuid.uuid4().hex
            claim = {
                "allocation_id": f"ALC-{nonce[:12]}",
                "tab_name": tab_name,
                "allocated_id": candidate,
                "nonce": nonce,
                "created_at": now_iso(),
            }
            if not self.append_record("IdAllocations", claim, raise_on_error=True):
                raise RuntimeError("Could not record an id allocation.")
            claims = [
                row for row in self.get_records("IdAllocations", fresh=True)
                if str(row.get("tab_name")) == tab_name and str(row.get("allocated_id")) == candidate
            ]
            if claims and str(claims[0].get("nonce")) == nonce:
                return candidate
        raise RuntimeError(f"Could not allocate a unique id for {tab_name}.")

    def allocate_bill_number(self) -> str:
        from app.timeutil import business_month
        month = business_month()
        prefix = f"KS-BILL-{month}"
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        highest = 0
        for row in self.get_records("Sales", fresh=True):
            match = pattern.match(str(row.get("bill_number", "")).strip())
            if match:
                highest = max(highest, int(match.group(1)))
        for _ in range(12):
            candidate = f"{prefix}-{highest + 1:05d}"
            nonce = uuid.uuid4().hex
            claim = {
                "allocation_id": f"ALC-{nonce[:12]}",
                "tab_name": "BillNumbers",
                "allocated_id": candidate,
                "nonce": nonce,
                "created_at": now_iso(),
            }
            if not self.append_record("IdAllocations", claim, raise_on_error=True):
                raise RuntimeError("Could not allocate a bill number.")
            claims = [
                row for row in self.get_records("IdAllocations", fresh=True)
                if str(row.get("allocated_id")) == candidate
            ]
            if claims and str(claims[0].get("nonce")) == nonce:
                return candidate
            highest += 1
        raise RuntimeError("Could not allocate a unique bill number.")

    def log_audit(self, actor: str, action: str, entity_type: str, entity_id: str,
                  field_changed: str = "", old_val: str = "", new_val: str = "",
                  reason: str = "", approved_by: str = "", related_id: str = ""):
        try:
            audit_id = self.generate_id("AuditLog")
        except Exception:
            audit_id = f"AUD-{uuid.uuid4().hex[:12]}"
        record = {
            "audit_id": audit_id,
            "event_datetime": now_iso(),
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
        try:
            self.append_record("AuditLog", record, raise_on_error=False)
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc)


db = SheetsDatabase()
