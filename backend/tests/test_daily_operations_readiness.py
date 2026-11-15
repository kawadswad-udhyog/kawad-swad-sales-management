"""
Comprehensive Regression & Operational Readiness Suite for Kawad Swad ERP.

Verifies:
1. Deterministic Product-to-Recipe Mapping (PRD-0001 sequential IDs, SKU variants, ambiguity -> 409, draft blocking, read-only audit, get_sku_costing fix).
2. Google Sheets Backward Compatibility (non-mutating writes, unknown extra columns preserved, duplicate/blank trailing headers tolerated via get_all_values fallback, read-only schema diagnostic endpoint).
3. Raw Material Opening Balance Verification & Unverified Warnings (recorded vs confirmed, Owner/PA verification endpoint, historical preservation).
4. Packaging Discrepancy Safeguards (55 kg historical unresolved locked against reversals/duplicates/synthetic sales; 2.4 kg pending review workflow).
5. Full E2E Daily Business Operations Flow (Raw Material Receipt -> Physical Verification -> Dal Milling -> Master Recipe Mapping -> Batch Creation -> Material Issue -> Batch Approval -> Packaging -> Finished Goods Register -> Central Warehouse Dispatch -> Van Loading Pass Issuance & Acceptance -> Sales Billing).
"""
import os

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import types
import unittest

if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class FastAPI:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def add_middleware(self, *args, **kwargs): pass
            def include_router(self, *args, **kwargs): pass
            def on_event(self, *args, **kwargs): return lambda f: f
            def middleware(self, *args, **kwargs): return lambda f: f
            def exception_handler(self, *args, **kwargs): return lambda f: f
            def get(self, *args, **kwargs): return lambda f: f
            def post(self, *args, **kwargs): return lambda f: f
            def put(self, *args, **kwargs): return lambda f: f
            def patch(self, *args, **kwargs): return lambda f: f
            def delete(self, *args, **kwargs): return lambda f: f

        class APIRouter:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def post(self, path="", **kwargs): return lambda f: f
            def get(self, path="", **kwargs): return lambda f: f
            def put(self, path="", **kwargs): return lambda f: f
            def patch(self, path="", **kwargs): return lambda f: f
            def delete(self, path="", **kwargs): return lambda f: f

        class HTTPException(Exception):
            def __init__(self, status_code, detail=None, headers=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers

        class Request:
            pass

        class status:
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_404_NOT_FOUND = 404
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_429_TOO_MANY_REQUESTS = 429
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503

        @staticmethod
        def Depends(f): return f

        @staticmethod
        def Header(default=None, alias=None): return default

        @staticmethod
        def Query(default=None, **kwargs): return default

    sys.modules["fastapi"] = MockFastAPIModule("fastapi")
    sys.modules["fastapi.security"] = types.ModuleType("security")
    sys.modules["fastapi.security"].HTTPBearer = lambda **kwargs: None
    sys.modules["fastapi.security"].HTTPAuthorizationCredentials = None
    sys.modules["fastapi.middleware"] = types.ModuleType("middleware")
    sys.modules["fastapi.middleware.cors"] = types.ModuleType("cors")
    sys.modules["fastapi.middleware.cors"].CORSMiddleware = object
    sys.modules["fastapi.responses"] = types.ModuleType("responses")
    sys.modules["fastapi.responses"].JSONResponse = lambda content=None, status_code=200: {"status_code": status_code, "content": content}

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
        def model_dump(self):
            return self.__dict__

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    sys.modules["pydantic"].BaseModel = MockBaseModel
    sys.modules["pydantic"].Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)

if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.ModuleType("jwt")
    sys.modules["jwt"].encode = lambda payload, secret, algorithm="HS256": "mock-jwt"
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-OWNER-01", "role": "OWNER"}

from fastapi import HTTPException
from app.sheets import db, REQUIRED_TABS
from app.recipes_master import MASTER_RECIPES_DEFINITION, RAW_MATERIALS_SEED
from app.calculations import (
    calculate_raw_material_balance,
    calculate_finished_stock_balance,
    calculate_warehouse_stock_balance,
    calculate_salesman_stock_balance,
    resolve_product_recipe,
    audit_product_recipe_mappings,
    classify_packaging_discrepancy,
    summarize_packaging_discrepancies,
    AmbiguousRecipeMappingError,
    MissingRecipeMappingError,
)
from app.routers import production as prod
from app.routers import stock as stock_router
from app.routers import sales as sales_router
from app.models import (
    VanLoadingPassCreate,
    VanLoadingItem,
    VanLoadingPassAccept,
    SaleCreate,
    SaleItemCreate,
)


def _reset_db():
    db.is_connected = False
    db.allow_in_memory_fallback = True
    db.spreadsheet = None
    db._records_cache.clear()
    db._worksheets.clear()
    db._fail_once.clear()
    for tab in REQUIRED_TABS:
        db.memory_store[tab] = []


class TestRecipeMappingAndSkuCosting(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        self._orig_spreadsheet = db.spreadsheet
        _reset_db()
        self.owner = {"user_id": "USR-OWNER-01", "full_name": "Owner", "role": "OWNER", "active": True}
        self.pa = {"user_id": "USR-PA-01", "full_name": "PA", "role": "PA", "active": True}
        db.memory_store["Users"] = [self.owner, self.pa]

    def tearDown(self):
        _reset_db()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback
        db.spreadsheet = self._orig_spreadsheet

    def test_prd_0001_and_sku_variants_resolve_deterministically_without_collisions(self):
        """Sequential PRD-0001 IDs and pack-size SKU variants resolve cleanly to exact master formulas."""
        asyncio.run(prod.bootstrap_master_recipes(self.owner))
        # Confirm Garlic variant so both Master and Garlic are approved
        asyncio.run(prod.confirm_master_recipe("RCP-MOONG-GARLIC-V2", prod.RecipeConfirmRequest(approved=True), self.owner))

        products = [
            {"product_id": "PRD-0001", "sku": "KS-MM-200", "product_name": "Moong Master Papad (200g)", "pack_weight_g": 200, "active": "true"},
            {"product_id": "PRD-0002", "sku": "KS-MM-500", "product_name": "Moong Master Papad (500g)", "pack_weight_g": 500, "active": "true"},
            {"product_id": "PRD-0003", "sku": "KS-MG-200", "product_name": "Moong Garlic Papad (200g)", "pack_weight_g": 200, "active": "true"},
            {"product_id": "PRD-0004", "sku": "CUSTOM-SKU", "product_name": "Special Party Pack (400g)", "recipe_id": "RCP-MOONG-MASTER-V2", "pack_weight_g": 400, "active": "true"},
        ]
        db.memory_store["Products"] = products
        recipes = db.get_records("Recipes", fresh=True)

        r1 = resolve_product_recipe(products[0], recipes, MASTER_RECIPES_DEFINITION, require_approved=True)
        r2 = resolve_product_recipe(products[1], recipes, MASTER_RECIPES_DEFINITION, require_approved=True)
        r3 = resolve_product_recipe(products[2], recipes, MASTER_RECIPES_DEFINITION, require_approved=True)
        r4 = resolve_product_recipe(products[3], recipes, MASTER_RECIPES_DEFINITION, require_approved=True)

        self.assertEqual(r1["recipe_id"], "RCP-MOONG-MASTER-V2")
        self.assertEqual(r2["recipe_id"], "RCP-MOONG-MASTER-V2")
        self.assertEqual(r3["recipe_id"], "RCP-MOONG-GARLIC-V2")
        self.assertEqual(r4["recipe_id"], "RCP-MOONG-MASTER-V2")
        self.assertEqual(r4["mapping_source"], "PRODUCT_RECIPE_ID")

    def test_ambiguous_mapping_raises_409_and_unapproved_draft_blocks_issuance(self):
        """Ambiguous recipes raise HTTP 409; unapproved Chana draft blocks issuance until Owner confirms."""
        asyncio.run(prod.bootstrap_master_recipes(self.owner))
        db.memory_store["Products"] = [
            {"product_id": "PRD-0010", "sku": "KS-AMB-200", "product_name": "Ambiguous Spice Papad (200g)", "pack_weight_g": 200, "active": "true"},
            {"product_id": "PRD-0011", "sku": "CHANA-250G", "product_name": "Chana Chotu Papad (250g)", "pack_weight_g": 250, "active": "true"},
        ]
        # Inject two distinct approved recipes with the exact same product name
        db.memory_store["Recipes"].extend([
            {
                "recipe_id": "RCP-AMB-A",
                "product_id": "PRD-AMB-A",
                "product_name_snapshot": "Ambiguous Spice Papad",
                "version": "1",
                "approved": "true",
                "expected_yield_kg": "1.2",
                "items_json": json.dumps([{"material_name": "Moong Dal Flour", "quantity_per_kg": 0.8, "unit": "kg"}]),
            },
            {
                "recipe_id": "RCP-AMB-B",
                "product_id": "PRD-AMB-B",
                "product_name_snapshot": "Ambiguous Spice Papad",
                "version": "1",
                "approved": "true",
                "expected_yield_kg": "1.2",
                "items_json": json.dumps([{"material_name": "Chana Dal Flour", "quantity_per_kg": 0.8, "unit": "kg"}]),
            },
        ])

        with self.assertRaises(HTTPException) as amb_ctx:
            asyncio.run(prod.create_batch(
                prod.ProductionCreate(product_id="PRD-0010", production_date="2026-11-10", quantity_kg=12.0),
                self.pa,
            ))
        self.assertEqual(amb_ctx.exception.status_code, 409)
        self.assertIn("Ambiguous recipe mapping", str(amb_ctx.exception.detail))

        # Chana Chotu is DRAFT/unapproved initially -> batch planning succeeds, but issuance blocks with 400
        chana_batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(product_id="PRD-0011", production_date="2026-11-10", quantity_kg=12.0),
            self.pa,
        ))
        self.assertEqual(chana_batch["recipe_id"], "RCP-CHANA-CHOTU-V2")
        with self.assertRaises(HTTPException) as draft_ctx:
            asyncio.run(prod.issue_materials(chana_batch["production_id"], self.pa))
        self.assertEqual(draft_ctx.exception.status_code, 400)
        self.assertIn("unapproved", str(draft_ctx.exception.detail).lower())

        # Audit endpoint detects approved, draft, ambiguous, and unmapped without mutating sheets
        db.memory_store["Products"].append(
            {"product_id": "PRD-0099", "sku": "UNKNOWN-SKU", "product_name": "Mystery New Snack", "pack_weight_g": 100, "active": "true"}
        )
        audit = asyncio.run(prod.get_recipe_mapping_audit(self.pa))
        self.assertEqual(audit["summary"]["ambiguous"], 1)
        self.assertEqual(audit["summary"]["mapped_draft"], 1)
        self.assertEqual(audit["summary"]["unmapped"], 1)

    def test_get_sku_costing_uses_bulk_cost_per_kg_without_nameerror(self):
        """Regression check for get_sku_costing using defined bulk_cost_per_kg variable."""
        asyncio.run(prod.bootstrap_master_recipes(self.owner))
        db.memory_store["Products"] = [
            {"product_id": "PRD-0001", "sku": "KS-MM-200", "product_name": "Moong Master Papad", "pack_weight_g": 200, "active": "true"}
        ]
        res = asyncio.run(prod.get_sku_costing("PRD-0001", self.pa))
        self.assertEqual(res["product_id"], "PRD-0001")
        self.assertIn("benchmark_production_cost_per_kg", res)
        self.assertGreater(res["benchmark_production_cost_per_kg"], 0)


class TestGoogleSheetsBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        self._orig_spreadsheet = db.spreadsheet
        _reset_db()

    def tearDown(self):
        _reset_db()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback
        db.spreadsheet = self._orig_spreadsheet

    def test_writes_do_not_mutate_headers_and_preserve_unknown_columns(self):
        """Non-mutating writes match existing sheet headers and never alter unknown columns or row-1 headers."""
        class LegacyWorksheet:
            def __init__(self):
                self.rows = [
                    ["product_id", "sku", "product_name", "legacy_tally_code", "owner_margin_note"],
                    ["PRD-0001", "KS-MM-200", "Moong Master Papad", "TLY-889", "Keep priority"],
                ]
                self.update_calls = []

            def row_values(self, row_idx):
                return list(self.rows[row_idx - 1])

            def get_all_records(self):
                headers = self.rows[0]
                return [dict(zip(headers, r)) for r in self.rows[1:]]

            def append_row(self, row, value_input_option=None):
                self.rows.append(list(row))

            def update(self, cell_range, values, value_input_option=None):
                self.update_calls.append((cell_range, values))
                if cell_range.startswith("A") and cell_range[1:].isdigit():
                    r_idx = int(cell_range[1:]) - 1
                    self.rows[r_idx] = list(values[0])

            def batch_update(self, batch_list, value_input_option=None):
                import re as _re
                for entry in batch_list:
                    self.update_calls.append((entry.get("range", ""), entry.get("values", [])))
                    rng = str(entry.get("range", ""))
                    start_ref = rng.split(":")[0]
                    m = _re.match(r"^([A-Z]+)(\d+)$", start_ref)
                    if m:
                        col_letters, row_num = m.group(1), int(m.group(2))
                        col_idx = 0
                        for ch in col_letters:
                            col_idx = col_idx * 26 + (ord(ch) - ord("A") + 1)
                        col_idx -= 1
                        row_idx = row_num - 1
                        vals = entry["values"][0]
                        if len(vals) == 1:
                            self.rows[row_idx][col_idx] = vals[0]
                        else:
                            for offset, v in enumerate(vals):
                                self.rows[row_idx][col_idx + offset] = v

        ws = LegacyWorksheet()

        class MockSpreadsheet:
            def worksheet(self, name):
                if name == "Products":
                    return ws
                raise Exception(f"Worksheet {name} not found")

        db.is_connected = True
        db.allow_in_memory_fallback = False
        db.spreadsheet = MockSpreadsheet()

        ok = db.append_record("Products", {
            "product_id": "PRD-0002",
            "sku": "KS-MM-500",
            "product_name": "Moong Master Papad (500g)",
            "pack_weight_g": 500,  # unmapped in legacy sheet headers!
            "extra_unused_field": "ignore",
        })
        self.assertTrue(ok)
        # Headers row must NOT be rewritten when authorize_header_update defaults to False
        self.assertEqual(ws.rows[0], ["product_id", "sku", "product_name", "legacy_tally_code", "owner_margin_note"])
        self.assertFalse(any(call[0] == "A1" for call in ws.update_calls))
        self.assertEqual(ws.rows[2][:3], ["PRD-0002", "KS-MM-500", "Moong Master Papad (500g)"])

        # Updating row 1 must preserve legacy_tally_code and owner_margin_note untouched
        ok_upd = db.update_record("Products", "product_id", "PRD-0001", {"sku": "KS-MM-200-NEW"})
        self.assertTrue(ok_upd)
        self.assertEqual(ws.rows[1][1], "KS-MM-200-NEW")
        self.assertEqual(ws.rows[1][3], "TLY-889")
        self.assertEqual(ws.rows[1][4], "Keep priority")

    def test_safe_read_tolerates_duplicate_and_blank_trailing_headers(self):
        """When worksheet.get_all_records fails due to duplicate/blank headers, get_all_values fallback succeeds."""
        class MessyHeaderWorksheet:
            def get_all_records(self):
                raise Exception("GSpreadException: the header row in the worksheet contains duplicates")

            def get_all_values(self):
                return [
                    ["raw_material_id", "material_name", "current_stock", "material_name", "", "  "],
                    ["RM-001", "Moong Dal Flour", "45.5", "Duplicate Col Ignored", "TrailingNote", ""],
                ]

        class MockSpreadsheet:
            def worksheet(self, name):
                if name == "RawMaterials":
                    return MessyHeaderWorksheet()
                raise Exception("missing")

        db.is_connected = True
        db.spreadsheet = MockSpreadsheet()
        rows = db.get_records("RawMaterials", fresh=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_material_id"], "RM-001")
        self.assertEqual(rows[0]["material_name"], "Moong Dal Flour")
        self.assertEqual(rows[0]["current_stock"], "45.5")

    def test_schema_compatibility_report_is_read_only(self):
        """inspect_schema_compatibility reports missing optional vs extra columns with mutated=False."""
        class CustomProductsWorksheet:
            title = "Products"
            def row_values(self, idx):
                return ["product_id", "sku", "product_name", "custom_owner_column"]
            def get_all_records(self):
                return [{"product_id": "PRD-1", "sku": "S1", "product_name": "Moong", "custom_owner_column": "Keep"}]

        class MockSpreadsheet:
            def worksheets(self):
                return [CustomProductsWorksheet()]
            def worksheet(self, name):
                if name == "Products":
                    return CustomProductsWorksheet()
                raise Exception(f"Worksheet {name} missing")

        db.is_connected = True
        db.spreadsheet = MockSpreadsheet()
        report = db.inspect_schema_compatibility()
        self.assertFalse(report["mutated"])
        self.assertIn("RawMaterials", report["missing_tabs"])
        self.assertIn("Products", report["extra_columns_preserved"])
        self.assertIn("custom_owner_column", report["extra_columns_preserved"]["Products"])
        self.assertIn("Products", report["missing_optional_columns"])


class TestRawMaterialVerificationAndPackagingDiscrepancy(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        _reset_db()
        self.owner = {"user_id": "USR-OWNER-01", "full_name": "Owner", "role": "OWNER", "active": True}
        self.pa = {"user_id": "USR-PA-01", "full_name": "PA", "role": "PA", "active": True}
        self.salesman = {"user_id": "USR-SALES-01", "full_name": "Sales", "role": "SALESMAN", "active": True}
        db.memory_store["Users"] = [self.owner, self.pa, self.salesman]

    def tearDown(self):
        _reset_db()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback

    def test_unverified_raw_material_opening_stock_flagged_and_verified_safely(self):
        """Existing current_stock is marked UNVERIFIED until verified; confirmation preserves history."""
        db.memory_store["RawMaterials"] = [
            {
                "raw_material_id": "RM-MOONG-FLOUR",
                "material_name": "Moong Dal Flour",
                "category": "FLOUR",
                "unit": "kg",
                "current_stock": 120.0,
            }
        ]
        items = asyncio.run(prod.list_raw_materials(self.pa))
        moong = next(i for i in items if i.raw_material_id == "RM-MOONG-FLOUR")
        self.assertFalse(moong.opening_stock_verified)
        self.assertEqual(moong.verification_status, "UNVERIFIED")
        self.assertEqual(moong.recorded_opening_stock, 120.0)
        self.assertIsNone(moong.verified_physical_stock)
        self.assertTrue(len(moong.unverified_opening_warning) > 10)

        # Missing confirmation checkbox -> 422
        with self.assertRaises(HTTPException) as chk_ctx:
            asyncio.run(prod.verify_raw_material_opening_stock(
                prod.RawMaterialOpeningVerificationRequest(
                    raw_material_id="RM-MOONG-FLOUR",
                    physical_count=95.0,
                    confirm_physical_count=False,
                    reason="Weighed sacks",
                ),
                self.owner,
            ))
        self.assertEqual(chk_ctx.exception.status_code, 422)

        # Salesman -> 403
        with self.assertRaises(HTTPException) as role_ctx:
            asyncio.run(prod.verify_raw_material_opening_stock(
                prod.RawMaterialOpeningVerificationRequest(
                    raw_material_id="RM-MOONG-FLOUR",
                    physical_count=95.0,
                    confirm_physical_count=True,
                    reason="Weighed sacks",
                ),
                self.salesman,
            ))
        self.assertEqual(role_ctx.exception.status_code, 403)

        # Owner verification -> confirmed
        res = asyncio.run(prod.verify_raw_material_opening_stock(
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=True,
                reason="Verified physical weighbridge count",
            ),
            self.owner,
        ))
        self.assertEqual(res["verification_status"], "CONFIRMED")
        self.assertEqual(res["verified_physical_stock"], 95.0)
        self.assertEqual(res["variance"], -25.0)

        # Original RawMaterials.current_stock column preserved untouched!
        self.assertEqual(db.memory_store["RawMaterials"][0]["current_stock"], 120.0)
        # Re-listing reflects CONFIRMED physical balance
        items_after = asyncio.run(prod.list_raw_materials(self.pa))
        moong_after = next(i for i in items_after if i.raw_material_id == "RM-MOONG-FLOUR")
        self.assertTrue(moong_after.opening_stock_verified)
        self.assertEqual(moong_after.verification_status, "CONFIRMED")
        self.assertEqual(moong_after.available_stock, 95.0)
        self.assertEqual(moong_after.unverified_opening_warning, "")

    def test_historical_55kg_locked_against_reversal_duplicate_and_synthetic_sale_while_2_4kg_reviewable(self):
        """55 kg historical variance is locked (409 on recover/approve); 2.4 kg remains reviewable by Owner."""
        db.memory_store["PackagingBatches"] = [
            {
                "packaging_id": "PKG-HIST-55",
                "packaging_date": "2026-10-15",
                "product_id": "PRD-0001",
                "product_name_snapshot": "Moong Master Papad",
                "bulk_kg_used": 75.0,
                "expected_kg": 20.0,
                "total_packets": 100,
                "difference_kg": 55.0,
                "status": "PENDING_REVIEW",
                "difference_status": "REVIEW_REQUIRED",
                "discrepancy_approved": "false",
                "notes": "Historical unresolved discrepancy: 75 kg deduction already recorded; 55 kg products sold but not recorded.",
            },
            {
                "packaging_id": "PKG-PEND-24",
                "packaging_date": "2026-11-12",
                "product_id": "PRD-0001",
                "product_name_snapshot": "Moong Master Papad",
                "bulk_kg_used": 52.4,
                "expected_kg": 50.0,
                "packets_200g": 250,
                "packets_500g": 0,
                "packets_1000g": 0,
                "total_packets": 250,
                "difference_kg": 2.4,
                "status": "PENDING_REVIEW",
                "difference_status": "REVIEW_REQUIRED",
                "discrepancy_approved": "false",
                "notes": "Breakage & moisture dry-loss variance pending Owner review.",
            },
        ]
        db.memory_store["Products"] = [
            {"product_id": "PRD-0001", "sku": "KS-MM-200", "product_name": "Moong Master Papad", "pack_weight_g": 200, "active": "true"}
        ]
        # Existing 75 kg deduction in ProductionStockLedger
        db.memory_store["ProductionStockLedger"] = [
            {"movement_id": "M-75", "reference_id": "PKG-HIST-55", "movement_type": "BULK_PACKAGED", "quantity_kg": 75.0}
        ]

        summary = asyncio.run(prod.packaging_discrepancies_summary(self.pa))
        self.assertEqual(summary["historical_unresolved_count"], 1)
        self.assertEqual(summary["historical_unresolved_kg"], 55.0)
        self.assertEqual(summary["pending_review_count"], 1)
        self.assertEqual(summary["pending_review_kg"], 2.4)

        # Recover & operational approve-discrepancy must both block with HTTP 409 for 55 kg historical row
        with self.assertRaises(HTTPException) as rec_ctx:
            asyncio.run(prod.recover_packaging("PKG-HIST-55", self.owner))
        self.assertEqual(rec_ctx.exception.status_code, 409)

        with self.assertRaises(HTTPException) as app_ctx:
            asyncio.run(prod.approve_packaging_discrepancy(
                "PKG-HIST-55",
                prod.DiscrepancyApprovalRequest(explanation="Attempt override"),
                self.owner,
            ))
        self.assertEqual(app_ctx.exception.status_code, 409)

        # Verify zero duplicate deductions and zero synthetic sales were created
        self.assertEqual(len(db.memory_store["Sales"]), 0)
        self.assertEqual(
            len([m for m in db.memory_store["ProductionStockLedger"] if m.get("reference_id") == "PKG-HIST-55"]),
            1,
        )

        # 2.4 kg pending review: Owner can approve cleanly without synthetic sales
        appr_24 = asyncio.run(prod.approve_packaging_discrepancy(
            "PKG-PEND-24",
            prod.DiscrepancyApprovalRequest(explanation="Verified 2.4 kg drying & breakage loss on packing table"),
            self.owner,
        ))
        self.assertEqual(appr_24["status"], "SUCCESS")
        updated_24 = next(p for p in db.memory_store["PackagingBatches"] if p["packaging_id"] == "PKG-PEND-24")
        self.assertEqual(updated_24["status"], "RECORDED")
        self.assertEqual(updated_24["difference_status"], "APPROVED_DISCREPANCY")
        self.assertEqual(len(db.memory_store["Sales"]), 0)


class TestFullOperationalEndToEndFlow(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        _reset_db()
        self.owner = {"user_id": "USR-OWNER-01", "full_name": "Owner", "role": "OWNER", "active": True}
        self.pa = {"user_id": "USR-PA-01", "full_name": "PA", "role": "PA", "active": True}
        self.salesman = {"user_id": "USR-SALES-01", "full_name": "Ramesh Van", "role": "SALESMAN", "active": True}
        db.memory_store["Users"] = [self.owner, self.pa, self.salesman]
        db.memory_store["Customers"] = [
            {"customer_id": "CUST-01", "shop_name": "Sharma Kirana", "customer_type": "RETAIL", "active": "true"}
        ]
        # Sequential PRD-0001 SKU linked deterministically via KS-MM-200 & normalized base name
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-0001",
                "sku": "KS-MM-200",
                "product_name": "Moong Master Papad (200g)",
                "category": "Papad",
                "variant": "Master",
                "pack_weight_g": 200,
                "selling_unit": "PACKET",
                "active": "true",
            }
        ]
        db.memory_store["RawMaterials"] = [dict(r, current_stock=0.0) for r in RAW_MATERIALS_SEED]

    def tearDown(self):
        _reset_db()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback

    def test_complete_daily_business_operations_flow(self):
        """
        Full operational trace:
        RM Receipt -> Opening Verification -> Dal Milling -> Master Recipe -> Batch -> Material Issue -> Approve
        -> Packaging -> Finished Goods Register -> Central Warehouse Dispatch -> Van Loading Pass -> Sale Billing
        """
        # 1. Bootstrap master recipes into Recipes sheet & confirm Moong Master
        asyncio.run(prod.bootstrap_master_recipes(self.owner))

        # 2. Verify physical opening stock for minor spices/oil/packaging (e.g., 20 kg Salt, 50 kg other ingredients)
        for mat in db.memory_store["RawMaterials"]:
            mid = mat["raw_material_id"]
            if mid not in {"RM-WHOLE-MOONG-DAL", "RM-MOONG-FLOUR"}:
                asyncio.run(prod.verify_raw_material_opening_stock(
                    prod.RawMaterialOpeningVerificationRequest(
                        raw_material_id=mid,
                        physical_count=100.0,
                        confirm_physical_count=True,
                        reason="Opening physical check",
                    ),
                    self.owner,
                ))

        # 3. Raw Material Receipt (Whole Moong Dal: 100 kg @ Rs 100/kg)
        rec_res = asyncio.run(prod.receive_raw_material(
            prod.RawMaterialReceiveRequest(
                raw_material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=100.0,
                supplier_name="Mandi Agro Traders",
                invoice_reference="INV-OPS-001",
                receipt_date="2026-11-14",
            ),
            self.pa,
        ))
        self.assertEqual(rec_res.new_available_stock, 100.0)

        # 4. Dal Milling (50 kg Whole Moong Dal -> 48 kg Moong Dal Flour, Rs 100 milling expense)
        mill_res = asyncio.run(prod.record_dal_milling_batch(
            prod.DalMillingCreate(
                source_material_id="RM-WHOLE-MOONG-DAL",
                input_quantity_kg=50.0,
                flour_output_kg=48.0,
                milling_expenses=100.0,
                milling_date="2026-11-14",
            ),
            self.pa,
        ))
        self.assertEqual(mill_res.new_whole_stock, 50.0)
        self.assertEqual(mill_res.new_flour_stock, 48.0)

        # 5. Create Production Batch for PRD-0001 (12 kg target), issue raw materials, approve batch
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-14",
                quantity_kg=12.0,
                wastage_kg=0.0,
                flour_base_used_kg=10.0,
            ),
            self.pa,
        ))
        self.assertEqual(batch["recipe_id"], "RCP-MOONG-MASTER-V2")
        issue_res = asyncio.run(prod.issue_materials(batch["production_id"], self.pa))
        self.assertEqual(issue_res["status"], "MATERIALS_ISSUED")
        approved_batch = asyncio.run(prod.approve_batch(
            batch["production_id"],
            prod.ApprovalRequest(approved=True, notes="QA passed"),
            self.owner,
        ))
        self.assertEqual(approved_batch["status"], "APPROVED")

        # 6. Packaging: 12 kg bulk -> 60 packets of 200g (exact match: 60 * 0.2 = 12.0 kg)
        pack_res = asyncio.run(prod.create_packaging(
            prod.PackagingCreate(
                product_id="PRD-0001",
                packaging_date="2026-11-14",
                bulk_kg_used=12.0,
                packets_200g=60,
                packets_500g=0,
                packets_1000g=0,
            ),
            self.pa,
        ))
        self.assertEqual(pack_res["total_packets"], 60)

        # 7. Finished Goods Register confirms 60 packets at Factory
        fg_bal = calculate_finished_stock_balance(db.get_records("ProductionStockLedger", fresh=True), "PRD-0001")
        self.assertEqual(fg_bal.get("PRD-0001", 0), 60)

        # 8. Dispatch 50 packets from Factory to Central Warehouse
        disp_res = asyncio.run(prod.dispatch(
            prod.DispatchCreate(
                product_id="PRD-0001",
                channel="WAREHOUSE",
                destination="Central Warehouse",
                quantity_packets=50,
                reference="DISP-E2E-001",
            ),
            self.pa,
        ))
        self.assertEqual(disp_res["channel"], "WAREHOUSE")
        wh_bal = calculate_warehouse_stock_balance(db.get_records("SalesmanStockLedger", fresh=True), "PRD-0001")
        self.assertEqual(wh_bal.get("PRD-0001", 0), 50)

        # 9. Van Loading Pass Issuance & Acceptance (30 packets loaded to Salesman Van)
        vlp = asyncio.run(stock_router.create_van_loading_pass(
            VanLoadingPassCreate(
                van_number="RJ-06-KS-01",
                salesman_user_id="USR-SALES-01",
                loading_date="2026-11-14",
                items=[VanLoadingItem(product_id="PRD-0001", quantity=30)],
            ),
            self.pa,
        ))
        accepted_vlp = asyncio.run(stock_router.accept_van_loading_pass(
            vlp.pass_id,
            VanLoadingPassAccept(notes="Verified 30 packets loaded"),
            self.salesman,
        ))
        self.assertEqual(accepted_vlp.status, "ACCEPTED")

        wh_after_load = calculate_warehouse_stock_balance(db.get_records("SalesmanStockLedger", fresh=True), "PRD-0001")
        van_bal = calculate_salesman_stock_balance(db.get_records("SalesmanStockLedger", fresh=True), "USR-SALES-01", "PRD-0001")
        self.assertEqual(wh_after_load.get("PRD-0001", 0), 20)
        self.assertEqual(van_bal, 30)

        # 10. Sales Billing (10 packets sold for Cash @ Rs 50/packet = Rs 500)
        sale_res = asyncio.run(sales_router.create_sale(
            SaleCreate(
                idempotency_key="SALE-E2E-001",
                sales_type="RETAIL",
                customer_id="CUST-01",
                customer_name_snapshot="Sharma Kirana",
                salesman_user_id="USR-SALES-01",
                delivery_status="DELIVERED",
                payment_status="PAID",
                payment_method="CASH",
                items=[SaleItemCreate(product_id="PRD-0001", quantity=10, actual_unit_price=50.0)],
            ),
            self.salesman,
        ))
        bill_tot = getattr(sale_res, "bill_total", None) if not isinstance(sale_res, dict) else sale_res.get("bill_total")
        self.assertEqual(bill_tot, 500.0)
        van_after_sale = calculate_salesman_stock_balance(db.get_records("SalesmanStockLedger", fresh=True), "USR-SALES-01", "PRD-0001")
        self.assertEqual(van_after_sale, 20)


class TestRawMaterialOpeningVerificationSecurityAndEnforcement(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        _reset_db()
        self.owner = {"user_id": "USR-OWNER-01", "full_name": "Owner", "role": "OWNER", "active": True}
        self.pa = {"user_id": "USR-PA-01", "full_name": "PA", "role": "PA", "active": True}
        self.salesman = {"user_id": "USR-SALES-01", "full_name": "Sales", "role": "SALESMAN", "active": True}
        db.memory_store["Users"] = [self.owner, self.pa, self.salesman]
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-0001",
                "sku": "KS-MM-200",
                "product_name": "Moong Master Papad (200g)",
                "category": "Papad",
                "variant": "Master",
                "pack_weight_g": 200,
                "selling_unit": "PACKET",
                "active": "true",
            }
        ]
        db.memory_store["Recipes"] = [
            {
                "recipe_id": "RCP-TEST-MM",
                "product_id": "PRD-0001",
                "product_name_snapshot": "Moong Master Papad (200g)",
                "version": "1",
                "approved": "true",
                "expected_yield_kg": "1.0",
                "items_json": json.dumps([
                    {"material_name": "Moong Dal Flour", "quantity_per_kg": 1.0, "unit": "kg"},
                    {"material_name": "Salt", "quantity_per_kg": 0.05, "unit": "kg"},
                ]),
            }
        ]
        db.memory_store["RawMaterials"] = [
            {
                "raw_material_id": "RM-MOONG-FLOUR",
                "material_name": "Moong Dal Flour",
                "category": "FLOUR",
                "unit": "kg",
                "current_stock": 120.0,
                "rate_per_unit": 95.0,
                "rate_status": "CONFIRMED",
            },
            {
                "raw_material_id": "RM-SALT",
                "material_name": "Salt",
                "category": "SPICE",
                "unit": "kg",
                "current_stock": 50.0,
                "rate_per_unit": 20.0,
                "rate_status": "CONFIRMED",
                "opening_stock_verified": "true",
            },
            {
                "raw_material_id": "RM-WHOLE-MOONG-DAL",
                "material_name": "Whole Moong Dal",
                "category": "WHOLE_GRAIN",
                "unit": "kg",
                "current_stock": 100.0,
                "rate_per_unit": 85.0,
                "rate_status": "CONFIRMED",
            },
        ]

    def tearDown(self):
        _reset_db()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback

    def test_01_unverified_opening_stock_blocks_issue_materials(self):
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=10.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(batch["production_id"], self.pa))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("UNVERIFIED", str(ctx.exception.detail))
        self.assertIn("Owner", str(ctx.exception.detail))
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 0)

    def test_02_unverified_opening_stock_blocks_auto_issue_and_rolls_back_batch(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_batch(
                prod.ProductionCreate(
                    product_id="PRD-0001",
                    production_date="2026-11-15",
                    quantity_kg=10.0,
                    wastage_kg=0.0,
                    auto_issue_materials=True,
                ),
                self.pa,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("UNVERIFIED", str(ctx.exception.detail))
        self.assertEqual(len(db.memory_store["ProductionBatches"]), 0)
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 0)

    def test_03_unverified_opening_stock_blocks_approve_batch(self):
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=10.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.approve_batch(
                batch["production_id"],
                prod.ApprovalRequest(approved=True),
                self.owner,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("UNVERIFIED", str(ctx.exception.detail))
        saved_batch = db.memory_store["ProductionBatches"][0]
        self.assertEqual(saved_batch["status"], "PENDING")
        self.assertEqual(saved_batch["materials_issued"], "false")
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 0)
        self.assertEqual(len(db.memory_store["ProductionStockLedger"]), 0)

    def test_04_unverified_opening_stock_blocks_dal_milling(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.record_dal_milling_batch(
                prod.DalMillingCreate(
                    source_material_id="RM-WHOLE-MOONG-DAL",
                    input_quantity_kg=50.0,
                    flour_output_kg=48.0,
                    milling_expenses=100.0,
                    milling_date="2026-11-15",
                ),
                self.pa,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("UNVERIFIED", str(ctx.exception.detail))
        self.assertIn("Owner", str(ctx.exception.detail))
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 0)
        self.assertEqual(len(db.memory_store["MillingBatches"]), 0)

    def test_05_partial_confirmed_receipt_usable_while_unverified_opening_blocked(self):
        asyncio.run(prod.receive_raw_material(
            prod.RawMaterialReceiveRequest(
                raw_material_id="RM-MOONG-FLOUR",
                quantity=5.0,
                unit="kg",
                purchase_rate=96.0,
                supplier_name="Flour Mill",
                invoice_reference="INV-PART-01",
                receipt_date="2026-11-15",
            ),
            self.pa,
        ))
        items = asyncio.run(prod.list_raw_materials(self.pa))
        moong = next(i for i in items if i.raw_material_id == "RM-MOONG-FLOUR")
        self.assertFalse(moong.opening_stock_verified)
        self.assertEqual(moong.available_stock, 125.0)
        self.assertEqual(moong.confirmed_available_stock, 5.0)

        # 4 kg uses confirmed received stock only -> allowed
        b_small = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=4.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        res_small = asyncio.run(prod.issue_materials(b_small["production_id"], self.pa))
        self.assertEqual(res_small["status"], "MATERIALS_ISSUED")

        # 10 kg tries to dip into unverified 120 kg opening stock -> blocked
        b_large = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=10.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(b_large["production_id"], self.pa))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("UNVERIFIED", str(ctx.exception.detail))

    def test_06_owner_verification_unlocks_production_and_writes_valid_schema(self):
        ver = asyncio.run(prod.verify_raw_material_opening_stock(
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=True,
                reason="Physical bag weighment",
                idempotency_key="VER-SCHEMA-01",
            ),
            self.owner,
        ))
        self.assertEqual(ver["verification_status"], "CONFIRMED")
        self.assertEqual(ver["confirmed_available_stock"], 95.0)
        self.assertFalse(ver["is_replay"])
        self.assertEqual(db.memory_store["RawMaterials"][0]["current_stock"], 120.0)

        ledger_rows = [
            r for r in db.memory_store["RawMaterialLedger"]
            if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"
        ]
        self.assertEqual(len(ledger_rows), 1)
        lrow = ledger_rows[0]
        self.assertIn("raw_material_txn_id", lrow)
        self.assertIn("issue_txn_id", lrow)
        self.assertIn("rate_per_unit", lrow)
        self.assertIn("production_id", lrow)
        self.assertNotIn("ledger_id", lrow)
        self.assertNotIn("reference", lrow)
        self.assertEqual(lrow["raw_material_txn_id"], ver["raw_material_txn_id"])

        audit_rows = [
            a for a in db.memory_store["AuditLog"]
            if a.get("action") == "VERIFY_RAW_MATERIAL_OPENING_STOCK"
        ]
        self.assertEqual(len(audit_rows), 1)
        self.assertEqual(audit_rows[0]["related_record_id"], ver["raw_material_txn_id"])

        # Now issuing 95 kg succeeds cleanly
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=95.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        issue_res = asyncio.run(prod.issue_materials(batch["production_id"], self.pa))
        self.assertEqual(issue_res["status"], "MATERIALS_ISSUED")
        items = asyncio.run(prod.list_raw_materials(self.pa))
        moong = next(i for i in items if i.raw_material_id == "RM-MOONG-FLOUR")
        self.assertEqual(moong.available_stock, 0.0)
        self.assertEqual(moong.confirmed_available_stock, 0.0)

    def test_07_owner_only_rbac_and_input_validation(self):
        for non_owner in (self.pa, self.salesman):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(prod.verify_raw_material_opening_stock(
                    prod.RawMaterialOpeningVerificationRequest(
                        raw_material_id="RM-MOONG-FLOUR",
                        physical_count=95.0,
                        confirm_physical_count=True,
                        reason="Attempted verification",
                    ),
                    non_owner,
                ))
            self.assertEqual(ctx.exception.status_code, 403)

        invalid_payloads = [
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=-5.0,
                confirm_physical_count=True,
                reason="Negative check",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=float("nan"),
                confirm_physical_count=True,
                reason="NaN check",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=float("inf"),
                confirm_physical_count=True,
                reason="Inf check",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=False,
                reason="Missing checkbox",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=True,
                reason="ok",
            ),
        ]
        for payload in invalid_payloads:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(prod.verify_raw_material_opening_stock(payload, self.owner))
            self.assertEqual(ctx.exception.status_code, 422)

    def test_08_idempotent_replay_and_auditlog_failure_recovery(self):
        db._fail_once["AuditLog"] = 1
        req = prod.RawMaterialOpeningVerificationRequest(
            raw_material_id="RM-MOONG-FLOUR",
            physical_count=95.0,
            confirm_physical_count=True,
            reason="Verified sacks with weighbridge",
            idempotency_key="VER-AUDIT-REC-01",
        )
        with self.assertRaises(HTTPException) as fail_ctx:
            asyncio.run(prod.verify_raw_material_opening_stock(req, self.owner))
        self.assertEqual(fail_ctx.exception.status_code, 503)

        self.assertEqual(
            len([r for r in db.memory_store["RawMaterialLedger"] if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"]),
            1,
        )
        self.assertEqual(
            len([a for a in db.memory_store["AuditLog"] if a.get("action") == "VERIFY_RAW_MATERIAL_OPENING_STOCK"]),
            0,
        )

        # Retry recovers missing AuditLog without duplicating RawMaterialLedger
        replay_res = asyncio.run(prod.verify_raw_material_opening_stock(req, self.owner))
        self.assertTrue(replay_res["is_replay"])
        self.assertEqual(replay_res["verified_physical_stock"], 95.0)
        self.assertEqual(
            len([r for r in db.memory_store["RawMaterialLedger"] if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"]),
            1,
        )
        self.assertEqual(
            len([a for a in db.memory_store["AuditLog"] if a.get("action") == "VERIFY_RAW_MATERIAL_OPENING_STOCK"]),
            1,
        )

        # Third identical call still produces zero duplicates
        replay_res_2 = asyncio.run(prod.verify_raw_material_opening_stock(req, self.owner))
        self.assertTrue(replay_res_2["is_replay"])
        self.assertEqual(
            len([r for r in db.memory_store["RawMaterialLedger"] if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"]),
            1,
        )
        self.assertEqual(
            len([a for a in db.memory_store["AuditLog"] if a.get("action") == "VERIFY_RAW_MATERIAL_OPENING_STOCK"]),
            1,
        )

    def test_09_conflicting_verification_retries_return_409(self):
        asyncio.run(prod.verify_raw_material_opening_stock(
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=True,
                reason="Initial count",
                idempotency_key="VER-CONF-01",
            ),
            self.owner,
        ))

        conflicts = [
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-SALT",
                physical_count=50.0,
                confirm_physical_count=True,
                reason="Initial count",
                idempotency_key="VER-CONF-01",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=96.0,
                confirm_physical_count=True,
                reason="Initial count",
                idempotency_key="VER-CONF-01",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=80.0,
                confirm_physical_count=True,
                reason="Initial count",
                idempotency_key="VER-CONF-02",
            ),
            prod.RawMaterialOpeningVerificationRequest(
                raw_material_id="RM-MOONG-FLOUR",
                physical_count=95.0,
                confirm_physical_count=True,
                reason="Different reason",
                idempotency_key="VER-CONF-02",
            ),
        ]
        for bad_req in conflicts:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(prod.verify_raw_material_opening_stock(bad_req, self.owner))
            self.assertEqual(ctx.exception.status_code, 409)

        self.assertEqual(
            len([r for r in db.memory_store["RawMaterialLedger"] if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"]),
            1,
        )

    def test_10_concurrent_verification_and_issuance_serialization(self):
        b1 = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=10.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))
        b2 = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-0001",
                production_date="2026-11-15",
                quantity_kg=10.0,
                wastage_kg=0.0,
                auto_issue_materials=False,
            ),
            self.pa,
        ))

        def run_verify():
            return asyncio.run(prod.verify_raw_material_opening_stock(
                prod.RawMaterialOpeningVerificationRequest(
                    raw_material_id="RM-MOONG-FLOUR",
                    physical_count=15.0,
                    confirm_physical_count=True,
                    reason="Physical stock 15 kg",
                    idempotency_key="VER-CONC-01",
                ),
                self.owner,
            ))

        def run_issue(batch_id: str):
            try:
                return asyncio.run(prod.issue_materials(batch_id, self.pa))
            except HTTPException as exc:
                return {"error": exc.status_code, "detail": exc.detail}

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_ver1 = pool.submit(run_verify)
            f_ver2 = pool.submit(run_verify)
            f_iss1 = pool.submit(run_issue, b1["production_id"])
            f_iss2 = pool.submit(run_issue, b2["production_id"])
            ver1 = f_ver1.result()
            ver2 = f_ver2.result()
            iss1 = f_iss1.result()
            iss2 = f_iss2.result()

        self.assertEqual(ver1["confirmed_available_stock"], 15.0)
        self.assertEqual(ver2["confirmed_available_stock"], 15.0)
        self.assertEqual(
            len([r for r in db.memory_store["RawMaterialLedger"] if r.get("movement_type") == "OPENING_STOCK_VERIFICATION"]),
            1,
        )
        self.assertEqual(
            len([a for a in db.memory_store["AuditLog"] if a.get("action") == "VERIFY_RAW_MATERIAL_OPENING_STOCK"]),
            1,
        )

        issued_count = sum(1 for r in (iss1, iss2) if r.get("status") == "MATERIALS_ISSUED")
        self.assertLessEqual(issued_count, 1)

        bal = calculate_raw_material_balance(
            "Moong Dal Flour",
            db.memory_store["RawMaterials"],
            db.memory_store["RawMaterialLedger"],
        )
        expected_remaining = 15.0 - (10.0 * issued_count)
        self.assertTrue(bal["opening_stock_verified"])
        self.assertEqual(bal["available"], expected_remaining)
        self.assertEqual(bal["confirmed_available"], expected_remaining)


if __name__ == "__main__":
    unittest.main()
