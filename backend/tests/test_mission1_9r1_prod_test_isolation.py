"""
Mission 1.9R-1: Critical Production Test-Mode Isolation Repair (M19-001)
Comprehensive regression test suite verifying fail-closed production/test isolation
across centralized config validation, startup ordering, JWT signing/verification,
Google Sheets initialization, volatile storage fallback guards, and transaction
coordinator durability enforcement.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 - ensures backend path and stdlib stubs when framework packages are absent

import app.auth as auth_mod
import app.config as config_mod
import app.main as main_mod
import app.sheets as sheets_mod
import app.transaction_safety as tx_safety_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.config import (
    ProductionTestModeConflictError,
    TEST_ONLY_JWT_SECRET,
    assert_production_test_isolation,
    assert_runtime_config,
    is_isolated_testing_mode,
    jwt_secret,
)
from app.transaction_safety import (
    CoordinatorDurabilityError,
    CoordinatorDurabilityMode,
    validate_coordinator_durability,
)
from tests._durability_test_helpers import make_nonvolatile_test_dir


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VALID_PROD_JWT_SECRET = "prod-k3y-9f8e7d6c5b4a3210-secure-session-signing-secret-2026"
VALID_PROD_ORIGIN = "https://kawad-swad-sales-frontend.onrender.com"


class TestMission19R1ProductionTestIsolation(unittest.TestCase):
    """Verify absolute production precedence over SALES_TESTING across all subsystems."""

    def setUp(self):
        self._pers_dir = make_nonvolatile_test_dir("ks_m19r1_prod")
        self._sa_file = os.path.join(self._pers_dir, "sa.json")
        with open(self._sa_file, "w", encoding="utf-8") as fh:
            json.dump({"type": "service_account", "project_id": "test-proj"}, fh)
        self._coord_db = os.path.join(self._pers_dir, "tx_coord.db")

    def tearDown(self):
        shutil.rmtree(self._pers_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # 1. SALES_ENV=production + SALES_TESTING=1 -> startup rejected
    # ------------------------------------------------------------------
    def test_01_production_with_testing_flag_rejected_in_process_and_lifespan(self):
        for truthy_flag in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(SALES_TESTING=truthy_flag):
                with patch.object(config_mod, "SALES_ENV", "production"), \
                     patch.dict(
                         os.environ,
                         {
                             "SALES_ENV": "production",
                             "SALES_TESTING": truthy_flag,
                             "SALES_JWT_SECRET": VALID_PROD_JWT_SECRET,
                             "TRANSACTION_DB_PATH": self._coord_db,
                         },
                         clear=False,
                     ):
                    with self.assertRaises(ProductionTestModeConflictError) as ctx_guard:
                        assert_production_test_isolation()
                    self.assertEqual(ctx_guard.exception.error_code, "PRODUCTION_TEST_MODE_CONFLICT")

                    with self.assertRaises(ProductionTestModeConflictError):
                        assert_runtime_config()

                    with self.assertRaises(ProductionTestModeConflictError):
                        main_mod._check_configuration()

                    # Verify lifespan fails BEFORE scheduling background Sheets init
                    with patch.object(main_mod, "_schedule_post_bind_sheets_init") as mock_sched:
                        async def _run_lifespan():
                            async with main_mod.lifespan(main_mod.app):
                                pass

                        with self.assertRaises(ProductionTestModeConflictError):
                            asyncio.run(_run_lifespan())
                        mock_sched.assert_not_called()

    def test_01b_subprocess_import_fails_before_storage_auth_coordinator_or_api_setup(self):
        """
        Real process startup test: SALES_ENV=production + SALES_TESTING=1 must fail at
        app.config import time BEFORE app.sheets, app.auth, coordinator, or FastAPI app initialize.
        """
        probe = (
            "import sys\n"
            "try:\n"
            "    import app.main\n"
            "except Exception as exc:\n"
            "    print('EXC_TYPE=' + type(exc).__name__)\n"
            "    print('EXC_CODE=' + str(getattr(exc, 'error_code', '')))\n"
            "    print('SHEETS_LOADED=' + str('app.sheets' in sys.modules))\n"
            "    print('AUTH_LOADED=' + str('app.auth' in sys.modules))\n"
            "    print('COORD_LOADED=' + str('app.accounting.transaction_coordinator' in sys.modules))\n"
            "    sys.exit(42)\n"
            "sys.exit(0)\n"
        )
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SALES_ENV"] = "production"
        env["SALES_TESTING"] = "1"
        env["SALES_JWT_SECRET"] = VALID_PROD_JWT_SECRET
        env["SALES_GOOGLE_SPREADSHEET_ID"] = "sheet-id-prod-123"
        env["SALES_GOOGLE_SERVICE_ACCOUNT_FILE"] = self._sa_file
        env["TRANSACTION_DB_PATH"] = self._coord_db
        env["PYTHONPATH"] = BACKEND_DIR

        proc = subprocess.run(
            [sys.executable, "-B", "-c", probe],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 42, f"Expected fail-closed exit 42, got {proc.returncode}: {proc.stdout}\n{proc.stderr}")
        self.assertIn("EXC_TYPE=ProductionTestModeConflictError", proc.stdout)
        self.assertIn("EXC_CODE=PRODUCTION_TEST_MODE_CONFLICT", proc.stdout)
        self.assertIn("SHEETS_LOADED=False", proc.stdout)
        self.assertIn("AUTH_LOADED=False", proc.stdout)
        self.assertIn("COORD_LOADED=False", proc.stdout)

    def test_01c_live_env_production_detected_even_if_module_constant_is_development(self):
        """Even if config.SALES_ENV was 'development' at import, live SALES_ENV=production + SALES_TESTING=1 fails closed."""
        with patch.object(config_mod, "SALES_ENV", "development"), \
             patch.dict(os.environ, {"SALES_ENV": "PRODUCTION", "SALES_TESTING": "1"}, clear=False):
            with self.assertRaises(ProductionTestModeConflictError):
                assert_production_test_isolation()
            with self.assertRaises(ProductionTestModeConflictError):
                jwt_secret()

    # ------------------------------------------------------------------
    # 2. Production + test flag -> test JWT secret cannot be returned
    # ------------------------------------------------------------------
    def test_02_production_with_test_flag_never_returns_test_jwt_secret(self):
        for raw_secret in ("", TEST_ONLY_JWT_SECRET, VALID_PROD_JWT_SECRET):
            with self.subTest(secret_configured=bool(raw_secret)):
                with patch.object(config_mod, "SALES_ENV", "production"), \
                     patch.dict(
                         os.environ,
                         {
                             "SALES_ENV": "production",
                             "SALES_TESTING": "1",
                             "SALES_JWT_SECRET": raw_secret,
                         },
                         clear=False,
                     ):
                    with self.assertRaises(ProductionTestModeConflictError):
                        jwt_secret()

                    with self.assertRaises(ProductionTestModeConflictError):
                        auth_mod.create_access_token({"sub": "USR-001", "user_id": "USR-001"})

                    # Token minted with known public test secret must NEVER verify in production
                    import jwt as jwt_lib
                    forged = jwt_lib.encode({"sub": "USR-001", "user_id": "USR-001"}, TEST_ONLY_JWT_SECRET, algorithm="HS256")
                    self.assertIsNone(auth_mod.decode_access_token(forged))

    # ------------------------------------------------------------------
    # 3. Production + test flag -> Google Sheets init cannot be bypassed
    # ------------------------------------------------------------------
    def test_03_production_with_test_flag_cannot_bypass_sheets_initialization(self):
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.dict(os.environ, {"SALES_ENV": "production", "SALES_TESTING": "1"}, clear=False):
            with self.assertRaises(ProductionTestModeConflictError):
                main_mod._schedule_post_bind_sheets_init()

            with self.assertRaises(ProductionTestModeConflictError):
                sheets_mod.db.start_background_init()

            with self.assertRaises(ProductionTestModeConflictError):
                sheets_mod.db.init_connection()

        # In production without test flag, _schedule_post_bind_sheets_init genuinely schedules background init
        called = []

        async def _verify_prod_schedule():
            with patch.object(config_mod, "SALES_ENV", "production"), \
                 patch.dict(os.environ, {"SALES_ENV": "production", "SALES_TESTING": "0"}, clear=False), \
                 patch.object(main_mod.db, "start_background_init", side_effect=lambda: called.append(True)):
                main_mod._schedule_post_bind_sheets_init()
                await asyncio.sleep(0.1)

        asyncio.run(_verify_prod_schedule())
        self.assertEqual(called, [True])

    # ------------------------------------------------------------------
    # 4. Production + test flag -> in-memory / volatile fallback cannot activate
    # ------------------------------------------------------------------
    def test_04_production_cannot_activate_in_memory_or_shared_file_fallback(self):
        # 4a: Production + SALES_TESTING=1 fails closed on SheetsDatabase init and access
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.dict(os.environ, {"SALES_ENV": "production", "SALES_TESTING": "1"}, clear=False):
            with self.assertRaises(ProductionTestModeConflictError):
                sheets_mod.SheetsDatabase(connect_on_init=False)

            with self.assertRaises(ProductionTestModeConflictError):
                _ = sheets_mod.db.allow_in_memory_fallback

            with self.assertRaises(ProductionTestModeConflictError):
                sheets_mod.db.get_records("Sales", fresh=True)

            with self.assertRaises(ProductionTestModeConflictError):
                sheets_mod.db.append_record("Sales", {"sale_id": "SALE-999"}, raise_on_error=True)

        # 4b: Production + SALES_TESTING=0 never enables in-memory or shared-file fallback
        shared_tmp = tempfile.mkdtemp(prefix="ks_m19r1_shared_")
        try:
            with patch.object(config_mod, "SALES_ENV", "production"), \
                 patch.dict(
                     os.environ,
                     {
                         "SALES_ENV": "production",
                         "SALES_TESTING": "0",
                         "SALES_SHARED_TEST_DIR": shared_tmp,
                     },
                     clear=False,
                 ):
                prod_db = sheets_mod.SheetsDatabase(connect_on_init=False)
                self.assertFalse(prod_db.allow_in_memory_fallback)
                self.assertIsNone(prod_db.shared_file_dir)

                with self.assertRaises(RuntimeError):
                    prod_db.allow_in_memory_fallback = True

                with self.assertRaises(RuntimeError):
                    prod_db.enable_shared_file_store(shared_tmp)

                # Disconnected reads and writes fail closed instead of falling back to volatile memory/files
                with self.assertRaises(RuntimeError) as read_ctx:
                    prod_db.get_records("Sales", fresh=True)
                self.assertIn("Persistent storage is unavailable", str(read_ctx.exception))

                with self.assertRaises(RuntimeError) as write_ctx:
                    prod_db.append_record("Sales", {"sale_id": "SALE-999"}, raise_on_error=True)
                self.assertIn("BLOCKED_PENDING_OWNER_SETUP", str(write_ctx.exception))
        finally:
            shutil.rmtree(shared_tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # 5. Production + test flag -> transaction durability checks cannot be skipped
    # ------------------------------------------------------------------
    def test_05_production_with_test_flag_cannot_bypass_transaction_durability(self):
        # Explicit env="production" + testing=True -> fail closed
        with self.assertRaises(CoordinatorDurabilityError) as ctx_direct:
            validate_coordinator_durability(db_path=self._coord_db, env="production", testing=True)
        self.assertEqual(ctx_direct.exception.error_code, "PRODUCTION_TEST_MODE_CONFLICT")
        self.assertEqual(ctx_direct.exception.mode, CoordinatorDurabilityMode.MISCONFIGURED)

        # Environment-driven SALES_ENV=production + SALES_TESTING=1 with volatile path or multi-instance -> fail closed
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.dict(
                 os.environ,
                 {
                     "SALES_ENV": "production",
                     "SALES_TESTING": "1",
                     "TRANSACTION_DB_PATH": "/tmp/should_never_pass.db",
                     "SALES_TX_ALLOW_VOLATILE_COORD": "true",
                     "SALES_INSTANCE_COUNT": "3",
                 },
                 clear=False,
             ):
            with self.assertRaises(CoordinatorDurabilityError) as ctx_env:
                validate_coordinator_durability()
            self.assertEqual(ctx_env.exception.error_code, "PRODUCTION_TEST_MODE_CONFLICT")

            with self.assertRaises(CoordinatorDurabilityError) as ctx_coord:
                TransactionCoordinator(db_path="/tmp/should_never_pass.db")
            self.assertEqual(ctx_coord.exception.error_code, "PRODUCTION_TEST_MODE_CONFLICT")

            # Deferred singleton mode still records durability error and blocks all mutations
            deferred = TransactionCoordinator(db_path="/tmp/should_never_pass.db", defer_durability_error=True)
            with self.assertRaises(CoordinatorDurabilityError) as ctx_mut:
                deferred.assert_writable_coordinator()
            self.assertEqual(ctx_mut.exception.error_code, "PRODUCTION_TEST_MODE_CONFLICT")

        # Production + SALES_TESTING=0 + SALES_TX_ALLOW_VOLATILE_COORD=true STILL rejects volatile path
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.dict(
                 os.environ,
                 {
                     "SALES_ENV": "production",
                     "SALES_TESTING": "0",
                     "TRANSACTION_DB_PATH": "/tmp/volatile_prod.db",
                     "SALES_TX_ALLOW_VOLATILE_COORD": "true",
                 },
                 clear=False,
             ):
            with self.assertRaises(CoordinatorDurabilityError) as ctx_vol:
                validate_coordinator_durability()
            self.assertEqual(ctx_vol.exception.error_code, "COORDINATOR_VOLATILE_PATH_IN_PRODUCTION")

    # ------------------------------------------------------------------
    # 6. SALES_ENV=development + SALES_TESTING=1 -> isolated test behavior continues
    # ------------------------------------------------------------------
    def test_06_development_with_testing_enabled_preserves_isolated_test_behavior(self):
        with patch.object(config_mod, "SALES_ENV", "development"), \
             patch.dict(
                 os.environ,
                 {
                     "SALES_ENV": "development",
                     "SALES_TESTING": "1",
                     "SALES_JWT_SECRET": "",
                     "TRANSACTION_DB_PATH": "",
                 },
                 clear=False,
             ):
            self.assertTrue(is_isolated_testing_mode())
            self.assertEqual(jwt_secret(), TEST_ONLY_JWT_SECRET)

            # Startup config check and Sheets init remain safely skipped in isolated dev test mode
            main_mod._check_configuration()
            with patch.object(main_mod.db, "start_background_init") as mock_bg:
                main_mod._schedule_post_bind_sheets_init()
                mock_bg.assert_not_called()

            test_db = sheets_mod.SheetsDatabase(connect_on_init=False)
            self.assertTrue(test_db.allow_in_memory_fallback)
            self.assertTrue(test_db.append_record("Sales", {"sale_id": "SALE-DEV-TEST-1"}, raise_on_error=True))
            self.assertEqual(len(test_db.get_records("Sales", fresh=True)), 1)

            coord_info = validate_coordinator_durability(env="development", testing=True)
            self.assertEqual(coord_info["mode"], CoordinatorDurabilityMode.VOLATILE_TEST.value)
            self.assertTrue(coord_info["testing"])

    # ------------------------------------------------------------------
    # 7. SALES_ENV=development + SALES_TESTING=0 -> normal development behavior continues
    # ------------------------------------------------------------------
    def test_07_development_with_testing_disabled_preserves_normal_dev_behavior(self):
        with patch.object(config_mod, "SALES_ENV", "development"), \
             patch.dict(
                 os.environ,
                 {
                     "SALES_ENV": "development",
                     "SALES_TESTING": "0",
                     "SALES_JWT_SECRET": "",
                     "TRANSACTION_DB_PATH": "",
                 },
                 clear=False,
             ):
            self.assertFalse(is_isolated_testing_mode())
            # Missing JWT secret in non-testing dev uses ephemeral secret, NOT hardcoded public test secret
            dev_secret = jwt_secret()
            self.assertNotEqual(dev_secret, TEST_ONLY_JWT_SECRET)
            self.assertGreaterEqual(len(dev_secret), 32)

            dev_db = sheets_mod.SheetsDatabase(connect_on_init=False)
            self.assertFalse(dev_db.allow_in_memory_fallback)

            coord_info = validate_coordinator_durability(env="development", testing=False)
            self.assertEqual(coord_info["mode"], CoordinatorDurabilityMode.DEV_LOCAL.value)
            self.assertFalse(coord_info["testing"])

            # Normal dev still schedules background Sheets init
            called = []

            async def _verify_dev_schedule():
                with patch.object(main_mod.db, "start_background_init", side_effect=lambda: called.append(True)):
                    main_mod._schedule_post_bind_sheets_init()
                    await asyncio.sleep(0.1)

            asyncio.run(_verify_dev_schedule())
            self.assertEqual(called, [True])

    # ------------------------------------------------------------------
    # 8. Production without testing flag + valid config -> normal validation passes
    # ------------------------------------------------------------------
    def test_08_valid_production_configuration_without_testing_flag_passes(self):
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", ""), \
             patch.dict(
                 os.environ,
                 {
                     "SALES_ENV": "production",
                     "SALES_TESTING": "0",
                     "SALES_JWT_SECRET": VALID_PROD_JWT_SECRET,
                     "TRANSACTION_DB_PATH": self._coord_db,
                     "SALES_INSTANCE_COUNT": "1",
                 },
                 clear=False,
             ):
            self.assertFalse(is_isolated_testing_mode())
            self.assertEqual(jwt_secret(), VALID_PROD_JWT_SECRET)
            assert_runtime_config()
            main_mod._check_configuration()

            prod_db = sheets_mod.SheetsDatabase(connect_on_init=False)
            self.assertFalse(prod_db.allow_in_memory_fallback)

            coord_info = validate_coordinator_durability()
            self.assertEqual(coord_info["mode"], CoordinatorDurabilityMode.PERSISTENT.value)
            self.assertTrue(coord_info["persistent"])
            self.assertFalse(coord_info["testing"])

    # ------------------------------------------------------------------
    # 9. Production with invalid/missing/test-only JWT secret -> fail closed & no secret exposure
    # ------------------------------------------------------------------
    def test_09_production_invalid_missing_or_test_jwt_secret_fails_closed_without_secret_leak(self):
        bad_secrets = [
            "",
            "short-secret-12345",
            "changeme",
            "secret",
            "kawad-swad-sales-mgmt-secure-token-key-2026-prod-secret",
            TEST_ONLY_JWT_SECRET,
        ]
        for bad_secret in bad_secrets:
            with self.subTest(bad_secret=bad_secret):
                with patch.object(config_mod, "SALES_ENV", "production"), \
                     patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
                     patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
                     patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
                     patch.dict(
                         os.environ,
                         {
                             "SALES_ENV": "production",
                             "SALES_TESTING": "0",
                             "SALES_JWT_SECRET": bad_secret,
                             "TRANSACTION_DB_PATH": self._coord_db,
                         },
                         clear=False,
                     ):
                    with self.assertRaises(RuntimeError) as ctx:
                        jwt_secret()
                    err_msg = str(ctx.exception)
                    self.assertIn("SALES_JWT_SECRET", err_msg)
                    # Verify raw secret values are never exposed in exception messages
                    if bad_secret and len(bad_secret) >= 8:
                        self.assertNotIn(bad_secret, err_msg)

                    with self.assertRaises(RuntimeError):
                        assert_runtime_config()

                    with self.assertRaises(RuntimeError):
                        main_mod._check_configuration()

    # ------------------------------------------------------------------
    # 10. No regression to existing production configuration safeguards
    # ------------------------------------------------------------------
    def test_10_existing_production_safeguards_remain_enforced(self):
        base_env = {
            "SALES_ENV": "production",
            "SALES_TESTING": "0",
            "SALES_JWT_SECRET": VALID_PROD_JWT_SECRET,
            "TRANSACTION_DB_PATH": self._coord_db,
            "SALES_INSTANCE_COUNT": "1",
        }

        # Wildcard CORS rejected
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", "*"), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
             patch.dict(os.environ, base_env, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                assert_runtime_config()
            self.assertIn("Wildcard CORS", str(ctx.exception))

        # Missing spreadsheet ID rejected
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", ""), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
             patch.dict(os.environ, base_env, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                assert_runtime_config()
            self.assertIn("SALES_GOOGLE_SPREADSHEET_ID", str(ctx.exception))

        # Missing service account credentials rejected
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/nonexistent/sa.json"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_JSON", ""), \
             patch.dict(os.environ, base_env, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                assert_runtime_config()
            self.assertIn("SERVICE_ACCOUNT", str(ctx.exception))

        # Horizontal scaling (>1 instance) rejected
        multi_env = dict(base_env, SALES_INSTANCE_COUNT="2")
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
             patch.dict(os.environ, multi_env, clear=False):
            with self.assertRaises(CoordinatorDurabilityError) as ctx:
                assert_runtime_config()
            self.assertEqual(ctx.exception.error_code, "COORDINATOR_MULTI_INSTANCE_UNSUPPORTED")

        # Missing TRANSACTION_DB_PATH rejected
        no_db_env = dict(base_env, TRANSACTION_DB_PATH="")
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_CORS_ORIGINS", VALID_PROD_ORIGIN), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "prod-sheet-id-2026"), \
             patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", self._sa_file), \
             patch.dict(os.environ, no_db_env, clear=False):
            with self.assertRaises(CoordinatorDurabilityError) as ctx:
                assert_runtime_config()
            self.assertEqual(ctx.exception.error_code, "COORDINATOR_PATH_UNCONFIGURED")


if __name__ == "__main__":
    unittest.main()
