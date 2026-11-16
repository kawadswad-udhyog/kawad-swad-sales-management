"""Tests for non-blocking Uvicorn port binding, finite gspread timeouts, safe worksheet discovery, fail-closed persistence, and bounded reconnection."""
import os

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # noqa: F401 - ensures stdlib stubs are active when fastapi is absent
import asyncio
from contextlib import contextmanager
import importlib.util
import json
import socket
import subprocess
import threading
import time
import types
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

import app.config as config_mod
import app.sheets as sheets_mod
from app.sheets import DEFAULT_GSPREAD_TIMEOUT, REQUIRED_TABS, SheetsDatabase


def _has_real_uvicorn_and_fastapi() -> bool:
    return importlib.util.find_spec("uvicorn") is not None


@contextmanager
def _patched_google_modules(fake_client, spreadsheet_id="sheet-123"):
    """Provide gspread + google.oauth2 stubs in sys.modules so tests work with or without optional packages installed."""
    sa_json = json.dumps({
        "type": "service_account",
        "project_id": "p",
        "private_key": "k",
        "client_email": "sa@p.iam.gserviceaccount.com",
    })

    fake_gspread = types.ModuleType("gspread")
    fake_gspread.authorize = lambda creds: fake_client

    fake_creds_cls = types.SimpleNamespace(
        from_service_account_info=lambda info, scopes=None: MagicMock(),
        from_service_account_file=lambda path, scopes=None: MagicMock(),
    )
    fake_sa_mod = types.ModuleType("google.oauth2.service_account")
    fake_sa_mod.Credentials = fake_creds_cls

    fake_oauth2_mod = types.ModuleType("google.oauth2")
    fake_oauth2_mod.service_account = fake_sa_mod

    fake_google_mod = types.ModuleType("google")
    fake_google_mod.oauth2 = fake_oauth2_mod

    with patch.object(sheets_mod, "SALES_GOOGLE_SPREADSHEET_ID", spreadsheet_id), \
         patch.object(sheets_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", sa_json), \
         patch.dict(
             sys.modules,
             {
                 "gspread": fake_gspread,
                 "google": fake_google_mod,
                 "google.oauth2": fake_oauth2_mod,
                 "google.oauth2.service_account": fake_sa_mod,
             },
         ):
        yield


class _FakeWorksheet:
    def __init__(self, title, headers=None):
        self.title = title
        self._headers = list(headers or ["id"])
        self.rows = []

    def row_values(self, row):
        return list(self._headers) if row == 1 else []

    def get_all_records(self):
        return [dict(r) for r in self.rows]

    def append_row(self, row, value_input_option="USER_ENTERED"):
        rec = {
            self._headers[idx]: (row[idx] if idx < len(row) else "")
            for idx in range(len(self._headers))
        }
        self.rows.append(rec)

    def update(self, *args, **kwargs):
        return {}


class _FakeSpreadsheet:
    def __init__(self, tabs=None, worksheets_exc=None):
        self.worksheets_exc = worksheets_exc
        self.add_worksheet_calls = []
        self._tabs = {
            t: _FakeWorksheet(t, list(cols))
            for t, cols in (tabs if tabs is not None else REQUIRED_TABS).items()
        }

    def worksheets(self):
        if self.worksheets_exc is not None:
            raise self.worksheets_exc
        return list(self._tabs.values())

    def worksheet(self, name):
        if name not in self._tabs:
            raise KeyError(name)
        return self._tabs[name]

    def add_worksheet(self, title, rows=1000, cols=26):
        self.add_worksheet_calls.append(title)
        ws = _FakeWorksheet(title, list(REQUIRED_TABS.get(title, ["id"])))
        self._tabs[title] = ws
        return ws


class TestStartupPortBindAndResilience(unittest.TestCase):
    def _make_isolated_db(self, allow_fallback=False):
        inst = SheetsDatabase(connect_on_init=False)
        inst.allow_in_memory_fallback = allow_fallback
        return inst

    def test_module_import_and_default_init_perform_zero_network_calls(self):
        """Instantiating SheetsDatabase() with defaults must not invoke gspread or block import."""
        with patch.object(sheets_mod.SheetsDatabase, "init_connection", side_effect=AssertionError("Must not connect on __init__")):
            inst = SheetsDatabase()
        self.assertFalse(inst.is_connected)
        self.assertIsNone(inst.spreadsheet)

    def test_finite_gspread_timeouts_enforced_and_never_none(self):
        """gspread client timeouts must always be finite (connect, read) and never None."""
        inst = self._make_isolated_db(allow_fallback=False)
        self.assertEqual(inst._validate_timeout(None), DEFAULT_GSPREAD_TIMEOUT)
        self.assertEqual(inst._validate_timeout((None, 10.0)), DEFAULT_GSPREAD_TIMEOUT)
        self.assertEqual(inst._validate_timeout(0), DEFAULT_GSPREAD_TIMEOUT)
        self.assertEqual(inst._validate_timeout((4.0, 12.0)), (4.0, 12.0))

        observed_timeouts = []
        fake_ss = _FakeSpreadsheet()

        class FakeHttpClient:
            def __init__(self):
                self.timeout = None

        class FakeGspreadClient:
            def __init__(self):
                self.http_client = FakeHttpClient()

            def set_timeout(self, timeout):
                self.http_client.timeout = timeout

            def open_by_key(self, key):
                observed_timeouts.append(self.http_client.timeout)
                return fake_ss

        fake_client = FakeGspreadClient()
        with _patched_google_modules(fake_client):
            ok = inst.init_connection()

        self.assertTrue(ok)
        self.assertEqual(len(observed_timeouts), 1)
        self.assertIsNotNone(observed_timeouts[0])
        self.assertEqual(observed_timeouts[0], DEFAULT_GSPREAD_TIMEOUT)
        self.assertIsNotNone(fake_client.http_client.timeout)

    def test_worksheet_discovery_failure_aborts_safely_with_zero_tab_creations(self):
        """If spreadsheet.worksheets() fails, abort safely without calling add_worksheet for 67 tabs."""
        inst = self._make_isolated_db(allow_fallback=False)
        broken_ss = _FakeSpreadsheet(worksheets_exc=RuntimeError("APIError: [429]: Quota exceeded"))

        class FakeHttpClient:
            timeout = None

        class FakeGspreadClient:
            http_client = FakeHttpClient()

            def set_timeout(self, t):
                self.http_client.timeout = t

            def open_by_key(self, key):
                return broken_ss

        with _patched_google_modules(FakeGspreadClient()):
            ok = inst.init_connection()

        self.assertFalse(ok)
        self.assertFalse(inst.is_connected)
        self.assertIsNone(inst.spreadsheet)
        self.assertEqual(broken_ss.add_worksheet_calls, [])

        # Direct call to ensure_required_tabs must also do zero creations when worksheets() fails
        inst.is_connected = True
        inst.spreadsheet = broken_ss
        self.assertFalse(inst.ensure_required_tabs())
        self.assertEqual(broken_ss.add_worksheet_calls, [])

    def test_fail_closed_writes_while_disconnected_and_restoration_on_connect(self):
        """Writes and reads fail closed while disconnected; successful connection restores normal operation."""
        inst = self._make_isolated_db(allow_fallback=False)
        inst.last_connection_error = "Initializing in background"

        self.assertFalse(inst.append_record("Sales", {"sale_id": "SALE-1", "bill_total": 100}, raise_on_error=False))
        with self.assertRaises(RuntimeError):
            inst.append_record("Sales", {"sale_id": "SALE-2"}, raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.update_record("Sales", "sale_id", "SALE-1", {"bill_status": "PAID"}, raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.delete_record("Sales", "sale_id", "SALE-1", raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.get_records("Sales", fresh=True)
        self.assertEqual(inst.memory_store["Sales"], [])

        # Now simulate successful connection
        fake_ss = _FakeSpreadsheet()

        class FakeGspreadClient:
            http_client = MagicMock(timeout=None)

            def set_timeout(self, t):
                self.http_client.timeout = t

            def open_by_key(self, key):
                return fake_ss

        with _patched_google_modules(FakeGspreadClient()):
            self.assertTrue(inst.init_connection())

        self.assertTrue(inst.is_connected)
        self.assertEqual(inst._consecutive_failures, 0)
        self.assertTrue(inst.append_record("Sales", {"sale_id": "SALE-100", "bill_total": 250}, raise_on_error=True))
        rows = inst.get_records("Sales", fresh=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sale_id"], "SALE-100")

    def test_concurrent_startup_and_reconnection_prevent_request_storms_and_apply_backoff(self):
        """Concurrent startup/reconnect calls execute single-flight and repeated failures apply bounded backoff."""
        inst = self._make_isolated_db(allow_fallback=False)
        inst._reconnect_cooldown_seconds = 10.0
        inst._max_auto_backoff_seconds = 60.0

        attempts = {"count": 0}
        entered_open = threading.Event()
        release_open = threading.Event()

        class SlowFailingClient:
            http_client = MagicMock(timeout=None)

            def set_timeout(self, t):
                self.http_client.timeout = t

            def open_by_key(self, key):
                attempts["count"] += 1
                entered_open.set()
                release_open.wait(timeout=5.0)
                raise TimeoutError("Simulated Google Sheets timeout")

        with _patched_google_modules(SlowFailingClient()):
            # 1. Multiple concurrent start_background_init() calls spawn only 1 attempt
            started_flags = [inst.start_background_init() for _ in range(5)]
            self.assertEqual(started_flags.count(True), 1)
            self.assertTrue(entered_open.wait(timeout=2.0))

            # 2. Concurrent attempt_auto_reconnect() calls while in flight do zero extra calls
            auto_results = []
            threads = [threading.Thread(target=lambda: auto_results.append(inst.attempt_auto_reconnect())) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(auto_results, [False] * 10)
            self.assertEqual(attempts["count"], 1)

            release_open.set()
            inst._background_thread.join(timeout=2.0)

            self.assertEqual(inst._consecutive_failures, 1)
            self.assertEqual(inst._auto_reconnect_cooldown_seconds(), 10.0)

            # 3. Within cooldown window, storm of auto-reconnect calls does 0 network calls
            for _ in range(10):
                self.assertFalse(inst.attempt_auto_reconnect())
            self.assertEqual(attempts["count"], 1)

            # 4. Once cooldown elapses, 10 concurrent threads produce only 1 reconnect attempt
            inst._last_conn_attempt_time = time.monotonic() - 100.0
            barrier = threading.Barrier(10)
            storm_results = []

            def worker():
                barrier.wait()
                storm_results.append(inst.attempt_auto_reconnect())

            storm_threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in storm_threads:
                t.start()
            for t in storm_threads:
                t.join()

            self.assertEqual(attempts["count"], 2)
            self.assertEqual(inst._consecutive_failures, 2)
            # Bounded exponential backoff increased after repeated failure (10s -> 20s)
            self.assertEqual(inst._auto_reconnect_cooldown_seconds(), 20.0)

            # 5. Repeated failures cap at _max_auto_backoff_seconds
            inst._consecutive_failures = 10
            self.assertEqual(inst._auto_reconnect_cooldown_seconds(), 60.0)

    def test_reconnection_recovers_after_outage(self):
        """Explicit reconnect clears caches and restores connected state after prior failures."""
        inst = self._make_isolated_db(allow_fallback=False)
        inst._consecutive_failures = 3
        inst._worksheets["Sales"] = "stale"
        inst._records_cache["Sales"] = (1.0, [{"sale_id": "OLD"}])

        fake_ss = _FakeSpreadsheet()

        class RecoveringClient:
            http_client = MagicMock(timeout=None)

            def set_timeout(self, t):
                self.http_client.timeout = t

            def open_by_key(self, key):
                return fake_ss

        with _patched_google_modules(RecoveringClient()):
            self.assertTrue(inst.reconnect())

        self.assertTrue(inst.is_connected)
        self.assertEqual(inst._consecutive_failures, 0)
        self.assertEqual(len(inst._records_cache), 0)

    def test_production_config_checks_reject_missing_or_invalid_credentials(self):
        """Production assert_runtime_config() must still fail-closed for missing/invalid secrets or Sheets config."""
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", ""), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/nonexistent/sa.json"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", ""), \
             patch.dict(os.environ, {"SALES_TESTING": "0", "SALES_JWT_SECRET": "a" * 40}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                config_mod.assert_runtime_config()
            self.assertIn("SALES_GOOGLE_SPREADSHEET_ID", str(ctx.exception))

        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "sheet-123"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/nonexistent/sa.json"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", ""), \
             patch.dict(os.environ, {"SALES_TESTING": "0", "SALES_JWT_SECRET": "a" * 40}, clear=False):
            with self.assertRaises(RuntimeError) as ctx2:
                config_mod.assert_runtime_config()
            self.assertIn("SERVICE_ACCOUNT", str(ctx2.exception))

        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "sheet-123"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/nonexistent/sa.json"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}'), \
             patch.dict(os.environ, {"SALES_TESTING": "0", "SALES_JWT_SECRET": "short"}, clear=False):
            with self.assertRaises(RuntimeError) as ctx3:
                config_mod.assert_runtime_config()
            self.assertIn("SALES_JWT_SECRET", str(ctx3.exception))

    def test_post_bind_scheduler_schedules_nonblocking_callback(self):
        """_schedule_post_bind_sheets_init must schedule via loop.call_later rather than running synchronously."""
        from app.main import _schedule_post_bind_sheets_init

        called = []

        async def run_check():
            with patch.dict(os.environ, {"SALES_TESTING": "0"}, clear=False), \
                 patch("app.main.db.start_background_init", side_effect=lambda: called.append(time.monotonic())):
                t_sched = time.monotonic()
                _schedule_post_bind_sheets_init()
                self.assertEqual(called, [], "Must not execute synchronously inside lifespan startup")
                await asyncio.sleep(0.12)
                self.assertEqual(len(called), 1)
                self.assertGreaterEqual(called[0] - t_sched, 0.04)

        asyncio.run(run_check())

    @unittest.skipUnless(_has_real_uvicorn_and_fastapi(), "Requires real uvicorn and fastapi packages")
    def test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s(self):
        """Real uvicorn subprocess must bind 0.0.0.0:$PORT and answer /health <3s even if Sheets hangs >5s."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        runner = f"""
import time, gspread, uvicorn
from unittest.mock import MagicMock
import google.oauth2.service_account as sa

sa.Credentials.from_service_account_info = lambda info, scopes=None: MagicMock()

class HangingWorksheet:
    def __init__(self, title):
        self.title = title

class HangingSpreadsheet:
    def worksheets(self):
        return [HangingWorksheet(t) for t in __import__("app.sheets", fromlist=["REQUIRED_TABS"]).REQUIRED_TABS]

class HangingClient:
    def __init__(self):
        self.http_client = MagicMock(timeout=None)
    def set_timeout(self, timeout):
        self.http_client.timeout = timeout
    def open_by_key(self, key):
        assert self.http_client.timeout is not None, "gspread timeout must never be None"
        time.sleep(6.0)
        return HangingSpreadsheet()

gspread.authorize = lambda creds: HangingClient()
uvicorn.run("main:app", host="0.0.0.0", port={port}, log_level="warning")
"""
        env = os.environ.copy()
        env["SALES_TESTING"] = "0"
        env["SALES_ENV"] = "production"
        env["SALES_JWT_SECRET"] = "x" * 40
        env["SALES_CORS_ORIGINS"] = "https://kawad-swad-sales-frontend.onrender.com"
        env["SALES_GOOGLE_SPREADSHEET_ID"] = "dummy-sheet-id-123"
        env["SALES_GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({
            "type": "service_account",
            "project_id": "p",
            "private_key": "k",
            "client_email": "sa@p.iam.gserviceaccount.com",
        })
        env["WEB_CONCURRENCY"] = "1"

        t0 = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, "-c", runner],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            health_payload = None
            elapsed = None
            while time.monotonic() - t0 < 3.0:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        if resp.status == 200:
                            health_payload = json.loads(resp.read().decode("utf-8"))
                            elapsed = time.monotonic() - t0
                            break
                except Exception:
                    time.sleep(0.1)

            self.assertIsNotNone(health_payload, "Uvicorn did not bind and answer /health within 3 seconds")
            self.assertLess(elapsed, 3.0)
            self.assertFalse(health_payload["google_sheets_connected"])
            self.assertFalse(health_payload["persistent_writes_enabled"])

            # Wait until the 6s simulated Sheets stall finishes and verify recovery
            recovered = False
            deadline = t0 + 9.5
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("google_sheets_connected") is True:
                            recovered = True
                            self.assertEqual(data["status"], "ok")
                            self.assertTrue(data["persistent_writes_enabled"])
                            break
                except Exception:
                    pass
                time.sleep(0.2)
            self.assertTrue(recovered, "Background init did not restore connected state after 6s Sheets delay")
        finally:
            proc.terminate()
            proc.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
