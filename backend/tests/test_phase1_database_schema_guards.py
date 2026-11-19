"""
Kawad Swad ERP — Phase 1 Database & Schema Contract Regression Tests (UNEXECUTED — Section 25 Moratorium).

Prepared per Phase 1 Audit (ZIP 38) Recommended Repair Order:
- DB-001: Application startup/import check for app.main, app.routers.v2_erp, and get_schema_coverage_summary.
- DB-002: Fail-closed write gating for ALL 12 CONFLICTING_CORE_SCHEMA_TABS until Owner reconciliation approval.
- DB-003 / DB-006: Honest coverage summary (91/255 catalogued, 164 unmapped) and zero duplicate group placement for ProductLots.
- DB-004: Centralized legacy ID alias validation and PKG/PKB collision protection.
- DB-005: Explicit locked_prefix enforcement across all 11 previously ungated creation actions.

NOTE: Under Master Policy Constitution v1.2 Section 25, this file is prepared as source-level test
coverage only and MUST NOT be executed until the Owner separately authorizes the testing phase.
"""

import unittest

from app import main as app_main
from app.action_registry import GOVERNED_ACTION_REGISTRY, get_governed_action_spec
from app.apps_script_bridge import AppsScriptBridge
from app.routers import v2_erp
from app.schema_registry import (
    CONFLICTING_CORE_SCHEMA_TABS,
    DATABASE_GROUPS_15,
    LOCKED_32_ID_PREFIXES,
    PENDING_OWNER_MAPPING_TABS,
    SCHEMA_HEADER_VARIANCES,
    WORKBOOK_TARGET_TAB_COUNT,
    approve_core_schema_reconciliation,
    clear_runtime_core_schema_reconciliations,
    get_allowed_id_prefixes_for_tab,
    get_schema_coverage_summary,
    get_schema_write_block_reason,
    validate_table_id_prefix,
)


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
    "RECORD_PACKAGING_PENDING_REVIEW": ("PackagingBatches", "PKB", None),
    "RECORD_PACKAGING_BATCH": ("PackagingBatches", "PKB", None),
    "CREATE_SALE": ("Sales", "INV", "SALE"),
    "CREATE_SALES_INVOICE": ("Sales", "INV", "SALE"),
    "CREATE_LEGACY_SALES_ORDER": ("Sales", "INV", "SALE"),
    "RECORD_SALE_PAYMENT": ("Payments", "RCPT", "PAY"),
    "RECONCILE_FACTORY_STOCK": ("ProductionStockLedger", "MOV", "PST"),
}


class TestPhase1DatabaseSchemaGuards(unittest.TestCase):
    def setUp(self):
        clear_runtime_core_schema_reconciliations()

    def tearDown(self):
        clear_runtime_core_schema_reconciliations()

    def test_db001_startup_imports_and_schema_coverage_summary(self):
        self.assertIsNotNone(app_main.app)
        self.assertIsNotNone(v2_erp.router)
        summary = get_schema_coverage_summary()
        self.assertEqual(summary["cleaned_tab_baseline"], WORKBOOK_TARGET_TAB_COUNT)
        self.assertEqual(summary["declared_database_groups"], 15)
        self.assertEqual(summary["core_required_tabs_count"], 67)
        self.assertEqual(summary["extended_v2_contracts_count"], 24)
        self.assertEqual(summary["unique_catalogued_workbook_tabs"], 91)
        self.assertEqual(summary["unmapped_workbook_tabs_remaining"], 164)
        self.assertEqual(summary["conflicting_core_schema_tabs_count"], 12)
        self.assertEqual(summary["pending_owner_mapping_tabs_count"], 24)
        self.assertEqual(summary["write_blocked_schema_tabs_count"], 36)
        self.assertFalse(summary["coverage_complete"])

    def test_db006_product_lots_single_canonical_group_placement(self):
        summary = get_schema_coverage_summary()
        self.assertEqual(summary["duplicate_group_placements"], {})
        self.assertEqual(summary["group_tab_references_total"], 91)
        group_03 = next(g for g in DATABASE_GROUPS_15 if g["group_code"] == "03")
        group_05 = next(g for g in DATABASE_GROUPS_15 if g["group_code"] == "05")
        self.assertIn("ProductLots", group_03["workbook_tabs"])
        self.assertNotIn("ProductLots", group_05["workbook_tabs"])
        self.assertIn("ProductLots", group_05.get("referenced_tabs", []))

    def test_db002_all_12_conflicting_core_tabs_fail_closed_on_write(self):
        self.assertEqual(CONFLICTING_CORE_SCHEMA_TABS, EXPECTED_12_CONFLICTING_CORE_TABS)
        bridge = AppsScriptBridge()

        for tab_name in sorted(EXPECTED_12_CONFLICTING_CORE_TABS):
            self.assertEqual(
                SCHEMA_HEADER_VARIANCES[tab_name]["status"],
                "CONFLICT_RECONCILIATION_REQUIRED",
            )
            block = get_schema_write_block_reason(tab_name)
            self.assertIsNotNone(block, f"Expected fail-closed block for conflicting core tab {tab_name}")
            self.assertEqual(block["error_code"], "CORE_SCHEMA_CONFLICT_UNRECONCILED")

            spec = next((s for s in GOVERNED_ACTION_REGISTRY.values() if s.target_tab == tab_name), None)
            self.assertIsNotNone(spec, f"Expected governed action targeting {tab_name}")

            res = bridge.execute_governed_write(
                action=spec.action,
                target_tab=spec.target_tab,
                payload={"test_probe": True},
                nonce=f"NONCE-BLOCK-{tab_name}",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field=spec.id_field,
            )
            self.assertEqual(res.status, "BLOCKED_PENDING_OWNER_SETUP")
            self.assertEqual(res.http_status, 503)
            self.assertEqual(res.error_code, "CORE_SCHEMA_CONFLICT_UNRECONCILED")
            self.assertFalse(res.retryable)

    def test_db002_owner_reconciliation_unlocks_specific_core_tab_only(self):
        approve_core_schema_reconciliation(
            "Customers",
            headers=["customer_id", "shop_name", "notes"],
            approved_by="USR-OWNER-001",
        )
        self.assertIsNone(get_schema_write_block_reason("Customers"))
        # Other conflicting tabs remain strictly fail-closed
        self.assertIsNotNone(get_schema_write_block_reason("Sales"))
        self.assertIsNotNone(get_schema_write_block_reason("Suppliers"))
        # Extended pending tabs remain strictly fail-closed
        for ext_tab in PENDING_OWNER_MAPPING_TABS:
            self.assertIsNotNone(get_schema_write_block_reason(ext_tab))

    def test_db004_pkg_pkb_collision_enforced_on_new_allocation_and_read(self):
        # PackagingMaterials strictly accepts PKG-* only
        self.assertEqual(get_allowed_id_prefixes_for_tab("PackagingMaterials", for_new_allocation=True), ("PKG",))
        self.assertTrue(validate_table_id_prefix("PackagingMaterials", "PKG-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("PackagingMaterials", "PKB-0001", for_new_allocation=True))

        # PackagingBatches new allocations strictly require PKB-* (PKG-* rejected to prevent collision)
        self.assertEqual(get_allowed_id_prefixes_for_tab("PackagingBatches", for_new_allocation=True), ("PKB",))
        self.assertTrue(validate_table_id_prefix("PackagingBatches", "PKB-0001", for_new_allocation=True))
        self.assertFalse(validate_table_id_prefix("PackagingBatches", "PKG-0001", for_new_allocation=True))

        # Historical reads of PackagingBatches still accept both PKB-* and legacy PKG-*
        self.assertEqual(get_allowed_id_prefixes_for_tab("PackagingBatches", for_new_allocation=False), ("PKB", "PKG"))
        self.assertTrue(validate_table_id_prefix("PackagingBatches", "PKG-000001", for_new_allocation=False))
        self.assertTrue(validate_table_id_prefix("PackagingBatches", "PKB-000001", for_new_allocation=False))

    def test_db005_all_11_affected_actions_enforce_locked_prefix_and_reject_invalid_ids(self):
        tab_to_locked = {tab: pfx for pfx, tab in LOCKED_32_ID_PREFIXES.items()}

        # Verify zero ungated creation actions remain for any table with a canonical locked prefix
        for action_name, spec in GOVERNED_ACTION_REGISTRY.items():
            if spec.requires_allocated_id and spec.target_tab in tab_to_locked:
                self.assertEqual(
                    spec.locked_prefix,
                    tab_to_locked[spec.target_tab],
                    f"Action {action_name} targeting {spec.target_tab} must declare locked_prefix={tab_to_locked[spec.target_tab]}",
                )

        # Verify canonical IDs, permitted legacy IDs, malformed IDs, and wrong-table IDs for all 11 actions
        for action_name, (tab_name, locked_prefix, permitted_legacy) in ELEVEN_AFFECTED_ACTIONS.items():
            spec = get_governed_action_spec(action_name)
            self.assertIsNotNone(spec)
            self.assertEqual(spec.target_tab, tab_name)
            self.assertEqual(spec.locked_prefix, locked_prefix)

            # 1. Canonical locked ID accepted
            self.assertTrue(
                AppsScriptBridge._validate_id_format(spec, f"{locked_prefix}-000123"),
                f"{action_name} should accept canonical {locked_prefix}-000123",
            )
            # 2. Permitted non-colliding legacy alias accepted (or PKG rejected for PackagingBatches)
            if permitted_legacy:
                self.assertTrue(
                    AppsScriptBridge._validate_id_format(spec, f"{permitted_legacy}-000123"),
                    f"{action_name} should accept permitted transitional alias {permitted_legacy}-000123",
                )
            elif tab_name == "PackagingBatches":
                self.assertFalse(
                    AppsScriptBridge._validate_id_format(spec, "PKG-000123"),
                    f"{action_name} must reject colliding PKG-000123 on new allocation",
                )
            # 3. Malformed IDs rejected
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, ""))
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, f"{locked_prefix}000123"))
            self.assertFalse(AppsScriptBridge._validate_id_format(spec, f"{locked_prefix}-12"))
            # 4. Wrong-table ID rejected
            wrong_prefix = "USR" if locked_prefix != "USR" else "PRD"
            self.assertFalse(
                AppsScriptBridge._validate_id_format(spec, f"{wrong_prefix}-000123"),
                f"{action_name} must reject wrong-table prefix {wrong_prefix}-000123",
            )


if __name__ == "__main__":
    unittest.main()
