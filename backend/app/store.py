import os, secrets, string
from datetime import datetime, timezone
from typing import Any
from app.services.sales_management_sheets import SalesGoogleSheets, SALES_HEADERS

AUTH_HEADERS = ("auth_id","user_id","username","password_hash","role","active","created_at","must_change_password")
class Store:
    def __init__(self): self.sheets = SalesGoogleSheets()
    def ws(self, name): return self.sheets.worksheet(name)
    def rows(self, name): return self.sheets.list_records(name)
    def append(self, name, row): return self.sheets.append_record(name, row)
    def auth_rows(self):
        ws = self.sheets._connect().worksheet("AuthUsers")
        actual = tuple(str(v).strip() for v in ws.row_values(1))
        if actual != AUTH_HEADERS:
            raise RuntimeError("AuthUsers header mismatch. Create the AuthUsers tab using the exact header row in docs/GOOGLE_SHEETS_SETUP.md.")
        return ws.get_all_records()
    def append_auth(self, row):
        ws = self.sheets._connect().worksheet("AuthUsers")
        actual = tuple(str(v).strip() for v in ws.row_values(1))
        if actual != AUTH_HEADERS: raise RuntimeError("AuthUsers worksheet header mismatch.")
        ws.append_row([row.get(h,"") for h in AUTH_HEADERS], value_input_option="USER_ENTERED")
    def append_audit(self, actor, action, entity_type, entity_id, reason=""):
        row={"audit_id": self.next_id("AuditLog"),"event_datetime":now(),"actor_user_id":actor.get("sub","system"),
        "action":action,"entity_type":entity_type,"entity_id":str(entity_id),"field_changed":"","old_value":"","new_value":"",
        "reason":reason,"approved_by_user_id":"","related_record_id":str(entity_id)}
        self.append("AuditLog",row)
    def next_id(self, sheet):
        prefix={"Users":"USR","Products":"PRD","Customers":"CUS","Sales":"SALE","SaleItems":"ITEM","Payments":"PAY",
        "SalesmanStockLedger":"STK","CashLedger":"CSH","Expenses":"EXP","ShopVisits":"VIS","DailyClosing":"CLOSE",
        "SalaryIncentives":"SAL","AuditLog":"AUD"}[sheet]
        # Unique enough for a single API writer; lock/atomic ID service is required for multi-worker concurrent writes.
        return f"{prefix}-{int(datetime.now(timezone.utc).timestamp()*1000)}-{secrets.token_hex(2).upper()}"
def now(): return datetime.now(timezone.utc).isoformat()
def as_float(value, default=0.0):
    try: return float(value or default)
    except (ValueError,TypeError): return default
def is_active(value): return str(value).strip().lower() in ("true","1","yes","active")
