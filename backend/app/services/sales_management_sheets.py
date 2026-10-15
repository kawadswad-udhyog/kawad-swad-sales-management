"""Isolated Google Sheets adapter for the sales-management development module.

This module intentionally does not use the ERP-wide spreadsheet setting. It
requires SALES_GOOGLE_SPREADSHEET_ID and a dedicated service-account file.
It is not mounted into the application router yet.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SALES_HEADERS: dict[str, tuple[str, ...]] = {
    "Users": ("user_id", "full_name", "role", "mobile", "email", "active", "created_at", "notes"),
    "Products": ("product_id", "sku", "product_name", "category", "variant", "pack_weight_g", "selling_unit", "retail_pack_only", "active", "notes"),
    "Customers": ("customer_id", "customer_type", "shop_name", "shopkeeper_name", "mobile", "alternate_mobile", "address", "locality_area", "city", "map_location", "active", "created_at", "notes"),
    "Sales": ("sale_id", "bill_number", "sale_datetime", "sales_type", "customer_id", "customer_name_snapshot", "entered_by_user_id", "salesman_user_id", "delivery_status", "payment_status", "subtotal", "discount_amount", "tax_amount", "bill_total", "bill_status", "created_at", "notes"),
    "SaleItems": ("sale_item_id", "sale_id", "product_id", "product_name_snapshot", "sku_snapshot", "pack_weight_g", "unit", "quantity", "actual_unit_price", "discount_amount", "line_total", "qualifying_kg", "created_at", "notes"),
    "Payments": ("payment_id", "sale_id", "payment_datetime", "payment_method", "amount", "reference_number", "received_by_user_id", "payment_status", "notes"),
    "SalesmanStockLedger": ("stock_txn_id", "txn_datetime", "salesman_user_id", "product_id", "sku_snapshot", "txn_type", "quantity", "unit", "pack_weight_g", "related_sale_id", "issued_by_user_id", "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes"),
    "CashLedger": ("cash_txn_id", "txn_datetime", "salesman_user_id", "txn_type", "amount", "payment_method", "related_sale_id", "related_expense_id", "issued_by_user_id", "received_by_user_id", "confirmed_by_user_id", "reference_id", "notes"),
    "Expenses": ("expense_id", "expense_datetime", "submitted_by_user_id", "salesman_user_id", "category", "amount", "description", "receipt_link_or_file_ref", "approval_status", "approved_by_user_id", "approval_datetime", "cash_reducing_expense", "related_closing_id", "notes"),
    "ShopVisits": ("visit_id", "visit_datetime", "salesman_user_id", "customer_id", "shop_name_snapshot", "visit_outcome", "order_taken", "follow_up_date", "next_action", "created_at", "notes"),
    "DailyClosing": ("closing_id", "closing_date", "salesman_user_id", "opening_cash", "cash_collected", "approved_cash_expenses", "expected_cash_return", "physical_cash_returned", "cash_difference", "opening_stock_reference", "stock_discrepancy_flag", "closing_status", "submitted_at", "reviewed_by_user_id", "reviewed_at", "notes"),
    "SalaryIncentives": ("record_id", "period_start", "period_end", "salesman_user_id", "record_type", "eligible_kg", "completed_100kg_blocks", "rate", "calculated_amount", "approved_amount", "approval_status", "approved_by_user_id", "paid_datetime", "payment_reference", "notes"),
    "AuditLog": ("audit_id", "event_datetime", "actor_user_id", "action", "entity_type", "entity_id", "field_changed", "old_value", "new_value", "reason", "approved_by_user_id", "related_record_id"),
    "Settings": ("setting_key", "setting_value", "description"),
}


class SalesSheetsConfigurationError(RuntimeError):
    """Raised when sales-specific Sheets credentials/configuration are absent."""


class SalesSheetsSchemaError(RuntimeError):
    """Raised when a worksheet does not match the agreed header contract."""


class SalesGoogleSheets:
    """Lazy, schema-checked adapter for the development spreadsheet.

    It deliberately refuses to fall back to the ERP's existing spreadsheet.
    Application-level authorization, ID allocation, idempotency, business
    rules, and audit logging must happen before any write.
    """

    def __init__(self, spreadsheet_id: str | None = None, service_account_file: str | None = None):
        self.spreadsheet_id = (spreadsheet_id or os.getenv("SALES_GOOGLE_SPREADSHEET_ID", "")).strip()
        self.service_account_file = (service_account_file or os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "")).strip()
        self._client = None
        self._spreadsheet = None
        self._lock = threading.RLock()

    def _connect(self):
        if not self.spreadsheet_id:
            raise SalesSheetsConfigurationError(
                "SALES_GOOGLE_SPREADSHEET_ID is required; refusing to use the ERP spreadsheet."
            )
        if not self.service_account_file:
            raise SalesSheetsConfigurationError(
                "SALES_GOOGLE_SERVICE_ACCOUNT_FILE is required for sales development."
            )
        path = Path(self.service_account_file)
        if not path.is_file():
            raise SalesSheetsConfigurationError(
                "The configured sales service-account file does not exist."
            )
        if self._spreadsheet is None:
            credentials = Credentials.from_service_account_file(str(path), scopes=SCOPES)
            self._client = gspread.authorize(credentials)
            self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
        return self._spreadsheet

    def worksheet(self, tab_name: str):
        if tab_name not in SALES_HEADERS:
            raise ValueError(f"Unsupported sales worksheet: {tab_name}")
        with self._lock:
            worksheet = self._connect().worksheet(tab_name)
            actual = tuple(str(value).strip() for value in worksheet.row_values(1))
            expected = SALES_HEADERS[tab_name]
            if actual[:len(expected)] != expected:
                raise SalesSheetsSchemaError(
                    f"Header mismatch for {tab_name}. Expected {expected!r}; got {actual!r}."
                )
            return worksheet

    def list_records(self, tab_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return self.worksheet(tab_name).get_all_records()

    def append_record(self, tab_name: str, record: dict[str, Any]) -> int:
        """Append one schema-checked record; caller must supply its generated ID."""
        headers = SALES_HEADERS.get(tab_name)
        if not headers:
            raise ValueError(f"Unsupported sales worksheet: {tab_name}")
        unknown = set(record) - set(headers)
        if unknown:
            raise ValueError(f"Unexpected fields for {tab_name}: {sorted(unknown)}")
        values = [record.get(header, "") for header in headers]
        with self._lock:
            worksheet = self.worksheet(tab_name)
            worksheet.append_row(values, value_input_option="USER_ENTERED")
            return len(worksheet.get_all_values())
