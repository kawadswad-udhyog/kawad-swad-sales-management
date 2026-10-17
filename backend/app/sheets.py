import os
import json
import logging
import re
import threading
import uuid
from typing import Dict, List, Any

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
}

REQUIRED_TABS = {
    "IdAllocations": ["allocation_id", "tab_name", "allocated_id", "nonce", "created_at"],
    "AuthUsers": ["auth_id", "user_id", "username", "password_hash", "role", "active", "created_at", "must_change_password"],
    "Sales": [
        "sale_id", "bill_number", "idempotency_key", "txn_status", "sale_datetime", "sales_type",
        "customer_id", "customer_name_snapshot", "customer_mobile", "customer_gstin",
        "entered_by_user_id", "salesman_user_id", "delivery_status", "payment_status",
        "payment_method", "payment_reference", "subtotal", "discount_amount", "tax_amount",
        "bill_total", "bill_status", "created_at", "notes",
    ],
    "Payments": [
        "payment_id", "sale_id", "payment_datetime", "payment_method", "amount",
        "reference_number", "received_by_user_id", "payment_status", "notes",
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
}


class SheetsDatabase:
    """Google Sheets adapter with an in-memory fallback for tests."""

    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self.is_connected = False
        self._records_cache: Dict[str, tuple] = {}
        self._records_cache_ttl_seconds = 8.0
        self._lock = threading.Lock()
        self._inflight: Dict[str, threading.Event] = {}
        self._fail_once: Dict[str, int] = {}
        self.memory_store: Dict[str, List[Dict[str, Any]]] = {name: [] for name in list(ID_PREFIXES) + ["Settings"]}
        self.init_connection()

    def init_connection(self):
        if not SALES_GOOGLE_SPREADSHEET_ID:
            logger.warning("SALES_GOOGLE_SPREADSHEET_ID not provided. Using in-memory fallback.")
            return
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = None
            if SALES_GOOGLE_SERVICE_ACCOUNT_JSON:
                info = json.loads(SALES_GOOGLE_SERVICE_ACCOUNT_JSON)
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            if not creds and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE):
                creds = Credentials.from_service_account_file(SALES_GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
            if not creds:
                logger.warning("No Google service account credentials found. Operating in-memory.")
                return
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(SALES_GOOGLE_SPREADSHEET_ID)
            self.is_connected = True
            logger.info("Connected to the configured Google Sheet.")
            self.ensure_required_tabs()
        except Exception as exc:
            logger.error("Failed to connect to Google Sheets: %s. Falling back to in-memory.", exc)

    def ensure_required_tabs(self):
        """Create missing bookkeeping tabs and append missing headers. Never clears rows."""
        if not (self.is_connected and self.spreadsheet):
            return
        for tab, headers in REQUIRED_TABS.items():
            try:
                try:
                    worksheet = self.spreadsheet.worksheet(tab)
                except Exception:
                    worksheet = self.spreadsheet.add_worksheet(title=tab, rows=1000, cols=max(26, len(headers) + 2))
                self._ensure_headers(worksheet, headers)
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

    def get_records(self, tab_name: str, fresh: bool = False) -> List[Dict[str, Any]]:
        if not (self.is_connected and self.spreadsheet):
            return [dict(row) for row in self.memory_store.get(tab_name, [])]
        import time
        now = time.monotonic()
        if not fresh:
            with self._lock:
                cached = self._records_cache.get(tab_name)
                if cached and now - cached[0] < self._records_cache_ttl_seconds:
                    return [dict(row) for row in cached[1]]
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
        try:
            worksheet = self.spreadsheet.worksheet(tab_name)
            records = worksheet.get_all_records()
            safe_records = [dict(row) for row in records]
            with self._lock:
                self._records_cache[tab_name] = (time.monotonic(), safe_records)
            return [dict(row) for row in safe_records]
        except Exception as exc:
            logger.warning("Error reading %s from sheet: %s", tab_name, exc)
            raise RuntimeError(f"Could not read {tab_name} from Google Sheets.") from exc
        finally:
            with self._lock:
                event = self._inflight.pop(tab_name, None)
                if event:
                    event.set()

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
                worksheet = self.spreadsheet.worksheet(tab_name)
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
                    raise
                return False
        self.memory_store.setdefault(tab_name, []).append(dict(record))
        return True

    def update_record(self, tab_name: str, id_field: str, id_value: str, updates: Dict[str, Any]) -> bool:
        self._invalidate_records_cache(tab_name)
        found = False
        for item in self.memory_store.get(tab_name, []):
            if str(item.get(id_field)) == str(id_value):
                item.update(updates)
                found = True
                break
        if not (self.is_connected and self.spreadsheet):
            return found
        try:
            worksheet = self.spreadsheet.worksheet(tab_name)
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
                return True
        except Exception as exc:
            logger.error("Error updating record in %s: %s", tab_name, exc)
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
