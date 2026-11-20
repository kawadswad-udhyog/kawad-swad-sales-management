"""Unit test verifying update_sheets_recipe_master logic and safe updates."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import unittest
from app.sheets import db
from scripts.update_sheets_recipe_master import run_update
import scripts.update_sheets_recipe_master as script_mod

class TestUpdateSheetsRecipeMaster(unittest.TestCase):
    def setUp(self):
        class MockWorksheet:
            def __init__(self, tab_name):
                self.tab_name = tab_name
            def get_all_records(self):
                return [dict(r) for r in db.memory_store.get(self.tab_name, [])]
            def append_row(self, row, value_input_option=None):
                from app.sheets import REQUIRED_TABS
                headers = REQUIRED_TABS.get(self.tab_name, ["col1", "col2", "col3"])
                record = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
                db.memory_store.setdefault(self.tab_name, []).append(record)
            def update(self, *args, **kwargs):
                pass
            def row_values(self, row_idx):
                from app.sheets import REQUIRED_TABS
                return REQUIRED_TABS.get(self.tab_name, ["col1", "col2", "col3"])

        class MockSpreadsheet:
            def worksheet(self, tab_name):
                return MockWorksheet(tab_name)

        self._orig_connected = db.is_connected
        self._orig_spreadsheet = db.spreadsheet
        self._orig_fallback = db.allow_in_memory_fallback
        db._records_cache.clear()
        db._worksheets.clear()
        db.is_connected = True
        db.spreadsheet = MockSpreadsheet()
        for k in list(db.memory_store):
            db.memory_store[k] = []
        db.memory_store.update({
            "Recipes": [
                {
                    "recipe_id": "RCP-OLD-1",
                    "product_id": "PRD-OLD",
                    "product_name_snapshot": "Old Papad",
                    "version": "1.0",
                    "approved": "true",
                    "notes": "Historical approved recipe",
                }
            ],
            "RawMaterials": [
                {
                    "raw_material_id": "RM-OLD-1",
                    "material_name": "Moong Dal Flour",
                    "current_stock": 500.0,
                    "unit": "kg",
                }
            ],
            "ProductionBatches": [
                {
                    "production_id": "PRB-000001",
                    "product_name_snapshot": "Old Papad",
                    "quantity_kg": 50.0,
                    "status": "APPROVED",
                }
            ],
            "PackagingBatches": [
                {
                    "packaging_id": "PKG-000001",
                    "total_packets": 250,
                }
            ],
        })

    def tearDown(self):
        db.is_connected = self._orig_connected
        db.spreadsheet = self._orig_spreadsheet
        db.allow_in_memory_fallback = self._orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_safe_sheets_update_execution(self):
        # Under Blueprint v2.1 Single-Write-Owner, legacy direct Sheets mutation scripts are fail-closed blocked
        from app.recipes_master import MASTER_RECIPES_DEFINITION
        orig_id = script_mod.SALES_GOOGLE_SPREADSHEET_ID
        script_mod.SALES_GOOGLE_SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        try:
            self.assertEqual(script_mod.SCRIPT_MUTATION_MODE, "LEGACY_DIRECT_WRITE_DISABLED")
            with self.assertRaises(RuntimeError) as ctx:
                run_update()
            self.assertIn("BLOCKED_PENDING_OWNER_SETUP", str(ctx.exception))

            # 1. Historical recipe must be preserved completely untouched
            recipes = db.get_records("Recipes", fresh=True)
            self.assertEqual(len(recipes), 1)
            self.assertEqual(recipes[0]["recipe_id"], "RCP-OLD-1")

            # 2. V2 recipe master definitions retain Moong Master V2 approved (1.2kg yield) & Chana Chotu V2 unapproved
            moong_v2 = next(r for r in MASTER_RECIPES_DEFINITION if r["recipe_id"] == "RCP-MOONG-MASTER-V2")
            self.assertTrue(moong_v2["approved"])
            self.assertEqual(moong_v2["expected_yield_kg"], 1.2)

            chana_v2 = next(r for r in MASTER_RECIPES_DEFINITION if r["recipe_id"] == "RCP-CHANA-CHOTU-V2")
            self.assertFalse(chana_v2["approved"])

            # 3. Existing stock in RawMaterials must not be overwritten
            moong_flour = next(r for r in db.get_records("RawMaterials", fresh=True) if r["material_name"].lower() == "moong dal flour")
            self.assertEqual(moong_flour["current_stock"], 500.0)

            # 4. Historical production and packaging batches must remain untouched
            batches = db.get_records("ProductionBatches", fresh=True)
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0]["production_id"], "PRB-000001")

            packaging = db.get_records("PackagingBatches", fresh=True)
            self.assertEqual(len(packaging), 1)
            self.assertEqual(packaging[0]["packaging_id"], "PKG-000001")
        finally:
            script_mod.SALES_GOOGLE_SPREADSHEET_ID = orig_id

if __name__ == "__main__":
    unittest.main()
