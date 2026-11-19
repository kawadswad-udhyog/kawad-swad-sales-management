"""
Kawad Swad ERP — Phase 1 Database & Schema Contract Regression Tests.

Covers:
- DB-001: get_schema_coverage_summary(), get_table_schema_registry(), and app.main / app.routers.v2_erp imports.
- DB-002: Fail-closed write gating for ALL 12 CONFLICTING_CORE_SCHEMA_TABS + secondary-tab bypass protection
  + Owner-only reconciliation unlock validation.
- DB-003 / DB-006: Honest 91/255 blueprint coverage (164 unmapped) and zero duplicate group placement for ProductLots.
- DB-004: Canonical-only new ID allocation across all 10 legacy aliases, historical read compatibility,
  PKG/PKB collision protection, and RCPT/SAL cross-table collision guards.
- DB-005: Explicit locked_prefix enforcement across all 11 previously ungated creation actions.
"""

import unittest

from app.action_registry import GOVERNED_ACTION_REGISTRY, get_governed_action_spec
from app.schema_registry import (
    COLLIDING_LEGACY_PREFIX_TABS,
    CONFLICTING_CORE_SCHEMA_TABS,
    DATABASE_GROUPS_15,
    LEGACY_TO_LOCKED_ID_PREFIX_ALIASES,
    LOCKED_32_ID_PREFIXES,
    PENDING_OWNER_MAPPING_TABS,
    SCHEMA_HEADER_VARIANCES,
    WORKBOOK_TARGET_TAB_COUNT,
    approve_core_schema_reconciliation,
    clear_runtime_core_schema_reconciliations,
    get_allowed_id_prefixes_for_tab,
    get_schema_coverage_summary,
    get_schema_write_block_reason,
    get_table_schema_registry,
    validate_table_id_prefix,
)
from app.sheets import ID_PREFIXES, REQUIRED_TABS


EXPECTED_12_CONFLICTING_CORE_TABS = {
    "Suppliers",
    "CustomRoles",
    "SalaryIncentives",
    "RawMaterials",
    "Products",
    "Workers",
    "Customers",
    "Sales",
    "ProductionBatches",
    "PackagingBatches",
    "Expenses",
    "ShopVisits",
}

ELEVEN_AFFECTED_ACTIONS = {
    "CREATE_CUSTOMER": ("Customers", "CUST", "CUS"),
    "CREATE_RAW_MATERIAL_MASTER": ("RawMaterials", "RM", "RWM"),
    "ADJUST_FINISHED_GOODS_STOCK": ("ProductionStockLedger", "MOV", "PST"),
    "CREATE_PRODUCTION_BATCH": ("ProductionBatches", "PB", "PRB"),
    "RECORD_PACKAGING_PENDING_REVIEW": ("PackagingBatches", "PKB", "PKG"),
    "RECORD_PACKAGING_BATCH": ("PackagingBatches", "PKB", "PKG"),
    "CREATE_SALE": ("Sales", "INV", "SALE"),
    "CREATE_SALES_INVOICE": ("Sales", "INV", "SALE"),
    "CREATE_LEGACY_SALES_ORDER": ("Sales", "INV", "SALE"),
    "RECORD_SALE_PAYMENT": ("Payments", "RCPT", "PAY"),
    "RECONCILE_FACTORY_STOCK": ("ProductionStockLedger", "MOV", "PST"),
}

SECONDARY_CONFLICT_BYPASS_ACTIONS = {
    "VERIFY_RAW_MATERIAL_OPENING_STOCK": ("RawMaterialLedger", "RawMaterials"),
    "RECEIVE_RAW_MATERIAL": ("RawMaterialLedger", "RawMaterials"),
    "ADJUST_RAW_MATERIAL_STOCK": ("RawMaterialLedger", "RawMaterials"),
    "RECEIVE_GOODS": ("GoodsReceipts", "RawMaterials"),
    "RECORD_MILLING_BATCH": ("MillingBatches", "RawMaterials"),
    "RECOVER_MILLING_BATCH": ("RawMaterialLedger", "RawMaterials"),
    "ISSUE_RAW_MATERIALS": ("RawMaterialLedger", "RawMaterials"),
    "ADJUST_FINISHED_GOODS_STOCK": ("ProductionStockLedger", "Products"),
    "RECORD_SALE_PAYMENT": ("Payments", "Sales"),
    "SUBMIT_DAILY_CLOSING": ("DailyClosing", "Expenses"),
    "REJECT_APPROVAL_REQUEST": ("ApprovalRequests", "ProductionBatches"),
    "APPROVE_AND_EXECUTE_REQUEST": ("ApprovalRequests", "ProductionBatches"),
}


class TestPhase1SchemaRegistryAndContracts(unittest.TestCase):
    def setUp(self):
        clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        clear_runtime_core_schema_reconciliations()

    def test_db001_schema_coverage_summary_and_registry_integrity(self):
        summary = get_schema_coverage_summary()
        registry = get_table_schema_registry()
        self.assertEqual(len(REQUIRED_TABS), 67)
        self.assertEqual(len(ID_PREFIXES), 66)
        self.assertEqual(summary["cleaned_tab_baseline"], WORKBOOK_TARGET_TAB_COUNT)
        self.assertEqual(summary["declared_database_groups"], 15)
        self.assertEqual(summary["core_required_tabs_count"], 67)
        self.assertEqual(summary["extended_v2_contracts_count"], 24)
        self.assertEqual(summary["unique_catalogued_workbook_tabs"], 91)
        self.assertEqual(len(registry), 91)
        self.assertEqual(summary["unmapped_workbook_tabs_remaining"], 164)
        self.assertEqual(summary["conflicting_core_schema_tabs_count"], 12)
        self.assertEqual(summary["pending_owner_mapping_tabs_count"], 24)
        self.assertEqual(summary["write_blocked_schema_tabs_count"], 36)
        self.assertFalse(summary["coverage_complete"])
        self.assertEqual(summary["coverage_status"], "INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT")

    def test_db006_product_lots_single_canonical_group_placement(self):
        summary = get_schema_coverage_summary()
        self.assertEqual(summary["duplicate_group_placements"], {})
        self.assertEqual(summary["group_tab_references_total"], 91)
        group_03 = next(g for g in DATABASE_GROUPS_15 if g["group_code"] == "03")
        group_05 = next(g for g in DATABASE_GROUPS_15 if g["group_code"] == "05")
        self.assertIn("ProductLots", group_03["workbook_tabs"])
        self.assertNotIn("ProductLots", group_05["workbook_tabs"])
        self.assertIn("ProductLots", group_05.get("referenced_tabs", []))

    def test_db002_all_12_conflicting_core_tabs_blocked_and_unlock_hardened(self):
        self.assertEqual(CONFLICTING_CORE_SCHEMA_TABS, EXPECTED_12_CONFLICTING_CORE_TABS)
        for tab_name in sorted(EXPECTED_12_CONFLICTING_CORE_TABS):
            self.assertEqual(
                SCHEMA_HEADER_VARIANCES[tab_name]["status"],
                "CONFLICT_RECONCILIATION_REQUIRED",
            )
            block = get_schema_write_block_reason(tab_name)
            self.assertIsNotNone(block, f"Expected fail-closed block for conflicting core tab {tab_name}")
            self.assertEqual(block["error_code"], "CORE_SCHEMA_CONFLICT_UNRECONCILED")

        # Unlock abuse checks: empty approver, empty headers, duplicate headers, non-conflicting tab must raise
        with self.assertRaises(ValueError):
            approve_core_schema_reconciliation("Customers", headers=["customer_id"], approved_by="")
        with self.assertRaises(ValueError):
            approve_core_schema_reconciliation("Customers", headers=[], approved_by="USR-OWNER-001")
        with self.assertRaises(ValueError):
            approve_core_schema_reconciliation("Customers", headers=["a", "a"], approved_by="USR-OWNER-001")
        with self.assertRaises(ValueError):
            approve_core_schema_reconciliation("Users", headers=["user_id"], approved_by="USR-OWNER-001")

        # Valid owner reconciliation unlocks ONLY the explicitly reconciled tab
        approve_core_schema_reconciliation(
            "Customers",
            headers=["customer_id", "shop_name", "notes"],
            approved_by="USR-OWNER-001",
        )
        self.assertIsNone(get_schema_write_block_reason("Customers"))
        self.assertIsNotNone(get_schema_write_block_reason("Sales"))
        self.assertIsNotNone(get_schema_write_block_reason("Suppliers"))
        for ext_tab in PENDING_OWNER_MAPPING_TABS:
            self.assertIsNotNone(get_schema_write_block_reason(ext_tab))

    def test_db004_canonical_new_allocations_legacy_reads_and_cross_table_collisions(self):
        # All 10 legacy aliases: canonical accepted on new allocation, legacy rejected on new allocation,
        # legacy accepted on historical read
        self.assertEqual(len(LEGACY_TO_LOCKED_ID_PREFIX_ALIASES), 10)
        for tab_name, info in LEGACY_TO_LOCKED_ID_PREFIX_ALIASES.items():
            legacy = info["legacy_prefix"]
            locked = info["locked_prefix"]
            self.assertFalse(info["allow_on_new_allocation"], f"{tab_name} must reject legacy {legacy} on new allocation")
            self.assertTrue(info["allow_on_read"], f"{tab_name} must preserve legacy {legacy} on read")
            self.assertEqual(get_allowed_id_prefixes_for_tab(tab_name, for_new_allocation=True), (locked,))
            self.assertEqual(get_allowed_id_prefixes_for_tab(tab_name, for_new_allocation=False), (locked, legacy))
            self.assertTrue(validate_table_id_prefix(tab_name, f"{locked}-000123", for_new_allocation=True))
            self.assertFalse(validate_table_id_prefix(tab_name, f"{legacy}-000123", for_new_allocation=True))
            self.assertTrue(validate_table_id_prefix(tab_name, f"{legacy}-000123", for_new_allocation=False))

        # PackagingMaterials vs PackagingBatches PKG/PKB collision
        self.assertTrue(validate_table_id_prefix("PackagingMaterials", "PKG-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("PackagingMaterials", "PKB-0001", for_new_allocation=True))
        self.assertTrue(validate_table_id_prefix("PackagingBatches", "PKB-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("PackagingBatches", "PKG-0001", for_new_allocation=True))
        self.assertTrue(validate_table_id_prefix("PackagingBatches", "PKG-000001", for_new_allocation=False))

        # RCPT and SAL cross-table collision guards
        self.assertIn("SalaryReceipts", COLLIDING_LEGACY_PREFIX_TABS)
        self.assertIn("SalaryIncentives", COLLIDING_LEGACY_PREFIX_TABS)
        self.assertTrue(validate_table_id_prefix("Payments", "RCPT-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("SalaryReceipts", "RCPT-0001", for_new_allocation=True))
        self.assertTrue(validate_table_id_prefix("SalaryReceipts", "RCPT-0001", for_new_allocation=False))
        self.assertTrue(validate_table_id_prefix("SalaryPayments", "SAL-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("SalaryIncentives", "SAL-0001", for_new_allocation=True))
        self.assertTrue(validate_table_id_prefix("SalaryIncentives", "SAL-0001", for_new_allocation=False))

    def test_db005_all_11_affected_actions_declare_locked_prefix_and_enforce_validation(self):
        tab_to_locked = {tab: pfx for pfx, tab in LOCKED_32_ID_PREFIXES.items()}
        for action_name, spec in GOVERNED_ACTION_REGISTRY.items():
            if spec.requires_allocated_id and spec.target_tab in tab_to_locked:
                self.assertEqual(
                    spec.locked_prefix,
                    tab_to_locked[spec.target_tab],
                    f"Action {action_name} targeting {spec.target_tab} must declare locked_prefix={tab_to_locked[spec.target_tab]}",
                )

        for action_name, (tab_name, locked_prefix, legacy_prefix) in ELEVEN_AFFECTED_ACTIONS.items():
            spec = get_governed_action_spec(action_name)
            self.assertIsNotNone(spec)
            self.assertEqual(spec.target_tab, tab_name)
            self.assertEqual(spec.locked_prefix, locked_prefix)
            self.assertTrue(
                validate_table_id_prefix(
                    tab_name, f"{locked_prefix}-000123", for_new_allocation=True, explicit_locked_prefix=locked_prefix
                )
            )
            self.assertFalse(
                validate_table_id_prefix(
                    tab_name, f"{legacy_prefix}-000123", for_new_allocation=True, explicit_locked_prefix=locked_prefix
                )
            )
            self.assertTrue(
                validate_table_id_prefix(
                    tab_name, f"{legacy_prefix}-000123", for_new_allocation=False, explicit_locked_prefix=locked_prefix
                )
            )
            self.assertFalse(
                validate_table_id_prefix(
                    tab_name, f"{locked_prefix}000123", for_new_allocation=True, explicit_locked_prefix=locked_prefix
                )
            )
            wrong_prefix = "USR" if locked_prefix != "USR" else "PRD"
            self.assertFalse(
                validate_table_id_prefix(
                    tab_name, f"{wrong_prefix}-000123", for_new_allocation=True, explicit_locked_prefix=locked_prefix
                )
            )


class TestPhase1BridgeAndAppStartup(unittest.TestCase):
    def setUp(self):
        clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        clear_runtime_core_schema_reconciliations()

    def test_db001_app_main_and_v2_erp_import_startup(self):
        import asyncio
        from app import main as app_main
        from app.routers import v2_erp

        self.assertIsNotNone(app_main.app)
        self.assertIsNotNone(v2_erp.router)
        payload = asyncio.run(
            v2_erp.get_schema_registry_metadata(
                current_user={"user_id": "USR-OWNER-001", "role": "OWNER_ADMIN"}
            )
        )
        self.assertEqual(payload["cleaned_tab_baseline"], 255)
        summary = payload["table_registry_summary"]
        self.assertEqual(summary["total_catalogued_tabs"], 91)
        self.assertEqual(summary["unique_catalogued_workbook_tabs"], 91)
        self.assertEqual(summary["unmapped_workbook_tabs_remaining"], 164)
        self.assertEqual(summary["conflicting_core_schema_tabs_count"], 12)
        self.assertEqual(summary["write_blocked_schema_tabs_count"], 36)
        self.assertFalse(summary["coverage_complete"])
        self.assertEqual(set(payload["conflicting_core_schema_tabs"]), EXPECTED_12_CONFLICTING_CORE_TABS)
        self.assertIsInstance(payload["tab_reconciliation_conflicts"], dict)

    def test_db002_bridge_blocks_primary_and_secondary_conflicting_core_tabs(self):
        from app.apps_script_bridge import AppsScriptBridge

        bridge = AppsScriptBridge()

        # Primary target tab block for all 12 conflicting core tabs
        for tab_name in sorted(EXPECTED_12_CONFLICTING_CORE_TABS):
            spec = next((s for s in GOVERNED_ACTION_REGISTRY.values() if s.target_tab == tab_name), None)
            self.assertIsNotNone(spec)
            res = bridge.execute_governed_write(
                action=spec.action,
                target_tab=spec.target_tab,
                payload={"probe": True},
                nonce=f"NONCE-PRI-{tab_name}",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field=spec.id_field,
            )
            self.assertEqual(res.status, "BLOCKED_PENDING_OWNER_SETUP")
            self.assertEqual(res.http_status, 503)
            self.assertEqual(res.error_code, "CORE_SCHEMA_CONFLICT_UNRECONCILED")
            self.assertFalse(res.retryable)

        # Secondary-tab bypass block (both when invalidate_tabs includes secondary tab AND when omitted)
        for action_name, (primary_tab, conflicting_sec_tab) in SECONDARY_CONFLICT_BYPASS_ACTIONS.items():
            spec = get_governed_action_spec(action_name)
            self.assertIsNotNone(spec)
            self.assertEqual(spec.target_tab, primary_tab)
            action_conflicting_tabs = {
                t for t in spec.allowed_invalidate_tabs if t in EXPECTED_12_CONFLICTING_CORE_TABS
            } | {conflicting_sec_tab}
            for inv in ([primary_tab, conflicting_sec_tab], None):
                res = bridge.execute_governed_write(
                    action=spec.action,
                    target_tab=spec.target_tab,
                    payload={"probe": True},
                    nonce=f"NONCE-SEC-{action_name}-{bool(inv)}",
                    actor_user_id="USR-OWNER-001",
                    actor_role="OWNER_ADMIN",
                    id_field=spec.id_field,
                    invalidate_tabs=inv,
                )
                self.assertEqual(res.status, "BLOCKED_PENDING_OWNER_SETUP")
                self.assertEqual(res.http_status, 503)
                self.assertEqual(res.error_code, "CORE_SCHEMA_CONFLICT_UNRECONCILED")
                self.assertTrue(
                    any(tab in res.message for tab in action_conflicting_tabs),
                    f"Expected one of {sorted(action_conflicting_tabs)} in {res.message!r}",
                )

    def test_db005_bridge_validate_id_format_on_all_11_actions(self):
        from app.apps_script_bridge import AppsScriptBridge

        for action_name, (_tab, locked_prefix, legacy_prefix) in ELEVEN_AFFECTED_ACTIONS.items():
            spec = get_governed_action_spec(action_name)
            self.assertTrue(AppsScriptBridge._validate_id_format(spec, f"{locked_prefix}-000123"))
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, f"{legacy_prefix}-000123"))
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, ""))
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, f"{locked_prefix}-12"))
            wrong_prefix = "USR" if locked_prefix != "USR" else "PRD"
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, f"{wrong_prefix}-000123"))


if __name__ == "__main__":
    unittest.main()
