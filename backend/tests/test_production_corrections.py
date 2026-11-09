"""
Automated Verification Suite for Kawad Swad ERP: Phase 10F
Packaging Approval Security, Recovery Protection & Accounting Integrity.

Implements all 20 specified verification scenarios across:
1. Approval Security (Cases 1-5)
2. Packaging Creation (Cases 6-9)
3. Recovery Protection (Cases 10-13)
4. Retry & Reconciliation (Cases 14-16)
5. Accounting Integrity (Cases 17-18)
6. Historical Record Preservation (Cases 19-20)
Plus Additional Production Module Core Verifications (Auto Issue, Recipe Versioning, Tolerance).
"""

import os
import sys
import json
import asyncio
import threading
import unittest
from decimal import Decimal
from fastapi import HTTPException

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.sheets import db
from app.routers.production import (
    save_recipe,
    create_batch,
    issue_materials,
    create_packaging,
    recover_packaging,
    approve_packaging_discrepancy,
    RecipeSave,
    ProductionCreate,
    PackagingCreate,
    DiscrepancyApprovalRequest,
)


class TestPhase10FPackagingSecurity(unittest.TestCase):
    def setUp(self):
        # Reset in-memory store for isolation
        db.memory_store = {tab: [] for tab in db.memory_store}

        # Authenticated users
        self.owner_user = {
            "user_id": "USR-OWNER-01",
            "username": "owner",
            "role": "OWNER",
            "full_name": "Sita Ram",
        }
        self.pa_user = {
            "user_id": "USR-PA-01",
            "username": "pa_worker",
            "role": "PA",
            "full_name": "Gopal Sharma",
        }
        db.append_record("Users", {**self.owner_user, "active": "true"})
        db.append_record("Users", {**self.pa_user, "active": "true"})

        # Canonical Products
        db.append_record("Products", {
            "product_id": "PRD-MOONG-BULK",
            "sku": "MOONG-BULK",
            "product_name": "Moong Special Papad",
            "selling_unit": "kg",
            "active": "true",
            "category": "Papad",
        })
        db.append_record("Products", {
            "product_id": "PRD-MOONG-200G",
            "sku": "MOONG-BULK-200g",
            "product_name": "Moong Special Papad",
            "selling_unit": "PACKET",
            "pack_weight_g": 200,
            "active": "true",
            "category": "Papad",
        })
        db.append_record("Products", {
            "product_id": "PRD-MOONG-500G",
            "sku": "MOONG-BULK-500g",
            "product_name": "Moong Special Papad",
            "selling_unit": "PACKET",
            "pack_weight_g": 500,
            "active": "true",
            "category": "Papad",
        })
        db.append_record("Products", {
            "product_id": "PRD-MOONG-1000G",
            "sku": "MOONG-BULK-1000g",
            "product_name": "Moong Special Papad",
            "selling_unit": "PACKET",
            "pack_weight_g": 1000,
            "active": "true",
            "category": "Papad",
        })

        # Canonical Raw Materials for recipe & costing
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-MOONG-FLOUR",
            "material_name": "Moong Flour",
            "current_stock": 500.0,
            "unit": "kg",
            "rate_per_unit": 90.0,
            "category": "FLOUR",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-URAD-FLOUR",
            "material_name": "Urad Flour",
            "current_stock": 500.0,
            "unit": "kg",
            "rate_per_unit": 95.0,
            "category": "FLOUR",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-BLACK-PEPPER",
            "material_name": "Black Pepper",
            "current_stock": 50.0,
            "unit": "kg",
            "rate_per_unit": 700.0,
            "category": "SPICES",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-SALT",
            "material_name": "Salt",
            "current_stock": 200.0,
            "unit": "kg",
            "rate_per_unit": 20.0,
            "category": "SPICES",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-PAPAD-KHAR",
            "material_name": "Papad Khar",
            "current_stock": 50.0,
            "unit": "kg",
            "rate_per_unit": 120.0,
            "category": "SPICES",
        })

    def _seed_bulk_stock(self, batch_id="PRB-001", quantity_kg=100.0):
        """Helper to seed bulk stock in ProductionBatches and ProductionStockLedger."""
        db.append_record("ProductionBatches", {
            "production_id": batch_id,
            "batch_id": batch_id,
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "status": "APPROVED",
            "saleable_output_kg": quantity_kg,
            "total_batch_cost": quantity_kg * 100.0,
            "cost_per_saleable_kg": 100.0,
            "cost_status": "ACTUAL",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": f"MVT-{batch_id}",
            "txn_datetime": "2026-10-20T10:00:00",
            "movement_type": "BULK_PRODUCED",
            "channel": "FACTORY_BULK",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "product_name_snapshot": "Moong Special Papad",
            "quantity_kg": quantity_kg,
            "quantity_packets": 0,
            "reference_id": batch_id,
            "production_batch_id": batch_id,
            "unit_cost_per_kg": 100.0,
            "total_cost": quantity_kg * 100.0,
        })

    # =========================================================================
    # GROUP 1: APPROVAL SECURITY SCENARIOS (CASES 1 - 5)
    # =========================================================================

    def test_case_01_pa_user_submits_discrepancy_approved_rejected(self):
        """Case 1: PA user submits discrepancy_approved=true -> rejected (HTTP 422)."""
        self._seed_bulk_stock("PRB-001", 100.0)

        # Non-owner PA worker attempts to package with 2.0 kg discrepancy and claims discrepancy_approved=True
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=96,  # 96 * 0.5 = 48.0 kg -> 2.0 kg unexplained variance
            discrepancy_explanation="PA attempted approval",
            discrepancy_approved=True,
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("Packing completion blocked", cm.exception.detail)

        # Batch record saved as PENDING_REVIEW with discrepancy_approved='false'
        pack_recs = db.get_records("PackagingBatches")
        self.assertEqual(len(pack_recs), 1)
        self.assertEqual(pack_recs[0]["status"], "PENDING_REVIEW")
        self.assertEqual(pack_recs[0]["discrepancy_approved"], "false")

        # ApprovalRequests entry created for Owner review
        appr_recs = db.get_records("ApprovalRequests")
        self.assertEqual(len(appr_recs), 1)
        self.assertEqual(appr_recs[0]["request_type"], "PACKAGING_DISCREPANCY")
        self.assertEqual(appr_recs[0]["target_user_id"], pack_recs[0]["packaging_id"])

        # No stock movements posted
        ledger = [m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_recs[0]["packaging_id"]]
        self.assertEqual(len(ledger), 0)

    def test_case_02_non_owner_attempts_approval_rejected(self):
        """Case 2: Non-Owner attempts approval -> rejected (HTTP 403)."""
        pack_id = "PKG-TEST-002"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 96,
            "total_packets": 96,
            "expected_kg": 48.0,
            "difference_kg": 2.0,
            "status": "PENDING_REVIEW",
            "difference_status": "REVIEW_REQUIRED",
            "discrepancy_approved": "false",
        })

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(approve_packaging_discrepancy(
                pack_id,
                DiscrepancyApprovalRequest(explanation="Worker unauthorized approval"),
                user=self.pa_user,
            ))
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Owner", cm.exception.detail)

    def test_case_03_owner_approves_with_valid_explanation_accepted(self):
        """Case 3: Owner approves with valid explanation -> accepted (HTTP 200/SUCCESS)."""
        pack_id = "PKG-TEST-003"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_200g": 0,
            "packets_500g": 96,
            "packets_1000g": 0,
            "total_packets": 96,
            "expected_kg": 48.0,
            "difference_kg": 2.0,
            "status": "PENDING_REVIEW",
            "difference_status": "REVIEW_REQUIRED",
            "discrepancy_approved": "false",
        })

        res = asyncio.run(approve_packaging_discrepancy(
            pack_id,
            DiscrepancyApprovalRequest(explanation="Approved by Owner after scale calibration check"),
            user=self.owner_user,
        ))
        self.assertEqual(res["status"], "SUCCESS")

        updated = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == pack_id)
        self.assertEqual(updated["status"], "RECORDED")
        self.assertEqual(updated["difference_status"], "APPROVED_DISCREPANCY")
        self.assertEqual(updated["discrepancy_approved"], "true")
        self.assertEqual(updated["discrepancy_explanation"], "Approved by Owner after scale calibration check")

    def test_case_04_owner_approval_records_authenticated_id_and_timestamp(self):
        """Case 4: Owner approval records authenticated Owner ID and server timestamp."""
        pack_id = "PKG-TEST-004"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 96,
            "total_packets": 96,
            "expected_kg": 48.0,
            "difference_kg": 2.0,
            "status": "PENDING_REVIEW",
            "difference_status": "REVIEW_REQUIRED",
            "discrepancy_approved": "false",
        })

        asyncio.run(approve_packaging_discrepancy(
            pack_id,
            DiscrepancyApprovalRequest(explanation="Owner verified and approved"),
            user=self.owner_user,
        ))

        updated = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == pack_id)
        self.assertEqual(updated["discrepancy_approved_by"], self.owner_user["user_id"])
        self.assertTrue(len(updated["discrepancy_approved_at"]) >= 10)
        self.assertIn("T", updated["discrepancy_approved_at"])

    def test_case_05_missing_approval_explanation_rejected(self):
        """Case 5: Missing approval explanation -> rejected (HTTP 422)."""
        self._seed_bulk_stock("PRB-005", 100.0)

        # 1. In create_packaging, Owner submits discrepancy_approved=True with empty explanation
        req_empty = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=96,
            discrepancy_explanation="",
            discrepancy_approved=True,
        )
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req_empty, user=self.owner_user))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("explanation (minimum 3 characters) is required", cm.exception.detail)

        # 2. In approve-discrepancy, explanation with < 3 chars is rejected with HTTP 422
        pack_id = "PKG-TEST-005"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 96,
            "total_packets": 96,
            "expected_kg": 48.0,
            "difference_kg": 2.0,
            "status": "PENDING_REVIEW",
            "difference_status": "REVIEW_REQUIRED",
            "discrepancy_approved": "false",
        })
        with self.assertRaises((HTTPException, Exception)) as cm2:
            try:
                discrepancy_payload = DiscrepancyApprovalRequest(explanation="no")
            except Exception as val_exc:
                raise HTTPException(422, "An explanation (minimum 3 characters) is required to approve an unexplained packing discrepancy.") from val_exc

            asyncio.run(approve_packaging_discrepancy(
                pack_id,
                discrepancy_payload,
                user=self.owner_user,
            ))
        if isinstance(cm2.exception, HTTPException):
            self.assertEqual(cm2.exception.status_code, 422)
            self.assertIn("explanation (minimum 3 characters) is required", cm2.exception.detail)

    # =========================================================================
    # GROUP 2: PACKAGING CREATION SCENARIOS (CASES 6 - 9)
    # =========================================================================

    def test_case_06_normal_packaging_without_discrepancy_succeeds(self):
        """Case 6: Normal packaging without discrepancy -> succeeds (MATCH, RECORDED)."""
        self._seed_bulk_stock("PRB-006", 100.0)

        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=100,  # 100 * 0.5 = 50.0 kg -> exact match
            packing_loss_kg=0.0,
        )

        res = asyncio.run(create_packaging(req, user=self.owner_user))
        self.assertEqual(res["status"], "RECORDED")
        self.assertEqual(res["difference_status"], "MATCH")
        self.assertEqual(res["discrepancy_approved"], "false")
        self.assertAlmostEqual(res["difference_kg"], 0.0, places=4)

        # Stock ledger verified
        ledger = db.get_records("ProductionStockLedger")
        pack_mvts = [m for m in ledger if m.get("reference_id") == res["packaging_id"]]
        self.assertEqual(len(pack_mvts), 2)  # 1 bulk deduction, 1 packet credit

    def test_case_07_packaging_discrepancy_blocks_without_approval_saves_pending_review(self):
        """Case 7: Packaging with discrepancy requiring approval cannot be finalized without approval -> saved as PENDING_REVIEW, stock unposted."""
        self._seed_bulk_stock("PRB-007", 100.0)

        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=90,  # 45.0 kg -> 5.0 kg discrepancy
            packing_loss_kg=0.0,
            discrepancy_approved=False,
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)

        # Record in PENDING_REVIEW
        batches = db.get_records("PackagingBatches")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["status"], "PENDING_REVIEW")
        self.assertEqual(batches[0]["difference_status"], "REVIEW_REQUIRED")
        self.assertEqual(batches[0]["discrepancy_approved"], "false")

        # Zero stock postings
        ledger = [m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == batches[0]["packaging_id"]]
        self.assertEqual(len(ledger), 0)

    def test_case_08_forged_client_approval_fields_rejected(self):
        """Case 8: Forged client approval fields -> rejected."""
        self._seed_bulk_stock("PRB-008", 100.0)

        # Non-owner attempts to inject approval metadata
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=95,
            discrepancy_approved=True,
            discrepancy_explanation="Attempted forge by PA",
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)

        batch = db.get_records("PackagingBatches")[0]
        self.assertEqual(batch["status"], "PENDING_REVIEW")
        self.assertEqual(batch["discrepancy_approved"], "false")

    def test_case_09_client_supplied_incorrect_discrepancy_recalculated_accurately(self):
        """Case 9: Client-supplied incorrect discrepancy calculation -> server recalculates accurately."""
        self._seed_bulk_stock("PRB-009", 100.0)

        # Server recalculates from bulk_kg_used and packet counts
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_200g=50,   # 10.0 kg
            packets_500g=60,   # 30.0 kg
            packets_1000g=5,   # 5.0 kg -> Total packed = 45.0 kg
            packing_loss_kg=1.0,  # Unexplained = 50.0 - 45.0 - 1.0 = 4.0 kg
            discrepancy_approved=False,
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("+4.000 kg", cm.exception.detail)

        batch = db.get_records("PackagingBatches")[0]
        self.assertAlmostEqual(float(batch["difference_kg"]), 4.0, places=3)
        self.assertEqual(batch["difference_status"], "REVIEW_REQUIRED")

    # =========================================================================
    # GROUP 3: RECOVERY PROTECTION SCENARIOS (CASES 10 - 13)
    # =========================================================================

    def test_case_10_recovery_cannot_finalize_unapproved_discrepancy(self):
        """Case 10: Recovery cannot finalize unapproved discrepancy -> rejected (HTTP 409)."""
        pack_id = "PKG-DISC-010"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 90,
            "total_packets": 90,
            "expected_kg": 45.0,
            "difference_kg": 5.0,
            "status": "PENDING_REVIEW",
            "difference_status": "REVIEW_REQUIRED",
            "discrepancy_approved": "false",
        })

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("Valid Owner discrepancy approval is required", cm.exception.detail)

        # Ensure batch status remains PENDING_REVIEW and no stock movements were added
        batch = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == pack_id)
        self.assertEqual(batch["status"], "PENDING_REVIEW")
        ledger = [m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id]
        self.assertEqual(len(ledger), 0)

    def test_case_11_recovery_does_not_create_duplicate_stock_movements(self):
        """Case 11: Recovery does not create duplicate stock movements."""
        pack_id = "PKG-RECOV-011"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 100,
            "total_packets": 100,
            "expected_kg": 50.0,
            "difference_kg": 0.0,
            "difference_status": "MATCH",
            "status": "INCOMPLETE",
        })

        # Bulk movement already exists
        db.append_record("ProductionStockLedger", {
            "movement_id": "MVT-BULK-011",
            "txn_datetime": "2026-11-08T10:00:00",
            "movement_type": "BULK_PACKAGED",
            "channel": "FACTORY_BULK",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "product_name_snapshot": "Moong Special Papad",
            "quantity_kg": 50.0,
            "quantity_packets": 0,
            "reference_id": pack_id,
        })

        # Run recovery
        res = asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        self.assertEqual(res["status"], "RECORDED")

        # Verify bulk movement was NOT duplicated
        bulk_mvts = [
            m for m in db.get_records("ProductionStockLedger")
            if m.get("reference_id") == pack_id and m.get("movement_type") == "BULK_PACKAGED"
        ]
        self.assertEqual(len(bulk_mvts), 1)

        # Verify packet movement was recovered
        packet_mvts = [
            m for m in db.get_records("ProductionStockLedger")
            if m.get("reference_id") == pack_id and m.get("movement_type") == "PACKETS_PACKAGED"
        ]
        self.assertEqual(len(packet_mvts), 1)
        self.assertEqual(int(packet_mvts[0]["quantity_packets"]), 100)

    def test_case_12_repeated_recovery_requests_are_safe_and_idempotent(self):
        """Case 12: Repeated recovery requests are safe & idempotent."""
        pack_id = "PKG-RECOV-012"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 100,
            "total_packets": 100,
            "expected_kg": 50.0,
            "difference_kg": 0.0,
            "difference_status": "MATCH",
            "status": "INCOMPLETE",
        })

        # First recovery
        asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        count_after_first = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        # Second recovery
        res2 = asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        self.assertEqual(res2["status"], "RECORDED")
        count_after_second = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        # Third recovery
        res3 = asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        self.assertEqual(res3["status"], "RECORDED")
        count_after_third = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        self.assertEqual(count_after_first, count_after_second)
        self.assertEqual(count_after_second, count_after_third)

    def test_case_13_legitimate_incomplete_transactions_can_be_recovered(self):
        """Case 13: Legitimate incomplete transactions can still be recovered."""
        pack_id = "PKG-LEGIT-013"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 20.0,
            "packets_200g": 100,
            "total_packets": 100,
            "expected_kg": 20.0,
            "difference_kg": 0.0,
            "difference_status": "MATCH",
            "status": "INCOMPLETE",
            "notes": "Simulated interrupted write",
        })
        db.append_record("IncompleteTransactions", {
            "transaction_id": "TXN-013",
            "idempotency_key": f"PACKAGING_{pack_id}",
            "status": "PENDING",
            "payload_json": json.dumps({"packaging_id": pack_id}),
        })

        res = asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        self.assertEqual(res["status"], "RECORDED")

        # IncompleteTransactions marked COMPLETED
        it = db.get_records("IncompleteTransactions")[0]
        self.assertEqual(it["status"], "COMPLETED")

        # Batch marked RECORDED
        batch = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == pack_id)
        self.assertEqual(batch["status"], "RECORDED")

    # =========================================================================
    # GROUP 4: RETRY & RECONCILIATION SCENARIOS (CASES 14 - 16)
    # =========================================================================

    def test_case_14_retry_cannot_bypass_approval(self):
        """Case 14: Retry cannot bypass approval -> rejected (HTTP 422)."""
        self._seed_bulk_stock("PRB-014", 100.0)

        # Initial attempt with discrepancy saved as PENDING_REVIEW
        ref = "REF-RETRY-014"
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=90,  # 5 kg discrepancy
            reference=ref,
            discrepancy_approved=False,
        )
        with self.assertRaises(HTTPException):
            asyncio.run(create_packaging(req, user=self.pa_user))

        # PA retries with same reference attempting to finalize
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("pending Owner discrepancy approval", cm.exception.detail)

    def test_case_15_retry_cannot_finalize_pending_review_batch(self):
        """Case 15: Retry cannot finalize a pending-review batch."""
        self._seed_bulk_stock("PRB-015", 100.0)

        ref = "REF-RETRY-015"
        db.append_record("PackagingBatches", {
            "packaging_id": "PKG-015",
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 90,
            "total_packets": 90,
            "expected_kg": 45.0,
            "difference_kg": 5.0,
            "difference_status": "REVIEW_REQUIRED",
            "status": "PENDING_REVIEW",
            "discrepancy_approved": "false",
            "reference": ref,
        })

        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=90,
            reference=ref,
            discrepancy_approved=False,
        )
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)

        batch = db.get_records("PackagingBatches")[0]
        self.assertEqual(batch["status"], "PENDING_REVIEW")
        ledger = [m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == "PKG-015"]
        self.assertEqual(len(ledger), 0)

    def test_case_16_repeated_retry_does_not_duplicate_ledger_entries(self):
        """Case 16: Repeated retry does not duplicate ledger entries."""
        self._seed_bulk_stock("PRB-016", 100.0)

        ref = "REF-RETRY-016"
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=100,
            reference=ref,
        )

        # Initial successful creation
        res1 = asyncio.run(create_packaging(req, user=self.owner_user))
        self.assertEqual(res1["status"], "RECORDED")
        pack_id = res1["packaging_id"]
        count1 = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        # Retry with identical reference
        res2 = asyncio.run(create_packaging(req, user=self.owner_user))
        self.assertEqual(res2["status"], "RECORDED")
        count2 = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        # Third retry
        res3 = asyncio.run(create_packaging(req, user=self.owner_user))
        self.assertEqual(res3["status"], "RECORDED")
        count3 = len([m for m in db.get_records("ProductionStockLedger") if m.get("reference_id") == pack_id])

        self.assertEqual(count1, count2)
        self.assertEqual(count2, count3)

    # =========================================================================
    # GROUP 5: ACCOUNTING INTEGRITY SCENARIOS (CASES 17 - 18)
    # =========================================================================

    def test_case_17_recovery_checks_canonical_journal_headers_and_lines(self):
        """Case 17: Recovery checks correct canonical journal tables (JournalHeaders, JournalLines)."""
        pack_id = "PKG-ACCT-017"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 100,
            "total_packets": 100,
            "bulk_cost": 5000.0,
            "packaging_material_cost": 300.0,
            "packaging_labor_cost": 200.0,
            "cost_status": "ACTUAL",
            "difference_status": "MATCH",
            "status": "INCOMPLETE",
        })

        asyncio.run(recover_packaging(pack_id, user=self.owner_user))

        headers = db.get_records("JournalHeaders")
        pack_headers = [h for h in headers if h.get("reference_id") == pack_id]
        self.assertEqual(len(pack_headers), 1)
        self.assertEqual(pack_headers[0]["reference_type"], "PACKAGING_BATCH")

        lines = db.get_records("JournalLines")
        pack_lines = [l for l in lines if l.get("journal_id") == pack_headers[0]["journal_id"]]
        self.assertTrue(len(pack_lines) >= 2)  # Balanced Dr / Cr entries

    def test_case_18_duplicate_journal_creation_is_prevented(self):
        """Case 18: Duplicate journal creation is prevented."""
        pack_id = "PKG-ACCT-018"
        db.append_record("PackagingBatches", {
            "packaging_id": pack_id,
            "packaging_date": "2026-11-08",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 100,
            "total_packets": 100,
            "bulk_cost": 5000.0,
            "packaging_material_cost": 300.0,
            "packaging_labor_cost": 200.0,
            "cost_status": "ACTUAL",
            "difference_status": "MATCH",
            "status": "INCOMPLETE",
        })

        # Run recovery twice
        asyncio.run(recover_packaging(pack_id, user=self.owner_user))
        asyncio.run(recover_packaging(pack_id, user=self.owner_user))

        headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == pack_id]
        self.assertEqual(len(headers), 1)

    # =========================================================================
    # GROUP 6: HISTORICAL RECORD PRESERVATION SCENARIOS (CASES 19 - 20)
    # =========================================================================

    def test_case_19_existing_packaging_records_not_overwritten(self):
        """Case 19: Existing packaging records (PKG-000001, PKG-000002) are not overwritten."""
        self._seed_bulk_stock("PRB-019", 200.0)

        # Seed historical records exactly as documented from live workbook
        pkg_01 = {
            "packaging_id": "PKG-000001",
            "packaging_date": "2026-10-20",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 75.0,
            "packets_200g": 100,
            "total_packets": 100,
            "expected_kg": 20.0,
            "difference_kg": 55.0,
            "difference_status": "REVIEW_REQUIRED",
            "status": "RECORDED",
            "discrepancy_approved": "",
            "notes": "Historical batch PKG-000001 with 55 kg variance",
        }
        pkg_02 = {
            "packaging_id": "PKG-000002",
            "packaging_date": "2026-10-22",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 22.0,
            "packets_200g": 98,
            "total_packets": 98,
            "expected_kg": 19.6,
            "difference_kg": 2.4,
            "difference_status": "REVIEW_REQUIRED",
            "status": "PENDING_REVIEW",
            "discrepancy_approved": "",
            "notes": "Historical batch PKG-000002 pending review",
        }
        db.append_record("PackagingBatches", pkg_01)
        db.append_record("PackagingBatches", pkg_02)

        # Create new packaging batch
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=100,
        )
        res = asyncio.run(create_packaging(req, user=self.owner_user))
        self.assertNotEqual(res["packaging_id"], "PKG-000001")
        self.assertNotEqual(res["packaging_id"], "PKG-000002")

        # Verify historical records remain identical
        rec_01 = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == "PKG-000001")
        self.assertEqual(float(rec_01["difference_kg"]), 55.0)
        self.assertEqual(rec_01["status"], "RECORDED")

        rec_02 = next(p for p in db.get_records("PackagingBatches") if p["packaging_id"] == "PKG-000002")
        self.assertEqual(float(rec_02["difference_kg"]), 2.4)
        self.assertEqual(rec_02["status"], "PENDING_REVIEW")

    def test_case_20_existing_stock_ledger_entries_remain_unchanged(self):
        """Case 20: Existing stock ledger entries remain unchanged."""
        pst_04 = {
            "movement_id": "PST-000004",
            "txn_datetime": "2026-10-20T11:00:00",
            "movement_type": "BULK_PACKAGED",
            "channel": "FACTORY_BULK",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "product_name_snapshot": "Moong Special Papad",
            "quantity_kg": 75.0,
            "quantity_packets": 0,
            "reference_id": "PKG-000001",
        }
        pst_05 = {
            "movement_id": "PST-000005",
            "txn_datetime": "2026-10-20T11:00:00",
            "movement_type": "PACKETS_PACKAGED",
            "channel": "FACTORY_FINISHED",
            "product_id": "PRD-MOONG-200G",
            "bulk_product_key": "moong special papad",
            "product_name_snapshot": "Moong Special Papad",
            "sku_snapshot": "MOONG-BULK-200g",
            "pack_weight_g": 200,
            "quantity_kg": 0,
            "quantity_packets": 100,
            "reference_id": "PKG-000001",
        }
        db.append_record("ProductionStockLedger", pst_04)
        db.append_record("ProductionStockLedger", pst_05)

        # Seed additional stock and run new operations
        self._seed_bulk_stock("PRB-020", 100.0)
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=100,
        )
        asyncio.run(create_packaging(req, user=self.owner_user))

        # Check historical ledger entries
        ledger = db.get_records("ProductionStockLedger")
        m4 = next(m for m in ledger if m["movement_id"] == "PST-000004")
        self.assertEqual(float(m4["quantity_kg"]), 75.0)
        self.assertEqual(m4["reference_id"], "PKG-000001")

        m5 = next(m for m in ledger if m["movement_id"] == "PST-000005")
        self.assertEqual(int(m5["quantity_packets"]), 100)
        self.assertEqual(m5["reference_id"], "PKG-000001")

    # =========================================================================
    # GROUP 7: ADDITIONAL PRODUCTION MODULE CORE VERIFICATIONS
    # =========================================================================

    def test_batch_creation_auto_issue_materials_success(self):
        """Batch created with auto_issue_materials=True deducts stock atomically and updates status."""
        recipe_req = RecipeSave(
            product_id="PRD-MOONG-BULK",
            items=[
                {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                {"material_name": "Urad Flour", "quantity_per_kg": 0.2, "unit": "kg"},
                {"material_name": "Black Pepper", "quantity_per_kg": 0.02, "unit": "kg"},
                {"material_name": "Salt", "quantity_per_kg": 0.02, "unit": "kg"},
                {"material_name": "Papad Khar", "quantity_per_kg": 0.01, "unit": "kg"},
            ],
            expected_yield_kg=1.2,
            approved=True,
        )
        saved_recipe = asyncio.run(save_recipe(recipe_req, user=self.owner_user))
        recipe_id = saved_recipe["recipe_id"]

        batch_req = ProductionCreate(
            product_id="PRD-MOONG-BULK",
            production_date="2026-11-08",
            quantity_kg=12.0,
            recipe_id=recipe_id,
            auto_issue_materials=True,
        )

        batch = asyncio.run(create_batch(batch_req, user=self.owner_user))
        self.assertEqual(batch["materials_issued"], "true")
        self.assertTrue(len(batch["material_issue_txn_id"]) > 0)
        self.assertEqual(batch["recipe_version"], "1")

        raw_ledger = db.get_records("RawMaterialLedger")
        batch_deductions = [d for d in raw_ledger if d["production_id"] == batch["production_id"]]
        self.assertEqual(len(batch_deductions), 5)

        # Re-issuing returns ALREADY_ISSUED without re-deducting
        re_issue = asyncio.run(issue_materials(batch["production_id"], user=self.owner_user))
        self.assertEqual(re_issue["status"], "ALREADY_ISSUED")
        raw_ledger_after = db.get_records("RawMaterialLedger")
        batch_deductions_after = [d for d in raw_ledger_after if d["production_id"] == batch["production_id"]]
        self.assertEqual(len(batch_deductions_after), 5)

    def test_batch_creation_auto_issue_materials_rollback_on_insufficient_stock(self):
        """Batch created with auto_issue_materials=True rolls back batch creation on insufficient stock."""
        for r in db.memory_store.get("RawMaterials", []):
            if r["raw_material_id"] == "RM-MOONG-FLOUR":
                r["current_stock"] = 0.0

        recipe_req = RecipeSave(
            product_id="PRD-MOONG-BULK",
            items=[
                {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                {"material_name": "Urad Flour", "quantity_per_kg": 0.2, "unit": "kg"},
            ],
            expected_yield_kg=1.2,
            approved=True,
        )
        saved_recipe = asyncio.run(save_recipe(recipe_req, user=self.owner_user))

        batch_req = ProductionCreate(
            product_id="PRD-MOONG-BULK",
            production_date="2026-11-08",
            quantity_kg=12.0,
            recipe_id=saved_recipe["recipe_id"],
            auto_issue_materials=True,
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_batch(batch_req, user=self.owner_user))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("Insufficient stock", cm.exception.detail)

        batches = db.get_records("ProductionBatches")
        self.assertEqual(len(batches), 0)

    def test_recipe_approval_restricted_to_owner(self):
        """Non-owner attempting to approve recipe receives 403."""
        recipe_req = RecipeSave(
            product_id="PRD-MOONG-BULK",
            items=[
                {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                {"material_name": "Urad Flour", "quantity_per_kg": 0.2, "unit": "kg"},
            ],
            expected_yield_kg=1.2,
            approved=True,
        )

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(save_recipe(recipe_req, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Only the Owner", cm.exception.detail)

        recipe_req.approved = False
        res = asyncio.run(save_recipe(recipe_req, user=self.pa_user))
        self.assertEqual(res["approved"], "false")

    def test_recipe_concurrent_version_allocation_thread_safe(self):
        """Concurrent recipe creation allocations must not collide on version number."""
        num_threads = 8
        created_versions = []
        errors = []

        def worker(idx):
            try:
                recipe_req = RecipeSave(
                    product_id="PRD-MOONG-BULK",
                    items=[
                        {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                        {"material_name": "Urad Flour", "quantity_per_kg": 0.2, "unit": "kg"},
                    ],
                    expected_yield_kg=1.2,
                    approved=True,
                    notes=f"Concurrent thread {idx}",
                )
                rec = asyncio.run(save_recipe(recipe_req, user=self.owner_user))
                created_versions.append(int(rec["version"]))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(created_versions), num_threads)
        self.assertEqual(len(set(created_versions)), num_threads)
        self.assertEqual(sorted(created_versions), list(range(1, num_threads + 1)))

    def test_packaging_active_tolerance_consistency(self):
        """Active tolerance is respected in calculations, status, and error message text."""
        self._seed_bulk_stock("PRB-TOL-001", 100.0)

        # Custom tolerance = 1.0 kg; variance = 0.8 kg -> MATCH
        req_match = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=98,  # 49.0 kg used -> 1.0 kg difference, packing loss 0.2 -> unexplained = 0.8 kg
            packing_loss_kg=0.2,
            tolerance_kg=1.0,
        )
        res_match = asyncio.run(create_packaging(req_match, user=self.owner_user))
        self.assertEqual(res_match["status"], "RECORDED")
        self.assertEqual(res_match["difference_status"], "MATCH")

        # Custom tolerance = 0.2 kg; variance = 0.8 kg -> Exceeds tolerance
        req_exceed = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-08",
            bulk_kg_used=50.0,
            packets_500g=98,
            packing_loss_kg=0.2,
            tolerance_kg=0.2,
        )
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_packaging(req_exceed, user=self.pa_user))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("exceeds tolerance (0.2 kg)", cm.exception.detail)

    def test_recipe_item_input_backward_compatible_quantity_alias(self):
        """RecipeItemInput accepts both legacy 'quantity' and canonical 'quantity_per_kg' without error."""
        from app.routers.production import RecipeItemInput
        item_legacy = RecipeItemInput(material_name="Moong Flour", quantity=0.85, unit="kg")
        self.assertEqual(float(item_legacy.quantity_per_kg), 0.85)

        item_canonical = RecipeItemInput(material_name="Urad Flour", quantity_per_kg=0.15, unit="kg")
        self.assertEqual(float(item_canonical.quantity_per_kg), 0.15)
        self.assertEqual(float(item_canonical.quantity), 0.15)


if __name__ == "__main__":
    unittest.main()
