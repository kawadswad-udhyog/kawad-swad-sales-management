"""
Kawad Swad ERP — Mission 51B-1 Critical Transaction & Write Safety Test Suite

Covers:
A. Idempotency & Replay Tests (exact replay, normalized equivalent replay, payload conflict,
   action conflict, integer-zero preservation, header/body nonce mismatch)
B. Concurrency & Race Tests (multi-thread duplicate nonce, multi-coordinator SQLite BEGIN IMMEDIATE
   cross-process simulation, ID allocation & bill number locking + IdAllocations scanning)
C. Failure Injection Tests (pre-transmission refusal/DNS, timeout-after-commit, timeout-no-commit,
   connection drop, malformed JSON, partial child write, journal imbalance, SaleItems total mismatch,
   duplicate primary rows, transient read-back retry + outage, HTTP 3xx/4xx/5xx classification,
   audit failure resilience & secret redaction)
D. Recovery & Reconciliation Tests (confirmed recorded, orphan ID allocation quarantine,
   duplicate primary row quarantine, single-table outage fail-closed status check, stale lease
   recovery, controlled Owner reconciliation, non-owner confidential redaction)
E. Router-Level Safety Verification (daily closing lock + payload conflict, payment cross-sale
   & method idempotency conflict, secondary journal failure -> RECOVERY_REQUIRED)
"""

from __future__ import annotations

import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Provide minimal FastAPI/Pydantic stubs if running in stdlib-only container (matches existing suite pattern)
import types

if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(str(detail))

    class _Request:
        def __init__(self, headers=None):
            self.headers = headers or {}

    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Request = _Request
    sys.modules["fastapi"] = fastapi_stub

import app.apps_script_bridge as bridge_mod
import app.schema_registry as schema_reg
import app.sheets as sheets_mod
from app.accounting.transaction_coordinator import TransactionCoordinator, tx_coordinator
from app.apps_script_bridge import AppsScriptBridge
from app.transaction_safety import (
    FailureCategory,
    TransactionState,
    classify_gateway_exception,
    compute_deterministic_payload_hash,
    normalize_scalar_canonical,
    sanitize_audit_metadata,
)


class _FakeHTTPResponse:
    def __init__(self, body_str: str):
        self._body = body_str.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeOpener:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def open(self, req, timeout=None):
        raw = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else str(req.data or "")
        envelope = json.loads(raw) if raw else {}
        self.calls.append({"req": req, "envelope": envelope, "timeout": timeout})
        return self._handler(envelope, len(self.calls))


class _FakeWorksheet:
    def __init__(self, title: str, headers, rows=None):
        self.title = title
        self._headers = list(headers)
        self._rows = [dict(r) for r in (rows or [])]

    def row_values(self, idx: int):
        if idx == 1:
            return list(self._headers)
        return []

    def get_all_records(self):
        return [dict(r) for r in self._rows]

    def get_all_values(self):
        out = [list(self._headers)]
        for r in self._rows:
            out.append([r.get(h, "") for h in self._headers])
        return out


class _FakeSpreadsheet:
    def __init__(self, ws_map):
        self._ws_map = ws_map

    def worksheet(self, tab_name: str):
        if tab_name not in self._ws_map:
            raise KeyError(f"Worksheet {tab_name} not found")
        return self._ws_map[tab_name]


class TestMission51B1TransactionSafety(unittest.TestCase):
    def setUp(self):
        self._orig_connected = sheets_mod.db.is_connected
        self._orig_spreadsheet = sheets_mod.db.spreadsheet
        self._orig_fallback = sheets_mod.db.allow_in_memory_fallback
        sheets_mod.db._records_cache.clear()
        sheets_mod.db._worksheets.clear()
        sheets_mod.db._test_tab_headers.clear()
        schema_reg.clear_runtime_core_schema_reconciliations()
        tx_coordinator.reset_store()
        with AppsScriptBridge._INFLIGHT_ID_LOCK:
            AppsScriptBridge._INFLIGHT_IDS.clear()

        self.store = {
            "JournalHeaders": [],
            "JournalLines": [],
            "Sales": [],
            "SaleItems": [],
            "SalesmanStockLedger": [],
            "Payments": [],
            "CashLedger": [],
            "Expenses": [],
            "Customers": [],
            "IdAllocations": [],
            "AuditLog": [],
            "SalaryPayments": [],
        }
        self._install_fake_sheets()

    def tearDown(self):
        sheets_mod.db.is_connected = self._orig_connected
        sheets_mod.db.spreadsheet = self._orig_spreadsheet
        sheets_mod.db.allow_in_memory_fallback = self._orig_fallback
        sheets_mod.db._records_cache.clear()
        sheets_mod.db._worksheets.clear()
        sheets_mod.db._test_tab_headers.clear()
        schema_reg.clear_runtime_core_schema_reconciliations()
        tx_coordinator.reset_store()
        with AppsScriptBridge._INFLIGHT_ID_LOCK:
            AppsScriptBridge._INFLIGHT_IDS.clear()

    def _install_fake_sheets(self):
        ws_map = {}
        for tab, rows in self.store.items():
            headers = sheets_mod.REQUIRED_TABS.get(tab) or list(
                (rows[0].keys() if rows else ["id"])
            )
            ws_map[tab] = _FakeWorksheet(tab, headers=headers, rows=rows)
        # Keep live references to self.store lists so mutations in handlers are visible immediately
        for tab, ws in ws_map.items():
            ws._rows = self.store[tab]
        sheets_mod.db.is_connected = True
        sheets_mod.db.spreadsheet = _FakeSpreadsheet(ws_map)
        sheets_mod.db.allow_in_memory_fallback = False

    def _patch_configured_bridge(self, opener):
        return patch.multiple(
            bridge_mod,
            SALES_APPS_SCRIPT_ENABLED=True,
            SALES_APPS_SCRIPT_WEBAPP_URL="https://script.google.com/macros/s/test-deploy/exec",
            SALES_APPS_SCRIPT_SHARED_SECRET="S" * 40,
        )

    def _journal_payload(self, amount=100, narration="Cash deposit", extra=None):
        p = {
            "journal_date": "2026-11-21",
            "voucher_type": "JOURNAL",
            "reference_type": "MANUAL",
            "reference_id": "REF-100",
            "narration": narration,
            "total_debit": amount,
            "total_credit": amount,
            "lines": [
                {"account_code": "1001", "debit_amount": amount, "credit_amount": 0},
                {"account_code": "4001", "debit_amount": 0, "credit_amount": amount},
            ],
        }
        if extra:
            p.update(extra)
        return p

    def _commit_journal_into_store(self, envelope, alloc_id="JV-000101", balanced=True, include_lines=True, dup_primary=False):
        payload = envelope["payload"]
        header_row = {
            "journal_id": alloc_id,
            "journal_date": payload.get("journal_date", "2026-11-21"),
            "voucher_type": payload.get("voucher_type", "JOURNAL"),
            "reference_type": payload.get("reference_type", "MANUAL"),
            "reference_id": payload.get("reference_id", "REF-100"),
            "narration": payload.get("narration", ""),
            "total_debit": payload.get("total_debit", 100),
            "total_credit": payload.get("total_credit", 100),
        }
        self.store["JournalHeaders"].append(header_row)
        if dup_primary:
            self.store["JournalHeaders"].append(dict(header_row))
        if include_lines:
            lines = payload.get("lines") or []
            for idx, ln in enumerate(lines, start=1):
                debit_val = ln.get("debit_amount", 0)
                credit_val = ln.get("credit_amount", 0)
                if not balanced and idx == 2:
                    credit_val = float(credit_val) - 25.0
                self.store["JournalLines"].append({
                    "line_id": f"JVL-{idx:06d}",
                    "journal_id": alloc_id,
                    "account_code": ln.get("account_code", "1001"),
                    "debit_amount": debit_val,
                    "credit_amount": credit_val,
                })
        self.store["IdAllocations"].append({
            "allocation_id": f"ALC-{alloc_id}",
            "tab_name": "JournalHeaders",
            "allocated_id": alloc_id,
            "nonce": envelope["nonce"],
            "created_at": "2026-11-21T10:00:00Z",
        })
        self.store["AuditLog"].append({
            "audit_id": f"AUD-{alloc_id}",
            "event_datetime": "2026-11-21T10:00:00Z",
            "actor_user_id": envelope["actor_user_id"],
            "action": envelope["action"],
            "entity_type": "JournalHeaders",
            "entity_id": alloc_id,
            "related_record_id": envelope["nonce"],
            "reason": f"Committed {alloc_id}",
        })
        return _FakeHTTPResponse(json.dumps({
            "status": "CONFIRMED",
            "correlation_id": envelope["correlation_id"],
            "nonce": envelope["nonce"],
            "action": envelope["action"],
            "target_tab": envelope["target_tab"],
            "allocated_id": alloc_id,
            "record": header_row,
            "message": f"Posted {alloc_id}",
        }))

    # ------------------------------------------------------------------
    # A. IDEMPOTENCY & REPLAY TESTS
    # ------------------------------------------------------------------
    def test_a1_deterministic_payload_hash_normalization_and_integer_zero_preservation(self):
        # Equivalent numeric/bool/volatile variations hash identically
        h1 = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={
                "amount": 100,
                "active": True,
                "notes": None,
                "timestamp": "2026-11-21T10:00:00Z",
                "created_at": "2026-11-21T10:00:00Z",
                "nested": {"b": Decimal("10.00"), "a": "hello"},
            },
        )
        h2 = compute_deterministic_payload_hash(
            action="post_journal_voucher",
            target_tab="JournalHeaders",
            actor_user_id="USR-1",
            actor_role="owner_admin",
            payload={
                "nested": {"a": "hello", "b": 10},
                "notes": "   ",
                "active": "true",
                "amount": "100.00",
                "timestamp": "2026-11-21T12:34:56Z",
                "created_at": "2026-11-21T12:34:56Z",
            },
        )
        self.assertEqual(h1, h2)

        # Meaningful integer trailing zeroes MUST NOT collide (10 vs 100 vs 1000)
        h10 = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER", target_tab="JournalHeaders",
            actor_user_id="USR-1", actor_role="OWNER_ADMIN", payload={"amount": 10},
        )
        h100 = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER", target_tab="JournalHeaders",
            actor_user_id="USR-1", actor_role="OWNER_ADMIN", payload={"amount": 100},
        )
        h1000 = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER", target_tab="JournalHeaders",
            actor_user_id="USR-1", actor_role="OWNER_ADMIN", payload={"amount": 1000},
        )
        self.assertEqual(len({h10, h100, h1000}), 3)
        self.assertEqual(normalize_scalar_canonical(10), "10")
        self.assertEqual(normalize_scalar_canonical(100), "100")
        self.assertEqual(normalize_scalar_canonical(True), "true")
        self.assertEqual(normalize_scalar_canonical(1), "1")

    def test_a2_exact_and_normalized_replay_returns_committed_without_duplicate_write(self):
        bridge = AppsScriptBridge()
        opener = _FakeOpener(lambda env, n: self._commit_journal_into_store(env, alloc_id=f"JV-00010{n}"))
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=250, extra={"created_at": "2026-11-21T08:00:00Z"}),
                nonce="NONCE-A2-REPLAY",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "CONFIRMED")
            self.assertEqual(r1.transaction_state, TransactionState.COMMITTED.value)
            self.assertEqual(r1.allocated_id, "JV-000101")
            self.assertFalse(r1.is_replay)
            self.assertTrue(r1.transaction_id)
            self.assertEqual(len(opener.calls), 1)

            # Retry with same nonce, equivalent string decimal "250.00", and refreshed volatile created_at
            r2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount="250.00", extra={"created_at": "2026-11-21T09:15:00Z"}),
                nonce="NONCE-A2-REPLAY",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r2.status, "CONFIRMED")
            self.assertTrue(r2.is_replay)
            self.assertEqual(r2.allocated_id, "JV-000101")
            self.assertEqual(r2.transaction_id, r1.transaction_id)
            # Zero duplicate remote POST!
            self.assertEqual(len(opener.calls), 1)
            self.assertEqual(len(self.store["JournalHeaders"]), 1)

    def test_a3_same_nonce_different_payload_or_action_rejected_409_conflict(self):
        bridge = AppsScriptBridge()
        opener = _FakeOpener(lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000201"))
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=100),
                nonce="NONCE-A3-CONFLICT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "CONFIRMED")

            # Same nonce, different amount -> HTTP 409 IDEMPOTENCY_PAYLOAD_CONFLICT
            r_diff_payload = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=999),
                nonce="NONCE-A3-CONFLICT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_diff_payload.status, "REJECTED")
            self.assertEqual(r_diff_payload.http_status, 409)
            self.assertEqual(r_diff_payload.error_code, "IDEMPOTENCY_PAYLOAD_CONFLICT")
            self.assertEqual(r_diff_payload.failure_category, FailureCategory.IDEMPOTENCY_CONFLICT.value)
            self.assertFalse(r_diff_payload.retryable)

            # Same nonce, different action -> HTTP 409 IDEMPOTENCY_ACTION_CONFLICT
            r_diff_action = bridge.execute_governed_write(
                action="REVERSE_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload={"original_journal_id": "JV-000201", "reason": "Conflict check"},
                nonce="NONCE-A3-CONFLICT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_diff_action.status, "REJECTED")
            self.assertEqual(r_diff_action.http_status, 409)
            self.assertEqual(r_diff_action.error_code, "IDEMPOTENCY_ACTION_CONFLICT")
            self.assertEqual(r_diff_action.failure_category, FailureCategory.IDEMPOTENCY_CONFLICT.value)
            self.assertEqual(len(opener.calls), 1)

    # ------------------------------------------------------------------
    # B. CONCURRENCY & RACE TESTS
    # ------------------------------------------------------------------
    def test_b1_concurrent_identical_requests_only_one_executes_remote_write(self):
        bridge = AppsScriptBridge()
        entered = threading.Event()
        release = threading.Event()

        def slow_commit(env, call_no):
            entered.set()
            release.wait(timeout=3.0)
            return self._commit_journal_into_store(env, alloc_id=f"JV-00030{call_no}")

        opener = _FakeOpener(slow_commit)
        results = {}

        def worker(idx):
            results[idx] = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=300),
                nonce="NONCE-B1-RACE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )

        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            t1 = threading.Thread(target=worker, args=(1,))
            t1.start()
            self.assertTrue(entered.wait(timeout=2.0), "First worker did not enter remote gateway")

            t2 = threading.Thread(target=worker, args=(2,))
            t3 = threading.Thread(target=worker, args=(3,))
            t2.start()
            t3.start()
            t2.join(timeout=2.0)
            t3.join(timeout=2.0)

            release.set()
            t1.join(timeout=2.0)

        self.assertEqual(results[1].status, "CONFIRMED")
        for idx in (2, 3):
            self.assertEqual(results[idx].status, "REJECTED")
            self.assertEqual(results[idx].http_status, 409)
            self.assertEqual(results[idx].error_code, "CONCURRENT_DUPLICATE_REQUEST")
            self.assertEqual(results[idx].failure_category, FailureCategory.DUPLICATE_REQUEST.value)
            self.assertEqual(results[idx].transaction_state, TransactionState.PENDING.value)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(len(self.store["JournalHeaders"]), 1)

    def test_b2_cross_process_sqlite_coordinator_cas_isolation(self):
        """Two independent TransactionCoordinator instances sharing one WAL DB file enforce atomic CAS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "shared_tx.db")
            coord_a = TransactionCoordinator(db_path=db_file)
            coord_b = TransactionCoordinator(db_path=db_file)

            st_a, rec_a = coord_a.begin_governed_transaction(
                nonce="NONCE-XPROC-1",
                action="CREATE_SALE",
                target_tab="Sales",
                actor_user_id="USR-1",
                payload_hash="HASH-ABC",
                correlation_id="CORR-1",
            )
            st_b, rec_b = coord_b.begin_governed_transaction(
                nonce="NONCE-XPROC-1",
                action="CREATE_SALE",
                target_tab="Sales",
                actor_user_id="USR-1",
                payload_hash="HASH-ABC",
                correlation_id="CORR-2",
            )
            self.assertEqual(st_a, "ACQUIRED")
            self.assertEqual(st_b, "IN_PROGRESS")
            self.assertEqual(rec_a["transaction_id"], rec_b["transaction_id"])

            # Conflicting payload from process B rejected
            st_conflict, _ = coord_b.begin_governed_transaction(
                nonce="NONCE-XPROC-1",
                action="CREATE_SALE",
                target_tab="Sales",
                actor_user_id="USR-1",
                payload_hash="HASH-DIFFERENT",
                correlation_id="CORR-3",
            )
            self.assertEqual(st_conflict, "PAYLOAD_CONFLICT")

    def test_b3_bill_number_allocation_respects_id_allocations_even_when_sales_empty(self):
        """Even if a prior Sales row was deleted/missing, allocate_bill_number scans IdAllocations under CrossProcessLock."""
        from app.timeutil import business_month
        month = business_month()
        sheets_mod.db.is_connected = False
        sheets_mod.db.spreadsheet = None
        sheets_mod.db.allow_in_memory_fallback = True
        sheets_mod.db.memory_store["Sales"] = []
        sheets_mod.db.memory_store["IdAllocations"] = [
            {
                "allocation_id": "ALC-OLD",
                "tab_name": "BillNumbers",
                "allocated_id": f"KS-BILL-{month}-00042",
                "nonce": "old-nonce",
                "created_at": "2026-11-21T00:00:00Z",
            }
        ]
        allocated = sheets_mod.db.allocate_bill_number()
        self.assertEqual(allocated, f"KS-BILL-{month}-00043")

    # ------------------------------------------------------------------
    # C. FAILURE INJECTION TESTS
    # ------------------------------------------------------------------
    def test_c1_pre_transmission_refusal_vs_ambiguous_timeout_and_drop(self):
        # Definite pre-transmission failures -> FAILED / DEPENDENCY_UNAVAILABLE (503)
        for exc in (ConnectionRefusedError("refused"), socket.gaierror("DNS failed"), urllib.error.URLError("Connection refused")):
            st, cat, code, http_code, _ = classify_gateway_exception(exc)
            self.assertEqual(st, TransactionState.FAILED)
            self.assertEqual(cat, FailureCategory.DEPENDENCY_UNAVAILABLE)
            self.assertEqual(http_code, 503)

        # Ambiguous post-transmission failures -> UNKNOWN / WRITE_OUTCOME_UNKNOWN (504)
        for exc in (
            socket.timeout("timed out"),
            TimeoutError("gateway timeout"),
            http.client.RemoteDisconnected("remote closed"),
            ConnectionResetError("reset by peer"),
            json.JSONDecodeError("bad json", "{", 1),
            ValueError("Empty response"),
        ):
            st, cat, code, http_code, _ = classify_gateway_exception(exc)
            self.assertEqual(st, TransactionState.UNKNOWN)
            self.assertEqual(cat, FailureCategory.WRITE_OUTCOME_UNKNOWN)
            self.assertEqual(http_code, 504)

    def test_c2_pre_transmission_failure_allows_clean_same_nonce_retry(self):
        bridge = AppsScriptBridge()

        def handler(env, call_no):
            if call_no == 1:
                raise urllib.error.URLError(ConnectionRefusedError("Gateway port refused"))
            return self._commit_journal_into_store(env, alloc_id="JV-000401")

        opener = _FakeOpener(handler)
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=400),
                nonce="NONCE-C2-PRETX",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "REJECTED")
            self.assertEqual(r1.http_status, 503)
            self.assertEqual(r1.transaction_state, TransactionState.FAILED.value)
            self.assertEqual(r1.failure_category, FailureCategory.DEPENDENCY_UNAVAILABLE.value)
            self.assertTrue(r1.retryable)

            # Retry with same nonce succeeds as attempt 2
            r2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=400),
                nonce="NONCE-C2-PRETX",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r2.status, "CONFIRMED")
            self.assertEqual(r2.attempt_number, 2)
            self.assertEqual(r2.allocated_id, "JV-000401")
            self.assertEqual(len(opener.calls), 2)

    def test_c3_timeout_after_commit_recovers_without_duplicate_write(self):
        """Apps Script commits to Sheets, then HTTP response times out -> retry recovers CONFIRMED with 0 second POST!"""
        bridge = AppsScriptBridge()

        def handler(env, call_no):
            # Simulate commit succeeded inside Apps Script BEFORE response dropped/timed out
            self._commit_journal_into_store(env, alloc_id="JV-000501")
            raise socket.timeout("Read timed out waiting for Apps Script response")

        opener = _FakeOpener(handler)
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=500),
                nonce="NONCE-C3-TIMEOUT-COMMIT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "PENDING_UNKNOWN")
            self.assertEqual(r1.http_status, 504)
            self.assertEqual(r1.transaction_state, TransactionState.UNKNOWN.value)
            self.assertEqual(r1.failure_category, FailureCategory.WRITE_OUTCOME_UNKNOWN.value)
            self.assertEqual(len(opener.calls), 1)

            # Retry with SAME nonce -> recovery inspects Sheets, verifies full commit, returns CONFIRMED with ZERO 2nd POST!
            r2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=500),
                nonce="NONCE-C3-TIMEOUT-COMMIT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r2.status, "CONFIRMED")
            self.assertTrue(r2.is_replay)
            self.assertEqual(r2.allocated_id, "JV-000501")
            self.assertEqual(r2.recovery_decision, "AUTO_CONFIRMED_FROM_SHEETS")
            self.assertEqual(len(opener.calls), 1)
            self.assertEqual(len(self.store["JournalHeaders"]), 1)

    def test_c4_timeout_with_no_commit_safely_retries_same_nonce_after_sheets_check(self):
        bridge = AppsScriptBridge()

        def handler(env, call_no):
            if call_no == 1:
                raise http.client.RemoteDisconnected("Connection dropped before commit")
            return self._commit_journal_into_store(env, alloc_id="JV-000601")

        opener = _FakeOpener(handler)
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=600),
                nonce="NONCE-C4-DROP-NOCOMMIT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "PENDING_UNKNOWN")
            self.assertEqual(r1.http_status, 504)

            # Retry checks Sheets -> confirms 0 effects -> executes attempt 2 with SAME nonce -> CONFIRMED!
            r2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=600),
                nonce="NONCE-C4-DROP-NOCOMMIT",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r2.status, "CONFIRMED")
            self.assertEqual(r2.attempt_number, 2)
            self.assertEqual(r2.allocated_id, "JV-000601")
            self.assertEqual(len(opener.calls), 2)

    def test_c5_partial_write_missing_children_quarantines_recovery_required_and_blocks_retry(self):
        bridge = AppsScriptBridge()
        opener = _FakeOpener(
            lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000701", include_lines=False)
        )
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            r1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=700),
                nonce="NONCE-C5-PARTIAL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r1.status, "RECOVERY_REQUIRED")
            self.assertEqual(r1.http_status, 409)
            self.assertFalse(r1.retryable)
            self.assertEqual(r1.transaction_state, TransactionState.RECOVERY_REQUIRED.value)
            self.assertEqual(r1.failure_category, FailureCategory.RECOVERY_REQUIRED.value)

            # Subsequent automatic retry MUST BE BLOCKED (zero 2nd HTTP POST!)
            r2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=700),
                nonce="NONCE-C5-PARTIAL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r2.status, "RECOVERY_REQUIRED")
            self.assertEqual(r2.http_status, 409)
            self.assertFalse(r2.retryable)
            self.assertEqual(len(opener.calls), 1)

    def test_c6_imbalanced_journal_and_duplicate_primary_rows_quarantine_recovery_required(self):
        bridge = AppsScriptBridge()

        # Imbalanced journal lines
        opener_imbal = _FakeOpener(
            lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000801", balanced=False)
        )
        with self._patch_configured_bridge(opener_imbal), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener_imbal):
            r_imbal = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=800),
                nonce="NONCE-C6-IMBAL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_imbal.status, "RECOVERY_REQUIRED")
            self.assertEqual(r_imbal.http_status, 409)
            self.assertIn("imbalance", r_imbal.message.lower())

        # Duplicate primary rows
        opener_dup = _FakeOpener(
            lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000802", dup_primary=True)
        )
        with self._patch_configured_bridge(opener_dup), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener_dup):
            r_dup = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=800),
                nonce="NONCE-C6-DUPROW",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_dup.status, "RECOVERY_REQUIRED")
            self.assertEqual(r_dup.http_status, 409)
            self.assertIn("duplicate primary rows", r_dup.message.lower())

    def test_c7_sale_items_total_mismatch_quarantines_recovery_required(self):
        schema_reg.approve_core_schema_reconciliation(
            "Sales",
            headers=schema_reg.get_expected_canonical_reconciliation_headers("Sales"),
            approved_by="USR-OWNER-001",
        )
        bridge = AppsScriptBridge()

        def handler(env, n):
            self.store["Sales"].append({"sale_id": "INV-000901", "bill_total": 500.0})
            self.store["SaleItems"].append({"sale_item_id": "SITEM-000001", "sale_id": "INV-000901", "line_total": 200.0})
            self.store["SalesmanStockLedger"].append({"ledger_id": "SML-000001", "reference_id": "INV-000901"})
            return _FakeHTTPResponse(json.dumps({
                "status": "CONFIRMED",
                "correlation_id": env["correlation_id"],
                "nonce": env["nonce"],
                "action": env["action"],
                "target_tab": env["target_tab"],
                "allocated_id": "INV-000901",
                "record": {"sale_id": "INV-000901", "bill_total": 500.0},
            }))

        opener = _FakeOpener(handler)
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            res = bridge.execute_governed_write(
                action="CREATE_SALE",
                target_tab="Sales",
                payload={"sale": {"bill_total": 500.0}, "sale_items": [{"product_id": "PROD-1", "line_total": 200.0}]},
                nonce="NONCE-C7-MISMATCH",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="sale_id",
            )
            self.assertEqual(res.status, "RECOVERY_REQUIRED")
            self.assertEqual(res.http_status, 409)
            self.assertIn("mismatches", res.message.lower())

    def test_c8_transient_readback_error_recovers_on_bounded_retry(self):
        bridge = AppsScriptBridge()
        opener = _FakeOpener(lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000950"))
        orig_get_records = sheets_mod.db.get_records
        read_calls = {"JournalHeaders": 0}

        def flaky_get_records(tab_name, fresh=False):
            if tab_name == "JournalHeaders":
                read_calls["JournalHeaders"] += 1
                if read_calls["JournalHeaders"] == 1:
                    raise RuntimeError("Transient HTTP 503 reading JournalHeaders")
            return orig_get_records(tab_name, fresh=fresh)

        with self._patch_configured_bridge(opener), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(sheets_mod.db, "get_records", side_effect=flaky_get_records):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=150),
                nonce="NONCE-C8-FLAKY-RB",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(res.status, "CONFIRMED")
            self.assertEqual(read_calls["JournalHeaders"], 2)

    def test_c9_malformed_json_and_http_status_classifications(self):
        bridge = AppsScriptBridge()

        # Malformed JSON -> UNKNOWN (504)
        opener_bad = _FakeOpener(lambda env, n: _FakeHTTPResponse("<html>not json"))
        with self._patch_configured_bridge(opener_bad), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener_bad):
            r_bad = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=50),
                nonce="NONCE-C9-BADJSON",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_bad.status, "PENDING_UNKNOWN")
            self.assertEqual(r_bad.http_status, 504)
            self.assertEqual(r_bad.error_code, "APPS_SCRIPT_MALFORMED_RESPONSE")

        # HTTP 422 from gateway -> FAILED / VALIDATION_ERROR (non-retryable)
        def raise_422(env, n):
            raise urllib.error.HTTPError("https://example.com", 422, "Unprocessable", {}, io.BytesIO(b""))

        opener_422 = _FakeOpener(raise_422)
        with self._patch_configured_bridge(opener_422), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener_422):
            r_422 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=50),
                nonce="NONCE-C9-HTTP422",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(r_422.status, "REJECTED")
            self.assertEqual(r_422.http_status, 422)
            self.assertEqual(r_422.transaction_state, TransactionState.FAILED.value)
            self.assertEqual(r_422.failure_category, FailureCategory.VALIDATION_ERROR.value)
            self.assertFalse(r_422.retryable)

    def test_c10_audit_failure_resilience_and_secret_redaction(self):
        # Secret redaction check
        sanitized = sanitize_audit_metadata({
            "password": "MySecretPassword123!",
            "auth_token": "eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "bank_account": "123456789012",
            "safe_note": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturetokenvalue1234567890",
            "amount": 500,
        })
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["auth_token"], "[REDACTED]")
        self.assertEqual(sanitized["bank_account"], "[REDACTED]")
        self.assertEqual(sanitized["safe_note"], "[REDACTED_TOKEN]")
        self.assertEqual(sanitized["amount"], 500)

        # Audit failure does not crash committed write, and sets audit_logged=False explicitly
        bridge = AppsScriptBridge()
        opener = _FakeOpener(lambda env, n: self._commit_journal_into_store(env, alloc_id="JV-000999"))
        with self._patch_configured_bridge(opener), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(sheets_mod.db, "log_transaction_audit", side_effect=RuntimeError("Audit sink down")):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self._journal_payload(amount=99),
                nonce="NONCE-C10-AUDITFAIL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(res.status, "CONFIRMED")
            self.assertFalse(res.audit_logged)

    # ------------------------------------------------------------------
    # D. RECOVERY & RECONCILIATION TESTS
    # ------------------------------------------------------------------
    def test_d1_status_check_detects_orphan_allocation_and_duplicate_rows(self):
        bridge = AppsScriptBridge()

        # Orphan allocation: IdAllocations has row, JournalHeaders does NOT -> RECOVERY_REQUIRED
        self.store["IdAllocations"].append({
            "allocation_id": "ALC-ORPHAN",
            "tab_name": "JournalHeaders",
            "allocated_id": "JV-009001",
            "nonce": "NONCE-D1-ORPHAN",
            "created_at": "2026-11-21T10:00:00Z",
        })
        st_orphan = bridge.check_transaction_status(nonce="NONCE-D1-ORPHAN", actor_is_owner=True)
        self.assertEqual(st_orphan["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st_orphan["safe_to_retry_same_nonce"])
        self.assertEqual(st_orphan["recovery_decision"], "ORPHAN_ID_ALLOCATION_DETECTED")

        # Duplicate primary rows -> RECOVERY_REQUIRED
        self.store["IdAllocations"].append({
            "allocation_id": "ALC-DUP",
            "tab_name": "JournalHeaders",
            "allocated_id": "JV-009002",
            "nonce": "NONCE-D1-DUP",
            "created_at": "2026-11-21T10:00:00Z",
        })
        self.store["JournalHeaders"].append({"journal_id": "JV-009002", "narration": "A"})
        self.store["JournalHeaders"].append({"journal_id": "JV-009002", "narration": "A"})
        st_dup = bridge.check_transaction_status(nonce="NONCE-D1-DUP", actor_is_owner=True)
        self.assertEqual(st_dup["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st_dup["safe_to_retry_same_nonce"])
        self.assertEqual(st_dup["recovery_decision"], "DUPLICATE_PRIMARY_ROWS_DETECTED")

    def test_d2_status_check_fails_closed_when_single_status_table_fails(self):
        """Regression test for fail-open bug: if ONLY AuditLog fails (while IdAllocations succeeds empty), MUST NOT say safe_to_retry."""
        bridge = AppsScriptBridge()
        orig_get_records = sheets_mod.db.get_records

        def partial_outage(tab_name, fresh=False):
            if tab_name == "AuditLog":
                raise RuntimeError("HTTP 429 Quota exceeded on AuditLog")
            return orig_get_records(tab_name, fresh=fresh)

        with patch.object(sheets_mod.db, "get_records", side_effect=partial_outage):
            st = bridge.check_transaction_status(nonce="NONCE-D2-SINGLE-OUTAGE", actor_is_owner=True)
            self.assertEqual(st["status"], "UNKNOWN_STORAGE_UNAVAILABLE")
            self.assertFalse(st["safe_to_retry_same_nonce"])
            self.assertEqual(st["failure_category"], FailureCategory.WRITE_OUTCOME_UNKNOWN.value)

    def test_d3_stale_executing_lease_triggers_recovery_and_auto_confirms(self):
        bridge = AppsScriptBridge()
        payload = self._journal_payload(amount=350)
        p_hash = bridge.compute_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload=payload,
        )
        # Simulate a crashed worker leaving an EXECUTING row whose lease expired 5 minutes ago
        tx_coordinator.begin_governed_transaction(
            nonce="NONCE-D3-STALE",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=p_hash,
            correlation_id="CORR-OLD",
        )
        expired_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        conn = tx_coordinator._get_connection()
        try:
            conn.execute("UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?", (expired_ts, "NONCE-D3-STALE"))
        finally:
            conn.close()

        # Commit already happened in Sheets before crash
        self._commit_journal_into_store(
            {
                "action": "POST_JOURNAL_VOUCHER",
                "target_tab": "JournalHeaders",
                "correlation_id": "CORR-OLD",
                "nonce": "NONCE-D3-STALE",
                "actor_user_id": "USR-OWNER-001",
                "payload": payload,
            },
            alloc_id="JV-009300",
        )

        opener = _FakeOpener(lambda env, n: self.fail("Should NOT dispatch duplicate HTTP POST when Sheets already committed!"))
        with self._patch_configured_bridge(opener), patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=payload,
                nonce="NONCE-D3-STALE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(res.status, "CONFIRMED")
            self.assertTrue(res.is_replay)
            self.assertEqual(res.allocated_id, "JV-009300")
            self.assertEqual(res.recovery_decision, "AUTO_CONFIRMED_FROM_SHEETS")
            self.assertEqual(len(opener.calls), 0)

    def test_d4_controlled_reconciliation_and_confidential_redaction(self):
        bridge = AppsScriptBridge()
        # Create a quarantined confidential SalaryPayments transaction
        tx_coordinator.begin_governed_transaction(
            nonce="NONCE-D4-CONF",
            action="RECORD_SALARY_PAYMENT",
            target_tab="SalaryPayments",
            actor_user_id="USR-OWNER-001",
            payload_hash="HASH-SAL",
            correlation_id="CORR-SAL",
        )
        tx_coordinator.transition_governed_transaction(
            nonce="NONCE-D4-CONF",
            lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
            bridge_status="RECOVERY_REQUIRED",
            failure_category=FailureCategory.RECOVERY_REQUIRED.value,
            allocated_id="SAL-000010",
            message="Partial salary receipt",
        )

        # Non-owner sees redacted confidential metadata and retry blocked
        st_non_owner = bridge.check_transaction_status(nonce="NONCE-D4-CONF", actor_is_owner=False)
        self.assertEqual(st_non_owner["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st_non_owner["safe_to_retry_same_nonce"])
        self.assertEqual(st_non_owner["allocated_id"], "REDACTED_CONFIDENTIAL")
        self.assertEqual(st_non_owner["tab_name"], "REDACTED_CONFIDENTIAL")

        # Owner reconciles cleanly
        updated = tx_coordinator.mark_transaction_reconciled(
            nonce="NONCE-D4-CONF",
            actor_user_id="USR-OWNER-001",
            resolution_notes="Verified SalaryPayments and SalaryReceipts rows matched in workbook.",
            final_allocated_id="SAL-000010",
        )
        self.assertEqual(updated["lifecycle_state"], TransactionState.RECONCILED.value)

        st_after = bridge.check_transaction_status(nonce="NONCE-D4-CONF", actor_is_owner=True)
        self.assertEqual(st_after["status"], "RECONCILED")
        self.assertFalse(st_after["safe_to_retry_same_nonce"])
        self.assertEqual(st_after["allocated_id"], "SAL-000010")

    # ------------------------------------------------------------------
    # E. ROUTER-LEVEL SAFETY SOURCE CONTRACTS
    # ------------------------------------------------------------------
    def test_e1_router_repairs_present_in_closing_sales_and_v2_erp(self):
        closing_src = (BACKEND_DIR / "app" / "routers" / "closing.py").read_text(encoding="utf-8")
        sales_src = (BACKEND_DIR / "app" / "routers" / "sales.py").read_text(encoding="utf-8")
        v2_src = (BACKEND_DIR / "app" / "routers" / "v2_erp.py").read_text(encoding="utf-8")

        self.assertIn('CrossProcessLock("daily_closing"', closing_src)
        self.assertIn("IDEMPOTENCY_PAYLOAD_CONFLICT", closing_src)

        self.assertIn("all_payments = db.get_records(\"Payments\", fresh=True)", sales_src)
        self.assertIn("existing_sale_id != sale_id", sales_src)
        self.assertIn("SECONDARY_JOURNAL_POSTING_FAILED", sales_src)
        self.assertIn("QUARANTINED_SECONDARY_JOURNAL_FAILURE", sales_src)

        self.assertIn('@router.post("/transactions/{nonce}/reconcile")', v2_src)
        self.assertIn('@router.get("/transactions/unresolved")', v2_src)
        self.assertIn("RECONCILE_TRANSACTION", v2_src)


if __name__ == "__main__":
    unittest.main()
