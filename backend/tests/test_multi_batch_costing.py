import unittest
from decimal import Decimal
import json
import asyncio
from unittest.mock import patch
from fastapi import HTTPException

from app.calculations.inventory import (
    calculate_batch_bulk_balances,
    resolve_packaging_batch_allocations,
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
)
from app.accounting.postings import post_packaging_batch_journal
from app.routers.production import create_packaging, recover_packaging, PackagingCreate, BatchAllocationItem
from app.sheets import db


class TestMultiBatchCosting(unittest.TestCase):
    def setUp(self):
        # Configure in-memory testing store
        db.memory_store = {
            "ProductionBatches": [],
            "ProductionStockLedger": [],
            "PackagingBatches": [],
            "Products": [
                {
                    "product_id": "PRD-MOONG-BULK",
                    "product_name": "Moong Special Papad",
                    "sku": "MOONG-BULK",
                    "pack_weight_g": 0,
                    "active": "true",
                },
                {
                    "product_id": "PRD-MOONG-200G",
                    "product_name": "Moong Special Papad",
                    "sku": "MOONG-200G",
                    "pack_weight_g": 200,
                    "active": "true",
                    "packaging_material_cost_per_packet": 2.25,
                    "packing_labour_per_packet": 0.75,
                },
                {
                    "product_id": "PRD-MOONG-500G",
                    "product_name": "Moong Special Papad",
                    "sku": "MOONG-500G",
                    "pack_weight_g": 500,
                    "active": "true",
                    "packaging_material_cost_per_packet": 4.50,
                    "packing_labour_per_packet": 1.25,
                },
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-POUCH-200G", "material_name": "Moong Pouch 200g", "rate_per_unit": 2.25, "unit": "pouch"},
            ],
            "JournalHeaders": [],
            "JournalLines": [],
            "AuditLog": [],
            "IncompleteTransactions": [],
            "ApprovalRequests": [],
        }
        self.user = {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER"}

    def test_multi_batch_explicit_allocation_calculation(self):
        """
        Verify the exact prompt specification:
        Batch A: 100 kg @ ₹142.75
        Batch B: 100 kg @ ₹155.00
        Packaging: 60 kg from Batch A, 40 kg from Batch B
        Expected bulk value:
        Batch A: ₹8,565 (60 * 142.75)
        Batch B: ₹6,200 (40 * 155.00)
        Total: ₹14,765
        """
        batches = [
            {
                "production_id": "PRB-BATCH-A",
                "production_date": "2026-11-01",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Special Papad",
                "net_quantity_kg": 100.0,
                "actual_cost_per_kg": 142.75,
                "status": "APPROVED",
            },
            {
                "production_id": "PRB-BATCH-B",
                "production_date": "2026-11-02",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Special Papad",
                "net_quantity_kg": 100.0,
                "actual_cost_per_kg": 155.00,
                "status": "APPROVED",
            },
        ]
        ledger = [
            {
                "movement_id": "MVT-001",
                "movement_type": "BULK_PRODUCED",
                "product_id": "PRD-MOONG-BULK",
                "bulk_product_key": "moong special papad",
                "quantity_kg": 100.0,
                "reference_id": "PRB-BATCH-A",
                "unit_cost_per_kg": 142.75,
                "total_cost": 14275.0,
            },
            {
                "movement_id": "MVT-002",
                "movement_type": "BULK_PRODUCED",
                "product_id": "PRD-MOONG-BULK",
                "bulk_product_key": "moong special papad",
                "quantity_kg": 100.0,
                "reference_id": "PRB-BATCH-B",
                "unit_cost_per_kg": 155.0,
                "total_cost": 15500.0,
            },
        ]

        # 1. Initial balances
        initial_balances = calculate_batch_bulk_balances(ledger, batches, "moong special papad")
        self.assertEqual(len(initial_balances), 2)
        self.assertEqual(initial_balances[0]["batch_id"], "PRB-BATCH-A")
        self.assertEqual(initial_balances[0]["available_kg"], 100.0)
        self.assertEqual(initial_balances[0]["actual_cost_per_kg"], 142.75)
        self.assertEqual(initial_balances[1]["batch_id"], "PRB-BATCH-B")
        self.assertEqual(initial_balances[1]["available_kg"], 100.0)
        self.assertEqual(initial_balances[1]["actual_cost_per_kg"], 155.00)

        # 2. Resolve explicit allocation: 60 kg from A, 40 kg from B
        req_allocations = [
            {"batch_id": "PRB-BATCH-A", "quantity_kg": 60.0},
            {"batch_id": "PRB-BATCH-B", "quantity_kg": 40.0},
        ]
        res = resolve_packaging_batch_allocations(
            bulk_kg_required=100.0,
            product_id_or_name="moong special papad",
            ledger_records=ledger,
            production_batches=batches,
            batch_allocations_requested=req_allocations,
        )

        self.assertEqual(res["total_bulk_kg"], 100.0)
        self.assertEqual(res["total_bulk_cost"], 14765.00)
        self.assertEqual(res["effective_bulk_cost_per_kg"], 147.65)

        alloc_a = next(a for a in res["allocations"] if a["batch_id"] == "PRB-BATCH-A")
        alloc_b = next(a for a in res["allocations"] if a["batch_id"] == "PRB-BATCH-B")
        self.assertEqual(alloc_a["quantity_kg"], 60.0)
        self.assertEqual(alloc_a["total_cost"], 8565.00)
        self.assertEqual(alloc_b["quantity_kg"], 40.0)
        self.assertEqual(alloc_b["total_cost"], 6200.00)

        # 3. Simulate ledger consumption
        ledger.append({
            "movement_id": "MVT-003",
            "movement_type": "BULK_PACKAGED",
            "quantity_kg": 60.0,
            "reference_id": "PKG-001",
            "production_batch_id": "PRB-BATCH-A",
            "unit_cost_per_kg": 142.75,
            "total_cost": 8565.00,
        })
        ledger.append({
            "movement_id": "MVT-004",
            "movement_type": "BULK_PACKAGED",
            "quantity_kg": 40.0,
            "reference_id": "PKG-001",
            "production_batch_id": "PRB-BATCH-B",
            "unit_cost_per_kg": 155.00,
            "total_cost": 6200.00,
        })

        # 4. Check balances after consumption
        after_balances = calculate_batch_bulk_balances(ledger, batches, "moong special papad")
        b_a = next(b for b in after_balances if b["batch_id"] == "PRB-BATCH-A")
        b_b = next(b for b in after_balances if b["batch_id"] == "PRB-BATCH-B")

        self.assertEqual(b_a["available_kg"], 40.0)
        self.assertEqual(b_a["remaining_value"], round(40.0 * 142.75, 2))  # ₹5,710.00
        self.assertEqual(b_b["available_kg"], 60.0)
        self.assertEqual(b_b["remaining_value"], round(60.0 * 155.00, 2))  # ₹9,300.00

    def test_overconsumption_rejection(self):
        """
        Verify that requesting more stock than available in a batch is rejected.
        """
        batches = [
            {
                "production_id": "PRB-001",
                "production_date": "2026-11-01",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Papad",
                "net_quantity_kg": 50.0,
                "actual_cost_per_kg": 140.0,
                "status": "APPROVED",
            }
        ]
        ledger = [
            {
                "movement_id": "MVT-001",
                "movement_type": "BULK_PRODUCED",
                "reference_id": "PRB-001",
                "quantity_kg": 50.0,
            }
        ]
        req_allocations = [
            {"batch_id": "PRB-001", "quantity_kg": 60.0}
        ]
        with self.assertRaises(ValueError) as ctx:
            resolve_packaging_batch_allocations(
                bulk_kg_required=60.0,
                product_id_or_name="Moong Papad",
                ledger_records=ledger,
                production_batches=batches,
                batch_allocations_requested=req_allocations,
            )
        self.assertIn("Insufficient unpackaged bulk stock in batch PRB-001", str(ctx.exception))

    def test_missing_batch_cost_rejection(self):
        """
        Verify that packaging material from an uncosted batch is strictly rejected.
        """
        batches = [
            {
                "production_id": "PRB-UNCOSTED",
                "production_date": "2026-11-01",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Papad",
                "net_quantity_kg": 50.0,
                "actual_cost_per_kg": 0.0,  # Uncosted
                "status": "APPROVED",
            }
        ]
        ledger = [
            {
                "movement_id": "MVT-001",
                "movement_type": "BULK_PRODUCED",
                "reference_id": "PRB-UNCOSTED",
                "quantity_kg": 50.0,
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            resolve_packaging_batch_allocations(
                bulk_kg_required=20.0,
                product_id_or_name="Moong Papad",
                ledger_records=ledger,
                production_batches=batches,
                batch_allocations_requested=[{"batch_id": "PRB-UNCOSTED", "quantity_kg": 20.0}],
            )
        self.assertIn("does not have an approved actual cost per kg", str(ctx.exception))

    def test_automatic_fifo_allocation(self):
        """
        Verify that when batch_allocations is omitted, the engine automatically
        allocates bulk stock in FIFO order.
        """
        batches = [
            {
                "production_id": "PRB-FIFO-1",
                "production_date": "2026-11-01",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Papad",
                "net_quantity_kg": 30.0,
                "actual_cost_per_kg": 140.0,
                "status": "APPROVED",
            },
            {
                "production_id": "PRB-FIFO-2",
                "production_date": "2026-11-02",
                "product_id": "PRD-MOONG-BULK",
                "product_name_snapshot": "Moong Papad",
                "net_quantity_kg": 70.0,
                "actual_cost_per_kg": 150.0,
                "status": "APPROVED",
            },
        ]
        ledger = [
            {"movement_type": "BULK_PRODUCED", "reference_id": "PRB-FIFO-1", "quantity_kg": 30.0},
            {"movement_type": "BULK_PRODUCED", "reference_id": "PRB-FIFO-2", "quantity_kg": 70.0},
        ]

        # Request 50 kg without specifying batch allocations
        res = resolve_packaging_batch_allocations(
            bulk_kg_required=50.0,
            product_id_or_name="Moong Papad",
            ledger_records=ledger,
            production_batches=batches,
            batch_allocations_requested=None,
        )

        self.assertEqual(len(res["allocations"]), 2)
        # Should take 30 kg from FIFO-1 and 20 kg from FIFO-2
        alloc1 = res["allocations"][0]
        alloc2 = res["allocations"][1]
        self.assertEqual(alloc1["batch_id"], "PRB-FIFO-1")
        self.assertEqual(alloc1["quantity_kg"], 30.0)
        self.assertEqual(alloc1["total_cost"], 4200.0)  # 30 * 140
        self.assertEqual(alloc2["batch_id"], "PRB-FIFO-2")
        self.assertEqual(alloc2["quantity_kg"], 20.0)
        self.assertEqual(alloc2["total_cost"], 3000.0)  # 20 * 150

        # Total bulk cost: 4200 + 3000 = 7200
        self.assertEqual(res["total_bulk_cost"], 7200.0)
        self.assertEqual(res["effective_bulk_cost_per_kg"], 144.0)

    def test_packaging_journal_balance_with_multi_batch(self):
        """
        Verify that packaging journal vouchers balance perfectly when multi-batch bulk is consumed.
        """
        pack_data = {
            "packaging_id": "PKG-001",
            "product_name_snapshot": "Moong Papad",
            "bulk_kg_used": 100.0,
            "total_packets": 500,
            "packaging_date": "2026-11-02",
            "bulk_cost": 14765.00,
            "batch_allocations_json": json.dumps([
                {"batch_id": "PRB-A", "quantity_kg": 60.0, "unit_cost_per_kg": 142.75, "total_cost": 8565.00},
                {"batch_id": "PRB-B", "quantity_kg": 40.0, "unit_cost_per_kg": 155.00, "total_cost": 6200.00},
            ]),
        }
        bulk_cost = Decimal("14765.00")
        mat_cost = Decimal("1125.00")  # 500 * 2.25
        lab_cost = Decimal("375.00")   # 500 * 0.75

        res = post_packaging_batch_journal(
            pack_data=pack_data,
            bulk_cost=bulk_cost,
            packing_material_cost=mat_cost,
            packing_labor_cost=lab_cost,
            actor="TEST_OPERATOR",
        )

        self.assertEqual(res["status"], "POSTED")
        total_finished = bulk_cost + mat_cost + lab_cost  # 14765 + 1125 + 375 = 16265.00
        self.assertEqual(res["total_debit"], float(total_finished))
        self.assertEqual(res["total_credit"], float(total_finished))

    def test_packaging_failure_marks_batch_incomplete_and_excludes_from_stock(self):
        """
        Failure Injection 1:
        Simulate database failure when appending to ProductionStockLedger.
        Verify:
        - Packaging record is created with status 'INCOMPLETE'.
        - create_packaging raises HTTPException 503.
        - Incomplete batch does NOT credit finished packet inventory.
        """
        db.memory_store["ProductionBatches"].append({
            "production_id": "PRB-FAIL-01",
            "production_date": "2026-11-01",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "net_quantity_kg": 50.0,
            "actual_cost_per_kg": 140.0,
            "status": "APPROVED",
        })
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MVT-SEED-01",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "quantity_kg": 50.0,
            "reference_id": "PRB-FAIL-01",
            "unit_cost_per_kg": 140.0,
            "total_cost": 7000.0,
        })

        original_append = db.append_record

        def fail_on_ledger(tab_name, record, raise_on_error=False):
            if tab_name == "ProductionStockLedger":
                raise RuntimeError("Simulated database failure during stock ledger append")
            return original_append(tab_name, record, raise_on_error=raise_on_error)

        with patch.object(db, "append_record", side_effect=fail_on_ledger):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_packaging(
                    PackagingCreate(
                        product_id="PRD-MOONG-BULK",
                        packaging_date="2026-11-02",
                        bulk_kg_used=10.0,
                        packets_200g=50,
                        reference="REF-FAIL-INJECT-01",
                    ),
                    self.user,
                ))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("INCOMPLETE", ctx.exception.detail)

        # 1. Verify batch marked as INCOMPLETE
        pack_batches = db.memory_store["PackagingBatches"]
        self.assertEqual(len(pack_batches), 1)
        self.assertEqual(pack_batches[0]["status"], "INCOMPLETE")
        self.assertIn("INCOMPLETE_STOCK_WRITE", pack_batches[0]["notes"])

        # 2. Verify finished goods balance is 0 (incomplete batch excluded from available stock)
        finished_bal = calculate_finished_stock_balance(db.memory_store["ProductionStockLedger"], "PRD-MOONG-200G")
        self.assertEqual(finished_bal.get("PRD-MOONG-200G", 0), 0)

    def test_recover_packaging_posts_missing_movements(self):
        """
        Failure Injection 2:
        Simulate recovery of an INCOMPLETE packaging batch.
        Verify:
        - recover_packaging posts missing bulk deduction and packet credit movements.
        - Status is updated to 'RECORDED'.
        - Finished packet inventory is now credited.
        """
        db.memory_store["PackagingBatches"].append({
            "packaging_id": "PKG-INCOMPLETE-99",
            "packaging_date": "2026-11-02",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 10.0,
            "packets_200g": 50,
            "packets_500g": 0,
            "packets_1000g": 0,
            "total_packets": 50,
            "expected_kg": 10.0,
            "status": "INCOMPLETE",
            "notes": "Failed earlier",
        })

        rec_res = asyncio.run(recover_packaging("PKG-INCOMPLETE-99", self.user))
        self.assertEqual(rec_res["status"], "RECORDED")

        # Verify movements were posted
        ledger = db.memory_store["ProductionStockLedger"]
        bulk_mvts = [m for m in ledger if m.get("reference_id") == "PKG-INCOMPLETE-99" and m.get("movement_type") == "BULK_PACKAGED"]
        pkt_mvts = [m for m in ledger if m.get("reference_id") == "PKG-INCOMPLETE-99" and m.get("movement_type") == "PACKETS_PACKAGED"]
        self.assertEqual(len(bulk_mvts), 1)
        self.assertEqual(bulk_mvts[0]["quantity_kg"], 10.0)
        self.assertEqual(len(pkt_mvts), 1)
        self.assertEqual(pkt_mvts[0]["quantity_packets"], 50)

        # Verify finished stock is now credited
        fin_stock = calculate_finished_stock_balance(ledger, "PRD-MOONG-200G")
        self.assertEqual(fin_stock.get("PRD-MOONG-200G", 0), 50)

    def test_duplicate_retries_produce_zero_duplicate_movements_and_vouchers(self):
        """
        Failure Injection 3 & 4:
        Simulate duplicate packaging requests (network retry or replay).
        Verify:
        - Exactly zero duplicate movements in ProductionStockLedger.
        - Exactly zero duplicate vouchers in JournalHeaders.
        - Returns existing packaging batch seamlessly.
        """
        db.memory_store["ProductionBatches"].append({
            "production_id": "PRB-IDEMP-01",
            "production_date": "2026-11-01",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "net_quantity_kg": 100.0,
            "actual_cost_per_kg": 140.0,
            "status": "APPROVED",
        })
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MVT-SEED-02",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "quantity_kg": 100.0,
            "reference_id": "PRB-IDEMP-01",
            "unit_cost_per_kg": 140.0,
            "total_cost": 14000.0,
        })

        # First request
        req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-02",
            bulk_kg_used=10.0,
            packets_200g=50,
            reference="PKG-IDEMP-RETRY-001",
        )
        res1 = asyncio.run(create_packaging(req, self.user))
        self.assertEqual(res1["status"], "RECORDED")
        pack_id = res1["packaging_id"]

        ledger_len_1 = len(db.memory_store["ProductionStockLedger"])
        voucher_len_1 = len(db.memory_store["JournalHeaders"])

        # Second request (network retry with identical reference and payload)
        res2 = asyncio.run(create_packaging(req, self.user))
        self.assertEqual(res2["packaging_id"], pack_id)

        ledger_len_2 = len(db.memory_store["ProductionStockLedger"])
        voucher_len_2 = len(db.memory_store["JournalHeaders"])

        # Must produce ZERO duplicate movements and ZERO duplicate vouchers
        self.assertEqual(ledger_len_1, ledger_len_2)
        self.assertEqual(voucher_len_1, voucher_len_2)

    def test_conflicting_retry_payload_rejected_with_409(self):
        """
        Verify that reusing an existing packaging reference with conflicting parameters
        is strictly rejected with HTTP 409 Conflict.
        """
        # Seed bulk stock and initial packaging
        db.memory_store["ProductionBatches"].append({
            "production_id": "PRB-IDEMP-02",
            "production_date": "2026-11-01",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "net_quantity_kg": 100.0,
            "actual_cost_per_kg": 140.0,
            "status": "APPROVED",
        })
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MVT-SEED-03",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong special papad",
            "quantity_kg": 100.0,
            "reference_id": "PRB-IDEMP-02",
            "unit_cost_per_kg": 140.0,
            "total_cost": 14000.0,
        })
        init_req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-02",
            bulk_kg_used=10.0,
            packets_200g=50,
            reference="PKG-IDEMP-CONFLICT-001",
        )
        asyncio.run(create_packaging(init_req, self.user))

        # Reusing PKG-IDEMP-CONFLICT-001 with conflicting packets (25 of 200g and 10 of 500g)
        conflicting_req = PackagingCreate(
            product_id="PRD-MOONG-BULK",
            packaging_date="2026-11-02",
            bulk_kg_used=10.0,
            packets_200g=25,
            packets_500g=10,
            reference="PKG-IDEMP-CONFLICT-001",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_packaging(conflicting_req, self.user))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("conflicting payload data", ctx.exception.detail)

    def test_recovery_idempotency_prevents_duplicate_movements_on_repeated_recover(self):
        """
        Verify that repeatedly calling recover_packaging on an already recovered batch
        does not duplicate stock ledger entries.
        """
        db.memory_store["PackagingBatches"].append({
            "packaging_id": "PKG-INCOMPLETE-REPEATED",
            "packaging_date": "2026-11-02",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 10.0,
            "packets_200g": 50,
            "packets_500g": 0,
            "packets_1000g": 0,
            "total_packets": 50,
            "expected_kg": 10.0,
            "status": "INCOMPLETE",
            "notes": "Failed earlier",
        })
        # First recovery
        res1 = asyncio.run(recover_packaging("PKG-INCOMPLETE-REPEATED", self.user))
        self.assertEqual(res1["status"], "RECORDED")
        first_count = len(db.memory_store["ProductionStockLedger"])

        # Second recovery call on the same batch
        res2 = asyncio.run(recover_packaging("PKG-INCOMPLETE-REPEATED", self.user))
        self.assertEqual(res2["status"], "RECORDED")
        second_count = len(db.memory_store["ProductionStockLedger"])
        self.assertEqual(first_count, second_count)


if __name__ == "__main__":
    unittest.main()
