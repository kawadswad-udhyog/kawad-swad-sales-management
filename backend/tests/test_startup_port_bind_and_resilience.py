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


import urllib.error


_UVICORN_SUBPROCESS_REQUIRED_MODULES = (
    "uvicorn",
    "fastapi",
    "pydantic",
    "starlette",
    "jwt",
)


def _missing_uvicorn_subprocess_deps() -> list:
    """Return all packages required to launch the real Uvicorn/FastAPI subprocess that are absent."""
    missing = []
    for mod_name in _UVICORN_SUBPROCESS_REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(mod_name)
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            missing.append(mod_name)
    return missing


def _has_real_uvicorn_and_fastapi() -> bool:
    return len(_missing_uvicorn_subprocess_deps()) == 0


def _terminate_subprocess_safely(proc: subprocess.Popen) -> str:
    """Terminate a test subprocess cleanly and return any remaining output."""
    output = ""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=5)
                output = out or ""
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate(timeout=5)
                output = out or ""
        else:
            out, _ = proc.communicate(timeout=5)
            output = out or ""
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    return output


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
        """Reads and direct writes fail closed while disconnected; connect restores live reads while keeping direct writes blocked under Single-Write-Owner."""
        inst = self._make_isolated_db(allow_fallback=False)
        inst.last_connection_error = "Initializing in background"

        with self.assertRaises(RuntimeError) as ctx0:
            inst.append_record("Sales", {"sale_id": "SALE-1", "bill_total": 100}, raise_on_error=False)
        self.assertIn("BLOCKED_PENDING_OWNER_SETUP", str(ctx0.exception))
        with self.assertRaises(RuntimeError):
            inst.append_record("Sales", {"sale_id": "SALE-2"}, raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.update_record("Sales", "sale_id", "SALE-1", {"bill_status": "PAID"}, raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.delete_record("Sales", "sale_id", "SALE-1", raise_on_error=True)
        with self.assertRaises(RuntimeError):
            inst.get_records("Sales", fresh=True)
        self.assertEqual(inst.memory_store["Sales"], [])

        # Now simulate successful connection with a pre-existing sheet row (written by Apps Script)
        fake_ss = _FakeSpreadsheet()
        fake_ss.worksheet("Sales").rows.append({"sale_id": "SALE-100", "bill_total": 250})

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
        # Single-Write-Owner: direct FastAPI sheet mutations remain strictly blocked even when connected
        with self.assertRaises(RuntimeError) as ctx_direct:
            inst.append_record("Sales", {"sale_id": "SALE-101", "bill_total": 250}, raise_on_error=True)
        self.assertIn("BLOCKED_PENDING_OWNER_SETUP", str(ctx_direct.exception))
        # Authoritative fresh reads are restored upon connection
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

    def test_storage_init_status_transitions_and_health_reporting(self):
        """storage_init_status accurately tracks not_started -> initializing -> failed -> connected."""
        inst = self._make_isolated_db(allow_fallback=False)
        self.assertEqual(inst.storage_init_status, "not_started")

        entered = threading.Event()
        release = threading.Event()
        should_fail = {"flag": True}
        fake_ss = _FakeSpreadsheet()

        class ToggleClient:
            http_client = MagicMock(timeout=None)

            def set_timeout(self, t):
                self.http_client.timeout = t

            def open_by_key(self, key):
                entered.set()
                release.wait(timeout=5.0)
                if should_fail["flag"]:
                    raise TimeoutError("Simulated stall failure")
                return fake_ss

        with _patched_google_modules(ToggleClient()):
            self.assertTrue(inst.start_background_init())
            self.assertTrue(entered.wait(timeout=2.0))
            self.assertEqual(inst.storage_init_status, "initializing")
            self.assertFalse(inst.is_connected)

            release.set()
            inst._background_thread.join(timeout=2.0)
            self.assertEqual(inst.storage_init_status, "failed")
            self.assertFalse(inst.is_connected)

            # Now recover cleanly
            should_fail["flag"] = False
            self.assertTrue(inst.reconnect())
            self.assertEqual(inst.storage_init_status, "connected")
            self.assertTrue(inst.is_connected)

    def test_uvicorn_dependency_check_validates_all_required_asgi_modules(self):
        """Dependency helper must verify all required ASGI runtime imports and report missing packages visibly."""
        with patch.object(
            importlib.util,
            "find_spec",
            side_effect=lambda name: object() if name == "uvicorn" else None,
        ):
            missing = _missing_uvicorn_subprocess_deps()
            self.assertNotIn("uvicorn", missing)
            self.assertIn("fastapi", missing)
            self.assertIn("pydantic", missing)
            self.assertIn("starlette", missing)
            self.assertIn("jwt", missing)
            self.assertFalse(_has_real_uvicorn_and_fastapi())

        with patch.object(importlib.util, "find_spec", return_value=object()):
            self.assertEqual(_missing_uvicorn_subprocess_deps(), [])
            self.assertTrue(_has_real_uvicorn_and_fastapi())

    def test_http_subprocess_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s_stdlib(self):
        """
        Deterministic stdlib HTTP subprocess test (runs in every Python environment):
        Verifies real app startup (_check_configuration + _schedule_post_bind_sheets_init)
        binds a TCP port and serves /health <3s while Google Sheets open_by_key() hangs 6s,
        accurately separates HTTP readiness from storage_init_status, fails closed (503) on
        business endpoints while storage is unavailable, recovers after the 6s delay, and
        cleans up the subprocess.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        runner = f"""
import asyncio
import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

# Inject deterministic gspread & google.oauth2 stubs with a real 6.0s open_by_key() stall
fake_sa_mod = types.ModuleType("google.oauth2.service_account")
fake_sa_mod.Credentials = types.SimpleNamespace(
    from_service_account_info=lambda info, scopes=None: MagicMock(),
    from_service_account_file=lambda path, scopes=None: MagicMock(),
)
fake_oauth2_mod = types.ModuleType("google.oauth2")
fake_oauth2_mod.service_account = fake_sa_mod
fake_google_mod = types.ModuleType("google")
fake_google_mod.oauth2 = fake_oauth2_mod

class HangingWorksheet:
    def __init__(self, title, headers):
        self.title = title
        self._headers = list(headers)
        self._rows = [{{"sale_id": "SALE-HEALTH-1", "bill_total": 100}}] if title == "Sales" else []
    def row_values(self, row):
        return list(self._headers) if row == 1 else []
    def get_all_records(self):
        return [dict(r) for r in self._rows]

class HangingSpreadsheet:
    def __init__(self):
        req_tabs = __import__("app.sheets", fromlist=["REQUIRED_TABS"]).REQUIRED_TABS
        self._tabs = {{t: HangingWorksheet(t, cols) for t, cols in req_tabs.items()}}
    def worksheets(self):
        return list(self._tabs.values())
    def worksheet(self, name):
        return self._tabs[name]

class HangingClient:
    def __init__(self):
        self.http_client = MagicMock(timeout=None)
    def set_timeout(self, timeout):
        self.http_client.timeout = timeout
    def open_by_key(self, key):
        assert self.http_client.timeout is not None, "gspread timeout must never be None"
        time.sleep(6.0)
        return HangingSpreadsheet()

fake_gspread = types.ModuleType("gspread")
fake_gspread.authorize = lambda creds: HangingClient()

sys.modules["gspread"] = fake_gspread
sys.modules["google"] = fake_google_mod
sys.modules["google.oauth2"] = fake_oauth2_mod
sys.modules["google.oauth2.service_account"] = fake_sa_mod

import tests  # ensures stdlib FastAPI/Pydantic/JWT stubs only when real packages are absent
import os
os.environ["SALES_TESTING"] = "0"

import app.main as main_mod
import app.auth as auth_mod
import app.sheets as sheets_mod

# Ensure production-like fail-closed mode (no in-memory fallback)
sheets_mod.db.allow_in_memory_fallback = False

# Run real startup configuration validation and post-bind background Sheets scheduler
main_mod._check_configuration()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, main_mod.health_check())
            return
        if self.path == "/api/sales":
            try:
                asyncio.run(auth_mod.require_sheets_connection())
                rows = sheets_mod.db.get_records("Sales", fresh=True)
                self._send_json(200, {{"rows": rows}})
            except Exception as exc:
                code = getattr(exc, "status_code", 503)
                detail = getattr(exc, "detail", str(exc))
                self._send_json(code, {{"detail": detail}})
            return
        self._send_json(404, {{"detail": "Not Found"}})

server = ThreadingHTTPServer(("127.0.0.1", {port}), Handler)

# Trigger background Sheets init immediately after HTTP port bind (mirrors lifespan post-bind schedule)
threading.Timer(0.05, sheets_mod.db.start_background_init).start()
server.serve_forever()
"""
        pers_coord_dir = os.path.join(backend_dir, f".startup_coord_test_stdlib_{os.getpid()}_{port}")
        os.makedirs(pers_coord_dir, exist_ok=True)
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
        env["TRANSACTION_DB_PATH"] = os.path.join(pers_coord_dir, "tx_coord.db")
        env["SALES_INSTANCE_COUNT"] = "1"

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
                if proc.poll() is not None:
                    out = _terminate_subprocess_safely(proc)
                    self.fail(f"Startup resilience subprocess exited early (rc={proc.returncode}):\n{out}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        if resp.status == 200:
                            health_payload = json.loads(resp.read().decode("utf-8"))
                            elapsed = time.monotonic() - t0
                            break
                except Exception:
                    time.sleep(0.05)

            if health_payload is None:
                out = _terminate_subprocess_safely(proc)
                self.fail(f"HTTP server did not bind and answer /health within 3 seconds.\nSubprocess output:\n{out}")

            self.assertLess(elapsed, 3.0)
            self.assertEqual(health_payload["backend"]["status"], "CONNECTED")
            self.assertEqual(health_payload["status"], "storage_disconnected")
            self.assertFalse(health_payload["google_sheets_connected"])
            self.assertFalse(health_payload["persistent_writes_enabled"])

            # Wait briefly past the 50ms post-bind schedule so background Sheets init is actively hanging
            time.sleep(0.15)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                during_hang = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(during_hang["storage_init_status"], "initializing")
            self.assertFalse(during_hang["google_sheets_connected"])
            self.assertFalse(during_hang["persistent_writes_enabled"])

            # Business endpoint requiring storage MUST fail closed promptly (503) while Sheets is still hanging
            t_biz = time.monotonic()
            with self.assertRaises(urllib.error.HTTPError) as biz_err:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sales", timeout=2.0)
            biz_elapsed = time.monotonic() - t_biz
            self.assertEqual(biz_err.exception.code, 503)
            self.assertLess(biz_elapsed, 1.5, "Business endpoint blocked instead of failing closed while Sheets hung")
            biz_err.exception.close()

            # Confirm Sheets hang is genuinely >5 seconds (still not connected before t0 + 4.5s)
            if time.monotonic() - t0 < 4.5:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                    still_hanging = json.loads(resp.read().decode("utf-8"))
                self.assertFalse(still_hanging["google_sheets_connected"])
                self.assertEqual(still_hanging["storage_init_status"], "initializing")

            # Wait until the 6s simulated Sheets stall finishes and verify recovery
            recovered = False
            deadline = t0 + 10.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    out = _terminate_subprocess_safely(proc)
                    self.fail(f"Subprocess exited unexpectedly during Sheets recovery (rc={proc.returncode}):\n{out}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("google_sheets_connected") is True:
                            recovered = True
                            self.assertGreaterEqual(time.monotonic() - t0, 5.0, "Simulated Sheets delay finished before 5s")
                            self.assertEqual(data["status"], "ok")
                            self.assertTrue(data["persistent_writes_enabled"])
                            self.assertEqual(data["storage_init_status"], "connected")
                            break
                except Exception:
                    pass
                time.sleep(0.2)
            self.assertTrue(recovered, "Background init did not restore connected state after 6s Sheets delay")

            # After recovery, business read succeeds
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sales", timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                sales_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(sales_data["rows"]), 1)
                self.assertEqual(sales_data["rows"][0]["sale_id"], "SALE-HEALTH-1")
        finally:
            _terminate_subprocess_safely(proc)
            import shutil
            shutil.rmtree(pers_coord_dir, ignore_errors=True)
            self.assertIsNotNone(proc.poll(), "Subprocess was not cleaned up")

    @unittest.skipUnless(
        _has_real_uvicorn_and_fastapi(),
        f"Requires real ASGI runtime packages ({', '.join(_missing_uvicorn_subprocess_deps()) or 'uvicorn/fastapi'}); "
        "install backend/requirements.txt to execute full Uvicorn ASGI subprocess check",
    )
    def test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s(self):
        """Real uvicorn subprocess must bind 0.0.0.0:$PORT and answer /health <3s even if Sheets hangs >5s."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        runner = f"""
import sys, time, types, uvicorn
from unittest.mock import MagicMock

# Provide deterministic gspread + google.oauth2.service_account stubs in sys.modules
# so the real Uvicorn + FastAPI ASGI startup test does not crash if optional Google
# client libraries are absent from a minimal test environment.
fake_sa_mod = types.ModuleType("google.oauth2.service_account")
fake_sa_mod.Credentials = types.SimpleNamespace(
    from_service_account_info=lambda info, scopes=None: MagicMock(),
    from_service_account_file=lambda path, scopes=None: MagicMock(),
)
fake_oauth2_mod = types.ModuleType("google.oauth2")
fake_oauth2_mod.service_account = fake_sa_mod
fake_google_mod = types.ModuleType("google")
fake_google_mod.oauth2 = fake_oauth2_mod

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

fake_gspread = types.ModuleType("gspread")
fake_gspread.authorize = lambda creds: HangingClient()

sys.modules["gspread"] = fake_gspread
sys.modules["google"] = fake_google_mod
sys.modules["google.oauth2"] = fake_oauth2_mod
sys.modules["google.oauth2.service_account"] = fake_sa_mod

uvicorn.run("main:app", host="0.0.0.0", port={port}, log_level="warning")
"""
        pers_coord_dir = os.path.join(backend_dir, f".startup_coord_test_uvicorn_{os.getpid()}_{port}")
        os.makedirs(pers_coord_dir, exist_ok=True)
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
        env["SALES_INSTANCE_COUNT"] = "1"
        env["TRANSACTION_DB_PATH"] = os.path.join(pers_coord_dir, "tx_coord.db")

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
                if proc.poll() is not None:
                    out = _terminate_subprocess_safely(proc)
                    self.fail(f"Uvicorn subprocess exited early (rc={proc.returncode}):\n{out}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        if resp.status == 200:
                            health_payload = json.loads(resp.read().decode("utf-8"))
                            elapsed = time.monotonic() - t0
                            break
                except Exception:
                    time.sleep(0.1)

            if health_payload is None:
                out = _terminate_subprocess_safely(proc)
                self.fail(f"Uvicorn did not bind and answer /health within 3 seconds.\nSubprocess output:\n{out}")

            self.assertLess(elapsed, 3.0)
            self.assertEqual(health_payload["backend"]["status"], "CONNECTED")
            self.assertEqual(health_payload["status"], "storage_disconnected")
            self.assertFalse(health_payload["google_sheets_connected"])
            self.assertFalse(health_payload["persistent_writes_enabled"])

            # Verify storage_init_status tracks initializing and business auth fails closed (503) promptly
            time.sleep(0.15)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                during_hang = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(during_hang["storage_init_status"], "initializing")
            self.assertFalse(during_hang["google_sheets_connected"])

            login_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/auth/login",
                data=json.dumps({"username": "owner", "password": "Password123!"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            t_biz = time.monotonic()
            with self.assertRaises(urllib.error.HTTPError) as biz_err:
                urllib.request.urlopen(login_req, timeout=2.0)
            self.assertEqual(biz_err.exception.code, 503)
            self.assertLess(time.monotonic() - t_biz, 1.5)
            biz_err.exception.close()

            # Wait until the 6s simulated Sheets stall finishes and verify recovery
            recovered = False
            deadline = t0 + 10.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    out = _terminate_subprocess_safely(proc)
                    self.fail(f"Uvicorn subprocess exited unexpectedly during recovery (rc={proc.returncode}):\n{out}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("google_sheets_connected") is True:
                            recovered = True
                            self.assertGreaterEqual(time.monotonic() - t0, 5.0)
                            self.assertEqual(data["status"], "ok")
                            self.assertTrue(data["persistent_writes_enabled"])
                            self.assertEqual(data["storage_init_status"], "connected")
                            break
                except Exception:
                    pass
                time.sleep(0.2)
            self.assertTrue(recovered, "Background init did not restore connected state after 6s Sheets delay")
        finally:
            _terminate_subprocess_safely(proc)
            import shutil
            shutil.rmtree(pers_coord_dir, ignore_errors=True)
            self.assertIsNotNone(proc.poll(), "Uvicorn subprocess was not cleaned up")


if __name__ == "__main__":
    unittest.main()
