"""
Kawad Swad ERP — Phase 1.6 Targeted Repair Regression Suite.

Covers all 9 Phase 1.5 verified defects (P1.5-001 through P1.5-009):
- P1.5-001 (CRITICAL): Secondary-tab schema bypass across all 127 governed actions & caller invalidate_tabs subsets.
- P1.5-002 (HIGH): SalaryIncentives SAL prefix deadlock + SalaryReceipts RCPT cross-table collision enforcement.
- P1.5-003 (HIGH): Token revocation fail-closed on missing sheet / read exception / malformed payload + auth hardening.
- P1.5-004 (HIGH): PHASE1_MASTER_AUDIT_REPORT.md exact 12 conflicting core tables verification.
- P1.5-005 (MEDIUM): Schema reconciliation unlock validation against trusted REQUIRED_TABS + variance baseline.
- P1.5-006 (MEDIUM): Backend Group 02 (Suppliers) & Group 10 (Expenses) header_mapping_status accuracy.
- P1.5-007 (MEDIUM): Pre-write ID prefix, duplicate, cross-table, and child-row validation BEFORE any HTTP POST.
- P1.5-008 (MEDIUM): Read-only Sheets OAuth scope, offline migration fail-closed guard, legacy scripts fail-closed, router static audit.
- P1.5-009 (LOW): Mock JWT HMAC signature & expiry enforcement, configurable login lockout duration/message, production spreadsheet ID fail-closed.
"""

import ast
import asyncio
import json
import os
import pathlib
import re
import time
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.auth as auth_mod
import app.apps_script_bridge as bridge_mod
import app.config as config_mod
import app.routers.auth as auth_router_mod
import app.schema_registry as schema_reg
import app.sheets as sheets_mod
import app.workforce_migration as wf_mig_mod
from app.action_registry import GOVERNED_ACTION_REGISTRY, get_governed_action_spec
from app.apps_script_bridge import AppsScriptBridge


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


class _FakeBridgeHttpResponse:
    def __init__(self, body: dict, status: int = 200):
        self._raw = json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestP15001SecondaryTabSchemaBypass(unittest.TestCase):
    def setUp(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def test_p15001_non_empty_subset_invalidate_tabs_cannot_bypass_schema_guard(self):
        """Reproduces exact P1.5-001 exploit: passing invalidate_tabs=['GoodsReceipts'] on RECEIVE_GOODS."""
        bridge = AppsScriptBridge()
        with patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            # Exact RECEIVE_GOODS pattern from purchasing.py
            res_grn = bridge.execute_governed_write(
                action="RECEIVE_GOODS",
                target_tab="GoodsReceipts",
                payload={"grn": {"po_id": "PO-000001"}},
                nonce="NONCE-P15001-GRN",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="receipt_id",
                invalidate_tabs=["GoodsReceipts"],
            )
            self.assertEqual(res_grn.status, "BLOCKED_PENDING_OWNER_SETUP")
            self.assertEqual(res_grn.http_status, 503)
            self.assertEqual(res_grn.error_code, "CORE_SCHEMA_CONFLICT_UNRECONCILED")
            self.assertIn("RawMaterials", res_grn.message)

            # Exact RECORD_MILLING_BATCH pattern from v2_erp.py
            res_mill = bridge.execute_governed_write(
                action="RECORD_MILLING_BATCH",
                target_tab="MillingBatches",
                payload={"milling_batch": {"raw_material_id": "RM-000001"}},
                nonce="NONCE-P15001-MILL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="milling_batch_id",
                invalidate_tabs=["MillingBatches", "RawMaterialLedger"],
            )
            self.assertEqual(res_mill.status, "BLOCKED_PENDING_OWNER_SETUP")
            self.assertEqual(res_mill.http_status, 503)
            self.assertEqual(res_mill.error_code, "CORE_SCHEMA_CONFLICT_UNRECONCILED")
            self.assertIn("RawMaterials", res_mill.message)

            # Zero HTTP calls attempted when blocked
            mock_opener.assert_not_called()

    def test_p15001_all_actions_touching_any_write_blocked_tab_fail_closed_for_all_inv_forms(self):
        """Every governed action touching ANY blocked tab (primary, allowed_invalidate_tabs, or child_checks) must fail closed."""
        bridge = AppsScriptBridge()
        checked_actions = 0
        with patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            for action_name, spec in GOVERNED_ACTION_REGISTRY.items():
                authoritative_tabs = (
                    {spec.target_tab}
                    | set(spec.allowed_invalidate_tabs)
                    | {c.tab for c in spec.readback.child_checks}
                )
                blocked_tabs = authoritative_tabs & schema_reg.WRITE_BLOCKED_SCHEMA_TABS
                if not blocked_tabs:
                    continue
                checked_actions += 1
                # Try passing empty list, primary-only subset, and None
                for inv in ([spec.target_tab], [], None):
                    res = bridge.execute_governed_write(
                        action=spec.action,
                        target_tab=spec.target_tab,
                        payload={"probe": True},
                        nonce=f"NONCE-ALL-{action_name}-{repr(inv)}",
                        actor_user_id="USR-OWNER-001",
                        actor_role="OWNER_ADMIN",
                        id_field=spec.id_field,
                        invalidate_tabs=inv,
                    )
                    self.assertEqual(
                        res.status,
                        "BLOCKED_PENDING_OWNER_SETUP",
                        f"Action {action_name} bypassed schema guard with invalidate_tabs={inv!r}",
                    )
                    self.assertEqual(res.http_status, 503)
                    self.assertIn(
                        res.error_code,
                        {"CORE_SCHEMA_CONFLICT_UNRECONCILED", "PENDING_OWNER_MAPPING"},
                    )
                    self.assertFalse(res.retryable)
            mock_opener.assert_not_called()
        self.assertGreaterEqual(checked_actions, 30)

    def test_p15001_router_callsites_include_secondary_tabs(self):
        """Verify purchasing.py and v2_erp.py call-sites explicitly declare secondary tabs."""
        purchasing_src = (BACKEND_DIR / "app" / "routers" / "purchasing.py").read_text(encoding="utf-8")
        v2_src = (BACKEND_DIR / "app" / "routers" / "v2_erp.py").read_text(encoding="utf-8")
        self.assertIn('"RawMaterials"', purchasing_src)
        self.assertIn('"PurchaseOrders"', purchasing_src)
        self.assertIn(
            'invalidate_tabs=["MillingBatches", "RawMaterialLedger", "RawMaterials", "JournalHeaders", "JournalLines"]',
            v2_src,
        )
        self.assertIn(
            'invalidate_tabs=["PackagingBatches", "ProductionStockLedger", "ProductLots", "Products"]',
            v2_src,
        )
        self.assertIn(
            'invalidate_tabs=["ProductionBatches", "ProductLots", "ProductionStockLedger", "RawMaterialLedger", "RawMaterials"]',
            v2_src,
        )


class TestP15002SalaryIncentiveDeadlockAndRcptCollision(unittest.TestCase):
    def setUp(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def test_p15002_create_salary_incentive_not_deadlocked_and_blocks_sal_collision(self):
        spec = get_governed_action_spec("CREATE_SALARY_INCENTIVE")
        self.assertIsNotNone(spec)
        self.assertIsNone(spec.locked_prefix)
        # Valid non-colliding canonical incentive IDs are accepted on new allocation
        self.assertTrue(AppsScriptBridge._validate_id_format(spec, "SINC-000001", for_new_allocation=True))
        self.assertTrue(AppsScriptBridge._validate_id_format(spec, "INC-000001", for_new_allocation=True))
        # Colliding SAL prefix is rejected on new allocation, allowed on historical read
        self.assertFalse(AppsScriptBridge._validate_id_format(spec, "SAL-000001", for_new_allocation=True))
        self.assertTrue(AppsScriptBridge._validate_id_format(spec, "SAL-000001", for_new_allocation=False))
        # Wrong locked prefixes belonging to other tables are rejected on new allocation
        self.assertFalse(AppsScriptBridge._validate_id_format(spec, "CUST-000001", for_new_allocation=True))
        self.assertFalse(AppsScriptBridge._validate_id_format(spec, "RCPT-000001", for_new_allocation=True))
        # Malformed IDs rejected
        self.assertFalse(AppsScriptBridge._validate_id_format(spec, "BAD", for_new_allocation=True))
        self.assertFalse(AppsScriptBridge._validate_id_format(spec, "", for_new_allocation=True))

    def test_p15002_no_governed_action_has_prefix_validation_deadlock(self):
        """Every single one of the 127 governed actions must accept at least one valid new-allocation ID."""
        self.assertGreaterEqual(len(GOVERNED_ACTION_REGISTRY), 120)
        for action_name, spec in GOVERNED_ACTION_REGISTRY.items():
            if not spec.requires_allocated_id:
                continue
            effective = AppsScriptBridge._effective_locked_prefix(spec)
            candidate = f"{effective}-000001" if effective else "TESTID-000001"
            self.assertTrue(
                AppsScriptBridge._validate_id_format(spec, candidate, for_new_allocation=True),
                f"Deadlock detected: action {action_name} (tab={spec.target_tab}) rejected candidate {candidate}",
            )

    def test_p15002_salary_receipts_rcpt_collision_blocked_prewrite_and_postwrite(self):
        bridge = AppsScriptBridge()
        # Pre-write rejection of colliding RCPT-* on RECORD_WORKFORCE_PAYMENT child SalaryReceipts
        with patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", return_value=[]):
            res = bridge.execute_governed_write(
                action="RECORD_WORKFORCE_PAYMENT",
                target_tab="WorkforcePayments",
                payload={
                    "payment": {"worker_id": "WRK-000001", "amount": 5000},
                    "receipt": {"receipt_id": "RCPT-000001", "receipt_number": "RCPT-000001"},
                },
                nonce="NONCE-P15002-RCPT-COLLIDE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(res.status, "REJECTED")
            self.assertEqual(res.http_status, 422)
            self.assertEqual(res.error_code, "INVALID_CHILD_ID_FORMAT")
            mock_opener.assert_not_called()

        # Pre-write cross-table collision check when Payments tries to reuse an existing SalaryReceipts ID
        schema_reg.approve_core_schema_reconciliation(
            "Sales",
            headers=schema_reg.get_expected_canonical_reconciliation_headers("Sales"),
            approved_by="USR-OWNER-001",
        )

        def fake_get_records(tab_name, fresh=False):
            if tab_name == "SalaryReceipts":
                return [{"receipt_id": "RCPT-000099", "receipt_number": "RCPT-000099"}]
            return []

        with patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", side_effect=fake_get_records):
            res = bridge.execute_governed_write(
                action="RECORD_SALE_PAYMENT",
                target_tab="Payments",
                payload={"payment_id": "RCPT-000099", "sale_id": "INV-000001", "amount": 100},
                nonce="NONCE-P15002-CROSS-TAB",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(res.status, "REJECTED")
            self.assertEqual(res.http_status, 409)
            self.assertEqual(res.error_code, "CROSS_TABLE_ID_COLLISION")
            mock_opener.assert_not_called()


class TestP15003TokenRevocationFailClosedAndAuthHardening(unittest.TestCase):
    def setUp(self):
        auth_mod._REVOKED_TOKENS.clear()
        auth_mod._USER_REVOKED_AT.clear()
        auth_router_mod._LOGIN_ATTEMPTS.clear()

    def tearDown(self):
        auth_mod._REVOKED_TOKENS.clear()
        auth_mod._USER_REVOKED_AT.clear()
        auth_router_mod._LOGIN_ATTEMPTS.clear()

    def _make_auth_row(self, **overrides):
        row = {
            "user_id": "USR-000001",
            "username": "owner",
            "full_name": "Owner",
            "role": "OWNER_ADMIN",
            "active": "true",
            "sessions_revoked_at": "",
            "password_hash": auth_mod.hash_password("ValidPass#2026"),
        }
        row.update(overrides)
        return row

    def test_p15003_revoked_tokens_read_failure_fails_closed_503(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        auth_row = self._make_auth_row()

        def fake_get_records(tab_name, fresh=False):
            if tab_name == "AuthUsers":
                return [auth_row]
            if tab_name == "RevokedTokens":
                raise RuntimeError("Google Sheets RevokedTokens tab unavailable")
            return []

        with patch.object(sheets_mod.db, "get_records", side_effect=fake_get_records):
            # Direct helper raises RevocationVerificationError
            payload = auth_mod.decode_access_token(token)
            with self.assertRaises(auth_mod.RevocationVerificationError):
                auth_mod.is_token_revoked(token, payload)

            # get_current_user fails closed with 503 REVOCATION_STORE_UNAVAILABLE
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail["error_code"], "REVOCATION_STORE_UNAVAILABLE")

    def test_p15003_malformed_revoked_tokens_payload_fails_closed_503(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        auth_row = self._make_auth_row()

        for bad_response in (None, "not-a-list", {"bad": "dict"}, ["not-a-dict-row"]):
            def fake_get_records(tab_name, fresh=False, _bad=bad_response):
                if tab_name == "AuthUsers":
                    return [auth_row]
                if tab_name == "RevokedTokens":
                    return _bad
                return []

            with patch.object(sheets_mod.db, "get_records", side_effect=fake_get_records):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(auth_mod.get_current_user(creds))
                self.assertEqual(ctx.exception.status_code, 503)
                self.assertEqual(ctx.exception.detail["error_code"], "REVOCATION_DATA_MALFORMED")

    def test_p15003_confirmed_revoked_and_non_revoked_tokens_handled_accurately(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        payload = auth_mod.decode_access_token(token)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        auth_row = self._make_auth_row()

        # Confirmed non-revoked succeeds
        with patch.object(
            sheets_mod.db,
            "get_records",
            side_effect=lambda tab, fresh=False: [auth_row] if tab == "AuthUsers" else [],
        ):
            user = asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(user["user_id"], "USR-000001")

        # Confirmed revoked in RevokedTokens sheet fails with 401
        with patch.object(
            sheets_mod.db,
            "get_records",
            side_effect=lambda tab, fresh=False: (
                [auth_row] if tab == "AuthUsers" else [{"jti": payload["jti"], "user_id": "USR-000001"}]
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 401)

    def test_p15003_corrupted_sessions_revoked_at_fails_closed_401(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        auth_row = self._make_auth_row(sessions_revoked_at="NOT-A-VALID-TIMESTAMP")

        with patch.object(
            sheets_mod.db,
            "get_records",
            side_effect=lambda tab, fresh=False: [auth_row] if tab == "AuthUsers" else [],
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 401)

    def test_p15003_account_deactivation_consistency_on_login_and_token_check(self):
        for inactive_val in ("false", "False", "0", "no", "NO", ""):
            self.assertTrue(auth_mod.is_account_deactivated(inactive_val))
        for active_val in ("true", "TRUE", "1", "yes", None):
            self.assertFalse(auth_mod.is_account_deactivated(active_val))

    def test_p15003_logout_warns_when_persistence_fails(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch.object(auth_router_mod, "revoke_token", return_value=False):
            result = asyncio.run(
                auth_router_mod.logout(
                    credentials=creds,
                    current_user={"user_id": "USR-000001", "role": "OWNER_ADMIN"},
                )
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["persisted"])
            self.assertIn("warning", result)
            self.assertIn("local", result["warning"].lower())


class TestP15004SchemaConflictAuditReportAccuracy(unittest.TestCase):
    def test_p15004_phase1_master_audit_report_matches_exact_12_conflicting_tabs(self):
        report_path = REPO_ROOT / "PHASE1_MASTER_AUDIT_REPORT.md"
        self.assertTrue(report_path.exists())
        text = report_path.read_text(encoding="utf-8")

        # Extract table rows under "### The 12 Conflicting Core Tables"
        section_match = re.search(
            r"### The 12 Conflicting Core Tables.*?\n(.*?)\n---",
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(section_match, "Could not locate The 12 Conflicting Core Tables section in PHASE1_MASTER_AUDIT_REPORT.md")
        section_body = section_match.group(1)

        reported_tabs = set(re.findall(r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|", section_body, flags=re.MULTILINE))
        self.assertEqual(
            reported_tabs,
            schema_reg.CONFLICTING_CORE_SCHEMA_TABS,
            f"Report tabs {sorted(reported_tabs)} do not match schema_registry.CONFLICTING_CORE_SCHEMA_TABS",
        )
        # Ensure previously misreported non-conflicting tables are NOT listed as conflicting core tables
        for wrong_tab in (
            "ApprovalRequests", "Attendance", "DailyClosings", "GoodsReceipts",
            "MillingBatches", "StockMovements", "SupplierBills",
        ):
            self.assertNotIn(wrong_tab, reported_tabs)


class TestP15005SafeSchemaReconciliationUnlock(unittest.TestCase):
    def setUp(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def test_p15005_rejects_arbitrary_partial_extra_and_reordered_headers(self):
        canonical = schema_reg.get_expected_canonical_reconciliation_headers("Customers")
        self.assertGreater(len(canonical), 5)

        # 1. Arbitrary fake headers
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001"
            )
        # 2. Missing required baseline columns
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers", headers=canonical[1:], approved_by="USR-OWNER-001"
            )
        # 3. Missing declared variance column ('notes')
        without_notes = [h for h in canonical if h != "notes"]
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers", headers=without_notes, approved_by="USR-OWNER-001"
            )
        # 4. Unexpected extra column
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers", headers=canonical + ["injected_extra_col"], approved_by="USR-OWNER-001"
            )
        # 5. Reordered baseline leading columns
        reordered = list(canonical)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers", headers=reordered, approved_by="USR-OWNER-001"
            )
        # 6. Physical headers mismatch
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "Customers",
                headers=canonical,
                approved_by="USR-OWNER-001",
                physical_headers=canonical[:-1] + ["wrong_physical_col"],
            )
        # 7. Non-conflicting / untrusted extended tab
        with self.assertRaises(ValueError):
            schema_reg.approve_core_schema_reconciliation(
                "SalesOrders", headers=["order_id"], approved_by="USR-OWNER-001"
            )

        # Tab must remain blocked after all invalid attempts
        self.assertIsNotNone(schema_reg.get_schema_write_block_reason("Customers"))

    def test_p15005_env_var_reconciliation_rejects_arbitrary_and_accepts_exact_canonical(self):
        canonical = schema_reg.get_expected_canonical_reconciliation_headers("Customers")
        bad_env = json.dumps({
            "Customers": {
                "status": "RECONCILED_OWNER_APPROVED",
                "approved_by": "USR-OWNER-001",
                "headers": ["totally_fake_column"],
            }
        })
        with patch.dict(os.environ, {"SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON": bad_env}):
            self.assertEqual(schema_reg.get_approved_core_schema_reconciliations(), {})
            self.assertIsNotNone(schema_reg.get_schema_write_block_reason("Customers"))

        good_env = json.dumps({
            "Customers": {
                "status": "RECONCILED_OWNER_APPROVED",
                "approved_by": "USR-OWNER-001",
                "headers": canonical,
                "physical_headers": canonical,
            }
        })
        with patch.dict(os.environ, {"SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON": good_env}):
            approved = schema_reg.get_approved_core_schema_reconciliations()
            self.assertIn("Customers", approved)
            self.assertIsNone(schema_reg.get_schema_write_block_reason("Customers"))
            # Other 11 conflicting core tables remain blocked
            self.assertIsNotNone(schema_reg.get_schema_write_block_reason("Sales"))

    def test_p15005_valid_canonical_unlock_with_matching_physical_headers_succeeds(self):
        canonical = schema_reg.get_expected_canonical_reconciliation_headers("Customers")
        entry = schema_reg.approve_core_schema_reconciliation(
            "Customers",
            headers=canonical,
            approved_by="USR-OWNER-001",
            physical_headers=list(canonical),
        )
        self.assertEqual(entry["status"], "RECONCILED_OWNER_APPROVED")
        self.assertIsNone(schema_reg.get_schema_write_block_reason("Customers"))
        self.assertIsNotNone(schema_reg.get_schema_write_block_reason("Suppliers"))


class TestP15006BackendGroupStatusAlignment(unittest.TestCase):
    def test_p15006_group_02_and_group_10_not_labeled_verified_core(self):
        g02 = next(g for g in schema_reg.DATABASE_GROUPS_15 if g["group_code"] == "02")
        g10 = next(g for g in schema_reg.DATABASE_GROUPS_15 if g["group_code"] == "10")
        self.assertEqual(g02["header_mapping_status"], "CONFLICT_RECONCILIATION_REQUIRED")
        self.assertEqual(g10["header_mapping_status"], "CONFLICT_RECONCILIATION_REQUIRED")


class TestP15007PreWriteIdValidation(unittest.TestCase):
    def setUp(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        schema_reg.clear_runtime_core_schema_reconciliations()

    def test_p15007_invalid_prefix_and_duplicate_id_rejected_before_http_post(self):
        bridge = AppsScriptBridge()
        # Use CREATE_PURCHASE_ORDER (PurchaseOrders is not in WRITE_BLOCKED_SCHEMA_TABS, locked prefix PO)
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", return_value=[{"po_id": "PO-000010"}]):
            # 1. Wrong prefix supplied in payload -> rejected BEFORE HTTP POST
            res_bad_prefix = bridge.execute_governed_write(
                action="CREATE_PURCHASE_ORDER",
                target_tab="PurchaseOrders",
                payload={"po_id": "CUST-000001", "supplier_id": "SUP-000001"},
                nonce="NONCE-P15007-BADPFX",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="po_id",
            )
            self.assertEqual(res_bad_prefix.status, "REJECTED")
            self.assertEqual(res_bad_prefix.http_status, 422)
            self.assertEqual(res_bad_prefix.error_code, "INVALID_PAYLOAD_ID_FORMAT")

            # 2. Malformed ID supplied in payload -> rejected BEFORE HTTP POST
            res_malformed = bridge.execute_governed_write(
                action="CREATE_PURCHASE_ORDER",
                target_tab="PurchaseOrders",
                payload={"po_id": "PO12", "supplier_id": "SUP-000001"},
                nonce="NONCE-P15007-MALFORMED",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="po_id",
            )
            self.assertEqual(res_malformed.status, "REJECTED")
            self.assertEqual(res_malformed.http_status, 422)
            self.assertEqual(res_malformed.error_code, "INVALID_PAYLOAD_ID_FORMAT")

            # 3. Duplicate primary ID -> rejected BEFORE HTTP POST with 409
            res_dup = bridge.execute_governed_write(
                action="CREATE_PURCHASE_ORDER",
                target_tab="PurchaseOrders",
                payload={"po_id": "PO-000010", "supplier_id": "SUP-000001"},
                nonce="NONCE-P15007-DUP",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="po_id",
            )
            self.assertEqual(res_dup.status, "REJECTED")
            self.assertEqual(res_dup.http_status, 409)
            self.assertEqual(res_dup.error_code, "DUPLICATE_RECORD_ID")

            # 4. Update/cancel with explicit blank target ID -> rejected BEFORE HTTP POST
            res_blank = bridge.execute_governed_write(
                action="CANCEL_PURCHASE_ORDER",
                target_tab="PurchaseOrders",
                payload={"po_id": "   ", "status": "CANCELLED"},
                nonce="NONCE-P15007-BLANK",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="po_id",
            )
            self.assertEqual(res_blank.status, "REJECTED")
            self.assertEqual(res_blank.http_status, 422)
            self.assertEqual(res_blank.error_code, "MISSING_TARGET_IDENTIFIER")

            # CRITICAL: Zero HTTP calls were executed for any of the 4 rejected requests!
            mock_opener.assert_not_called()

    def test_p15007_invalid_child_journal_line_id_rejected_before_http_post(self):
        bridge = AppsScriptBridge()
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", return_value=[]):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload={
                    "journal_id": "JV-000001",
                    "lines": [
                        {"line_id": "CUST-000001", "debit": 100, "credit": 0},
                    ],
                },
                nonce="NONCE-P15007-JRNLINE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(res.status, "REJECTED")
            self.assertEqual(res.http_status, 422)
            self.assertEqual(res.error_code, "INVALID_CHILD_ID_FORMAT")
            mock_opener.assert_not_called()


class TestP15008DirectWritePathsAndReadOnlyOAuthScope(unittest.TestCase):
    def test_p15008_sheets_oauth_scopes_are_strictly_readonly(self):
        self.assertEqual(
            sheets_mod.SHEETS_OAUTH_SCOPES,
            ["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        sheets_src = (BACKEND_DIR / "app" / "sheets.py").read_text(encoding="utf-8")
        self.assertNotIn("https://www.googleapis.com/auth/spreadsheets\"", sheets_src)
        self.assertNotIn("https://www.googleapis.com/auth/drive.file", sheets_src)

    def test_p15008_workforce_migration_fails_closed_without_explicit_offline_flag(self):
        with patch.dict(
            os.environ,
            {"SALES_TESTING": "0", "SALES_ALLOW_OFFLINE_SHEETS_MIGRATION": "false"},
            clear=False,
        ):
            with self.assertRaises(wf_mig_mod.AuthorizationError) as ctx_exec:
                wf_mig_mod._assert_offline_migration_allowed("execute_workforce_migration")
            self.assertIn("Single-Write-Owner", str(ctx_exec.exception))

            with self.assertRaises(wf_mig_mod.AuthorizationError) as ctx_rb:
                wf_mig_mod._assert_offline_migration_allowed("rollback_workforce_migration")
            self.assertIn("Single-Write-Owner", str(ctx_rb.exception))

    def test_p15008_legacy_direct_write_scripts_fail_closed_by_default(self):
        for script_name in ("bootstrap_owner.py", "reset_password.py", "update_sheets_recipe_master.py"):
            script_path = BACKEND_DIR / "scripts" / script_name
            src = script_path.read_text(encoding="utf-8")
            self.assertIn('SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"', src)
            self.assertIn("BLOCKED_SINGLE_WRITE_OWNER", src)
            self.assertIn("_assert_offline_script_allowed", src)

    def test_p15008_zero_direct_sheets_mutations_or_rogue_http_in_routers(self):
        forbidden_db_methods = {
            "append_row", "append_rows", "update_row", "delete_row",
            "update_cell", "batch_update", "clear", "insert_row",
        }
        routers_dir = BACKEND_DIR / "app" / "routers"
        for py_file in sorted(routers_dir.glob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "db":
                        self.assertNotIn(
                            node.func.attr,
                            forbidden_db_methods,
                            f"Direct db.{node.func.attr}() found in {py_file.name}:{node.lineno}",
                        )


class TestP15009AuthConfigLockoutAndTestFidelity(unittest.TestCase):
    def setUp(self):
        auth_router_mod._LOGIN_ATTEMPTS.clear()

    def tearDown(self):
        auth_router_mod._LOGIN_ATTEMPTS.clear()

    def test_p15009_jwt_rejects_expired_and_tampered_tokens_accepts_valid(self):
        valid_token = auth_mod.create_access_token(
            {"user_id": "USR-000001", "role": "OWNER_ADMIN"},
            expires_delta=timedelta(minutes=5),
        )
        decoded = auth_mod.decode_access_token(valid_token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["user_id"], "USR-000001")

        # Expired token MUST be rejected even under mock jwt fallback
        expired_token = auth_mod.create_access_token(
            {"user_id": "USR-000001", "role": "OWNER_ADMIN"},
            expires_delta=timedelta(seconds=-10),
        )
        self.assertIsNone(auth_mod.decode_access_token(expired_token))

        # Tampered signature MUST be rejected
        parts = valid_token.split(".")
        self.assertEqual(len(parts), 3)
        tampered = f"{parts[0]}.{parts[1]}.tampered_sig_0000"
        self.assertIsNone(auth_mod.decode_access_token(tampered))

    def test_p15009_login_lockout_duration_and_message_match_and_reset_correctly(self):
        from fastapi import BackgroundTasks
        from app.models import LoginRequest

        # Verify default lockout config consistency (300s = 5 minutes)
        self.assertEqual(config_mod.SALES_LOGIN_MAX_ATTEMPTS, 5)
        self.assertEqual(config_mod.SALES_LOGIN_LOCKOUT_SECONDS, 300.0)
        self.assertEqual(auth_router_mod._format_lockout_duration(300.0), "5 minutes")
        self.assertEqual(auth_router_mod._format_lockout_duration(60.0), "1 minute")
        self.assertEqual(auth_router_mod._format_lockout_duration(45.0), "45 seconds")

        auth_row = {
            "user_id": "USR-000001",
            "username": "testuser",
            "full_name": "Test User",
            "role": "OWNER_ADMIN",
            "active": "true",
            "password_hash": auth_mod.hash_password("CorrectPass#2026"),
        }
        deactivated_row = {
            "user_id": "USR-000002",
            "username": "disableduser",
            "full_name": "Disabled",
            "role": "FIELD_SALESMAN",
            "active": "0",
            "password_hash": auth_mod.hash_password("CorrectPass#2026"),
        }

        with patch.object(auth_router_mod, "_MAX_FAILED_ATTEMPTS", 3), \
             patch.object(auth_router_mod, "_LOCKOUT_WINDOW_SECONDS", 120.0), \
             patch.object(auth_router_mod.db, "get_records", return_value=[auth_row, deactivated_row]):
            # Deactivated user with active="0" is rejected with 403
            with self.assertRaises(HTTPException) as ctx_dis:
                asyncio.run(
                    auth_router_mod.login(
                        LoginRequest(username="disableduser", password="CorrectPass#2026"),
                        BackgroundTasks(),
                    )
                )
            self.assertEqual(ctx_dis.exception.status_code, 403)

            # 3 failed attempts trigger 401, 4th attempt triggers 429 with matching "2 minutes" message
            for _ in range(3):
                with self.assertRaises(HTTPException) as ctx_bad:
                    asyncio.run(
                        auth_router_mod.login(
                            LoginRequest(username="testuser", password="WrongPassword!"),
                            BackgroundTasks(),
                        )
                    )
                self.assertEqual(ctx_bad.exception.status_code, 401)

            with self.assertRaises(HTTPException) as ctx_lock:
                asyncio.run(
                    auth_router_mod.login(
                        LoginRequest(username="testuser", password="CorrectPass#2026"),
                        BackgroundTasks(),
                    )
                )
            self.assertEqual(ctx_lock.exception.status_code, 429)
            self.assertIn("2 minutes", str(ctx_lock.exception.detail))

            # Advance timestamps beyond 120s window -> lockout expires -> successful login succeeds & clears attempts
            auth_router_mod._LOGIN_ATTEMPTS["testuser"] = [time.time() - 125.0] * 3
            token_resp = asyncio.run(
                auth_router_mod.login(
                    LoginRequest(username="testuser", password="CorrectPass#2026"),
                    BackgroundTasks(),
                )
            )
            self.assertEqual(token_resp.user_id, "USR-000001")
            self.assertNotIn("testuser", auth_router_mod._LOGIN_ATTEMPTS)

    def test_p15009_require_sheets_connection_fails_closed_in_production_without_spreadsheet_id(self):
        with patch.object(config_mod, "SALES_ENV", "production"), \
             patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", ""), \
             patch.object(sheets_mod.db, "is_connected", True):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.require_sheets_connection())
            self.assertEqual(ctx.exception.status_code, 503)

    def test_p15009_malformed_jwt_rejected_by_decode_and_get_current_user(self):
        for bad_jwt in ("", "not-a-jwt", "only.two", "a.b.c", "eyJ.invalid.payload"):
            self.assertIsNone(auth_mod.decode_access_token(bad_jwt))
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=bad_jwt or "x")
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 401)


class TestPhase16AdditionalAdversarialGuards(unittest.TestCase):
    def setUp(self):
        schema_reg.clear_runtime_core_schema_reconciliations()
        auth_mod._REVOKED_TOKENS.clear()
        auth_mod._USER_REVOKED_AT.clear()

    def tearDown(self):
        schema_reg.clear_runtime_core_schema_reconciliations()
        auth_mod._REVOKED_TOKENS.clear()
        auth_mod._USER_REVOKED_AT.clear()

    def test_p15001_unknown_requested_invalidation_tab_fails_closed_zero_http(self):
        bridge = AppsScriptBridge()
        with patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            res = bridge.execute_governed_write(
                action="CREATE_PURCHASE_ORDER",
                target_tab="PurchaseOrders",
                payload={"supplier_id": "SUP-000001"},
                nonce="NONCE-P15001-UNKNOWN-TAB",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="po_id",
                invalidate_tabs=["PurchaseOrders", "TotallyUnknownTab"],
            )
            self.assertEqual(res.status, "REJECTED")
            self.assertEqual(res.http_status, 422)
            self.assertEqual(res.error_code, "UNAUTHORIZED_INVALIDATION_TAB")
            mock_opener.assert_not_called()

    def test_p15003_protected_write_and_auth_request_denied_during_revocation_outage(self):
        token = auth_mod.create_access_token({"user_id": "USR-000001", "role": "OWNER_ADMIN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        auth_row = {
            "user_id": "USR-000001",
            "username": "owner",
            "full_name": "Owner",
            "role": "OWNER_ADMIN",
            "active": "true",
            "sessions_revoked_at": "",
        }

        def outage_records(tab_name, fresh=False):
            if tab_name == "AuthUsers":
                return [auth_row]
            if tab_name == "RevokedTokens":
                raise ConnectionError("Simulated Google Sheets network outage")
            return []

        with patch.object(sheets_mod.db, "get_records", side_effect=outage_records), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            # Protected write gate (get_current_user dependency) denies with 503 before any write executes
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth_mod.get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail["error_code"], "REVOCATION_STORE_UNAVAILABLE")
            mock_opener.assert_not_called()

    def test_p15005_reconciliation_rejection_emits_clear_warning_logs(self):
        with self.assertLogs("kawad_swad.schema_registry", level="WARNING") as cm:
            with self.assertRaises(ValueError):
                schema_reg.approve_core_schema_reconciliation(
                    "Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001"
                )
        joined = "\n".join(cm.output)
        self.assertIn("Customers", joined)
        self.assertIn("rejected", joined.lower())

        bad_env = json.dumps({
            "Customers": {
                "status": "RECONCILED_OWNER_APPROVED",
                "approved_by": "USR-OWNER-001",
                "headers": ["totally_fake_column"],
            }
        })
        with patch.dict(os.environ, {"SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON": bad_env}):
            with self.assertLogs("kawad_swad.schema_registry", level="WARNING") as cm_env:
                self.assertEqual(schema_reg.get_approved_core_schema_reconciliations(), {})
            self.assertIn("Customers", "\n".join(cm_env.output))

    def test_p15002_p15007_duplicate_child_ids_in_same_request_and_workforce_cross_table_collision(self):
        bridge = AppsScriptBridge()
        # 1. Duplicate child IDs within the SAME request payload
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", return_value=[]):
            res_dup_in_req = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload={
                    "journal_id": "JV-000001",
                    "lines": [
                        {"line_id": "JVL-000001", "debit": 100, "credit": 0},
                        {"line_id": "JVL-000001", "debit": 0, "credit": 100},
                    ],
                },
                nonce="NONCE-SAME-REQ-DUP",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
            self.assertEqual(res_dup_in_req.status, "REJECTED")
            self.assertEqual(res_dup_in_req.http_status, 409)
            self.assertEqual(res_dup_in_req.error_code, "DUPLICATE_CHILD_RECORD_ID")
            mock_opener.assert_not_called()

        # 2. RECORD_WORKFORCE_PAYMENT child SalaryReceipts ID colliding with existing Payments row
        def fake_payments_collision(tab_name, fresh=False):
            if tab_name == "Payments":
                return [{"payment_id": "SRCP-000077", "receipt_id": "SRCP-000077"}]
            return []

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", side_effect=fake_payments_collision):
            res_cross = bridge.execute_governed_write(
                action="RECORD_WORKFORCE_PAYMENT",
                target_tab="WorkforcePayments",
                payload={
                    "payment": {"worker_id": "WRK-000001", "amount": 5000},
                    "receipt": {"receipt_id": "SRCP-000077"},
                },
                nonce="NONCE-CROSS-PAY",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(res_cross.status, "REJECTED")
            self.assertEqual(res_cross.http_status, 409)
            self.assertEqual(res_cross.error_code, "CROSS_TABLE_ID_COLLISION")
            mock_opener.assert_not_called()

    def test_p15008_offline_opt_in_cannot_activate_in_production_and_direct_db_write_blocked(self):
        # Even when SALES_ALLOW_OFFLINE_SHEETS_MIGRATION=1 is set, SALES_ENV=production MUST fail closed
        with patch.dict(
            os.environ,
            {"SALES_ENV": "production", "SALES_ALLOW_OFFLINE_SHEETS_MIGRATION": "1", "SALES_TESTING": "0"},
            clear=False,
        ):
            with self.assertRaises(wf_mig_mod.AuthorizationError):
                wf_mig_mod._assert_offline_migration_allowed("execute_workforce_migration")

        # Direct db.append_record() fails closed when allow_in_memory_fallback=False
        with patch.object(sheets_mod.db, "allow_in_memory_fallback", False):
            with self.assertRaises(RuntimeError) as ctx_db:
                sheets_mod.db.append_record("Sales", {"sale_id": "INV-000001"})
            self.assertIn("BLOCKED_PENDING_OWNER_SETUP", str(ctx_db.exception))

        # migrate_workforce_stage3.py declares SCRIPT_MUTATION_MODE and enforces offline opt-in
        mig_cli_src = (BACKEND_DIR / "scripts" / "migrate_workforce_stage3.py").read_text(encoding="utf-8")
        self.assertIn('SCRIPT_MUTATION_MODE = "OFFLINE_MAINTENANCE_OPT_IN_REQUIRED"', mig_cli_src)
        self.assertIn("_assert_offline_migration_allowed", mig_cli_src)


if __name__ == "__main__":
    unittest.main()
