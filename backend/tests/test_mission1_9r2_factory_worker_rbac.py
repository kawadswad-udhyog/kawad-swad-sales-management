"""
Mission 1.9R-2: FACTORY_WORKER Privilege Escalation Repair (M19-002)
Targeted security test suite verifying least-privilege RBAC enforcement for
FACTORY_WORKER, legacy aliases (PRODUCTION_WORKER, WORKER), and related
role-normalization boundaries across backend permission helpers and routes.
"""

import os

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
import unittest
from unittest.mock import patch

import tests  # noqa: F401 - initializes test runtime shims when optional packages absent
from fastapi import HTTPException

from app import auth as auth_mod
from app import permissions as perms
from app.routers import auth as auth_router
from app.routers import production as prod_mod
from app.routers import quality as quality_mod
from app.routers import v2_erp as v2_erp_mod
from app.routers import workforce as workforce_mod
from app.sheets import ID_PREFIXES, REQUIRED_TABS, db
from tests.phase4_fixtures import seed_basic_moong_recipe
from tests.v2_test_harness import LocalAppsScriptSimulator, V2RouterProxy

prod = V2RouterProxy(prod_mod)
v2_erp = V2RouterProxy(v2_erp_mod)
quality = V2RouterProxy(quality_mod)
workforce = V2RouterProxy(workforce_mod)


class _DummyRequest:
    _seq = 0

    def __init__(self, headers=None):
        _DummyRequest._seq += 1
        default_headers = {"X-KS-Idempotency-Key": f"m19r2-nonce-{_DummyRequest._seq}"}
        if headers:
            default_headers.update(headers)
        self.headers = default_headers
        self.client = None


class TestMission19R2FactoryWorkerRBAC(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        db.is_connected = False
        db.allow_in_memory_fallback = True
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()
        for key in list(REQUIRED_TABS.keys()) + list(ID_PREFIXES.keys()):
            db.memory_store[key] = []
        self._sim = LocalAppsScriptSimulator().start()

        db.memory_store.update(
            {
                "Products": [
                    {
                        "product_id": "PRD-M-200",
                        "sku": "KS-MP-200",
                        "product_name": "Moong Master Papad",
                        "active": "true",
                        "pack_weight_g": 200,
                    },
                ],
                "RawMaterials": [
                    {
                        "raw_material_id": "RM-MOONG",
                        "material_name": "Moong Flour",
                        "current_stock": 500.0,
                        "unit": "kg",
                        "rate_per_unit": 90.0,
                        "rate_status": "CONFIRMED",
                        "opening_stock_verified": "true",
                    },
                    {
                        "raw_material_id": "RM-SALT",
                        "material_name": "Salt",
                        "current_stock": 100.0,
                        "unit": "kg",
                        "rate_per_unit": 20.0,
                        "rate_status": "CONFIRMED",
                        "opening_stock_verified": "true",
                    },
                    {
                        "raw_material_id": "RM-OIL",
                        "material_name": "Edible Oil",
                        "current_stock": 50.0,
                        "unit": "L",
                        "rate_per_unit": 140.0,
                        "rate_status": "CONFIRMED",
                        "opening_stock_verified": "true",
                    },
                ],
                "AuthUsers": [
                    {
                        "user_id": "USR-FW-1",
                        "name": "Floor Worker",
                        "email": "worker@kawadswad.local",
                        "role": "FACTORY_WORKER",
                        "active": "true",
                        "token_version": 1,
                    },
                    {
                        "user_id": "USR-PW-1",
                        "name": "Legacy Production Worker",
                        "email": "prodworker@kawadswad.local",
                        "role": "PRODUCTION_WORKER",
                        "active": "true",
                        "token_version": 1,
                    },
                    {
                        "user_id": "USR-W-1",
                        "name": "Legacy Worker",
                        "email": "w1@kawadswad.local",
                        "role": "WORKER",
                        "active": "true",
                        "token_version": 1,
                    },
                ],
            }
        )
        seed_basic_moong_recipe(db, "PRD-M-200", "Moong Master Papad")

        self.owner_user = {"user_id": "USR-OWN-1", "role": "OWNER_ADMIN", "name": "Owner", "email": "owner@ks.local"}
        self.owner_legacy_user = {"user_id": "USR-OWN-2", "role": "OWNER", "name": "Legacy Owner"}
        self.pa_user = {"user_id": "USR-PA-1", "role": "PA", "name": "PA"}
        self.production_user = {"user_id": "USR-PROD-1", "role": "PRODUCTION", "name": "Production Operator"}
        self.packaging_user = {"user_id": "USR-PACK-1", "role": "PACKAGING", "name": "Packaging Operator"}
        self.factory_worker = {"user_id": "USR-FW-1", "role": "FACTORY_WORKER", "name": "Floor Worker"}
        self.prod_worker_alias = {"user_id": "USR-PW-1", "role": "PRODUCTION_WORKER", "name": "Legacy Prod Worker"}
        self.worker_alias = {"user_id": "USR-W-1", "role": "WORKER", "name": "Legacy Worker"}
        self.dispatch_user = {"user_id": "USR-DISP-1", "role": "DISPATCH", "name": "Dispatch User"}
        self.auditor_user = {"user_id": "USR-AUD-1", "role": "AUDITOR", "name": "Auditor"}

    def tearDown(self):
        self._sim.stop()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()

    def _assert_403(self, exc_ctx):
        self.assertEqual(exc_ctx.exception.status_code, 403)
        self.assertTrue(str(exc_ctx.exception.detail).strip())

    # 1. FACTORY_WORKER can view permitted production resources
    def test_01_factory_worker_can_view_production_resources(self):
        self.assertTrue(perms.has_permission(self.factory_worker, "production", "view"))
        self.assertEqual(
            perms.effective_permissions_for(self.factory_worker),
            {"production": ["view"]},
        )

        summary = asyncio.run(prod.summary(self.factory_worker))
        self.assertIn("bulk_stock", summary)

        recipes = asyncio.run(prod.recipes(self.factory_worker))
        self.assertIsInstance(recipes, list)

        batches = asyncio.run(prod.batches(self.factory_worker))
        self.assertIsInstance(batches, list)

        caps = asyncio.run(v2_erp.get_erp_capabilities(self.factory_worker))
        self.assertEqual(caps["role"], "FACTORY_WORKER")
        self.assertEqual(caps["module_permissions"], {"production": ["view"]})

    # 2. FACTORY_WORKER cannot create production records (HTTP 403)
    def test_02_factory_worker_cannot_create_production_records(self):
        self.assertFalse(perms.has_permission(self.factory_worker, "production", "create"))

        with self.assertRaises(HTTPException) as ctx_batch:
            asyncio.run(
                prod.create_batch(
                    prod_mod.ProductionCreate(
                        product_id="PRD-M-200",
                        production_date="2026-11-01",
                        quantity_kg=10,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_batch)

        with self.assertRaises(HTTPException) as ctx_recipe:
            asyncio.run(
                prod.save_recipe(
                    prod_mod.RecipeSave(
                        product_id="PRD-M-200",
                        base_output_kg=10,
                        ingredients=[{"raw_material_id": "RM-MOONG", "quantity": 10, "unit": "kg"}],
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_recipe)

        with self.assertRaises(HTTPException) as ctx_rm:
            asyncio.run(
                prod.receive_raw_material(
                    prod_mod.RawMaterialReceiveRequest(
                        raw_material_id="RM-MOONG",
                        quantity=25,
                        unit="kg",
                        rate_per_unit=90,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_rm)

        with self.assertRaises(HTTPException) as ctx_pack:
            asyncio.run(
                prod.create_packaging(
                    prod_mod.PackagingCreate(
                        product_id="PRD-M-200",
                        packaging_date="2026-11-01",
                        bulk_used_kg=5,
                        packets_produced=25,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_pack)

        with self.assertRaises(HTTPException) as ctx_v2_batch:
            asyncio.run(
                v2_erp.create_v2_production_batch(
                    v2_erp_mod.GovernedProductionBatchRequest(
                        product_id="PRD-M-200",
                        planned_quantity_kg=10,
                        nonce="fw-test-nonce-1",
                    ),
                    self.factory_worker,
                    _DummyRequest(),
                )
            )
        self._assert_403(ctx_v2_batch)

        with self.assertRaises(HTTPException) as ctx_v2_mill:
            asyncio.run(
                v2_erp.create_v2_milling_batch(
                    v2_erp_mod.GovernedMillingBatchRequest(
                        source_material_id="RM-MOONG",
                        input_quantity_kg=20,
                        flour_output_kg=18,
                        nonce="fw-test-nonce-2",
                    ),
                    self.factory_worker,
                    _DummyRequest(),
                )
            )
        self._assert_403(ctx_v2_mill)

    # 3. FACTORY_WORKER cannot edit production records (HTTP 403)
    def test_03_factory_worker_cannot_edit_production_records(self):
        for action in (
            "create",
            "update",
            "edit",
            "delete",
            "record_consumption",
            "record_output",
            "record_loss",
            "record_gig_work",
            "costing",
        ):
            self.assertFalse(
                perms.has_permission(self.factory_worker, "production", action),
                f"FACTORY_WORKER must not have production:{action}",
            )

        with self.assertRaises(HTTPException) as ctx_att:
            asyncio.run(
                prod.update_attendance(
                    "ATT-1",
                    prod_mod.AttendanceUpdate(status="PRESENT", notes="unauthorized edit"),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_att)

        with self.assertRaises(HTTPException) as ctx_issue:
            asyncio.run(
                prod.issue_materials(
                    "PRD-BATCH-1",
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_issue)

        with self.assertRaises(HTTPException) as ctx_mill:
            asyncio.run(
                prod.record_dal_milling_batch(
                    prod_mod.DalMillingCreate(
                        raw_dal_id="RM-WHOLE-MOONG-DAL",
                        raw_dal_input_kg=10,
                        flour_output_kg=9,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_mill)

        with self.assertRaises(HTTPException) as ctx_disp:
            asyncio.run(
                prod.dispatch(
                    prod_mod.DispatchCreate(
                        product_id="PRD-M-200",
                        quantity_packets=5,
                        channel="WHOLESALE",
                        destination="Unauthorized",
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_disp)

    # 4. FACTORY_WORKER cannot approve production mutations (HTTP 403)
    def test_04_factory_worker_cannot_approve_production_mutations(self):
        self.assertFalse(perms.has_permission(self.factory_worker, "production", "approve"))

        batch = asyncio.run(
            prod.create_batch(
                prod_mod.ProductionCreate(
                    product_id="PRD-M-200",
                    production_date="2026-11-01",
                    quantity_kg=10,
                ),
                _DummyRequest(),
                self.production_user,
            )
        )

        with self.assertRaises(HTTPException) as ctx_approve:
            asyncio.run(
                prod.approve_batch(
                    batch["batch_id"],
                    prod_mod.ApprovalRequest(approved=True),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_approve)
        self.assertIn("Owner", str(ctx_approve.exception.detail))

        with self.assertRaises(HTTPException) as ctx_confirm:
            asyncio.run(
                prod.confirm_master_recipe(
                    "RCP-1",
                    prod_mod.RecipeConfirmRequest(notes="unauthorized confirm"),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_confirm)

    # 5. FACTORY_WORKER cannot perform privileged writes via alternate routes (HTTP 403)
    def test_05_factory_worker_denied_on_alternate_privileged_routes(self):
        with self.assertRaises(HTTPException) as ctx_perm_guard:
            perms.require_production_access(self.factory_worker)
        self._assert_403(ctx_perm_guard)

        with self.assertRaises(HTTPException) as ctx_mod_act:
            perms.require_module_action(self.factory_worker, "production", "create")
        self._assert_403(ctx_mod_act)

        with self.assertRaises(HTTPException) as ctx_roles:
            perms.require_roles(self.factory_worker, {"OWNER_ADMIN", "PRODUCTION"})
        self._assert_403(ctx_roles)

        with self.assertRaises(HTTPException) as ctx_qc:
            asyncio.run(
                quality.create_quality_check(
                    quality_mod.QualityCheckCreate(
                        check_type="PRODUCTION_BATCH",
                        reference_type="PRODUCTION_BATCH",
                        reference_id="PRD-BATCH-1",
                        product_or_material_id="PRD-M-200",
                        item_name="Moong Master Papad",
                        result="PASS",
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_qc)

        with self.assertRaises(HTTPException) as ctx_v2_gig:
            asyncio.run(
                v2_erp.submit_gig_worker_entry(
                    v2_erp_mod.GigWorkSubmitRequest(
                        labour_id="LAB-1",
                        work_date="2026-11-01",
                        quantity_kg=10,
                        rate_per_kg=15,
                        nonce="fw-gig-nonce-1",
                    ),
                    self.factory_worker,
                    _DummyRequest(),
                )
            )
        self._assert_403(ctx_v2_gig)

        with self.assertRaises(HTTPException) as ctx_wf_att:
            asyncio.run(
                workforce.save_labour_attendance_bulk(
                    workforce_mod.LabourAttendanceBulk(
                        attendance_date="2026-11-01",
                        records=[],
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_wf_att)

        with self.assertRaises(HTTPException) as ctx_wf_work:
            asyncio.run(
                workforce.create_labour_work_entry(
                    workforce_mod.LabourWorkEntryCreate(
                        labour_id="LAB-1",
                        work_date="2026-11-01",
                        task_type="ROLLING",
                        quantity=5,
                        rate=10,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_wf_work)

    # 6. Canonical role mapping cannot elevate FACTORY_WORKER to PRODUCTION
    def test_06_canonical_role_mapping_does_not_elevate_factory_worker(self):
        self.assertEqual(perms.CANONICAL_ROLE_V2_MAP["FACTORY_WORKER"], "FACTORY_WORKER")
        self.assertNotEqual(perms.CANONICAL_ROLE_V2_MAP["FACTORY_WORKER"], "PRODUCTION")
        self.assertEqual(perms.canonical_role_v2("FACTORY_WORKER"), "FACTORY_WORKER")
        self.assertEqual(perms.role_v2_of(self.factory_worker), "FACTORY_WORKER")
        self.assertEqual(perms.resolve_authorized_role("FACTORY_WORKER"), "FACTORY_WORKER")
        self.assertEqual(perms.ui_role("FACTORY_WORKER"), "FACTORY_WORKER")
        self.assertTrue(perms.is_factory_worker(self.factory_worker))

        me_resp = asyncio.run(auth_router.get_me(self.factory_worker))
        self.assertEqual(me_resp["role"], "FACTORY_WORKER")

    # 7. Legacy aliases (PRODUCTION_WORKER, WORKER, case/whitespace variants) cannot elevate
    def test_07_legacy_aliases_cannot_elevate_to_production(self):
        alias_tokens = [
            "PRODUCTION_WORKER",
            "WORKER",
            "factory_worker",
            "  production_worker  ",
            " worker ",
        ]
        for token in alias_tokens:
            user = {"user_id": f"USR-{token.strip()}", "role": token}
            self.assertEqual(perms.canonical_role_v2(token), "FACTORY_WORKER")
            self.assertEqual(perms.role_v2_of(user), "FACTORY_WORKER")
            self.assertEqual(perms.resolve_authorized_role(token), "FACTORY_WORKER")
            self.assertEqual(perms.ui_role(token), "FACTORY_WORKER")
            self.assertTrue(perms.is_factory_worker(user))
            self.assertTrue(perms.has_permission(user, "production", "view"))
            self.assertFalse(perms.has_permission(user, "production", "create"))
            self.assertFalse(perms.has_permission(user, "production", "record_output"))
            self.assertFalse(perms.has_permission(user, "quality", "submit_qc"))

            # View allowed
            summary = asyncio.run(prod.summary(user))
            self.assertIn("bulk_stock", summary)

            # Create denied (HTTP 403)
            with self.assertRaises(HTTPException) as ctx_create:
                asyncio.run(
                    prod.create_batch(
                        prod_mod.ProductionCreate(
                            product_id="PRD-M-200",
                            production_date="2026-11-01",
                            quantity_kg=5,
                        ),
                        _DummyRequest(),
                        user,
                    )
                )
            self._assert_403(ctx_create)

            # v2 create denied (HTTP 403)
            with self.assertRaises(HTTPException) as ctx_v2:
                asyncio.run(
                    v2_erp.create_v2_production_batch(
                        v2_erp_mod.GovernedProductionBatchRequest(
                            product_id="PRD-M-200",
                            planned_quantity_kg=5,
                            nonce=f"alias-nonce-{token.strip()}",
                        ),
                        user,
                        _DummyRequest(),
                    )
                )
            self._assert_403(ctx_v2)

            # Quality check denied (HTTP 403)
            with self.assertRaises(HTTPException) as ctx_qc:
                asyncio.run(
                    quality.create_quality_check(
                        quality_mod.QualityCheckCreate(
                            check_type="PRODUCTION_BATCH",
                            reference_type="PRODUCTION_BATCH",
                            reference_id="PRD-BATCH-1",
                            product_or_material_id="PRD-M-200",
                            item_name="Moong Master Papad",
                            result="PASS",
                        ),
                        _DummyRequest(),
                        user,
                    )
                )
            self._assert_403(ctx_qc)

    # 8. Role normalization & specificity cannot widen explicit least-privilege rules
    def test_08_role_normalization_cannot_widen_least_privilege_rules(self):
        # Even if CANONICAL_ROLE_V2_MAP were hypothetically misconfigured to map
        # FACTORY_WORKER -> PRODUCTION, explicit DEFAULT_ROLE_PERMISSIONS["FACTORY_WORKER"]
        # must still take strict precedence (no OR-union widening).
        with patch.dict(perms.CANONICAL_ROLE_V2_MAP, {"FACTORY_WORKER": "PRODUCTION"}):
            self.assertTrue(perms.has_permission(self.factory_worker, "production", "view"))
            self.assertFalse(perms.has_permission(self.factory_worker, "production", "create"))
            self.assertFalse(perms.has_permission(self.factory_worker, "production", "record_output"))
            self.assertFalse(perms.has_permission(self.factory_worker, "quality", "submit_qc"))
            self.assertEqual(
                perms.effective_permissions_for(self.factory_worker),
                {"production": ["view"]},
            )
            # Explicit defense-in-depth guard still blocks FACTORY_WORKER
            with self.assertRaises(HTTPException) as ctx_guard:
                perms.require_production_access(self.factory_worker)
            self._assert_403(ctx_guard)

        # DISPATCH resolves cleanly to STORE without escalating to SALES write permissions
        self.assertEqual(perms.canonical_role_v2("DISPATCH"), "STORE")
        self.assertEqual(perms.ui_role("DISPATCH"), "STORE")
        self.assertTrue(perms.has_permission(self.dispatch_user, "logistics", "dispatch"))
        self.assertFalse(perms.has_permission(self.dispatch_user, "sales", "create"))
        self.assertFalse(perms.has_permission(self.dispatch_user, "channels", "create"))

        # AUDITOR remains strictly view-only
        self.assertTrue(perms.has_permission(self.auditor_user, "production", "view"))
        self.assertFalse(perms.has_permission(self.auditor_user, "production", "create"))
        with self.assertRaises(HTTPException) as ctx_aud:
            asyncio.run(
                prod.create_batch(
                    prod_mod.ProductionCreate(
                        product_id="PRD-M-200",
                        production_date="2026-11-01",
                        quantity_kg=5,
                    ),
                    _DummyRequest(),
                    self.auditor_user,
                )
            )
        self._assert_403(ctx_aud)

        # Forged JWT claiming role=PRODUCTION for an AuthUsers FACTORY_WORKER is overridden by fresh DB lookup
        forged_token = auth_mod.create_access_token(
            {"sub": "USR-FW-1", "role": "PRODUCTION", "tv": 1}
        )
        creds = auth_mod.HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged_token)
        resolved_user = asyncio.run(auth_mod.get_current_user(credentials=creds))
        self.assertEqual(resolved_user["role"], "FACTORY_WORKER")
        self.assertFalse(perms.has_permission(resolved_user, "production", "create"))
        with self.assertRaises(HTTPException) as ctx_forged:
            asyncio.run(
                prod.create_batch(
                    prod_mod.ProductionCreate(
                        product_id="PRD-M-200",
                        production_date="2026-11-01",
                        quantity_kg=5,
                    ),
                    _DummyRequest(),
                    resolved_user,
                )
            )
        self._assert_403(ctx_forged)

        # Blank / unknown role fails closed
        self.assertFalse(perms.has_permission({"user_id": "U-BLANK", "role": ""}, "production", "view"))
        self.assertFalse(perms.has_permission({"user_id": "U-UNK", "role": "UNKNOWN_ROLE"}, "production", "view"))
        self.assertIsNone(perms.resolve_authorized_role("UNKNOWN_ROLE"))

    # 9. Authorized production roles (PRODUCTION, PACKAGING, PA) retain legitimate access
    def test_09_authorized_production_roles_retain_legitimate_access(self):
        # PRODUCTION operator retains full operational production capabilities (excluding Owner-only approval)
        self.assertEqual(perms.role_v2_of(self.production_user), "PRODUCTION")
        self.assertTrue(perms.has_permission(self.production_user, "production", "view"))
        self.assertTrue(perms.has_permission(self.production_user, "production", "create"))
        self.assertTrue(perms.has_permission(self.production_user, "production", "record_consumption"))
        self.assertTrue(perms.has_permission(self.production_user, "production", "record_output"))
        self.assertTrue(perms.has_permission(self.production_user, "quality", "submit_qc"))
        self.assertFalse(perms.has_permission(self.production_user, "production", "approve"))

        actor, role = perms.require_production_access(self.production_user)
        self.assertEqual((actor, role), ("USR-PROD-1", "PRODUCTION"))

        batch_prod = asyncio.run(
            prod.create_batch(
                prod_mod.ProductionCreate(
                    product_id="PRD-M-200",
                    production_date="2026-11-01",
                    quantity_kg=10,
                ),
                _DummyRequest(),
                self.production_user,
            )
        )
        self.assertEqual(batch_prod["status"], "PENDING")

        # PACKAGING retains packaging & production access
        actor_p, role_p = perms.require_production_access(self.packaging_user)
        self.assertEqual((actor_p, role_p), ("USR-PACK-1", "PACKAGING"))
        self.assertTrue(perms.has_permission(self.packaging_user, "packaging", "create"))

        # PA retains production creation, denied Owner-only approval
        self.assertTrue(perms.has_permission(self.pa_user, "production", "create"))
        batch_pa = asyncio.run(
            prod.create_batch(
                prod_mod.ProductionCreate(
                    product_id="PRD-M-200",
                    production_date="2026-11-01",
                    quantity_kg=8,
                ),
                _DummyRequest(),
                self.pa_user,
            )
        )
        self.assertEqual(batch_pa["status"], "PENDING")
        with self.assertRaises(HTTPException) as ctx_pa_approve:
            asyncio.run(
                prod.approve_batch(
                    batch_pa["batch_id"],
                    prod_mod.ApprovalRequest(approved=True),
                    _DummyRequest(),
                    self.pa_user,
                )
            )
        self._assert_403(ctx_pa_approve)

    # 10. OWNER_ADMIN (and legacy OWNER) retains full access including approvals
    def test_10_owner_admin_retains_full_access_and_approvals(self):
        for owner in (self.owner_user, self.owner_legacy_user):
            self.assertTrue(perms.is_owner(owner))
            self.assertTrue(perms.has_permission(owner, "production", "view"))
            self.assertTrue(perms.has_permission(owner, "production", "create"))
            self.assertTrue(perms.has_permission(owner, "production", "approve"))
            perms.require_owner(owner)
            perms.require_production_access(owner)

        batch = asyncio.run(
            prod.create_batch(
                prod_mod.ProductionCreate(
                    product_id="PRD-M-200",
                    production_date="2026-11-01",
                    quantity_kg=10,
                ),
                _DummyRequest(),
                self.owner_user,
            )
        )
        self.assertIn(batch["status"], {"PENDING", "APPROVED"})
        approved = asyncio.run(
            prod.approve_batch(
                batch["batch_id"],
                prod_mod.ApprovalRequest(approved=True),
                _DummyRequest(),
                self.owner_user,
            )
        )
        self.assertEqual(approved["status"], "APPROVED")

    # 11. Route-level backend enforcement across production, v2_erp, quality, and workforce routers
    def test_11_route_level_backend_enforcement_end_to_end(self):
        # Verify production router read vs write split on real handlers for FACTORY_WORKER vs PRODUCTION
        fw_read = asyncio.run(prod.summary(self.factory_worker))
        self.assertIn("bulk_stock", fw_read)
        prod_read = asyncio.run(prod.summary(self.production_user))
        self.assertIn("bulk_stock", prod_read)

        # Verify write route succeeds for PRODUCTION and fails with 403 for FACTORY_WORKER
        created = asyncio.run(
            prod.create_batch(
                prod_mod.ProductionCreate(
                    product_id="PRD-M-200",
                    production_date="2026-11-02",
                    quantity_kg=6,
                ),
                _DummyRequest(),
                self.production_user,
            )
        )
        self.assertEqual(created["status"], "PENDING")

        with self.assertRaises(HTTPException) as ctx_fw_write:
            asyncio.run(
                prod.create_batch(
                    prod_mod.ProductionCreate(
                        product_id="PRD-M-200",
                        production_date="2026-11-02",
                        quantity_kg=6,
                    ),
                    _DummyRequest(),
                    self.factory_worker,
                )
            )
        self._assert_403(ctx_fw_write)

        # Verify /api/v2/meta/capabilities accurately reflects least-privilege permissions per role
        fw_caps = asyncio.run(v2_erp.get_erp_capabilities(self.factory_worker))
        prod_caps = asyncio.run(v2_erp.get_erp_capabilities(self.production_user))
        self.assertEqual(fw_caps["role"], "FACTORY_WORKER")
        self.assertEqual(fw_caps["module_permissions"], {"production": ["view"]})
        self.assertEqual(prod_caps["role"], "PRODUCTION")
        self.assertIn("create", prod_caps["module_permissions"]["production"])

    # 12. All negative authorization cases return HTTP 403 with explicit denial detail
    def test_12_negative_authorization_returns_http_403_with_clear_detail(self):
        negative_calls = [
            lambda: perms.require_production_access(self.factory_worker),
            lambda: perms.require_production_access(self.prod_worker_alias),
            lambda: perms.require_production_access(self.worker_alias),
            lambda: perms.require_module_action(self.factory_worker, "production", "create"),
            lambda: perms.require_module_action(self.factory_worker, "production", "approve"),
            lambda: perms.require_roles(self.factory_worker, {"PRODUCTION", "OWNER_ADMIN"}),
            lambda: prod_mod.require_production_access(self.factory_worker),
            lambda: prod_mod.require_owner(self.factory_worker),
        ]
        for idx, fn in enumerate(negative_calls):
            with self.assertRaises(HTTPException, msg=f"Case {idx} did not raise HTTPException") as ctx:
                fn()
            self.assertEqual(ctx.exception.status_code, 403, f"Case {idx} expected HTTP 403")
            detail = str(ctx.exception.detail).strip()
            self.assertTrue(len(detail) >= 10, f"Case {idx} expected clear denial detail, got: {detail!r}")


if __name__ == "__main__":
    unittest.main()
