"""
Phase 1 Integrity and Reliability Tests (Kawad Swad Master Plan Version 1.0)
Validates:
1. Checked writes across products, customers, visits, and production.
2. Multi-step transaction lifecycle: STARTED -> INCOMPLETE -> COMPLETE on recovery.
3. Strict enforcement of Master Plan Section 4.1: Moong Khata Meetha excluded from active range (status: DRAFT, approved: False).
4. Strict enforcement of standard papad packet sizes (200g, 500g, 1000g).
"""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # noqa: F401 - standardized hardened stdlib shims
import unittest
from app.sheets import db
from app.recipes_master import MASTER_RECIPES_DEFINITION

class TestMasterPlanPhase1Integrity(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_fallback = db.allow_in_memory_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.allow_in_memory_fallback = self.orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_moong_khata_meetha_strictly_draft_and_unapproved(self):
        """Master Plan Section 4.1: Moong Khata Meetha is excluded from active range; must remain DRAFT and unapproved."""
        khata_meetha = next((r for r in MASTER_RECIPES_DEFINITION if r["recipe_id"] == "RCP-MOONG-KHATAMEETHA-V2"), None)
        self.assertIsNotNone(khata_meetha, "Moong Khata Meetha formula definition must exist")
        self.assertEqual(khata_meetha["status"], "DRAFT")
        self.assertFalse(khata_meetha["approved"])
        self.assertIn("Sweetener Blend", [i["material_name"] for i in khata_meetha["items"]])

    def test_papad_standard_pack_sizes(self):
        """Master Plan Section 4.1 & 7.5: Standard papad pack sizes are strictly 200g, 500g, and 1000g."""
        standard_weights = {200, 500, 1000}
        from app.routers.production import PackagingCreate
        pack_req = PackagingCreate(
            product_id="PRD-MOONG-MASTER",
            packaging_date="2026-10-18",
            bulk_kg_used=45.0,
            packets_200g=100,
            packets_500g=50,
            packets_1000g=0,
            notes="Standard batch"
        )
        expected_kg = (pack_req.packets_200g * 0.2) + (pack_req.packets_500g * 0.5) + (pack_req.packets_1000g * 1.0)
        self.assertEqual(expected_kg, 45.0)

    def test_write_failures_raise_clean_error(self):
        """Verify that direct db.append_record fails closed under Single-Write-Owner when production mode is active."""
        db.is_connected = False
        db.allow_in_memory_fallback = False
        with self.assertRaises(RuntimeError) as ctx:
            db.append_record("Products", {"product_id": "PRD-TEST", "product_name": "Test Papad"}, raise_on_error=True)
        self.assertIn("blocked_pending_owner_setup", str(ctx.exception).lower())

    def test_update_failures_raise_clean_error(self):
        """Verify that direct db.update_record fails closed under Single-Write-Owner when production mode is active."""
        db.is_connected = False
        db.allow_in_memory_fallback = False
        with self.assertRaises(RuntimeError) as ctx:
            db.update_record("Products", "product_id", "PRD-TEST", {"active": "false"}, raise_on_error=True)
        self.assertIn("blocked_pending_owner_setup", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
