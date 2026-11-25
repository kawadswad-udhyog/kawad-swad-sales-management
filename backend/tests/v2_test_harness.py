"""
Kawad Swad ERP — Transport-Boundary Local Apps Script Test Simulator (TEST-ONLY).

Purpose:
- Allows existing and new backend unit/integration tests to execute real FastAPI router
  and service functions end-to-end WITHOUT bypassing or weakening ANY production guard in:
  * app/apps_script_bridge.py (allowlist, schema gate, pre-write ID/prefix/duplicate-ID checks,
    HMAC signing, echo validation, post-write ID validation, _verify_readback, cache invalidation)
  * app/schema_registry.py (fail-closed core schema reconciliation validation)
  * app/sheets.py (Single-Write-Owner direct-write blocking and read-only OAuth scopes)
- Intercepts ONLY HTTP POSTs to the local synthetic test URL (`https://script.google.com/macros/s/local-test-sim/exec`)
  inside isolated SALES_TESTING=1 test fixtures, verifies HMAC-SHA256 signature, and applies
  atomic sheet state transitions to `db.memory_store` (or `db.shared_file_dir` JSON files for
  multi-process concurrency tests).
- Never makes live network calls, never touches Google Sheets, and automatically clears all
  test-scoped runtime reconciliations in `stop()` / `__exit__()`.
"""

from __future__ import annotations

import copy
import fcntl
import functools
import hashlib
import hmac
import inspect
import io
import json
import os
import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

from fastapi import Request

import app.apps_script_bridge as bridge_mod
import app.schema_registry as schema_reg
from app.action_registry import GOVERNED_ACTION_REGISTRY, GovernedActionSpec
from app.sheets import ID_PREFIXES, REQUIRED_TABS, db
from app.timeutil import now_iso
from app.accounting.transaction_coordinator import tx_coordinator


TEST_SIM_URL = "https://script.google.com/macros/s/local-test-sim/exec"
TEST_SIM_SECRET = "local-test-only-apps-script-hmac-secret-64-chars-0123456789abcdef"


def make_test_request(
    nonce: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Request:
    """Create a FastAPI-compatible test Request with a unique X-KS-Idempotency-Key header."""
    hdrs: Dict[str, str] = {"X-KS-Idempotency-Key": nonce or f"TEST-NONCE-{uuid.uuid4().hex[:16].upper()}"}
    if headers:
        hdrs.update(headers)
    return Request(headers=hdrs)


def _extract_idempotency_key(args: tuple, kwargs: dict) -> Optional[str]:
    for val in list(args) + list(kwargs.values()):
        if val is None or isinstance(val, (str, int, float, bool, dict, list, tuple)):
            continue
        idem = getattr(val, "idempotency_key", None)
        if isinstance(idem, str) and idem.strip():
            return idem.strip()
    return None


def wrap_v2_endpoint(fn):
    """Wrap a FastAPI route coroutine/function for direct unit-test invocation by injecting a POL-015 Request when omitted."""
    if not callable(fn):
        return fn
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn
    param_names = list(sig.parameters.keys())
    if "request" not in param_names:
        return fn
    req_idx = param_names.index("request")

    def _inject_request(args: tuple, kwargs: dict) -> Tuple[tuple, dict]:
        if "request" in kwargs:
            return args, kwargs
        if len(args) > req_idx and (isinstance(args[req_idx], Request) or hasattr(args[req_idx], "headers")):
            return args, kwargs
        test_req = make_test_request(nonce=_extract_idempotency_key(args, kwargs))
        if len(args) <= req_idx:
            new_kwargs = dict(kwargs)
            new_kwargs["request"] = test_req
            return args, new_kwargs
        new_args = args[:req_idx] + (test_req,) + args[req_idx:]
        return new_args, kwargs

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async_wrapper(*args, **kwargs):
            new_args, new_kwargs = _inject_request(args, kwargs)
            return await fn(*new_args, **new_kwargs)
        return _async_wrapper

    @functools.wraps(fn)
    def _sync_wrapper(*args, **kwargs):
        new_args, new_kwargs = _inject_request(args, kwargs)
        return fn(*new_args, **new_kwargs)
    return _sync_wrapper


class V2RouterProxy:
    """Transparent test proxy around a FastAPI router module that injects POL-015 Request headers on direct calls."""

    def __init__(self, module):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_wrapped_cache", {})

    def __getattr__(self, name: str):
        mod = object.__getattribute__(self, "_module")
        cache = object.__getattribute__(self, "_wrapped_cache")
        if name in cache:
            return cache[name]
        attr = getattr(mod, name)
        if inspect.isfunction(attr):
            wrapped = wrap_v2_endpoint(attr)
            cache[name] = wrapped
            return wrapped
        return attr

    def __setattr__(self, name: str, value: Any):
        setattr(object.__getattribute__(self, "_module"), name, value)


class _FakeHTTPResponse:
    def __init__(self, body_dict: Dict[str, Any], status: int = 200):
        self._raw = json.dumps(body_dict, default=str).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LocalAppsScriptSimulator:
    """
    Transport-boundary mock of the Google Apps Script Single-Write-Owner Web App.

    Installs test-scoped patches on `app.apps_script_bridge` configuration and
    `urllib.request.build_opener`, plus temporary canonical Owner reconciliations
    for the 12 core conflicting tables during the test fixture lifecycle.
    """

    def __init__(self, reconcile_core_tables: bool = True):
        self.reconcile_core_tables = reconcile_core_tables
        self._lock = threading.RLock()
        self._nonce_cache: Dict[str, Dict[str, Any]] = {}
        self._counters: Dict[str, int] = {}
        self._patches: List[Any] = []
        self._active = False
        self._owner_bootstrap_completed: bool = False
        self._current_nonce: str = ""
        self.calls: List[Dict[str, Any]] = []

    def start(self) -> "LocalAppsScriptSimulator":
        if self._active:
            return self
        tx_coordinator.reset_store()
        if self.reconcile_core_tables:
            for tab in schema_reg.CONFLICTING_CORE_SCHEMA_TABS:
                canonical = schema_reg.get_expected_canonical_reconciliation_headers(tab)
                if canonical:
                    schema_reg.approve_core_schema_reconciliation(
                        tab,
                        headers=canonical,
                        approved_by="TEST-HARNESS-OWNER",
                    )

        sim = self

        class _SimOpener:
            def open(self, req, timeout=None):
                return sim._dispatch_http_request(req)

        self._atomic_audit_logged: set = set()
        orig_log_audit = db.log_audit

        def _dedup_log_audit(actor: str, action: str, entity_type: str, entity_id: str,
                             field_changed: str = "", old_val: str = "", new_val: str = "",
                             reason: str = "", approved_by: str = "", related_id: str = ""):
            key = (str(action or "").strip().upper(), str(entity_id or "").strip())
            if key in sim._atomic_audit_logged:
                sim._atomic_audit_logged.discard(key)
                return
            return orig_log_audit(
                actor, action, entity_type, entity_id,
                field_changed=field_changed, old_val=old_val, new_val=new_val,
                reason=reason, approved_by=approved_by, related_id=related_id,
            )

        self._patches = [
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", TEST_SIM_URL),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", TEST_SIM_SECRET),
            patch.object(bridge_mod.urllib.request, "build_opener", return_value=_SimOpener()),
            patch.object(db, "log_audit", side_effect=_dedup_log_audit),
        ]
        for p in self._patches:
            p.start()
        self._active = True
        return self

    def stop(self) -> None:
        if not self._active:
            return
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass
        self._patches = []
        if self.reconcile_core_tables:
            schema_reg.clear_runtime_core_schema_reconciliations()
        tx_coordinator.reset_store()
        self._owner_bootstrap_completed = False
        self._current_nonce = ""
        self._active = False

    def __enter__(self) -> "LocalAppsScriptSimulator":
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False

    # ------------------------------------------------------------------
    # Atomic store helpers (supports both in-memory and shared-file mode)
    # ------------------------------------------------------------------
    def _shared_dir(self) -> Optional[str]:
        return db.shared_file_dir or os.getenv("SALES_SHARED_TEST_DIR") or None

    @contextmanager
    def _atomic_store_lock(self):
        s_dir = self._shared_dir()
        if s_dir:
            os.makedirs(s_dir, exist_ok=True)
            lock_path = os.path.join(s_dir, "_sim_apps_script.lock")
            with open(lock_path, "a+", encoding="utf-8") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        else:
            with self._lock:
                yield

    def _load_tab(self, tab_name: str) -> List[Dict[str, Any]]:
        s_dir = self._shared_dir()
        if s_dir:
            rows = db._read_shared_records(tab_name)
            db.memory_store[tab_name] = [dict(r) for r in rows]
            return [dict(r) for r in rows]
        return [dict(r) for r in db.memory_store.get(tab_name, [])]

    def _save_tab(self, tab_name: str, rows: List[Dict[str, Any]]) -> None:
        s_dir = self._shared_dir()
        clean_rows = [dict(r) for r in rows]
        if s_dir:
            db._write_shared_records(tab_name, clean_rows)
        db.memory_store[tab_name] = clean_rows
        db.invalidate_tab_cache(tab_name)

    def _check_injected_failure(self, tab_name: str) -> Optional[str]:
        with db._lock:
            cnt = db._fail_once.get(tab_name, 0)
            if cnt > 0:
                db._fail_once[tab_name] = cnt - 1
                return f"Injected storage failure on '{tab_name}'"
        return None

    def _is_append_record_patched(self) -> bool:
        fn = getattr(db, "append_record", None)
        if fn is None:
            return False
        func = getattr(fn, "__func__", None)
        return func is not type(db).append_record

    def _append_row(self, tab_name: str, row: Dict[str, Any]) -> None:
        fail = self._check_injected_failure(tab_name)
        if fail:
            raise RuntimeError(fail)
        rows = self._load_tab(tab_name)
        rows.append(dict(row))
        self._save_tab(tab_name, rows)

    def _append_row_honoring_patch(self, tab_name: str, row: Dict[str, Any]) -> None:
        if self._is_append_record_patched():
            # Allow test-injected monkey-patches on db.append_record to intercept/fail writes
            # without letting unpatched db.append_record hit the V2.1 direct-write block.
            db_cls = type(db)
            def _mem_append(_self_db, t_name, rec, raise_on_error=False):
                self._append_row(t_name, rec)
                return True
            with patch.object(db_cls, "append_record", _mem_append):
                db.append_record(tab_name, dict(row), raise_on_error=True)
            return
        self._append_row(tab_name, row)

    def _update_row(self, tab_name: str, key_field: str, key_value: str, updates: Dict[str, Any]) -> bool:
        fail = self._check_injected_failure(tab_name)
        if fail:
            raise RuntimeError(fail)
        rows = self._load_tab(tab_name)
        target = str(key_value or "").strip()
        updated = False
        for row in rows:
            if str(row.get(key_field, "")).strip() == target:
                row.update(updates)
                updated = True
                break
        if updated:
            self._save_tab(tab_name, rows)
        return updated

    def _delete_row(self, tab_name: str, key_field: str, key_value: str) -> bool:
        fail = self._check_injected_failure(tab_name)
        if fail:
            raise RuntimeError(fail)
        rows = self._load_tab(tab_name)
        target = str(key_value or "").strip()
        new_rows = [r for r in rows if str(r.get(key_field, "")).strip() != target]
        if len(new_rows) != len(rows):
            self._save_tab(tab_name, new_rows)
            return True
        return False

    def _alloc_id(self, tab_name: str, spec: Optional[GovernedActionSpec] = None, explicit_prefix: Optional[str] = None) -> str:
        prefix = explicit_prefix
        if not prefix and spec is not None and spec.locked_prefix:
            prefix = spec.locked_prefix
        if not prefix:
            prefix = schema_reg.get_locked_prefix_for_tab(tab_name)
        if not prefix:
            if tab_name == "SalaryReceipts":
                prefix = "SRCP"
            elif tab_name == "SalaryIncentives":
                prefix = "SINC"
            else:
                prefix = ID_PREFIXES.get(tab_name, tab_name[:3].upper())

        rows = self._load_tab(tab_name)
        existing_ids: set = set()
        id_field = spec.id_field if spec else None
        for r in rows:
            if id_field and r.get(id_field):
                existing_ids.add(str(r.get(id_field)).strip().upper())
            for k, v in r.items():
                if k.endswith("_id") and v:
                    existing_ids.add(str(v).strip().upper())

        seq = self._counters.get(tab_name, 0) + 1
        while True:
            cand = f"{prefix}-{seq:06d}"
            if cand.upper() not in existing_ids:
                self._counters[tab_name] = seq
                return cand
            seq += 1

    def _load_nonce_cache(self) -> Dict[str, Dict[str, Any]]:
        s_dir = self._shared_dir()
        if s_dir:
            path = os.path.join(s_dir, "_sim_nonces.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            return data
                except Exception:
                    return {}
            return {}
        return self._nonce_cache

    def _save_nonce_entry(self, nonce: str, resp_dict: Dict[str, Any]) -> None:
        s_dir = self._shared_dir()
        if s_dir:
            cache = self._load_nonce_cache()
            cache[nonce] = resp_dict
            path = os.path.join(s_dir, "_sim_nonces.json")
            tmp = f"{path}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f, default=str)
            os.replace(tmp, path)
        else:
            self._nonce_cache[nonce] = resp_dict

    # ------------------------------------------------------------------
    # HTTP Request Entry Point (verifies signature, executes atomically)
    # ------------------------------------------------------------------
    def _dispatch_http_request(self, req) -> _FakeHTTPResponse:
        url = getattr(req, "full_url", "")
        if url != TEST_SIM_URL:
            raise RuntimeError(f"LocalAppsScriptSimulator blocked unexpected external URL: {url}")

        raw_body = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else str(req.data or "")
        header_sig = req.headers.get("X-ks-signature") or req.headers.get("X-KS-Signature") or ""
        try:
            outer = json.loads(raw_body)
        except Exception:
            return _FakeHTTPResponse({
                "status": "REJECTED",
                "error_code": "INVALID_JSON_ENVELOPE",
                "message": "Simulated Apps Script rejected malformed JSON body.",
                "http_status": 400,
            })

        if isinstance(outer, dict) and isinstance(outer.get("canonical_envelope"), str) and outer.get("signature"):
            body_sig = str(outer.get("signature") or "")
            canonical_str = str(outer.get("canonical_envelope") or "")
            expected_sig = bridge_mod.AppsScriptBridge.sign_envelope(canonical_str, TEST_SIM_SECRET)
            sig_ok = hmac.compare_digest(body_sig, expected_sig)
            if header_sig:
                sig_ok = sig_ok and hmac.compare_digest(header_sig, expected_sig)
            if not sig_ok:
                return _FakeHTTPResponse({
                    "status": "REJECTED",
                    "error_code": "INVALID_HMAC_SIGNATURE",
                    "message": "Simulated Apps Script rejected invalid HMAC signature.",
                    "http_status": 401,
                })
            envelope = json.loads(canonical_str)
        else:
            expected_sig = bridge_mod.AppsScriptBridge.sign_envelope(raw_body, TEST_SIM_SECRET)
            if not hmac.compare_digest(header_sig, expected_sig):
                return _FakeHTTPResponse({
                    "status": "REJECTED",
                    "error_code": "INVALID_HMAC_SIGNATURE",
                    "message": "Simulated Apps Script rejected invalid HMAC signature.",
                    "http_status": 401,
                })
            envelope = outer

        action = str(envelope.get("action") or "").strip().upper()
        target_tab = str(envelope.get("target_tab") or "").strip()
        nonce = str(envelope.get("nonce") or "").strip()
        corr_id = str(envelope.get("correlation_id") or "").strip()
        payload = envelope.get("payload") or {}
        actor_user_id = str(envelope.get("actor_user_id") or "")
        self._current_nonce = nonce

        self.calls.append(copy.deepcopy(envelope))

        with self._atomic_store_lock():
            # Idempotent nonce replay check
            nonces = self._load_nonce_cache()
            if nonce and nonce in nonces:
                prev = dict(nonces[nonce])
                prev["correlation_id"] = corr_id
                prev["nonce"] = nonce
                prev["action"] = action
                prev["target_tab"] = target_tab
                prev["idempotent_replay"] = True
                return _FakeHTTPResponse(prev)

            spec = GOVERNED_ACTION_REGISTRY.get(action)
            if spec is None:
                return _FakeHTTPResponse({
                    "status": "REJECTED",
                    "correlation_id": corr_id,
                    "nonce": nonce,
                    "action": action,
                    "target_tab": target_tab,
                    "error_code": "UNREGISTERED_GOVERNED_ACTION",
                    "message": f"Action '{action}' is not registered.",
                    "http_status": 403,
                })

            try:
                outcome = self._execute_action(action, target_tab, payload, actor_user_id, spec)
            except _SimRejectError as rej:
                return _FakeHTTPResponse({
                    "status": "REJECTED",
                    "correlation_id": corr_id,
                    "nonce": nonce,
                    "action": action,
                    "target_tab": target_tab,
                    "error_code": rej.error_code,
                    "message": rej.message,
                    "http_status": rej.http_status,
                    "retryable": rej.retryable,
                })
            except Exception as exc:
                return _FakeHTTPResponse({
                    "status": "REJECTED",
                    "correlation_id": corr_id,
                    "nonce": nonce,
                    "action": action,
                    "target_tab": target_tab,
                    "error_code": "SIMULATOR_WRITE_ERROR",
                    "message": str(exc),
                    "http_status": 503,
                    "retryable": True,
                })

            resp_dict = {
                "status": "CONFIRMED",
                "correlation_id": corr_id,
                "nonce": nonce,
                "action": action,
                "target_tab": target_tab,
                "allocated_id": outcome.get("allocated_id"),
                "record": outcome.get("record"),
                "data": outcome.get("data"),
            }
            if nonce:
                self._save_nonce_entry(nonce, resp_dict)
            return _FakeHTTPResponse(resp_dict)

    # ------------------------------------------------------------------
    # Action Execution Engine
    # ------------------------------------------------------------------
    def _execute_action(
        self,
        action: str,
        target_tab: str,
        payload: Dict[str, Any],
        actor_user_id: str,
        spec: GovernedActionSpec,
    ) -> Dict[str, Any]:
        # 1. Accounting Journal Vouchers (atomic header + lines)
        if action == "POST_JOURNAL_VOUCHER":
            return self._act_post_journal_voucher(payload, spec)
        if action == "REVERSE_JOURNAL_VOUCHER":
            return self._act_reverse_journal_voucher(payload, spec)

        # 2. Sales & Sale Payments (atomic multi-tab)
        if action in ("CREATE_SALE", "RESUME_SALE"):
            return self._act_create_or_resume_sale(action, payload, spec)
        if action == "CANCEL_SALE":
            return self._act_cancel_sale(payload)
        if action == "RECORD_SALE_PAYMENT":
            return self._act_record_sale_payment(payload, spec)

        # 3. Credit-Limit Approval CAS & Approval Workflow
        if action in ("RESERVE_CREDIT_APPROVAL", "RELEASE_CREDIT_APPROVAL", "CONSUME_CREDIT_APPROVAL"):
            return self._act_credit_approval_cas(action, payload)
        if action == "APPROVE_AND_EXECUTE_REQUEST":
            return self._act_approve_and_execute_request(payload, actor_user_id)
        if action == "REJECT_APPROVAL_REQUEST":
            return self._act_reject_approval_request(payload)

        # 4. Raw Materials, Milling, Production, Packaging, Dispatch
        if action == "RECEIVE_RAW_MATERIAL":
            return self._act_receive_raw_material(payload, spec)
        if action == "ISSUE_RAW_MATERIALS":
            return self._act_issue_raw_materials(payload, spec)
        if action == "RECOVER_RAW_MATERIALS_STATUS":
            return self._act_recover_raw_materials_status(payload)
        if action == "VERIFY_RAW_MATERIAL_OPENING_STOCK":
            return self._act_verify_rm_opening_stock(payload, actor_user_id, spec)
        if action == "RECORD_MILLING_BATCH":
            return self._act_record_milling_batch(payload, spec)
        if action == "RECOVER_MILLING_BATCH":
            return self._act_recover_milling_batch(payload, spec)
        if action == "CREATE_PRODUCTION_BATCH":
            return self._act_create_production_batch(payload, spec)
        if action == "APPROVE_PRODUCTION_BATCH":
            return self._act_approve_production_batch(payload)
        if action == "RESOLVE_LEGACY_BATCH_COST":
            return self._act_resolve_legacy_batch_cost(payload)
        if action in ("RECORD_PACKAGING_BATCH", "RECORD_PACKAGING_PENDING_REVIEW"):
            return self._act_record_packaging(action, payload, spec)
        if action == "RECONCILE_PACKAGING_BATCH":
            return self._act_reconcile_packaging(payload)
        if action == "APPROVE_PACKAGING_DISCREPANCY":
            return self._act_approve_packaging_discrepancy(payload)
        if action == "RECOVER_PACKAGING":
            return self._act_recover_packaging(payload)
        if action in ("RECORD_DISTRIBUTION_DISPATCH", "PRODUCTION_STOCK_DISPATCH", "RECONCILE_DISPATCH"):
            return self._act_dispatch(action, payload, spec)
        if action == "RECORD_STOCK_MOVEMENT":
            return self._act_record_stock_movement(payload, spec)

        # 5. Van Loading Passes (atomic stock reservation)
        if action == "CREATE_VAN_LOADING_PASS":
            return self._act_create_van_loading_pass(payload, spec)
        if action == "ACCEPT_VAN_LOADING_PASS":
            return self._act_accept_van_loading_pass(payload)
        if action == "REPORT_VAN_LOADING_DISCREPANCY":
            return self._act_report_van_loading_discrepancy(payload)
        if action == "CANCEL_VAN_LOADING_PASS":
            return self._act_cancel_van_loading_pass(payload)
        if action == "REVIEW_STOCK_DISCREPANCY":
            return self._act_review_stock_discrepancy(payload)

        # 6. Purchasing & Supplier Bills/Payments
        if action == "CREATE_PURCHASE_ORDER":
            return self._act_create_purchase_order(payload, spec)
        if action == "RECEIVE_GOODS":
            return self._act_receive_goods(payload, spec)
        if action == "RECORD_SUPPLIER_PAYMENT":
            return self._act_record_supplier_payment(payload, spec)
        if action == "APPLY_SUPPLIER_ADVANCE":
            return self._act_apply_supplier_advance(payload, spec)
        if action == "CREATE_SUPPLIER_RETURN":
            return self._act_create_supplier_return(payload, spec)

        # 7. Users, Auth, Revocation
        if action == "BOOTSTRAP_FIRST_OWNER":
            return self._act_bootstrap_first_owner(payload, spec)
        if action == "CREATE_USER":
            return self._act_create_user(payload, spec)
        if action in ("UPDATE_USER", "DEACTIVATE_USER", "REACTIVATE_USER", "RECONCILE_ROLE_ALIAS"):
            return self._act_update_user(action, payload)
        if action == "RESET_PASSWORD":
            return self._act_reset_password(payload)
        if action == "REVOKE_TOKEN":
            self._append_row("RevokedTokens", dict(payload))
            return {"allocated_id": payload.get("jti"), "record": dict(payload)}
        if action == "REVOKE_USER_SESSIONS":
            uid = str(payload.get("user_id") or "").strip()
            self._update_row("AuthUsers", "user_id", uid, {
                "sessions_revoked_at": payload.get("sessions_revoked_at", now_iso()),
            })
            return {"allocated_id": uid, "record": dict(payload)}

        # 8. Workforce, Payroll, Attendance, Expenses, Closing
        if action == "CALCULATE_PAYROLL":
            return self._act_calculate_payroll(payload, spec)
        if action == "UPDATE_PAYROLL_ITEM":
            return self._act_update_payroll_item(payload)
        if action == "RECORD_WORKFORCE_PAYMENT":
            return self._act_record_workforce_payment(payload, spec)
        if action in ("RECORD_BULK_WORKER_ATTENDANCE", "BULK_LABOUR_ATTENDANCE"):
            return self._act_bulk_rows(target_tab, payload, spec)
        if action == "UPSERT_SALARY_STRUCTURE":
            return self._act_upsert_salary_structure(payload, spec)
        if action == "REVIEW_EXPENSE":
            return self._act_review_expense(payload)
        if action == "SUBMIT_DAILY_CLOSING":
            return self._act_submit_daily_closing(payload, spec)
        if action == "UPDATE_LOT_STATUS":
            return self._act_update_lot_status(payload)
        if action == "CREATE_PRODUCT_LOT":
            return self._act_create_product_lot(payload, spec)
        if action == "UPDATE_CA_POLICY":
            return self._act_update_ca_policy(payload)

        # 9. Generic single-table Create / Update / Delete handler driven by GovernedActionSpec
        return self._act_generic(action, target_tab, payload, spec)

    # ------------------------------------------------------------------
    # Specific Multi-Table Handlers
    # ------------------------------------------------------------------
    def _act_post_journal_voucher(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        lines = payload.get("lines") or []
        tot_d = sum(Decimal(str(l.get("debit_amount", l.get("debit", 0)) or 0)) for l in lines)
        tot_c = sum(Decimal(str(l.get("credit_amount", l.get("credit", 0)) or 0)) for l in lines)
        if abs(tot_d - tot_c) > Decimal("0.01"):
            raise _SimRejectError("UNBALANCED_JOURNAL", f"Unbalanced journal: debit={tot_d}, credit={tot_c}", 422)

        jid = str(payload.get("journal_id") or "").strip() or self._alloc_id("JournalHeaders", spec)
        header = {k: v for k, v in payload.items() if k != "lines"}
        header["journal_id"] = jid
        header.setdefault("status", "POSTED")
        header.setdefault("total_debit", float(tot_d))
        header.setdefault("total_credit", float(tot_c))
        header.setdefault("created_at", now_iso())

        # Check injected failure on JournalLines BEFORE committing header (atomic Apps Script rollback)
        fail_lines = self._check_injected_failure("JournalLines")
        if fail_lines:
            raise RuntimeError(fail_lines)

        self._append_row("JournalHeaders", header)
        saved_lines = []
        for idx, line in enumerate(lines, 1):
            lrow = dict(line)
            lrow["journal_id"] = jid
            lrow["line_id"] = str(lrow.get("line_id") or "").strip() or self._alloc_id("JournalLines", explicit_prefix="JVL")
            lrow.setdefault("line_no", idx)
            lrow.setdefault("debit_amount", float(lrow.get("debit_amount", lrow.get("debit", 0)) or 0))
            lrow.setdefault("credit_amount", float(lrow.get("credit_amount", lrow.get("credit", 0)) or 0))
            self._append_row("JournalLines", lrow)
            saved_lines.append(lrow)
        return {"allocated_id": jid, "record": header, "data": {"journal_id": jid, "lines": saved_lines}}

    def _act_reverse_journal_voucher(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        orig_jid = str(payload.get("original_journal_id") or "").strip()
        lines = payload.get("lines") or []
        rev_jid = str(payload.get("journal_id") or "").strip() or self._alloc_id("JournalHeaders", spec)
        header = {
            "journal_id": rev_jid,
            "entry_date": payload.get("entry_date") or now_iso()[:10],
            "voucher_type": "REVERSAL",
            "reference_type": "JOURNAL_REVERSAL",
            "reference_id": orig_jid,
            "narration": payload.get("narration") or f"Reversal of {orig_jid}",
            "total_debit": payload.get("total_debit", 0),
            "total_credit": payload.get("total_credit", 0),
            "status": "POSTED",
            "posted_by": payload.get("posted_by", ""),
            "created_at": now_iso(),
            "reversed_by_journal_id": "",
        }
        self._append_row("JournalHeaders", header)
        for idx, line in enumerate(lines, 1):
            lrow = dict(line)
            lrow["journal_id"] = rev_jid
            lrow["line_id"] = str(lrow.get("line_id") or "").strip() or self._alloc_id("JournalLines", explicit_prefix="JVL")
            lrow.setdefault("line_no", idx)
            self._append_row("JournalLines", lrow)
        if orig_jid:
            self._update_row("JournalHeaders", "journal_id", orig_jid, {
                "status": "REVERSED",
                "reversed_by_journal_id": rev_jid,
            })
        return {"allocated_id": rev_jid, "record": header}

    def _act_create_or_resume_sale(self, action: str, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        sale_obj = dict(payload.get("sale") or payload.get("sale_record") or {
            k: v for k, v in payload.items()
            if k not in (
                "items", "sale_items", "stock_movements", "stock_ledger_rows",
                "ledger_entries", "payment", "payments", "cash_ledger_rows",
                "credit_approval_id", "owner_credit_approval_id", "estimated_cogs",
            )
        })
        sale_id = str(payload.get("sale_id") or sale_obj.get("sale_id") or "").strip()
        if not sale_id:
            sale_id = self._alloc_id("Sales", spec)
        sale_obj["sale_id"] = sale_id
        if not str(sale_obj.get("bill_number") or "").strip():
            seq_part = sale_id.split("-")[-1] if "-" in sale_id else sale_id
            sale_obj["bill_number"] = f"BILL-{seq_part}"
        sale_obj.setdefault("txn_status", "COMPLETE")
        sale_obj.setdefault("transaction_status", "COMPLETE")

        items = payload.get("sale_items") or payload.get("items") or []
        stock_entries = payload.get("stock_ledger_rows") or payload.get("stock_movements") or payload.get("ledger_entries") or []
        payment_entries = list(payload.get("payments") or [])
        if isinstance(payload.get("payment"), dict) and float(payload["payment"].get("amount", 0) or 0) > 0:
            payment_entries.append(payload["payment"])
        cash_entries = list(payload.get("cash_ledger_rows") or [])

        # Atomic credit-approval CAS if referenced inside payload
        credit_req_id = str(
            payload.get("owner_credit_approval_id")
            or payload.get("credit_approval_id")
            or sale_obj.get("owner_credit_approval_id")
            or sale_obj.get("credit_approval_id")
            or ""
        ).strip()
        if credit_req_id:
            approvals = self._load_tab("ApprovalRequests")
            req_row = next((r for r in approvals if str(r.get("request_id", "")).strip() == credit_req_id), None)
            if req_row is not None:
                is_cons = str(req_row.get("is_consumed", "")).strip().lower() in ("true", "1", "yes")
                res_by = str(req_row.get("reserved_by_sale_id", "")).strip()
                if is_cons and str(req_row.get("consumed_by_sale_id", "")).strip() != sale_id:
                    raise _SimRejectError("CREDIT_APPROVAL_ALREADY_CONSUMED", "Credit approval already consumed.", 409)
                if res_by and res_by != sale_id:
                    raise _SimRejectError("CREDIT_APPROVAL_RESERVED", "Credit approval reserved by another sale.", 409)

        # Pre-check injected failures across child tables atomically before committing parent Sales row
        for child_tab, child_list in (
            ("SaleItems", items),
            ("SalesmanStockLedger", stock_entries),
            ("Payments", payment_entries),
            ("CashLedger", cash_entries),
        ):
            if child_list:
                fail_c = self._check_injected_failure(child_tab)
                if fail_c:
                    raise RuntimeError(fail_c)
        if credit_req_id:
            fail_a = self._check_injected_failure("ApprovalRequests")
            if fail_a:
                raise RuntimeError(fail_a)

        if action == "CREATE_SALE":
            self._append_row("Sales", sale_obj)
        else:
            if not self._update_row("Sales", "sale_id", sale_id, sale_obj):
                self._append_row("Sales", sale_obj)

        existing_items = self._load_tab("SaleItems")
        existing_item_ids = {str(r.get("sale_item_id", "")).strip() for r in existing_items if str(r.get("sale_id", "")).strip() == sale_id}
        for item in items:
            if not isinstance(item, dict):
                continue
            irow = dict(item)
            irow["sale_id"] = sale_id
            iid = str(irow.get("sale_item_id") or "").strip() or self._alloc_id("SaleItems", explicit_prefix="SIT")
            irow["sale_item_id"] = iid
            if iid not in existing_item_ids:
                self._append_row("SaleItems", irow)
                existing_item_ids.add(iid)

        existing_ledger = self._load_tab("SalesmanStockLedger")
        for mov in stock_entries:
            if not isinstance(mov, dict):
                continue
            mrow = dict(mov)
            mrow["related_sale_id"] = sale_id
            mrow.setdefault("reference_sale_id", sale_id)
            mrow.setdefault("sale_id", sale_id)
            if str(mrow.get("reference_id") or "").startswith("LINE#"):
                mrow["reference_id"] = f"{sale_obj['bill_number']}#{mrow.get('line_no', 1)}"
            mid = str(mrow.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", explicit_prefix="STK")
            mrow["stock_txn_id"] = mid
            if not any(str(r.get("stock_txn_id", "")).strip() == mid for r in existing_ledger):
                self._append_row("SalesmanStockLedger", mrow)
                existing_ledger.append(mrow)

        if not stock_entries and items:
            salesman_id = str(sale_obj.get("salesman_user_id") or payload.get("salesman_user_id") or "")
            existing_for_sale = [r for r in existing_ledger if str(r.get("related_sale_id") or r.get("reference_sale_id") or "").strip() == sale_id]
            if not existing_for_sale:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    qty = int(item.get("quantity_packets") or item.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    mrow = {
                        "stock_txn_id": self._alloc_id("SalesmanStockLedger", explicit_prefix="STK"),
                        "txn_datetime": sale_obj.get("sale_datetime") or now_iso(),
                        "salesman_user_id": salesman_id,
                        "product_id": item.get("product_id", ""),
                        "txn_type": "SOLD_DELIVERY",
                        "quantity": -abs(qty),
                        "related_sale_id": sale_id,
                        "reference_sale_id": sale_id,
                        "notes": f"Sale deduction {sale_id}",
                    }
                    self._append_row("SalesmanStockLedger", mrow)

        for pay_raw in payment_entries:
            if not isinstance(pay_raw, dict):
                continue
            if float(pay_raw.get("amount", 0) or 0) <= 0:
                continue
            pay = dict(pay_raw)
            pay["sale_id"] = sale_id
            if not str(pay.get("reference_number") or "").strip():
                pay["reference_number"] = sale_obj["bill_number"]
            pay["payment_id"] = str(pay.get("payment_id") or "").strip() or self._alloc_id("Payments", explicit_prefix="RCPT")
            self._append_row("Payments", pay)

        for cash_raw in cash_entries:
            if not isinstance(cash_raw, dict):
                continue
            crow = dict(cash_raw)
            crow["related_sale_id"] = sale_id
            if not str(crow.get("reference_id") or "").strip():
                crow["reference_id"] = sale_obj["bill_number"]
            crow["cash_txn_id"] = str(crow.get("cash_txn_id") or "").strip() or self._alloc_id("CashLedger", explicit_prefix="CSH")
            self._append_row("CashLedger", crow)

        if credit_req_id:
            self._update_row("ApprovalRequests", "request_id", credit_req_id, {
                "is_consumed": True,
                "consumed_by_sale_id": sale_id,
                "consumed_at": now_iso(),
            })

        return {"allocated_id": sale_id, "record": sale_obj}

    def _act_cancel_sale(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sale_id = str(payload.get("sale_id") or "").strip()
        updates = {
            k: v for k, v in payload.items()
            if k not in ("sale_id", "stock_reversals", "payment_reversals", "cash_reversals")
        }
        updates.setdefault("bill_status", "CANCELLED")
        self._update_row("Sales", "sale_id", sale_id, updates)
        for sr in (payload.get("stock_reversals") or []):
            if isinstance(sr, dict):
                srow = dict(sr)
                srow["stock_txn_id"] = str(srow.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", explicit_prefix="STK")
                self._append_row("SalesmanStockLedger", srow)
        for pr in (payload.get("payment_reversals") or []):
            if isinstance(pr, dict):
                prow = dict(pr)
                prow["payment_id"] = str(prow.get("payment_id") or "").strip() or self._alloc_id("Payments", explicit_prefix="RCPT")
                self._append_row("Payments", prow)
        for cr in (payload.get("cash_reversals") or []):
            if isinstance(cr, dict):
                crow = dict(cr)
                crow["cash_txn_id"] = str(crow.get("cash_txn_id") or "").strip() or self._alloc_id("CashLedger", explicit_prefix="CSH")
                self._append_row("CashLedger", crow)
        return {"allocated_id": sale_id, "record": {"sale_id": sale_id, **updates}}

    def _act_record_sale_payment(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        pay_obj = dict(payload.get("payment") or {
            k: v for k, v in payload.items()
            if k not in ("sale_updates", "cash_ledger_row", "sale_payment_status_update")
        })
        cash_row = payload.get("cash_ledger_row")
        # Check injected failure on CashLedger or Sales BEFORE committing Payments (atomic rollback)
        if isinstance(cash_row, dict):
            fail_cash = self._check_injected_failure("CashLedger")
            if fail_cash:
                raise RuntimeError(fail_cash)
        fail_sales = self._check_injected_failure("Sales")
        if fail_sales:
            raise RuntimeError(fail_sales)

        pid = str(payload.get("payment_id") or pay_obj.get("payment_id") or "").strip() or self._alloc_id("Payments", spec)
        pay_obj["payment_id"] = pid
        self._append_row("Payments", pay_obj)

        if isinstance(cash_row, dict):
            crow = dict(cash_row)
            crow["cash_txn_id"] = str(crow.get("cash_txn_id") or "").strip() or self._alloc_id("CashLedger", explicit_prefix="CSH")
            self._append_row("CashLedger", crow)

        sale_status_upd = payload.get("sale_payment_status_update")
        sale_id = str(
            payload.get("sale_id")
            or pay_obj.get("sale_id")
            or (sale_status_upd.get("sale_id") if isinstance(sale_status_upd, dict) else "")
            or ""
        ).strip()
        sale_updates = payload.get("sale_updates")
        if sale_id:
            if isinstance(sale_status_upd, dict):
                self._update_row("Sales", "sale_id", sale_id, {k: v for k, v in sale_status_upd.items() if k != "sale_id"})
            elif isinstance(sale_updates, dict):
                self._update_row("Sales", "sale_id", sale_id, sale_updates)
            else:
                sales_rows = self._load_tab("Sales")
                srow = next((r for r in sales_rows if str(r.get("sale_id", "")).strip() == sale_id), None)
                if srow is not None:
                    amt = Decimal(str(pay_obj.get("amount") or 0))
                    prev_paid = Decimal(str(srow.get("amount_paid") or 0))
                    total = Decimal(str(srow.get("bill_total") or 0))
                    new_paid = prev_paid + amt
                    new_bal = max(Decimal("0.00"), total - new_paid)
                    new_status = "PAID" if new_bal <= Decimal("0.01") else ("PARTIAL" if new_paid > 0 else "UNPAID")
                    self._update_row("Sales", "sale_id", sale_id, {
                        "amount_paid": float(new_paid),
                        "balance_due": float(new_bal),
                        "payment_status": new_status,
                        "bill_status": new_status,
                    })
        return {"allocated_id": pid, "record": pay_obj}

    def _act_credit_approval_cas(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        req_id = str(payload.get("request_id") or "").strip()
        expected = payload.get("expected_conditions") or {}
        rows = self._load_tab("ApprovalRequests")
        target = next((r for r in rows if str(r.get("request_id", "")).strip() == req_id), None)
        if target is None:
            raise _SimRejectError("APPROVAL_NOT_FOUND", f"Approval request '{req_id}' not found.", 404)

        for cond_k, cond_v in expected.items():
            actual_raw = target.get(cond_k, "")
            if isinstance(cond_v, bool):
                actual_bool = str(actual_raw).strip().lower() in ("true", "1", "yes")
                if actual_bool != cond_v:
                    raise _SimRejectError(
                        "CAS_CONFLICT",
                        f"Condition mismatch on {cond_k}: expected {cond_v}, got {actual_raw}",
                        409,
                    )
            else:
                if str(actual_raw or "").strip() != str(cond_v or "").strip():
                    raise _SimRejectError(
                        "CAS_CONFLICT",
                        f"Condition mismatch on {cond_k}: expected '{cond_v}', got '{actual_raw}'",
                        409,
                    )

        updates = {k: v for k, v in payload.items() if k not in ("request_id", "expected_conditions")}
        self._update_row("ApprovalRequests", "request_id", req_id, updates)
        updated = dict(target)
        updated.update(updates)
        return {"allocated_id": req_id, "record": updated}

    def _act_approve_and_execute_request(self, payload: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
        req_id = str(payload.get("request_id") or "").strip()
        execution = payload.get("execution") or {}
        req_type = str(execution.get("request_type") or "").strip().upper()
        target_uid = str(execution.get("target_user_id") or "").strip()
        now_s = now_iso()

        if req_type == "CREATE_USER":
            fail_u = self._check_injected_failure("Users")
            if fail_u:
                raise RuntimeError(fail_u)
            fail_a = self._check_injected_failure("AuthUsers")
            if fail_a:
                raise RuntimeError(fail_a)
            up = dict(execution.get("user_payload") or {})
            uid = target_uid or self._alloc_id("Users", explicit_prefix="USR")
            up["user_id"] = uid
            up.setdefault("active", "true")
            up.setdefault("created_at", now_s)
            self._append_row("Users", up)
            self._append_row("AuthUsers", {
                "auth_id": self._alloc_id("AuthUsers", explicit_prefix="AUT"),
                "user_id": uid,
                "username": up.get("username", ""),
                "role": up.get("role", "SALESMAN"),
                "password_hash": execution.get("password_hash", ""),
                "must_change_password": execution.get("must_change_password", "true"),
                "active": "true",
                "sessions_revoked_at": "",
                "created_at": now_s,
            })
            target_uid = uid
        elif req_type == "UPDATE_USER" and target_uid:
            act_p = dict(execution.get("action_payload") or {})
            self._update_row("Users", "user_id", target_uid, act_p)
            if "username" in act_p:
                self._update_row("AuthUsers", "user_id", target_uid, {"username": act_p["username"]})
        elif req_type == "DEACTIVATE_USER" and target_uid:
            self._update_row("Users", "user_id", target_uid, {"active": "false"})
            self._update_row("AuthUsers", "user_id", target_uid, {"active": "false", "sessions_revoked_at": now_s})
        elif req_type == "REACTIVATE_USER" and target_uid:
            self._update_row("Users", "user_id", target_uid, {"active": "true"})
            self._update_row("AuthUsers", "user_id", target_uid, {"active": "true"})
        elif req_type == "RESET_PASSWORD" and target_uid:
            self._update_row("AuthUsers", "user_id", target_uid, {
                "password_hash": execution.get("password_hash", ""),
                "must_change_password": execution.get("must_change_password", "true"),
                "sessions_revoked_at": now_s,
            })
        elif req_type == "PRODUCTION_BATCH":
            act_p = dict(execution.get("action_payload") or {})
            pid = str(act_p.get("production_id") or target_uid or "").strip()
            if pid:
                self._update_row("ProductionBatches", "production_id", pid, {"status": "APPROVED"})

        updates = {
            "status": "EXECUTED",
            "decided_by": payload.get("decided_by", actor_user_id),
            "decided_at": payload.get("decided_at", now_s),
            "decision_notes": payload.get("decision_notes", ""),
            "executed_at": now_s,
            "target_user_id": target_uid,
        }
        self._update_row("ApprovalRequests", "request_id", req_id, updates)
        return {"allocated_id": req_id, "record": {"request_id": req_id, **updates}}

    def _act_reject_approval_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req_id = str(payload.get("request_id") or "").strip()
        updates = {k: v for k, v in payload.items() if k != "request_id"}
        updates["status"] = "REJECTED"
        self._update_row("ApprovalRequests", "request_id", req_id, updates)
        if str(payload.get("request_type") or "").upper() == "PRODUCTION_BATCH":
            pid = str(payload.get("target_user_id") or "").strip()
            if pid:
                self._update_row("ProductionBatches", "production_id", pid, {"status": "REJECTED"})
        return {"allocated_id": req_id, "record": {"request_id": req_id, **updates}}

    def _act_receive_raw_material(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload.get("ledger_entry") or {k: v for k, v in payload.items() if k not in ("raw_material_update", "material_update")})
        txn_id = str(payload.get("raw_material_txn_id") or rec.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", spec)
        rec["raw_material_txn_id"] = txn_id

        patched = self._is_append_record_patched()
        incomp_id = None
        if patched:
            meta = {}
            try:
                meta = json.loads(str(rec.get("notes") or "{}"))
            except Exception:
                meta = {}
            idemp_key = str(meta.get("request_id") or rec.get("issue_txn_id") or "").strip()
            incomp_id = self._alloc_id("IncompleteTransactions", explicit_prefix="INC")
            incomp_row = {
                "txn_id": incomp_id,
                "idempotency_key": idemp_key,
                "operation": "RECEIVE_RAW_MATERIAL",
                "status": "IN_PROGRESS",
                "payload_json": json.dumps({
                    "payload_hash": meta.get("payload_hash", ""),
                    "line_key": str(rec.get("issue_txn_id") or "").strip(),
                }),
                "created_at": now_iso(),
            }
            try:
                self._append_row_honoring_patch("IncompleteTransactions", incomp_row)
            except Exception as exc:
                raise RuntimeError(f"Failed to record intent in IncompleteTransactions: {exc}") from exc

        try:
            self._append_row_honoring_patch("RawMaterialLedger", rec)
        except Exception:
            if incomp_id:
                self._update_row("IncompleteTransactions", "txn_id", incomp_id, {"status": "PARTIAL_FAILED"})
            raise

        if incomp_id:
            self._update_row("IncompleteTransactions", "txn_id", incomp_id, {"status": "COMPLETED"})

        # RawMaterials.current_stock is the immutable historical opening stock;
        # only update RawMaterials if an explicit update dict was supplied.
        rm_id = str(rec.get("raw_material_id") or payload.get("raw_material_id") or "").strip()
        rm_upd = payload.get("raw_material_update") or payload.get("material_update")
        if rm_id and isinstance(rm_upd, dict):
            self._update_row("RawMaterials", "raw_material_id", rm_id, rm_upd)
        return {"allocated_id": txn_id, "record": rec}

    def _act_verify_rm_opening_stock(self, payload: Dict[str, Any], actor_user_id: str, spec: GovernedActionSpec) -> Dict[str, Any]:
        # Pre-check injected failures atomically before committing RawMaterialLedger or AuditLog
        fail_rml = self._check_injected_failure("RawMaterialLedger")
        if fail_rml:
            raise RuntimeError(fail_rml)
        audit_action = str(payload.get("audit_action") or "").strip()
        if audit_action:
            fail_aud = self._check_injected_failure("AuditLog")
            if fail_aud:
                raise RuntimeError(fail_aud)

        audit_meta_keys = ("raw_material_update", "audit_action", "audit_reason", "old_available", "new_available")
        rec = dict(payload.get("ledger_entry") or {k: v for k, v in payload.items() if k not in audit_meta_keys})
        txn_id = str(payload.get("raw_material_txn_id") or rec.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", spec)
        rec["raw_material_txn_id"] = txn_id
        self._append_row("RawMaterialLedger", rec)

        rm_id = str(rec.get("raw_material_id") or payload.get("raw_material_id") or "").strip()
        if rm_id and isinstance(payload.get("raw_material_update"), dict):
            self._update_row("RawMaterials", "raw_material_id", rm_id, payload["raw_material_update"])

        if audit_action:
            aud_row = {
                "audit_id": self._alloc_id("AuditLog", explicit_prefix="AUD"),
                "event_datetime": now_iso(),
                "actor_user_id": actor_user_id or str(rec.get("created_by") or ""),
                "action": audit_action,
                "entity_type": "RawMaterials",
                "entity_id": rm_id,
                "field_changed": "opening_stock_verified",
                "old_value": str(payload.get("old_available", "")),
                "new_value": str(payload.get("new_available", "")),
                "reason": str(payload.get("audit_reason", "")),
                "approved_by_user_id": actor_user_id or str(rec.get("created_by") or ""),
                "related_record_id": txn_id,
            }
            self._append_row("AuditLog", aud_row)
            self._atomic_audit_logged.add((audit_action.upper(), rm_id))

        return {"allocated_id": txn_id, "record": rec}

    def _act_issue_raw_materials(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        prod_id = str(payload.get("production_id") or "").strip()
        entries = payload.get("deductions") or payload.get("ledger_entries") or payload.get("items") or []
        rm_updates = payload.get("raw_material_updates") or []
        batch_upd = payload.get("batch_updates") or payload.get("batch_update") or {}

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            erow = dict(entry)
            erow["raw_material_txn_id"] = str(erow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
            if prod_id:
                erow.setdefault("production_id", prod_id)
            self._append_row_honoring_patch("RawMaterialLedger", erow)

        for ru in rm_updates:
            if isinstance(ru, dict) and ru.get("raw_material_id"):
                self._update_row("RawMaterials", "raw_material_id", str(ru["raw_material_id"]), {
                    k: v for k, v in ru.items() if k != "raw_material_id"
                })

        if prod_id:
            upd = dict(batch_upd) if isinstance(batch_upd, dict) else {}
            upd.setdefault("materials_issued", "true")
            if "total_raw_material_cost" in payload:
                upd["total_raw_material_cost"] = payload["total_raw_material_cost"]
            self._update_row("ProductionBatches", "production_id", prod_id, upd)

        return {"allocated_id": prod_id, "record": {"production_id": prod_id, **(batch_upd if isinstance(batch_upd, dict) else {})}}

    def _act_recover_raw_materials_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prod_id = str(payload.get("production_id") or "").strip()
        updates = dict(payload.get("updates") or {k: v for k, v in payload.items() if k != "production_id"})
        if prod_id:
            self._update_row("ProductionBatches", "production_id", prod_id, updates)
        return {"allocated_id": prod_id, "record": {"production_id": prod_id, **updates}}

    def _act_record_milling_batch(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        batch = dict(payload.get("milling_batch") or payload.get("batch") or {
            k: v for k, v in payload.items()
            if k not in ("ledger_entries", "raw_material_updates", "source_update", "output_update", "leg1_consumption", "leg2_output")
        })
        mid = str(payload.get("milling_batch_id") or batch.get("milling_batch_id") or "").strip() or self._alloc_id("MillingBatches", spec)
        batch["milling_batch_id"] = mid

        patched = self._is_append_record_patched()
        incomp_id = None
        if patched:
            meta = {}
            if isinstance(payload.get("leg1_consumption"), dict):
                try:
                    meta = json.loads(str(payload["leg1_consumption"].get("notes") or "{}"))
                except Exception:
                    meta = {}
            incomp_id = self._alloc_id("IncompleteTransactions", explicit_prefix="INC")
            incomp_row = {
                "txn_id": incomp_id,
                "idempotency_key": str(meta.get("idempotency_key") or mid).strip(),
                "operation": "RECORD_MILLING_BATCH",
                "status": "IN_PROGRESS",
                "payload_json": json.dumps({"payload_hash": meta.get("payload_hash", ""), "milling_batch_id": mid}),
                "created_at": now_iso(),
            }
            try:
                self._append_row_honoring_patch("IncompleteTransactions", incomp_row)
            except Exception as exc:
                raise RuntimeError(f"Failed to record milling intent in IncompleteTransactions: {exc}") from exc

        input_txn_id = ""
        output_txn_id = ""
        try:
            if isinstance(payload.get("leg1_consumption"), dict):
                leg1 = dict(payload["leg1_consumption"])
                input_txn_id = str(leg1.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                leg1["raw_material_txn_id"] = input_txn_id
                leg1.setdefault("issue_txn_id", mid)
                self._append_row_honoring_patch("RawMaterialLedger", leg1)
                batch["input_txn_id"] = input_txn_id

            if isinstance(payload.get("leg2_output"), dict):
                leg2 = dict(payload["leg2_output"])
                output_txn_id = str(leg2.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                leg2["raw_material_txn_id"] = output_txn_id
                leg2.setdefault("issue_txn_id", mid)
                self._append_row_honoring_patch("RawMaterialLedger", leg2)
                batch["output_txn_id"] = output_txn_id

            for entry in (payload.get("ledger_entries") or []):
                if isinstance(entry, dict):
                    erow = dict(entry)
                    erow["raw_material_txn_id"] = str(erow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                    erow.setdefault("issue_txn_id", mid)
                    self._append_row_honoring_patch("RawMaterialLedger", erow)

            self._append_row("MillingBatches", batch)
        except Exception:
            if incomp_id:
                self._update_row("IncompleteTransactions", "txn_id", incomp_id, {"status": "PARTIAL_FAILED"})
            raise

        if incomp_id:
            self._update_row("IncompleteTransactions", "txn_id", incomp_id, {"status": "COMPLETED"})

        for ru in (payload.get("raw_material_updates") or []):
            if isinstance(ru, dict) and ru.get("raw_material_id"):
                self._update_row("RawMaterials", "raw_material_id", str(ru["raw_material_id"]), {
                    k: v for k, v in ru.items() if k != "raw_material_id"
                })
        return {"allocated_id": mid, "record": batch}

    def _act_recover_milling_batch(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload.get("leg2_row") or payload.get("ledger_entry") or {
            k: v for k, v in payload.items()
            if k not in ("raw_material_update", "batch_update", "milling_batch_row")
        })
        txn_id = str(payload.get("raw_material_txn_id") or rec.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", spec)
        rec["raw_material_txn_id"] = txn_id
        self._append_row_honoring_patch("RawMaterialLedger", rec)

        if isinstance(payload.get("milling_batch_row"), dict):
            mrow = dict(payload["milling_batch_row"])
            mb_id = str(mrow.get("milling_batch_id") or "").strip()
            existing = [r for r in self._load_tab("MillingBatches") if str(r.get("milling_batch_id", "")).strip() == mb_id]
            if existing and mb_id:
                self._update_row("MillingBatches", "milling_batch_id", mb_id, mrow)
            else:
                self._append_row("MillingBatches", mrow)
        if isinstance(payload.get("raw_material_update"), dict) and payload["raw_material_update"].get("raw_material_id"):
            ru = payload["raw_material_update"]
            self._update_row("RawMaterials", "raw_material_id", str(ru["raw_material_id"]), {k: v for k, v in ru.items() if k != "raw_material_id"})
        if isinstance(payload.get("batch_update"), dict) and payload.get("milling_batch_id"):
            self._update_row("MillingBatches", "milling_batch_id", str(payload["milling_batch_id"]), payload["batch_update"])

        # Mark any matching PARTIAL_FAILED / IN_PROGRESS milling intent row COMPLETED
        meta = {}
        try:
            meta = json.loads(str(rec.get("notes") or "{}"))
        except Exception:
            meta = {}
        idemp_key = str(meta.get("idempotency_key") or "").strip()
        incomp_rows = self._load_tab("IncompleteTransactions")
        changed_incomp = False
        for row in incomp_rows:
            if row.get("operation") == "RECORD_MILLING_BATCH" and (
                (idemp_key and str(row.get("idempotency_key", "")).strip() == idemp_key)
                or str(row.get("status", "")).upper() in ("PARTIAL_FAILED", "IN_PROGRESS")
            ):
                row["status"] = "COMPLETED"
                changed_incomp = True
        if changed_incomp:
            self._save_tab("IncompleteTransactions", incomp_rows)

        return {"allocated_id": txn_id, "record": rec}

    def _act_approve_production_batch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prod_id = str(payload.get("production_id") or "").strip()
        updates = dict(payload.get("updates") or {
            k: v for k, v in payload.items()
            if k not in ("production_id", "material_issue_plan", "bulk_stock_movement", "approval_request_ids", "approval_decision", "cost_review")
        })
        issue_plan = payload.get("material_issue_plan")
        if isinstance(issue_plan, dict):
            for entry in (issue_plan.get("deductions") or []):
                if isinstance(entry, dict):
                    erow = dict(entry)
                    erow["raw_material_txn_id"] = str(erow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                    erow.setdefault("production_id", prod_id)
                    self._append_row("RawMaterialLedger", erow)

        bulk_mov = payload.get("bulk_stock_movement")
        if isinstance(bulk_mov, dict):
            mrow = dict(bulk_mov)
            mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
            mrow.setdefault("reference_id", prod_id)
            self._append_row("ProductionStockLedger", mrow)

        if prod_id:
            self._update_row("ProductionBatches", "production_id", prod_id, updates)

        appr_dec = payload.get("approval_decision")
        if isinstance(appr_dec, dict):
            for req_id in (payload.get("approval_request_ids") or []):
                if req_id:
                    self._update_row("ApprovalRequests", "request_id", str(req_id), appr_dec)

        return {"allocated_id": prod_id, "record": {"production_id": prod_id, **updates}}

    def _act_create_production_batch(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload.get("record") or {k: v for k, v in payload.items() if k not in ("auto_issue_materials", "material_issue_plan", "approval_request")})
        bid = str(payload.get("production_id") or rec.get("production_id") or "").strip() or self._alloc_id("ProductionBatches", spec)
        rec["production_id"] = bid
        rec["batch_id"] = bid

        issue_plan = payload.get("material_issue_plan")
        if payload.get("auto_issue_materials") and isinstance(issue_plan, dict):
            deduction_rows = issue_plan.get("deduction_rows") or issue_plan.get("deductions") or []
            if deduction_rows:
                issue_txn_id = f"RML-ISSUE-{bid}"
                rec["materials_issued"] = "true"
                rec["material_issue_txn_id"] = issue_txn_id
                for drow in deduction_rows:
                    if isinstance(drow, dict):
                        erow = dict(drow)
                        erow["raw_material_txn_id"] = str(erow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                        erow["production_id"] = bid
                        erow.setdefault("issue_txn_id", issue_txn_id)
                        self._append_row_honoring_patch("RawMaterialLedger", erow)

        self._append_row("ProductionBatches", rec)

        appr = payload.get("approval_request")
        if isinstance(appr, dict):
            arow = dict(appr)
            arow["request_id"] = str(arow.get("request_id") or "").strip() or self._alloc_id("ApprovalRequests", explicit_prefix="APR")
            arow.setdefault("target_user_id", bid)
            arow.setdefault("status", "PENDING")
            arow.setdefault("created_at", now_iso())
            self._append_row("ApprovalRequests", arow)

        return {"allocated_id": bid, "record": rec}

    def _act_resolve_legacy_batch_cost(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prod_id = str(payload.get("production_id") or "").strip()
        updates = dict(payload.get("updates") or {})
        if prod_id and updates:
            self._update_row("ProductionBatches", "production_id", prod_id, updates)
        mvt_upd = payload.get("bulk_movement_updates")
        if isinstance(mvt_upd, dict):
            for mid in (payload.get("bulk_movement_ids") or []):
                if mid:
                    self._update_row("ProductionStockLedger", "movement_id", str(mid), mvt_upd)
        return {"allocated_id": prod_id, "record": {"production_id": prod_id, **updates}}

    def _act_record_packaging(self, action: str, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        pkg = dict(payload.get("record") or payload.get("packaging") or payload.get("batch") or {
            k: v for k, v in payload.items()
            if k not in ("stock_movements", "ledger_entries", "production_batch_updates", "raw_material_entries", "sku_cost_updates", "approval_request")
        })
        pid = str(payload.get("packaging_id") or pkg.get("packaging_id") or "").strip() or self._alloc_id("PackagingBatches", spec)
        pkg["packaging_id"] = pid
        self._append_row_honoring_patch("PackagingBatches", pkg)

        appr = payload.get("approval_request")
        if isinstance(appr, dict):
            arow = dict(appr)
            arow["request_id"] = str(arow.get("request_id") or "").strip() or self._alloc_id("ApprovalRequests", explicit_prefix="APR")
            arow.setdefault("target_user_id", pid)
            arow.setdefault("status", "PENDING")
            arow.setdefault("created_at", now_iso())
            self._append_row("ApprovalRequests", arow)

        try:
            for mov in (payload.get("stock_movements") or payload.get("ledger_entries") or []):
                if isinstance(mov, dict):
                    mrow = dict(mov)
                    mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
                    mrow["reference_id"] = str(mrow.get("reference_id") or "").strip() or pid
                    self._append_row_honoring_patch("ProductionStockLedger", mrow)
        except Exception as exc:
            prev_notes = str(pkg.get("notes") or "")
            inc_notes = f"{prev_notes} [INCOMPLETE_STOCK_WRITE: {exc}]".strip()
            self._update_row("PackagingBatches", "packaging_id", pid, {"status": "INCOMPLETE", "notes": inc_notes})
            raise RuntimeError(f"Packaging batch '{pid}' marked INCOMPLETE due to stock ledger write failure: {exc}") from exc

        for rme in (payload.get("raw_material_entries") or []):
            if isinstance(rme, dict):
                erow = dict(rme)
                erow["raw_material_txn_id"] = str(erow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                self._append_row("RawMaterialLedger", erow)

        for pbu in (payload.get("production_batch_updates") or []):
            if isinstance(pbu, dict) and pbu.get("production_id"):
                self._update_row("ProductionBatches", "production_id", str(pbu["production_id"]), {
                    k: v for k, v in pbu.items() if k != "production_id"
                })

        for scu in (payload.get("sku_cost_updates") or []):
            if isinstance(scu, dict) and scu.get("product_id"):
                self._update_row("Products", "product_id", str(scu["product_id"]), {
                    k: v for k, v in scu.items() if k != "product_id"
                })
        return {"allocated_id": pid, "record": pkg}

    def _act_reconcile_packaging(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = str(payload.get("packaging_id") or "").strip()
        updates = dict(payload.get("updates") or payload.get("packaging_updates") or {})
        if pid and updates:
            self._update_row("PackagingBatches", "packaging_id", pid, updates)
        for mov in (payload.get("stock_movements") or []):
            if isinstance(mov, dict):
                mrow = dict(mov)
                mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
                mrow["reference_id"] = str(mrow.get("reference_id") or "").strip() or pid
                self._append_row("ProductionStockLedger", mrow)
        return {"allocated_id": pid, "record": {"packaging_id": pid, **updates}}

    def _act_approve_packaging_discrepancy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = str(payload.get("packaging_id") or "").strip()
        audit_ev = payload.get("audit_event")
        # Pre-check injected failures atomically before mutating any tab
        for tab_chk in ("PackagingBatches", "ProductionStockLedger"):
            fail = self._check_injected_failure(tab_chk)
            if fail:
                raise RuntimeError(fail)
        if isinstance(audit_ev, dict):
            fail_aud = self._check_injected_failure("AuditLog")
            if fail_aud:
                raise RuntimeError(fail_aud)

        updates = dict(payload.get("packaging_updates") or payload.get("packaging_update") or {
            k: v for k, v in payload.items()
            if k not in (
                "packaging_id", "stock_movements", "ledger_entries", "production_batch_updates",
                "approval_request_ids", "approval_request_updates", "audit_event",
            )
        })
        if pid and updates:
            self._update_row("PackagingBatches", "packaging_id", pid, updates)
        for mov in (payload.get("stock_movements") or payload.get("ledger_entries") or []):
            if isinstance(mov, dict):
                mrow = dict(mov)
                mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
                mrow["reference_id"] = str(mrow.get("reference_id") or "").strip() or pid
                self._append_row("ProductionStockLedger", mrow)
        appr_upd = payload.get("approval_request_updates")
        if isinstance(appr_upd, dict):
            for req_id in (payload.get("approval_request_ids") or []):
                if req_id:
                    self._update_row("ApprovalRequests", "request_id", str(req_id), appr_upd)
        if isinstance(audit_ev, dict):
            arow = dict(audit_ev)
            arow["audit_id"] = str(arow.get("audit_id") or "").strip() or self._alloc_id("AuditLog", explicit_prefix="AUD")
            arow.setdefault("event_datetime", now_iso())
            self._append_row("AuditLog", arow)
            self._atomic_audit_logged.add((str(arow.get("action") or "").strip().upper(), str(arow.get("entity_id") or pid).strip()))
        return {"allocated_id": pid, "record": {"packaging_id": pid, **updates}}

    def _act_recover_packaging(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = str(payload.get("packaging_id") or "").strip()
        updates = dict(payload.get("packaging_updates") or payload.get("packaging_update") or {
            k: v for k, v in payload.items()
            if k not in ("packaging_id", "stock_movements", "ledger_entries", "incomplete_transaction_ids", "incomplete_transaction_updates")
        })
        if pid and updates:
            self._update_row("PackagingBatches", "packaging_id", pid, updates)
        for mov in (payload.get("stock_movements") or payload.get("ledger_entries") or []):
            if isinstance(mov, dict):
                mrow = dict(mov)
                mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
                mrow["reference_id"] = str(mrow.get("reference_id") or "").strip() or pid
                self._append_row("ProductionStockLedger", mrow)
        it_upd = payload.get("incomplete_transaction_updates")
        if isinstance(it_upd, dict):
            for it_id in (payload.get("incomplete_transaction_ids") or []):
                if it_id:
                    self._update_row("IncompleteTransactions", "transaction_id", str(it_id), it_upd)
        return {"allocated_id": pid, "record": {"packaging_id": pid, **updates}}

    def _act_dispatch(self, action: str, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        if action == "RECONCILE_DISPATCH":
            did = str(payload.get("dispatch_id") or "").strip()
            updates = dict(payload.get("updates") or {
                k: v for k, v in payload.items()
                if k not in ("dispatch_id", "production_stock_movement", "salesman_stock_movement", "production_movements", "salesman_movements")
            })
            if did and updates:
                self._update_row("ProductionDispatches", "dispatch_id", did, updates)
            disp = {"dispatch_id": did, **updates}
        else:
            disp = dict(payload.get("record") or payload.get("dispatch") or {
                k: v for k, v in payload.items()
                if k not in ("production_movements", "salesman_movements", "ledger_entries", "stock_movements", "production_stock_movement", "salesman_stock_movement")
            })
            did = str(payload.get("dispatch_id") or disp.get("dispatch_id") or "").strip()
            if not did:
                did = self._alloc_id("ProductionDispatches", spec)
            disp["dispatch_id"] = did
            self._append_row("ProductionDispatches", disp)

        prod_movs = list(payload.get("production_movements") or payload.get("ledger_entries") or payload.get("stock_movements") or [])
        if isinstance(payload.get("production_stock_movement"), dict):
            prod_movs.append(payload["production_stock_movement"])
        for mov in prod_movs:
            if isinstance(mov, dict):
                mrow = dict(mov)
                mrow["movement_id"] = str(mrow.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
                mrow["reference_id"] = str(mrow.get("reference_id") or "").strip() or did
                self._append_row("ProductionStockLedger", mrow)

        sales_movs = list(payload.get("salesman_movements") or [])
        if isinstance(payload.get("salesman_stock_movement"), dict):
            sales_movs.append(payload["salesman_stock_movement"])
        for smov in sales_movs:
            if isinstance(smov, dict):
                srow = dict(smov)
                srow["stock_txn_id"] = str(srow.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", explicit_prefix="STK")
                srow["reference_id"] = str(srow.get("reference_id") or "").strip() or did
                self._append_row("SalesmanStockLedger", srow)

        return {"allocated_id": did, "record": disp}

    def _warehouse_available_packets(self, product_id: str) -> int:
        """Compute current unreserved warehouse finished-goods packets for atomic concurrency checks."""
        pid = str(product_id or "").strip()
        prod_ledger = self._load_tab("ProductionStockLedger")
        sales_ledger = self._load_tab("SalesmanStockLedger")
        passes = self._load_tab("VanLoadingPasses")

        # Match backend/app/routers/stock.py warehouse stock formula
        total_in = 0
        for r in prod_ledger:
            if str(r.get("product_id", "")).strip() == pid:
                mtype = str(r.get("movement_type", "")).strip().upper()
                if mtype in ("PACKAGING_IN", "TRANSFER_TO_WAREHOUSE", "WAREHOUSE_IN", "OPENING_STOCK", "ADJUSTMENT", "RECONCILIATION"):
                    total_in += int(float(r.get("quantity_packets") or r.get("quantity") or 0))
                elif mtype in ("DISPATCH_OUT", "WAREHOUSE_OUT"):
                    total_in -= abs(int(float(r.get("quantity_packets") or r.get("quantity") or 0)))

        # SalesmanStockLedger ISSUE/RETURN/ADJUSTMENT movements
        for r in sales_ledger:
            if str(r.get("product_id", "")).strip() == pid:
                mtype = str(r.get("movement_type", "")).strip().upper()
                qty = int(float(r.get("quantity_packets") or 0))
                if mtype == "ISSUE":
                    total_in -= abs(qty)
                elif mtype == "RETURN":
                    total_in += abs(qty)
                elif mtype in ("WAREHOUSE_OPENING", "WAREHOUSE_IN", "WAREHOUSE_ADJUSTMENT"):
                    total_in += qty

        # Pending van loading passes reserve warehouse stock
        reserved = 0
        for vp in passes:
            if str(vp.get("status", "")).strip().upper() in ("PENDING_ACCEPTANCE", "PENDING", "DISCREPANCY_REPORTED"):
                try:
                    vitems = json.loads(str(vp.get("items_json") or "[]"))
                except Exception:
                    vitems = []
                for vi in vitems:
                    if str(vi.get("product_id", "")).strip() == pid:
                        reserved += int(float(vi.get("quantity_packets") or 0))

        return total_in - reserved

    def _act_record_stock_movement(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload.get("movement") or {k: v for k, v in payload.items() if k != "production_movement"})
        mtype = str(rec.get("movement_type") or "").strip().upper()
        pid = str(rec.get("product_id") or "").strip()
        qty = int(float(rec.get("quantity_packets") or 0))

        # Atomic warehouse availability guard for ISSUE when warehouse stock tracking is active
        if mtype == "ISSUE" and qty > 0 and payload.get("enforce_warehouse_stock", False):
            avail = self._warehouse_available_packets(pid)
            if qty > avail:
                raise _SimRejectError(
                    "INSUFFICIENT_WAREHOUSE_STOCK",
                    f"Insufficient warehouse stock for {pid}: requested {qty}, available {avail}.",
                    409,
                )

        tid = str(payload.get("stock_txn_id") or rec.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", spec)
        rec["stock_txn_id"] = tid
        self._append_row("SalesmanStockLedger", rec)

        if isinstance(payload.get("production_movement"), dict):
            pm = dict(payload["production_movement"])
            pm["movement_id"] = str(pm.get("movement_id") or "").strip() or self._alloc_id("ProductionStockLedger", explicit_prefix="PST")
            self._append_row("ProductionStockLedger", pm)

        return {"allocated_id": tid, "record": rec}

    def _act_create_van_loading_pass(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload)
        # Enforce atomic warehouse stock reservation for every SKU in the pass
        try:
            items = json.loads(str(rec.get("items_json") or "[]"))
        except Exception:
            items = []
        if items and (self._load_tab("ProductionStockLedger") or any(
            str(r.get("movement_type", "")).upper().startswith("WAREHOUSE")
            for r in self._load_tab("SalesmanStockLedger")
        )):
            for item in items:
                pid = str(item.get("product_id") or "").strip()
                req_qty = int(float(item.get("quantity_packets") or 0))
                avail = self._warehouse_available_packets(pid)
                if req_qty > avail:
                    raise _SimRejectError(
                        "INSUFFICIENT_WAREHOUSE_STOCK",
                        f"Insufficient warehouse stock for {pid}: requested {req_qty}, available {avail}.",
                        409,
                    )

        pass_id = str(rec.get("pass_id") or "").strip() or self._alloc_id("VanLoadingPasses", spec)
        rec["pass_id"] = pass_id
        rec.setdefault("pass_number", pass_id)
        self._append_row("VanLoadingPasses", rec)
        return {"allocated_id": pass_id, "record": rec}

    def _act_accept_van_loading_pass(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pass_id = str(payload.get("pass_id") or "").strip()
        passes = self._load_tab("VanLoadingPasses")
        existing = next((p for p in passes if str(p.get("pass_id", "")).strip() == pass_id), None)
        if existing is None:
            raise _SimRejectError("VAN_PASS_NOT_FOUND", f"Van loading pass '{pass_id}' not found.", 404)
        cur_status = str(existing.get("status", "")).strip().upper()
        if cur_status != "PENDING_ACCEPTANCE":
            raise _SimRejectError("VAN_PASS_INVALID_STATE", f"Van pass '{pass_id}' already in status '{cur_status}'.", 409)

        # Write ledger movements first so partial failure recovery tests reflect real Sheets append ordering
        for mov in (payload.get("ledger_movements") or payload.get("stock_movements") or payload.get("ledger_entries") or []):
            if isinstance(mov, dict):
                mrow = dict(mov)
                mrow["stock_txn_id"] = str(mrow.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", explicit_prefix="STK")
                # Respect custom monkey-patched db.append_record if tests injected flaky_append on SalesmanStockLedger
                if getattr(db.append_record, "__func__", None) is None:
                    ok = db.append_record("SalesmanStockLedger", mrow, raise_on_error=True)
                    if not ok:
                        raise RuntimeError("SalesmanStockLedger append failed")
                else:
                    self._append_row("SalesmanStockLedger", mrow)

        updates = {k: v for k, v in payload.items() if k not in ("pass_id", "stock_movements", "ledger_entries", "ledger_movements")}
        updates["status"] = "ACCEPTED"
        self._update_row("VanLoadingPasses", "pass_id", pass_id, updates)
        return {"allocated_id": pass_id, "record": {**existing, **updates}}

    def _act_report_van_loading_discrepancy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pass_id = str(payload.get("pass_id") or "").strip()
        discs = list(payload.get("discrepancy_records") or [])
        if isinstance(payload.get("stock_discrepancy"), dict):
            discs.append(payload["stock_discrepancy"])
        elif isinstance(payload.get("discrepancy"), dict):
            discs.append(payload["discrepancy"])
        # Fail closed before updating VanLoadingPasses if StockDiscrepancies fails
        if discs:
            fail_d = self._check_injected_failure("StockDiscrepancies")
            if fail_d:
                raise RuntimeError(fail_d)
        updates = {k: v for k, v in payload.items() if k not in ("pass_id", "discrepancy_records", "discrepancy", "stock_discrepancy")}
        updates.setdefault("status", "DISCREPANCY_REPORTED")
        self._update_row("VanLoadingPasses", "pass_id", pass_id, updates)
        for d in discs:
            if isinstance(d, dict):
                drow = dict(d)
                drow["discrepancy_id"] = str(drow.get("discrepancy_id") or "").strip() or self._alloc_id("StockDiscrepancies", explicit_prefix="DSC")
                self._append_row("StockDiscrepancies", drow)
        return {"allocated_id": pass_id, "record": {"pass_id": pass_id, **updates}}

    def _act_cancel_van_loading_pass(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pass_id = str(payload.get("pass_id") or "").strip()
        updates = {k: v for k, v in payload.items() if k != "pass_id"}
        updates["status"] = "CANCELLED"
        self._update_row("VanLoadingPasses", "pass_id", pass_id, updates)
        return {"allocated_id": pass_id, "record": {"pass_id": pass_id, **updates}}

    def _act_review_stock_discrepancy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        did = str(payload.get("discrepancy_id") or "").strip()
        mov = payload.get("ledger_adjustment") or payload.get("adjustment_movement") or payload.get("stock_movement")
        if isinstance(mov, dict):
            mrow = dict(mov)
            mrow["stock_txn_id"] = str(mrow.get("stock_txn_id") or "").strip() or self._alloc_id("SalesmanStockLedger", explicit_prefix="STK")
            self._append_row("SalesmanStockLedger", mrow)
        updates = {
            k: v for k, v in payload.items()
            if k not in ("discrepancy_id", "ledger_adjustment", "adjustment_movement", "stock_movement", "audit_event")
        }
        self._update_row("StockDiscrepancies", "discrepancy_id", did, updates)
        audit_ev = payload.get("audit_event")
        if isinstance(audit_ev, dict):
            arow = dict(audit_ev)
            arow["audit_id"] = str(arow.get("audit_id") or "").strip() or self._alloc_id("AuditLog", explicit_prefix="AUD")
            arow.setdefault("event_datetime", now_iso())
            self._append_row("AuditLog", arow)
            self._atomic_audit_logged.add((str(arow.get("action") or "").strip().upper(), str(arow.get("entity_id") or did).strip()))
        return {"allocated_id": did, "record": {"discrepancy_id": did, **updates}}

    def _act_create_purchase_order(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        po = dict(payload.get("po") or {k: v for k, v in payload.items() if k != "items"})
        poid = str(payload.get("po_id") or po.get("po_id") or "").strip() or self._alloc_id("PurchaseOrders", spec)
        po["po_id"] = poid
        self._append_row("PurchaseOrders", po)
        for item in (payload.get("items") or []):
            if isinstance(item, dict):
                irow = dict(item)
                irow["po_id"] = poid
                irow["po_item_id"] = str(irow.get("po_item_id") or "").strip() or self._alloc_id("PurchaseOrderItems", explicit_prefix="POI")
                self._append_row("PurchaseOrderItems", irow)
        return {"allocated_id": poid, "record": po}

    def _act_receive_goods(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        grn = dict(payload.get("grn") or {
            k: v for k, v in payload.items()
            if k not in ("items", "ledger_entries", "raw_material_updates", "po_updates", "po_item_updates")
        })
        rid = str(payload.get("receipt_id") or grn.get("receipt_id") or "").strip() or self._alloc_id("GoodsReceipts", spec)
        grn["receipt_id"] = rid
        self._append_row("GoodsReceipts", grn)
        for item in (payload.get("items") or []):
            if isinstance(item, dict):
                irow = dict(item)
                irow["receipt_id"] = rid
                irow["receipt_item_id"] = str(irow.get("receipt_item_id") or "").strip() or self._alloc_id("GoodsReceiptItems", explicit_prefix="GRI")
                self._append_row("GoodsReceiptItems", irow)
        for le in (payload.get("ledger_entries") or []):
            if isinstance(le, dict):
                lrow = dict(le)
                lrow["raw_material_txn_id"] = str(lrow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                self._append_row("RawMaterialLedger", lrow)
        for ru in (payload.get("raw_material_updates") or []):
            if isinstance(ru, dict) and ru.get("raw_material_id"):
                self._update_row("RawMaterials", "raw_material_id", str(ru["raw_material_id"]), {k: v for k, v in ru.items() if k != "raw_material_id"})
        if isinstance(payload.get("po_updates"), dict) and payload["po_updates"].get("po_id"):
            pu = payload["po_updates"]
            self._update_row("PurchaseOrders", "po_id", str(pu["po_id"]), {k: v for k, v in pu.items() if k != "po_id"})
        return {"allocated_id": rid, "record": grn}

    def _act_record_supplier_payment(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        pay = dict(payload.get("payment") or {k: v for k, v in payload.items() if k not in ("bill_update", "bill_updates")})
        existing_pid = str(payload.get("payment_id") or pay.get("payment_id") or "").strip()
        pid = existing_pid or self._alloc_id("SupplierPayments", spec)
        pay["payment_id"] = pid
        target_status = str(pay.get("status") or "PAID")

        bill_upd = payload.get("bill_update")
        bill_id = str(payload.get("bill_id") or pay.get("bill_id") or (bill_upd.get("bill_id") if isinstance(bill_upd, dict) else "") or "").strip()

        staged_pay = dict(pay)
        if bill_id and isinstance(bill_upd, dict):
            staged_pay["status"] = "INCOMPLETE"
        if existing_pid and self._update_row("SupplierPayments", "payment_id", pid, staged_pay):
            pass
        else:
            self._append_row("SupplierPayments", staged_pay)

        if bill_id:
            if isinstance(bill_upd, dict):
                upd_clean = {k: v for k, v in bill_upd.items() if k not in ("bill_id", "existing_notes")}
                existing_notes = str(bill_upd.get("existing_notes") or "").strip()
                marker = f"[spay:{pid}]"
                if marker not in existing_notes:
                    upd_clean["notes"] = f"{existing_notes} {marker}".strip()
                self._update_row("SupplierBills", "bill_id", bill_id, upd_clean)
            elif not existing_pid:
                bills = self._load_tab("SupplierBills")
                brow = next((b for b in bills if str(b.get("bill_id", "")).strip() == bill_id), None)
                if brow is not None:
                    amt = Decimal(str(pay.get("amount") or 0))
                    prev_paid = Decimal(str(brow.get("paid_amount") or brow.get("amount_paid") or 0))
                    total = Decimal(str(brow.get("total_amount") or 0))
                    new_paid = prev_paid + amt
                    new_bal = max(Decimal("0.00"), total - new_paid)
                    new_stat = "PAID" if new_bal <= Decimal("0.05") else ("PARTIALLY_PAID" if new_paid > 0 else "UNPAID")
                    self._update_row("SupplierBills", "bill_id", bill_id, {
                        "paid_amount": float(new_paid),
                        "balance_amount": float(new_bal),
                        "payment_status": new_stat,
                    })
        if staged_pay["status"] != target_status:
            pay["status"] = target_status
            self._update_row("SupplierPayments", "payment_id", pid, {"status": target_status})
        return {"allocated_id": pid, "record": pay}

    def _act_apply_supplier_advance(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        pay_upd = dict(payload.get("payment_update") or {
            k: v for k, v in payload.items()
            if k not in ("payment_id", "bill_update", "new_payment_record", "allocation")
        })
        pid = str(payload.get("payment_id") or pay_upd.get("payment_id") or "").strip()
        if isinstance(payload.get("bill_update"), dict) and payload["bill_update"].get("bill_id"):
            bu = payload["bill_update"]
            bu_clean = {k: v for k, v in bu.items() if k not in ("bill_id", "existing_notes")}
            if "existing_notes" in bu:
                existing_notes = str(bu.get("existing_notes") or "").strip()
                marker = f"[spay:{pid}]"
                if marker not in existing_notes:
                    bu_clean["notes"] = f"{existing_notes} {marker}".strip()
            self._update_row("SupplierBills", "bill_id", str(bu["bill_id"]), bu_clean)
        if pid:
            self._update_row("SupplierPayments", "payment_id", pid, {k: v for k, v in pay_upd.items() if k != "payment_id"})
        if isinstance(payload.get("new_payment_record"), dict):
            np = dict(payload["new_payment_record"])
            np["payment_id"] = str(np.get("payment_id") or "").strip() or self._alloc_id("SupplierPayments", spec)
            self._append_row("SupplierPayments", np)
            if not pid:
                pid = np["payment_id"]
        return {"allocated_id": pid, "record": {"payment_id": pid, **pay_upd}}

    def _act_create_supplier_return(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        ret = dict(payload.get("return_record") or {k: v for k, v in payload.items() if k not in ("items", "ledger_entries")})
        rid = str(payload.get("return_id") or ret.get("return_id") or "").strip() or self._alloc_id("SupplierReturns", spec)
        ret["return_id"] = rid
        self._append_row("SupplierReturns", ret)
        for item in (payload.get("items") or []):
            if isinstance(item, dict):
                irow = dict(item)
                irow["return_id"] = rid
                irow["return_item_id"] = str(irow.get("return_item_id") or "").strip() or self._alloc_id("SupplierReturnItems", explicit_prefix="SRI")
                self._append_row("SupplierReturnItems", irow)
        for le in (payload.get("ledger_entries") or []):
            if isinstance(le, dict):
                lrow = dict(le)
                lrow["raw_material_txn_id"] = str(lrow.get("raw_material_txn_id") or "").strip() or self._alloc_id("RawMaterialLedger", explicit_prefix="RML")
                self._append_row("RawMaterialLedger", lrow)
        return {"allocated_id": rid, "record": ret}

    def _act_bootstrap_first_owner(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        if self._owner_bootstrap_completed:
            raise _SimRejectError(
                "OWNER_BOOTSTRAP_ALREADY_COMPLETED",
                "One-time first-owner bootstrap has already completed and is permanently locked.",
                409,
            )

        existing_users = [
            r for r in self._load_tab("Users")
            if isinstance(r, dict) and any(str(v or "").strip() for v in r.values())
        ]
        existing_auth = [
            r for r in self._load_tab("AuthUsers")
            if isinstance(r, dict) and any(str(v or "").strip() for v in r.values())
        ]
        if existing_users or existing_auth:
            raise _SimRejectError(
                "OWNER_ALREADY_INITIALIZED",
                "First-owner bootstrap rejected: Users or AuthUsers already contains records.",
                409,
            )

        pw_hash = str(payload.get("password_hash") or "").strip()
        if not pw_hash.startswith("pbkdf2:sha256:") or len(pw_hash.split("$")) != 3:
            raise _SimRejectError(
                "INVALID_PASSWORD_HASH",
                "Plain-text or non-PBKDF2 password hashes are strictly rejected.",
                422,
            )

        digest = str(payload.get("bootstrap_token_digest") or "").strip().lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _SimRejectError(
                "INVALID_BOOTSTRAP_PROOF",
                "Missing or malformed bootstrap verification digest.",
                403,
            )

        fail_a = self._check_injected_failure("AuthUsers")
        if fail_a:
            raise RuntimeError(fail_a)

        uid = self._alloc_id("Users", spec)
        auth_id = self._alloc_id("AuthUsers", explicit_prefix="AUTH")
        created_at = str(payload.get("created_at") or now_iso())
        updated_at = str(payload.get("updated_at") or created_at)
        effective_from = str(payload.get("effective_from") or created_at[:10])
        username = str(payload.get("username") or "").strip().lower()
        full_name = str(payload.get("full_name") or "").strip()

        user_rec = {
            "user_id": uid,
            "full_name": full_name,
            "username": username,
            "role": "OWNER_ADMIN",
            "mobile": str(payload.get("mobile") or "").strip(),
            "email": str(payload.get("email") or "").strip(),
            "active": "true",
            "created_at": created_at,
            "notes": str(payload.get("notes") or "").strip(),
            "employment_type": str(payload.get("employment_type") or "OWNER").strip(),
            "designation": str(payload.get("designation") or "Owner / Managing Director").strip(),
            "department": str(payload.get("department") or "Executive").strip(),
            "reporting_manager_id": "",
            "joining_date": effective_from,
            "employment_status": str(payload.get("employment_status") or "ACTIVE").strip(),
            "salary_frequency": "",
            "salary_structure_id": "",
            "address": "",
            "emergency_contact": "",
            "bank_details": "",
            "document_references": "",
            "updated_at": updated_at,
            "created_by": uid,
            "effective_from": effective_from,
            "effective_to": "",
        }
        auth_rec = {
            "auth_id": auth_id,
            "user_id": uid,
            "username": username,
            "password_hash": pw_hash,
            "role": "OWNER_ADMIN",
            "active": "true",
            "created_at": created_at,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        }

        if self._current_nonce:
            self._append_row("IdAllocations", {
                "allocation_id": self._alloc_id("IdAllocations", explicit_prefix="ALC"),
                "tab_name": "Users",
                "allocated_id": uid,
                "nonce": self._current_nonce,
                "created_at": created_at,
            })
        self._append_row("Users", user_rec)
        self._append_row("AuthUsers", auth_rec)
        self._owner_bootstrap_completed = True
        return {"allocated_id": uid, "record": dict(user_rec)}

    def _act_create_user(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        # Atomic check: fail before mutating Users if AuthUsers fails
        fail_a = self._check_injected_failure("AuthUsers")
        if fail_a:
            raise RuntimeError(fail_a)
        user_rec = dict(payload.get("user") or payload.get("user_record") or {
            k: v for k, v in payload.items() if k not in ("auth_user", "auth_record")
        })
        uid = str(payload.get("user_id") or user_rec.get("user_id") or "").strip() or self._alloc_id("Users", spec)
        user_rec["user_id"] = uid
        self._append_row("Users", user_rec)
        auth_rec = dict(payload.get("auth_user") or payload.get("auth_record") or {
            "auth_id": self._alloc_id("AuthUsers", explicit_prefix="AUT"),
            "user_id": uid,
            "username": user_rec.get("username", ""),
            "role": user_rec.get("role", "SALESMAN"),
            "password_hash": payload.get("password_hash", ""),
            "must_change_password": payload.get("must_change_password", "true"),
            "active": user_rec.get("active", "true"),
            "sessions_revoked_at": "",
            "created_at": user_rec.get("created_at") or now_iso(),
        })
        auth_rec["user_id"] = uid
        auth_rec.setdefault("auth_id", self._alloc_id("AuthUsers", explicit_prefix="AUT"))
        self._append_row("AuthUsers", auth_rec)
        return {"allocated_id": uid, "record": user_rec}

    def _act_update_user(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        uid = str(payload.get("user_id") or "").strip()
        user_upd = dict(payload.get("user_updates") or {
            k: v for k, v in payload.items() if k not in ("user_id", "auth_updates")
        })
        if action == "DEACTIVATE_USER":
            user_upd.setdefault("active", "false")
        elif action == "REACTIVATE_USER":
            user_upd.setdefault("active", "true")
        auth_upd = dict(payload.get("auth_updates") or {})
        if action == "DEACTIVATE_USER":
            auth_upd.setdefault("active", "false")
            auth_upd.setdefault("sessions_revoked_at", payload.get("sessions_revoked_at", now_iso()))
        elif action == "REACTIVATE_USER":
            auth_upd.setdefault("active", "true")
        if "username" in user_upd:
            auth_upd.setdefault("username", user_upd["username"])
        # Atomic check: if AuthUsers update fails, do NOT leave partial Users update
        if auth_upd:
            fail_a = self._check_injected_failure("AuthUsers")
            if fail_a:
                raise RuntimeError(fail_a)
        self._update_row("Users", "user_id", uid, user_upd)
        if auth_upd:
            self._update_row("AuthUsers", "user_id", uid, auth_upd)
        return {"allocated_id": uid, "record": {"user_id": uid, **user_upd}}

    def _act_reset_password(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        uid = str(payload.get("user_id") or "").strip()
        updates = {k: v for k, v in payload.items() if k != "user_id"}
        self._update_row("AuthUsers", "user_id", uid, updates)
        return {"allocated_id": uid, "record": {"user_id": uid, **updates}}

    def _act_calculate_payroll(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        run_rec = dict(payload.get("run") or payload.get("payroll_run") or {
            k: v for k, v in payload.items() if k not in ("items", "replace_existing_run_id")
        })
        replace_id = str(payload.get("replace_existing_run_id") or "").strip()
        rid = str(replace_id or payload.get("payroll_run_id") or run_rec.get("payroll_run_id") or "").strip() or self._alloc_id("PayrollRuns", spec)
        run_rec["payroll_run_id"] = rid
        if replace_id:
            if not self._update_row("PayrollRuns", "payroll_run_id", rid, run_rec):
                self._append_row("PayrollRuns", run_rec)
            # Clear old items for this draft run before appending recalculated items
            old_items = self._load_tab("PayrollItems")
            self._save_tab("PayrollItems", [r for r in old_items if str(r.get("payroll_run_id") or "").strip() != rid])
        else:
            self._append_row("PayrollRuns", run_rec)
        saved_items = []
        for item in (payload.get("items") or []):
            if isinstance(item, dict):
                irow = dict(item)
                irow["payroll_run_id"] = rid
                iid = str(irow.get("item_id") or irow.get("payroll_item_id") or "").strip() or self._alloc_id("PayrollItems", explicit_prefix="PYI")
                irow["item_id"] = iid
                irow["payroll_item_id"] = iid
                self._append_row("PayrollItems", irow)
                saved_items.append(irow)
        return {"allocated_id": rid, "record": run_rec, "data": {"items": saved_items}}

    def _act_update_payroll_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item_upd = dict(payload.get("item_update") or {
            k: v for k, v in payload.items() if k != "run_totals_update"
        })
        iid = str(item_upd.get("item_id") or payload.get("item_id") or "").strip()
        if iid:
            if not self._update_row("PayrollItems", "item_id", iid, item_upd):
                self._update_row("PayrollItems", "payroll_item_id", iid, item_upd)
        run_upd = payload.get("run_totals_update")
        if isinstance(run_upd, dict) and run_upd.get("payroll_run_id"):
            rid = str(run_upd["payroll_run_id"]).strip()
            self._update_row("PayrollRuns", "payroll_run_id", rid, {k: v for k, v in run_upd.items() if k != "payroll_run_id"})
        return {"allocated_id": iid, "record": item_upd}

    def _act_record_workforce_payment(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        pay = dict(payload.get("payment") or {
            k: v for k, v in payload.items()
            if k not in ("receipt", "source_update", "reference_update", "target_update")
        })
        pid = str(payload.get("payment_id") or pay.get("payment_id") or "").strip() or self._alloc_id("WorkforcePayments", spec)
        pay["payment_id"] = pid
        self._append_row("WorkforcePayments", pay)

        rid = ""
        rnum = ""
        rcpt = payload.get("receipt")
        if isinstance(rcpt, dict):
            rrow = dict(rcpt)
            rrow["payment_id"] = pid
            rid = str(rrow.get("receipt_id") or "").strip() or self._alloc_id("SalaryReceipts", explicit_prefix="SRCP")
            rrow["receipt_id"] = rid
            pdate = str(rrow.get("payment_date") or pay.get("payment_date") or now_iso()[:10]).replace("-", "")
            rnum = str(rrow.get("receipt_number") or "").strip() or f"REC-{pdate}-{rid.split('-')[-1]}"
            rrow["receipt_number"] = rnum
            self._append_row("SalaryReceipts", rrow)

        ref_upd = payload.get("source_update") or payload.get("reference_update") or payload.get("target_update")
        if isinstance(ref_upd, dict) and ref_upd.get("tab") and ref_upd.get("key_field") and ref_upd.get("key_value"):
            self._update_row(str(ref_upd["tab"]), str(ref_upd["key_field"]), str(ref_upd["key_value"]), dict(ref_upd.get("updates") or {}))
        return {"allocated_id": pid, "record": {**pay, "receipt_id": rid, "receipt_number": rnum}}

    def _act_bulk_rows(self, target_tab: str, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        bulk = spec.readback.bulk_rows_check
        list_keys = bulk.payload_list_keys if bulk else ("records", "entries", "rows", "attendance")
        rows_to_write = []
        for lk in list_keys:
            val = payload.get(lk)
            if isinstance(val, list):
                rows_to_write.extend(val)
        for item in rows_to_write:
            if isinstance(item, dict):
                row = dict(item)
                if target_tab == "WorkerAttendance" and not row.get("attendance_id"):
                    row["attendance_id"] = self._alloc_id("WorkerAttendance", explicit_prefix="ATT")
                elif target_tab == "LabourAttendance" and not row.get("attendance_id"):
                    row["attendance_id"] = self._alloc_id("LabourAttendance", explicit_prefix="LAT")
                if "attendance_date" not in row and payload.get("attendance_date"):
                    row["attendance_date"] = payload["attendance_date"]
                if "date" not in row and payload.get("date"):
                    row["date"] = payload["date"]
                self._append_row(target_tab, row)
        return {"allocated_id": None, "record": {"count": len(rows_to_write)}}

    def _act_upsert_salary_structure(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        rec = dict(payload.get("salary_structure") or payload.get("structure") or {
            k: v for k, v in payload.items() if k not in ("user_update", "is_update", "update_user_structure_id")
        })
        sid = str(payload.get("structure_id") or rec.get("structure_id") or "").strip() or self._alloc_id("SalaryStructures", spec)
        rec["structure_id"] = sid
        if not self._update_row("SalaryStructures", "structure_id", sid, rec):
            self._append_row("SalaryStructures", rec)
        if isinstance(payload.get("user_update"), dict) and payload["user_update"].get("user_id"):
            uu = payload["user_update"]
            self._update_row("Users", "user_id", str(uu["user_id"]), {k: v for k, v in uu.items() if k != "user_id"})
        elif payload.get("update_user_structure_id") and rec.get("user_id"):
            self._update_row("Users", "user_id", str(rec["user_id"]), {"salary_structure_id": sid})
        return {"allocated_id": sid, "record": rec}

    def _act_review_expense(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        eid = str(payload.get("expense_id") or "").strip()
        updates = {k: v for k, v in payload.items() if k != "expense_id"}
        self._update_row("Expenses", "expense_id", eid, updates)
        return {"allocated_id": eid, "record": {"expense_id": eid, **updates}}

    def _act_submit_daily_closing(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        exp_ids = payload.get("qualifying_expense_ids") or []
        if exp_ids:
            fail_exp = self._check_injected_failure("Expenses")
            if fail_exp:
                raise RuntimeError(fail_exp)
        rec = dict(payload.get("closing") or {
            k: v for k, v in payload.items() if k not in ("expense_updates", "qualifying_expense_ids")
        })
        cid = str(payload.get("closing_id") or rec.get("closing_id") or "").strip() or self._alloc_id("DailyClosing", spec)
        rec["closing_id"] = cid
        self._append_row("DailyClosing", rec)
        for eid in exp_ids:
            self._update_row("Expenses", "expense_id", str(eid), {"related_closing_id": cid})
        return {"allocated_id": cid, "record": rec}

    def _act_create_product_lot(self, payload: Dict[str, Any], spec: GovernedActionSpec) -> Dict[str, Any]:
        lot = dict(payload.get("lot") or {k: v for k, v in payload.items() if k != "movement"})
        lid = str(payload.get("lot_id") or lot.get("lot_id") or "").strip() or self._alloc_id("ProductLots", spec)
        lot["lot_id"] = lid
        self._append_row("ProductLots", lot)
        if isinstance(payload.get("movement"), dict):
            m = dict(payload["movement"])
            m["lot_id"] = lid
            m["lot_movement_id"] = str(m.get("lot_movement_id") or "").strip() or self._alloc_id("LotMovements", explicit_prefix="LMV")
            self._append_row("LotMovements", m)
        return {"allocated_id": lid, "record": lot}

    def _act_update_lot_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        lid = str(payload.get("lot_id") or "").strip()
        updates = {k: v for k, v in payload.items() if k not in ("lot_id", "movement")}
        self._update_row("ProductLots", "lot_id", lid, updates)
        if isinstance(payload.get("movement"), dict):
            m = dict(payload["movement"])
            m["lot_id"] = lid
            m["lot_movement_id"] = str(m.get("lot_movement_id") or "").strip() or self._alloc_id("LotMovements", explicit_prefix="LMV")
            self._append_row("LotMovements", m)
        return {"allocated_id": lid, "record": {"lot_id": lid, **updates}}

    def _act_update_ca_policy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = str(payload.get("setting_key") or "").strip()
        rec = dict(payload)
        if not self._update_row("Settings", "setting_key", key, rec):
            self._append_row("Settings", rec)
        return {"allocated_id": key, "record": rec}

    def _act_generic(
        self,
        action: str,
        target_tab: str,
        payload: Dict[str, Any],
        spec: GovernedActionSpec,
    ) -> Dict[str, Any]:
        id_field = spec.id_field
        if isinstance(payload.get("record"), dict):
            rec = dict(payload["record"])
        elif isinstance(payload.get("updates"), dict):
            rec = {k: v for k, v in payload.items() if k != "updates"}
            rec.update(payload["updates"])
        else:
            rec = dict(payload)

        # Deletion / soft-deletion actions
        if spec.readback.expect_absent or spec.readback.expect_absent_or_soft_deleted:
            key_val = str(rec.get(id_field) or payload.get(id_field) or "").strip() if id_field else ""
            if id_field and key_val:
                self._delete_row(target_tab, id_field, key_val)
            elif spec.readback.primary_match_fields:
                rows = self._load_tab(target_tab)
                criteria = [
                    (f, str(rec.get(f) or payload.get(f) or "").strip())
                    for f in spec.readback.primary_match_fields
                    if str(rec.get(f) or payload.get(f) or "").strip()
                ]
                if criteria:
                    new_rows = [
                        r for r in rows
                        if not all(str(r.get(k, "")).strip() == v for k, v in criteria)
                    ]
                    self._save_tab(target_tab, new_rows)
            return {"allocated_id": key_val or None, "record": None}

        # Create actions requiring allocated ID
        if spec.requires_allocated_id:
            alloc_id = str(rec.get(id_field) or payload.get(id_field) or "").strip() if id_field else ""
            if not alloc_id:
                alloc_id = self._alloc_id(target_tab, spec)
            if id_field:
                rec[id_field] = alloc_id
            self._append_row(target_tab, rec)
            return {"allocated_id": alloc_id, "record": rec}

        # Update / upsert actions
        if id_field:
            key_val = str(rec.get(id_field) or payload.get(id_field) or "").strip()
            if key_val:
                if not self._update_row(target_tab, id_field, key_val, rec):
                    rec[id_field] = key_val
                    self._append_row(target_tab, rec)
                return {"allocated_id": key_val, "record": rec}

        # Fallback: match by primary_match_fields or append
        if spec.readback.primary_match_fields:
            criteria = [
                (f, str(rec.get(f) or payload.get(f) or "").strip())
                for f in spec.readback.primary_match_fields
                if str(rec.get(f) or payload.get(f) or "").strip()
            ]
            if criteria:
                rows = self._load_tab(target_tab)
                matched = False
                for r in rows:
                    if all(str(r.get(k, "")).strip() == v for k, v in criteria):
                        r.update(rec)
                        matched = True
                        break
                if not matched:
                    rows.append(rec)
                self._save_tab(target_tab, rows)
                return {"allocated_id": None, "record": rec}

        self._append_row(target_tab, rec)
        return {"allocated_id": None, "record": rec}


class _SimRejectError(Exception):
    def __init__(self, error_code: str, message: str, http_status: int = 409, retryable: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
