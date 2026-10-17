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
        db.is_connected = False
        db.spreadsheet = None

    def test_safe_sheets_update_execution(self):
        # Override SALES_GOOGLE_SPREADSHEET_ID for test execution
        orig_id = script_mod.SALES_GOOGLE_SPREADSHEET_ID
        script_mod.SALES_GOOGLE_SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        try:
            run_update()
            # 1. Historical recipe must be preserved
            recipes = db.get_records("Recipes")
            self.assertTrue(any(r["recipe_id"] == "RCP-OLD-1" for r in recipes))

            # 2. Moong Master V2 must be present and approved
            moong_v2 = next(r for r in recipes if r["recipe_id"] == "RCP-MOONG-MASTER-V2")
            self.assertEqual(moong_v2["approved"], "true")
            self.assertEqual(moong_v2["expected_yield_kg"], 1.2)

            # 3. Chana Chotu V2 must be present and unapproved (draft/proposed)
            chana_v2 = next(r for r in recipes if r["recipe_id"] == "RCP-CHANA-CHOTU-V2")
            self.assertEqual(chana_v2["approved"], "false")

            # 4. Existing stock in RawMaterials must not be overwritten
            moong_flour = next(r for r in db.get_records("RawMaterials") if r["material_name"].lower() == "moong dal flour")
            self.assertEqual(moong_flour["current_stock"], 500.0)

            # 5. Historical production and packaging batches must remain untouched
            batches = db.get_records("ProductionBatches")
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0]["production_id"], "PRB-000001")

            packaging = db.get_records("PackagingBatches")
            self.assertEqual(len(packaging), 1)
            self.assertEqual(packaging[0]["packaging_id"], "PKG-000001")
        finally:
            script_mod.SALES_GOOGLE_SPREADSHEET_ID = orig_id

if __name__ == "__main__":
    unittest.main()
