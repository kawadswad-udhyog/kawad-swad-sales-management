from app.timeutil import business_today, now_iso
from typing import Any, Dict, List, Optional
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.auth import get_current_user
from app.sheets import db
from app.config import SALES_GOOGLE_SPREADSHEET_ID
from app.recipes_master import (
    MASTER_RECIPES_DEFINITION,
    RAW_MATERIALS_SEED,
    STANDARD_RATES,
    calculate_recipe_cost,
    normalize_quantity_to_std_unit,
)
from app.calculations import (
    normalize_to_canonical_unit,
    round_stock,
    round_money,
    round_ratio,
    validate_recipe_formulation,
    calculate_production_requirements,
    reconcile_production_output,
    calculate_packed_weight,
    calculate_packing_variance,
    validate_packing_discrepancy,
    get_latest_purchase_rate,
    calculate_batch_actual_cost,
    calculate_finished_sku_cost,
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_raw_material_balance,
    DEFAULT_PACKING_TOLERANCE_KG,
)

router = APIRouter(prefix="/api/production", tags=["Production"])

# Part 2 & Part 8: Only the Owner may access production operations.
OWNER_ROLES = {"OWNER", "OWNER_ADMIN", "ADMIN"}


def actor_info(user: dict):
    return str(user.get("user_id", "")), str(user.get("role", "")).upper()


def require_owner(user: dict):
    """Enforce strict Owner-only access for all production endpoints."""
    actor, role = actor_info(user)
    if role not in OWNER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only the Owner can access production and packaging operations."
        )
    return actor, role


# Backward-compatible wrappers pointing to strict Owner-only check
def require_admin(user: dict):
    return require_owner(user)


def require_production_worker(user: dict):
    return require_owner(user)


def require_persistent_store():
    # Production and stock writes must not silently land only in process memory when Sheets is configured.
    if SALES_GOOGLE_SPREADSHEET_ID and not (db.is_connected and db.spreadsheet):
        raise HTTPException(
            status_code=503,
            detail="Google Sheets is disconnected. Production and stock changes are blocked until the connection is restored."
        )


def make_id(tab: str):
    return db.generate_id(tab)


def now():
    return now_iso()


def truthy(v):
    return str(v).strip().lower() in {"true", "1", "yes", "active", "y"}


def field(row: dict, *keys, default=""):
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
        if k.lower() in low and low[k.lower()] not in (None, ""):
            return low[k.lower()]
    return default


# Pydantic Schemas
class WorkerCreate(BaseModel):
    worker_name: str = Field(min_length=2, max_length=100)
    mobile: str = ""
    daily_wage: float = Field(ge=0)
    active: bool = True
    notes: str = ""


class AttendanceCreate(BaseModel):
    worker_id: str
    attendance_date: str
    status: str = "PRESENT"
    notes: str = ""


class RecipeItemInput(BaseModel):
    material_name: str = Field(min_length=1, max_length=100)
    quantity_per_kg: float = Field(gt=0, description="Material quantity required per 1 kg finished papad")
    unit: str = "kg"


class RecipeSave(BaseModel):
    product_id: str
    items: List[RecipeItemInput] = Field(min_length=1)
    approved: bool = False
    expected_yield_kg: float = Field(gt=0, default=1.2)
    notes: str = ""


class ProductionCreate(BaseModel):
    product_id: str
    production_date: str
    quantity_kg: float = Field(gt=0, description="Planned or recorded saleable output in kg")
    gross_output_kg: Optional[float] = Field(ge=0, default=None)
    saleable_output_kg: Optional[float] = Field(ge=0, default=None)
    wastage_kg: float = Field(ge=0, default=0)
    process_loss_kg: float = Field(ge=0, default=0)
    loss_reason: str = ""
    flour_base_used_kg: Optional[float] = Field(ge=0, default=None)
    recipe_id: Optional[str] = None
    auto_issue_materials: bool = False
    notes: str = ""


class MaterialIssueRequest(BaseModel):
    production_id: str
    notes: str = ""


class DiscrepancyApprovalRequest(BaseModel):
    explanation: str = Field(min_length=3, description="Owner explanation for unexplained packing variance")


class RecipeConfirmRequest(BaseModel):
    approved: bool = True
    expected_yield_kg: Optional[float] = None
    change_notes: Optional[str] = None


class RecipeCalculateRequest(BaseModel):
    items: List[Dict[str, Any]]
    expected_yield_kg: float = Field(gt=0, default=1.2)


class ApprovalRequest(BaseModel):
    approved: bool
    notes: str = ""


class PackagingCreate(BaseModel):
    product_id: str
    packaging_date: str
    bulk_kg_used: float = Field(gt=0)
    packets_200g: int = Field(ge=0, default=0)
    packets_500g: int = Field(ge=0, default=0)
    packets_1000g: int = Field(ge=0, default=0)
    packing_loss_kg: float = Field(ge=0, default=0.0)
    loss_reason: str = ""
    discrepancy_explanation: str = ""
    discrepancy_approved: bool = False
    reference: str = ""
    notes: str = ""


class DispatchCreate(BaseModel):
    product_id: str
    channel: str
    destination: str = ""
    quantity_packets: int = Field(gt=0)
    reference: str = ""
    notes: str = ""


# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------

@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    require_owner(user)
    ledger = db.get_records("ProductionStockLedger")
    products_records = db.get_records("Products")
    products = {str(field(p, "product_id")): p for p in products_records}

    bulk_balances = calculate_bulk_stock_balance(ledger)
    finished_balances = calculate_finished_stock_balance(ledger)

    bulk_stock_list = []
    for bulk_key, qty in bulk_balances.items():
        name_match = next((field(p, "product_name") for p in products_records if str(field(p, "product_name")).strip().lower() == bulk_key), bulk_key.title())
        bulk_stock_list.append({
            "product_id": bulk_key,
            "product_name": name_match,
            "quantity_kg": round_stock(qty),
        })

    finished_stock_list = []
    for pid, qty in finished_balances.items():
        p_name = str(field(products.get(pid, {}), "product_name", default=pid))
        p_sku = str(field(products.get(pid, {}), "sku", default=""))
        finished_stock_list.append({
            "product_id": pid,
            "product_name": f"{p_name} ({p_sku})" if p_sku else p_name,
            "quantity_packets": qty,
        })

    return {
        "bulk_stock": bulk_stock_list,
        "finished_stock": finished_stock_list,
        "workers_active": sum(1 for w in db.get_records("Workers") if truthy(field(w, "active", default="true"))),
        "wage_accrued_today": round(sum(float(field(a, "wage_accrued", default=0) or 0) for a in db.get_records("WorkerAttendance") if str(field(a, "attendance_date")) == business_today()), 2),
        "pending_production": sum(1 for b in db.get_records("ProductionBatches") if str(field(b, "status")).upper() == "PENDING"),
    }


@router.get("/workers")
async def workers(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("Workers")


@router.post("/workers")
async def add_worker(req: WorkerCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()
    if any(str(field(w, "worker_name")).strip().lower() == req.worker_name.strip().lower() and truthy(field(w, "active", default="true")) for w in db.get_records("Workers")):
        raise HTTPException(409, "An active worker with this name already exists")
    rec = {
        "worker_id": make_id("Workers"),
        "worker_name": req.worker_name.strip(),
        "mobile": req.mobile.strip(),
        "daily_wage": req.daily_wage,
        "active": str(req.active).lower(),
        "notes": req.notes.strip(),
        "created_at": now(),
        "created_by": actor,
    }
    if not db.append_record("Workers", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save worker")
    db.log_audit(actor, "CREATE_WORKER", "Workers", rec["worker_id"], reason=f"Created worker {rec['worker_name']}")
    return rec


@router.get("/attendance")
async def attendance(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("WorkerAttendance")


@router.post("/attendance")
async def record_attendance(req: AttendanceCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()
    status_value = req.status.strip().upper()
    if status_value not in {"PRESENT", "ABSENT", "HALF_DAY"}:
        raise HTTPException(400, "Attendance must be PRESENT, ABSENT, or HALF_DAY")
    worker = next((w for w in db.get_records("Workers") if str(field(w, "worker_id")) == req.worker_id), None)
    if not worker:
        raise HTTPException(404, "Worker not found")
    existing = next((a for a in db.get_records("WorkerAttendance") if str(field(a, "worker_id")) == req.worker_id and str(field(a, "attendance_date")) == req.attendance_date), None)
    if existing:
        raise HTTPException(409, "Attendance is already recorded for this worker and date. Ask Owner to correct it through an audited correction workflow.")
    daily_wage = float(field(worker, "daily_wage", default=0) or 0)
    payable = daily_wage if status_value == "PRESENT" else daily_wage * 0.5 if status_value == "HALF_DAY" else 0
    rec = {
        "attendance_id": make_id("WorkerAttendance"),
        "worker_id": req.worker_id,
        "worker_name_snapshot": field(worker, "worker_name"),
        "attendance_date": req.attendance_date,
        "status": status_value,
        "daily_wage_snapshot": daily_wage,
        "wage_accrued": round(payable, 2),
        "notes": req.notes,
        "created_at": now(),
        "created_by": actor,
    }
    if not db.append_record("WorkerAttendance", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save attendance")
    db.log_audit(actor, "RECORD_WORKER_ATTENDANCE", "WorkerAttendance", rec["attendance_id"], reason=f"{rec['worker_name_snapshot']} {status_value} on {req.attendance_date}")
    return rec


@router.get("/recipes")
async def recipes(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("Recipes")


@router.post("/recipes")
async def save_recipe(req: RecipeSave, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()
    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == req.product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")
    if not truthy(field(product, "active", default="true")):
        raise HTTPException(400, "Cannot create a recipe for an inactive product")

    prod_name = str(field(product, "product_name"))
    raw_items = [i.model_dump() if hasattr(i, 'model_dump') else i.dict() for i in req.items]

    # Validate formulation rules (Moong Master papad check, positive quantities)
    try:
        validate_recipe_formulation(prod_name, raw_items, req.expected_yield_kg)
    except ValueError as val_err:
        raise HTTPException(422, detail=str(val_err))

    version = 1 + sum(1 for r in db.get_records("Recipes") if str(field(r, "product_id")) == req.product_id)
    recipe_id = make_id("Recipes")

    rec = {
        "recipe_id": recipe_id,
        "product_id": req.product_id,
        "product_name_snapshot": prod_name,
        "version": version,
        "approved": str(req.approved).lower(),
        "expected_yield_kg": req.expected_yield_kg,
        "items_json": json.dumps(raw_items),
        "notes": req.notes,
        "created_at": now(),
        "created_by": actor,
    }
    if not db.append_record("Recipes", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save recipe")
    db.log_audit(actor, "CREATE_RECIPE", "Recipes", recipe_id, reason=f"Recipe version {version} for {prod_name}")
    return rec


@router.get("/recipes/master")
async def get_master_recipes(user: dict = Depends(get_current_user)):
    require_owner(user)
    custom_recipes = db.get_records("Recipes")
    enriched = []
    for master in MASTER_RECIPES_DEFINITION:
        matching = [
            r for r in custom_recipes
            if str(field(r, "recipe_id")) == master["recipe_id"]
            or (str(field(r, "product_id")) == master["product_id"] and truthy(field(r, "approved")))
        ]
        status = master.get("status", "DRAFT")
        approved = master.get("approved", False)
        yield_kg = float(master.get("expected_yield_kg", 1.2))
        notes = master.get("change_notes", "")

        if matching:
            latest = matching[-1]
            if truthy(field(latest, "approved")):
                status = "APPROVED"
                approved = True
            if field(latest, "notes"):
                notes = str(field(latest, "notes"))

        cost_info = calculate_recipe_cost(master["items"], yield_kg)
        enriched.append({
            **master,
            "status": status,
            "approved": approved,
            "expected_yield_kg": yield_kg,
            "change_notes": notes,
            **cost_info,
        })
    return enriched


@router.post("/recipes/master/bootstrap")
async def bootstrap_master_recipes(user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()

    existing_raw = db.get_records("RawMaterials")
    existing_raw_names = {str(field(r, "material_name", "raw_material_name", "name")).strip().lower() for r in existing_raw}
    added_materials = 0
    for rm in RAW_MATERIALS_SEED:
        if rm["material_name"].strip().lower() not in existing_raw_names:
            row = {
                "raw_material_id": rm["raw_material_id"],
                "material_name": rm["material_name"],
                "current_stock": rm["current_stock"],
                "unit": rm["unit"],
                "rate_per_unit": rm["rate_per_unit"] if rm["rate_per_unit"] is not None else "",
                "rate_status": rm["rate_status"],
                "category": rm["category"],
                "created_at": now(),
                "created_by": actor,
            }
            db.append_record("RawMaterials", row, raise_on_error=True)
            existing_raw_names.add(rm["material_name"].strip().lower())
            added_materials += 1

    existing_recipes = db.get_records("Recipes")
    existing_recipe_ids = {str(field(r, "recipe_id")) for r in existing_recipes}
    added_recipes = 0
    for m in MASTER_RECIPES_DEFINITION:
        if m["recipe_id"] not in existing_recipe_ids:
            items_for_storage = []
            for item in m["items"]:
                raw_qty = float(item["quantity"])
                unit = item["unit"]
                std_qty, std_unit = normalize_quantity_to_std_unit(raw_qty, unit)
                qty_per_kg = round(std_qty / float(m["expected_yield_kg"]), 4) if float(m["expected_yield_kg"]) > 0 else 0
                items_for_storage.append({
                    "material_name": item["material_name"],
                    "quantity_per_kg": qty_per_kg,
                    "unit": std_unit,
                    "raw_quantity": raw_qty,
                    "raw_unit": unit,
                    "rate_per_unit": item.get("rate_per_unit"),
                    "rate_status": item.get("rate_status", "CONFIRMED"),
                })
            rec = {
                "recipe_id": m["recipe_id"],
                "product_id": m["product_id"],
                "product_name_snapshot": m["product_name_snapshot"],
                "product_family": m["product_family"],
                "version": m["version"],
                "approved": str(m["approved"]).lower(),
                "expected_yield_kg": m["expected_yield_kg"],
                "items_json": json.dumps(items_for_storage),
                "notes": m["change_notes"],
                "created_at": now(),
                "created_by": actor,
            }
            db.append_record("Recipes", rec, raise_on_error=True)
            added_recipes += 1

    db.log_audit(actor, "BOOTSTRAP_MASTER_RECIPES", "Recipes", "ALL", reason=f"Bootstrapped {added_recipes} recipes, {added_materials} raw materials")
    return {
        "status": "success",
        "added_materials": added_materials,
        "added_recipes": added_recipes,
        "message": "Successfully synced Version 2.0 master recipes and raw materials.",
    }


@router.post("/recipes/master/{recipe_id}/confirm")
async def confirm_master_recipe(recipe_id: str, req: RecipeConfirmRequest, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()

    master = next((m for m in MASTER_RECIPES_DEFINITION if m["recipe_id"] == recipe_id), None)
    if not master:
        raise HTTPException(status_code=404, detail="Master recipe not found")

    yield_kg = req.expected_yield_kg if req.expected_yield_kg and req.expected_yield_kg > 0 else master["expected_yield_kg"]
    notes = req.change_notes or f"Confirmed by Owner on {business_today()}"

    items_for_storage = []
    for item in master["items"]:
        raw_qty = float(item["quantity"])
        unit = item["unit"]
        std_qty, std_unit = normalize_quantity_to_std_unit(raw_qty, unit)
        qty_per_kg = round(std_qty / yield_kg, 4) if yield_kg > 0 else 0
        items_for_storage.append({
            "material_name": item["material_name"],
            "quantity_per_kg": qty_per_kg,
            "unit": std_unit,
            "raw_quantity": raw_qty,
            "raw_unit": unit,
            "rate_per_unit": item.get("rate_per_unit"),
            "rate_status": item.get("rate_status", "CONFIRMED"),
        })

    existing = next((r for r in db.get_records("Recipes") if str(field(r, "recipe_id")) == recipe_id), None)
    if existing:
        db.update_record("Recipes", "recipe_id", recipe_id, {
            "approved": str(req.approved).lower(),
            "expected_yield_kg": yield_kg,
            "notes": notes,
            "approved_by": actor,
            "approved_at": now(),
            "items_json": json.dumps(items_for_storage),
        })
    else:
        rec = {
            "recipe_id": recipe_id,
            "product_id": master["product_id"],
            "product_name_snapshot": master["product_name_snapshot"],
            "product_family": master["product_family"],
            "version": master["version"],
            "approved": str(req.approved).lower(),
            "expected_yield_kg": yield_kg,
            "items_json": json.dumps(items_for_storage),
            "notes": notes,
            "created_at": now(),
            "created_by": actor,
            "approved_by": actor,
            "approved_at": now(),
        }
        db.append_record("Recipes", rec, raise_on_error=True)

    db.log_audit(actor, "CONFIRM_MASTER_RECIPE", "Recipes", recipe_id, reason=f"Approved: {req.approved}, Yield: {yield_kg} kg")
    return {"status": "success", "recipe_id": recipe_id, "approved": req.approved, "expected_yield_kg": yield_kg}


@router.post("/recipes/calculate")
async def calculate_custom_recipe_cost(req: RecipeCalculateRequest, user: dict = Depends(get_current_user)):
    require_owner(user)
    return calculate_recipe_cost(req.items, req.expected_yield_kg)


# -------------------------------------------------------------
# Production Batches & Material Issue Lifecycle
# -------------------------------------------------------------

@router.get("/batches")
async def batches(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("ProductionBatches")


@router.post("/batches")
async def create_batch(req: ProductionCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()

    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == req.product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")
    if not truthy(field(product, "active", default="true")):
        raise HTTPException(400, "Inactive products cannot be produced")

    # Reconcile quantities using the production calculation engine
    gross_kg = req.gross_output_kg if req.gross_output_kg is not None else req.quantity_kg
    saleable_kg = req.saleable_output_kg if req.saleable_output_kg is not None else (req.quantity_kg - req.wastage_kg)
    if saleable_kg < 0:
        raise HTTPException(400, "Saleable quantity cannot be negative")
    if req.wastage_kg >= req.quantity_kg and req.gross_output_kg is None:
        raise HTTPException(400, "Wastage must be less than produced quantity")

    reconciliation = reconcile_production_output(
        saleable_output_kg=saleable_kg,
        gross_output_kg=gross_kg,
        rejected_output_kg=req.wastage_kg,
        process_loss_kg=req.process_loss_kg,
        flour_base_used_kg=req.flour_base_used_kg,
        benchmark_yield_ratio=1.2,
    )

    batch_id = make_id("ProductionBatches")
    rec = {
        "production_id": batch_id,
        "production_date": req.production_date,
        "product_id": req.product_id,
        "product_name_snapshot": field(product, "product_name"),
        "quantity_kg": req.quantity_kg,
        "gross_output_kg": reconciliation["gross_output_kg"],
        "wastage_kg": req.wastage_kg,
        "process_loss_kg": req.process_loss_kg,
        "loss_reason": req.loss_reason,
        "net_quantity_kg": reconciliation["saleable_output_kg"],
        "saleable_output_kg": reconciliation["saleable_output_kg"],
        "unexplained_variance_kg": reconciliation["unexplained_variance_kg"],
        "flour_base_used_kg": req.flour_base_used_kg if req.flour_base_used_kg is not None else "",
        "benchmark_yield_kg": reconciliation["benchmark_yield_kg"] if reconciliation["benchmark_yield_kg"] is not None else "",
        "actual_yield_ratio": reconciliation["actual_yield_ratio"] if reconciliation["actual_yield_ratio"] is not None else "",
        "yield_variance_kg": reconciliation["yield_variance_kg"] if reconciliation["yield_variance_kg"] is not None else 0.0,
        "recipe_id": req.recipe_id or "",
        "materials_issued": "false",
        "status": "PENDING",
        "notes": req.notes,
        "created_at": now(),
        "created_by": actor,
        "approved_by": "",
        "approved_at": "",
    }

    if not db.append_record("ProductionBatches", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save production batch")
    db.log_audit(actor, "CREATE_PRODUCTION_BATCH", "ProductionBatches", batch_id, reason=f"{rec['net_quantity_kg']} kg {rec['product_name_snapshot']}; pending approval")
    return rec


@router.post("/batches/{production_id}/issue-materials")
async def issue_materials(production_id: str, user: dict = Depends(get_current_user)):
    """
    Issue raw materials to a production batch.
    Deducts raw materials exactly once, snapshots purchase rates, and assigns a unique transaction ID.
    Idempotent: Re-calling for an already issued batch returns the existing issue without re-deducting.
    """
    actor, _ = require_owner(user)
    require_persistent_store()

    batch = next((b for b in db.get_records("ProductionBatches") if str(field(b, "production_id")) == production_id), None)
    if not batch:
        raise HTTPException(404, "Production batch not found")

    # Idempotency check: Have materials already been issued for this production_id?
    raw_ledger = db.get_records("RawMaterialLedger")
    existing_issue = [x for x in raw_ledger if str(field(x, "production_id")) == production_id and str(field(x, "movement_type")).upper() == "PRODUCTION_CONSUMPTION"]
    if existing_issue and truthy(field(batch, "materials_issued")):
        return {
            "status": "ALREADY_ISSUED",
            "production_id": production_id,
            "issued_items_count": len(existing_issue),
            "message": "Raw materials were already issued for this batch. No duplicate deduction made.",
        }

    # Find approved recipe
    prod_id = str(field(batch, "product_id"))
    prod_name = str(field(batch, "product_name_snapshot"))
    recipe_rows = [
        r for r in db.get_records("Recipes")
        if (
            str(field(r, "product_name_snapshot")).strip().lower() == prod_name.strip().lower()
            or (prod_id and str(field(r, "product_id")) == prod_id)
        )
        and truthy(field(r, "approved"))
    ]
    if not recipe_rows:
        raise HTTPException(400, "No approved recipe exists for this product. Save and approve recipe before issuing materials.")
    recipe = sorted(recipe_rows, key=lambda r: int(float(field(r, "version", default=0) or 0)))[-1]
    items = json.loads(str(field(recipe, "items_json", default="[]")))

    production_kg = float(field(batch, "net_quantity_kg", default=0) or 0)
    raw_master = db.get_records("RawMaterials")

    # Validate stock sufficiency before any deduction
    deductions = []
    for item in items:
        name = str(item.get("material_name", "")).strip()
        required = round(float(item.get("quantity_per_kg", 0)) * production_kg, 4)
        stock_bal = calculate_raw_material_balance(name, raw_master, raw_ledger, exclude_production_id=production_id)
        if not stock_bal["exists"]:
            raise HTTPException(400, f"Raw material '{name}' is missing from RawMaterials master. Add it before issuing materials.")
        if stock_bal["available"] < required:
            raise HTTPException(400, f"Insufficient stock for {name}: need {required} {stock_bal['unit']}, available {stock_bal['available']}.")

        rate_info = get_latest_purchase_rate(name, raw_master, raw_ledger)
        deductions.append({
            "material_name": name,
            "quantity": required,
            "unit": stock_bal["unit"],
            "raw_material_id": stock_bal["raw_material_id"],
            "rate_per_unit": rate_info.get("rate_per_canonical_unit") or "",
        })

    issue_txn_id = make_id("RawMaterialLedger")
    for d in deductions:
        if d["quantity"] <= 0:
            continue
        row = {
            "raw_material_txn_id": make_id("RawMaterialLedger"),
            "txn_datetime": now(),
            "material_name": d["material_name"],
            "raw_material_id": d["raw_material_id"],
            "movement_type": "PRODUCTION_CONSUMPTION",
            "quantity": d["quantity"],
            "unit": d["unit"],
            "rate_per_unit": d["rate_per_unit"],
            "production_id": production_id,
            "issue_txn_id": issue_txn_id,
            "created_by": actor,
            "notes": f"Batch {production_id} material issue under Recipe {field(recipe, 'recipe_id')}",
        }
        if not db.append_record("RawMaterialLedger", row, raise_on_error=True):
            raise HTTPException(503, "Could not record raw material deduction in ledger.")

    db.update_record("ProductionBatches", "production_id", production_id, {
        "materials_issued": "true",
        "material_issue_txn_id": issue_txn_id,
        "recipe_id": field(recipe, "recipe_id"),
    })
    db.log_audit(actor, "ISSUE_RAW_MATERIALS", "ProductionBatches", production_id, reason=f"Issued raw materials for {production_kg} kg papad")

    return {
        "status": "MATERIALS_ISSUED",
        "production_id": production_id,
        "material_issue_txn_id": issue_txn_id,
        "deductions": deductions,
    }


@router.post("/batches/{production_id}/approval")
async def approve_batch(production_id: str, req: ApprovalRequest, user: dict = Depends(get_current_user)):
    """
    Approve production batch.
    - If materials were already issued, DO NOT deduct them again.
    - If not issued, issue them now idempotently.
    - Crediting bulk output to inventory occurs exactly once.
    """
    actor, _ = require_owner(user)
    require_persistent_store()

    batches = db.get_records("ProductionBatches")
    rec = next((b for b in batches if str(field(b, "production_id")) == production_id), None)
    if not rec:
        raise HTTPException(404, "Production batch not found")
    if str(field(rec, "status")).upper() != "PENDING":
        raise HTTPException(409, "This batch has already been reviewed")

    if not req.approved:
        updates = {"status": "REJECTED", "approved_by": actor, "approved_at": now(), "approval_notes": req.notes}
        if not db.update_record("ProductionBatches", "production_id", production_id, updates):
            raise HTTPException(503, "Rejection was not saved.")
        db.log_audit(actor, "REJECT_PRODUCTION", "ProductionBatches", production_id, reason=req.notes)
        return {**rec, **updates}

    # Find approved recipe
    recipe_rows = [
        r for r in db.get_records("Recipes")
        if (
            str(field(r, "product_name_snapshot")).strip().lower() == str(field(rec, "product_name_snapshot")).strip().lower()
            or (field(rec, "product_id") and str(field(r, "product_id")) == str(field(rec, "product_id")))
        )
        and truthy(field(r, "approved"))
    ]
    if not recipe_rows:
        raise HTTPException(400, "No approved recipe exists for this product. Save and approve its recipe before approving production.")
    recipe = sorted(recipe_rows, key=lambda r: int(float(field(r, "version", default=0) or 0)))[-1]
    items = json.loads(str(field(recipe, "items_json", default="[]")))
    production_kg = float(field(rec, "net_quantity_kg", default=0) or 0)

    # Check if materials were already issued
    raw_ledger = db.get_records("RawMaterialLedger")
    already_issued = any(
        str(field(x, "production_id")) == production_id and str(field(x, "movement_type")).upper() == "PRODUCTION_CONSUMPTION"
        for x in raw_ledger
    )

    if not already_issued:
        # Issue materials now (only if not previously issued)
        raw_master = db.get_records("RawMaterials")
        deductions = []
        for item in items:
            name = str(item.get("material_name", "")).strip()
            required = round(float(item.get("quantity_per_kg", 0)) * production_kg, 4)
            stock_bal = calculate_raw_material_balance(name, raw_master, raw_ledger, exclude_production_id=production_id)
            if not stock_bal["exists"]:
                raise HTTPException(400, f"Raw material '{name}' is missing from RawMaterials master.")
            if stock_bal["available"] < required:
                raise HTTPException(400, f"Insufficient stock for {name}: need {required} {stock_bal['unit']}, available {stock_bal['available']}.")
            rate_info = get_latest_purchase_rate(name, raw_master, raw_ledger)
            deductions.append({
                "material_name": name,
                "quantity": required,
                "unit": stock_bal["unit"],
                "raw_material_id": stock_bal["raw_material_id"],
                "rate_per_unit": rate_info.get("rate_per_canonical_unit") or "",
            })

        issue_txn_id = make_id("RawMaterialLedger")
        for d in deductions:
            if d["quantity"] <= 0:
                continue
            ledger_row = {
                "raw_material_txn_id": make_id("RawMaterialLedger"),
                "txn_datetime": now(),
                "material_name": d["material_name"],
                "raw_material_id": d["raw_material_id"],
                "movement_type": "PRODUCTION_CONSUMPTION",
                "quantity": d["quantity"],
                "unit": d["unit"],
                "rate_per_unit": d["rate_per_unit"],
                "production_id": production_id,
                "issue_txn_id": issue_txn_id,
                "created_by": actor,
                "notes": f"Batch {production_id} approval material deduction under Recipe {field(recipe, 'recipe_id')}",
            }
            if not db.append_record("RawMaterialLedger", ledger_row, raise_on_error=True):
                raise HTTPException(503, "Could not record raw material consumption.")

    # Post bulk output to inventory exactly once
    existing_bulk = next((x for x in db.get_records("ProductionStockLedger") if str(field(x, "reference_id")) == production_id and str(field(x, "movement_type")).upper() == "BULK_PRODUCED"), None)
    if not existing_bulk:
        stock = {
            "movement_id": make_id("ProductionStockLedger"),
            "txn_datetime": now(),
            "movement_type": "BULK_PRODUCED",
            "product_id": field(rec, "product_id"),
            "bulk_product_key": str(field(rec, "product_name_snapshot")).strip().lower(),
            "product_name_snapshot": field(rec, "product_name_snapshot"),
            "quantity_kg": production_kg,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
            "reference_id": production_id,
            "created_by": actor,
            "notes": req.notes,
        }
        if not db.append_record("ProductionStockLedger", stock, raise_on_error=True):
            raise HTTPException(503, "Could not record bulk stock.")

    updates = {
        "status": "APPROVED",
        "approved_by": actor,
        "approved_at": now(),
        "approval_notes": req.notes,
        "recipe_id": field(recipe, "recipe_id"),
        "materials_issued": "true",
    }
    if not db.update_record("ProductionBatches", "production_id", production_id, updates):
        raise HTTPException(503, "Batch status could not be saved. Existing ledger entries remain safe.")

    db.log_audit(actor, "APPROVE_PRODUCTION", "ProductionBatches", production_id, reason=f"Approved {production_kg} kg and credited bulk inventory.")
    return {**rec, **updates}


# -------------------------------------------------------------
# Packaging Batches with Discrepancy Blocking
# -------------------------------------------------------------

@router.get("/packaging")
async def packaging(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("PackagingBatches")


@router.post("/packaging")
async def create_packaging(req: PackagingCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()

    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == req.product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")
    if not truthy(field(product, "active", default="true")):
        raise HTTPException(400, "Inactive products cannot be packaged")

    bulk_key = str(field(product, "product_name")).strip().lower()

    # Calculate packed weight from SKU configurations
    packet_entries = [
        {"product_id": req.product_id, "sku": f"{field(product, 'sku')}-200g", "pack_weight_g": 200, "packet_quantity": req.packets_200g},
        {"product_id": req.product_id, "sku": f"{field(product, 'sku')}-500g", "pack_weight_g": 500, "packet_quantity": req.packets_500g},
        {"product_id": req.product_id, "sku": f"{field(product, 'sku')}-1000g", "pack_weight_g": 1000, "packet_quantity": req.packets_1000g},
    ]
    total_packed_kg, total_packets, _ = calculate_packed_weight(packet_entries)
    if total_packets <= 0:
        raise HTTPException(400, "Enter at least one packet quantity to package.")

    # Calculate variance and discrepancy check
    variance_info = calculate_packing_variance(
        bulk_consumed_kg=req.bulk_kg_used,
        total_packed_kg=total_packed_kg,
        packing_loss_kg=req.packing_loss_kg,
        tolerance_kg=DEFAULT_PACKING_TOLERANCE_KG,
    )

    unexplained_variance = variance_info["unexplained_variance_kg"]
    is_discrepancy = variance_info["is_discrepancy"]

    # Block completion if unexplained discrepancy exists without Owner approval
    if is_discrepancy and not req.discrepancy_approved:
        # Save a recoverable pending-review record if reference is provided
        pack_id = make_id("PackagingBatches")
        pending_rec = {
            "packaging_id": pack_id,
            "packaging_date": req.packaging_date,
            "product_id": req.product_id,
            "product_name_snapshot": field(product, "product_name"),
            "bulk_kg_used": req.bulk_kg_used,
            "packets_200g": req.packets_200g,
            "packets_500g": req.packets_500g,
            "packets_1000g": req.packets_1000g,
            "total_packets": total_packets,
            "expected_kg": total_packed_kg,
            "packing_loss_kg": req.packing_loss_kg,
            "loss_reason": req.loss_reason,
            "difference_kg": unexplained_variance,
            "difference_status": "REVIEW_REQUIRED",
            "status": "PENDING_REVIEW",
            "discrepancy_approved": "false",
            "reference": req.reference,
            "notes": f"{req.notes} [UNEXPLAINED VARIANCE {unexplained_variance:+.3f} kg]",
            "created_at": now(),
            "created_by": actor,
        }
        db.append_record("PackagingBatches", pending_rec)
        raise HTTPException(
            status_code=422,
            detail=f"Packing completion blocked: Unexplained variance of {unexplained_variance:+.3f} kg exceeds tolerance ({DEFAULT_PACKING_TOLERANCE_KG} kg). "
                   f"The Owner must either correct the entry or submit an authorized explanation to approve the discrepancy."
        )

    # Check available bulk stock
    ledger = db.get_records("ProductionStockLedger")
    bulk_balances = calculate_bulk_stock_balance(ledger, bulk_key)
    available_bulk = bulk_balances.get(bulk_key, 0.0)
    if req.bulk_kg_used > available_bulk + 0.0001:
        raise HTTPException(400, f"Insufficient unpackaged bulk stock. Available: {available_bulk:.3f} kg; Requested: {req.bulk_kg_used:.3f} kg.")

    # Idempotency / Retry reconciliation
    if req.reference and req.reference.strip():
        ref_clean = req.reference.strip()
        existing_pack = next((p for p in db.get_records("PackagingBatches") if str(field(p, "reference", default="")).strip() == ref_clean), None)
        if existing_pack:
            pack_id = str(field(existing_pack, "packaging_id"))
            pack_status = str(field(existing_pack, "status")).upper()
            if pack_status in {"RECORDED", "COMPLETE"}:
                return existing_pack

            # Reconcile incomplete packaging batch without double-writing
            existing_bulk_mvt = next((m for m in ledger if str(field(m, "reference_id")) == pack_id and str(field(m, "movement_type")).upper() == "BULK_PACKAGED"), None)
            if not existing_bulk_mvt:
                row = {
                    "movement_id": make_id("ProductionStockLedger"),
                    "txn_datetime": now(),
                    "movement_type": "BULK_PACKAGED",
                    "quantity_kg": req.bulk_kg_used,
                    "quantity_packets": 0,
                    "channel": "FACTORY_BULK",
                    "product_id": req.product_id,
                    "bulk_product_key": bulk_key,
                    "product_name_snapshot": field(product, "product_name"),
                    "reference_id": pack_id,
                    "created_by": actor,
                    "notes": f"Reconciled retry: {req.notes}",
                }
                if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
                    raise HTTPException(503, "Could not record bulk stock deduction during recovery.")

            for weight_g, packet_count in [(200, req.packets_200g), (500, req.packets_500g), (1000, req.packets_1000g)]:
                if packet_count <= 0:
                    continue
                sku_product = next((p for p in db.get_records("Products") if str(field(p, "product_name")).strip().lower() == bulk_key and int(float(field(p, "pack_weight_g", default=0) or 0)) == weight_g and truthy(field(p, "active", default="true"))), None)
                if sku_product:
                    target_sku_id = str(field(sku_product, "product_id"))
                    existing_sku_mvt = next((m for m in ledger if str(field(m, "reference_id")) == pack_id and str(field(m, "product_id")) == target_sku_id and str(field(m, "movement_type")).upper() == "PACKETS_PACKAGED"), None)
                    if not existing_sku_mvt:
                        row = {
                            "movement_id": make_id("ProductionStockLedger"),
                            "txn_datetime": now(),
                            "movement_type": "PACKETS_PACKAGED",
                            "quantity_kg": 0,
                            "quantity_packets": packet_count,
                            "channel": "FACTORY_FINISHED",
                            "product_id": target_sku_id,
                            "bulk_product_key": bulk_key,
                            "product_name_snapshot": field(sku_product, "product_name"),
                            "sku_snapshot": field(sku_product, "sku"),
                            "pack_weight_g": weight_g,
                            "reference_id": pack_id,
                            "created_by": actor,
                            "notes": f"Reconciled retry: {req.notes}",
                        }
                        if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
                            raise HTTPException(503, f"Could not record {weight_g}g packet stock during recovery.")

            db.update_record("PackagingBatches", "packaging_id", pack_id, {"status": "RECORDED", "notes": f"{req.notes} [RECONCILED]"})
            existing_pack["status"] = "RECORDED"
            db.log_audit(actor, "RECONCILE_PACKAGING", "PackagingBatches", pack_id, reason=f"Reconciled packaging batch {pack_id}")
            return existing_pack

    # New Packaging Record
    pack_id = make_id("PackagingBatches")
    rec = {
        "packaging_id": pack_id,
        "packaging_date": req.packaging_date,
        "product_id": req.product_id,
        "product_name_snapshot": field(product, "product_name"),
        "bulk_kg_used": req.bulk_kg_used,
        "packets_200g": req.packets_200g,
        "packets_500g": req.packets_500g,
        "packets_1000g": req.packets_1000g,
        "total_packets": total_packets,
        "expected_kg": total_packed_kg,
        "packing_loss_kg": req.packing_loss_kg,
        "loss_reason": req.loss_reason,
        "difference_kg": unexplained_variance,
        "difference_status": "APPROVED_DISCREPANCY" if (is_discrepancy and req.discrepancy_approved) else ("MATCH" if abs(unexplained_variance) <= DEFAULT_PACKING_TOLERANCE_KG else "REVIEW_REQUIRED"),
        "discrepancy_approved": "true" if req.discrepancy_approved else "false",
        "discrepancy_explanation": req.discrepancy_explanation,
        "status": "RECORDED",
        "reference": req.reference,
        "notes": req.notes,
        "created_at": now(),
        "created_by": actor,
    }
    if not db.append_record("PackagingBatches", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save packaging record")

    # Stock ledger postings
    movements = [{
        "movement_type": "BULK_PACKAGED",
        "quantity_kg": req.bulk_kg_used,
        "quantity_packets": 0,
        "channel": "FACTORY_BULK",
        "product_id": req.product_id,
        "bulk_product_key": bulk_key,
        "product_name_snapshot": field(product, "product_name"),
    }]

    for weight_g, packet_count in [(200, req.packets_200g), (500, req.packets_500g), (1000, req.packets_1000g)]:
        if packet_count <= 0:
            continue
        sku_product = next((p for p in db.get_records("Products") if str(field(p, "product_name")).strip().lower() == bulk_key and int(float(field(p, "pack_weight_g", default=0) or 0)) == weight_g and truthy(field(p, "active", default="true"))), None)
        if not sku_product:
            raise HTTPException(400, f"No active {weight_g} g SKU found for {field(product, 'product_name')}. Create/activate that pack-size product first.")
        movements.append({
            "movement_type": "PACKETS_PACKAGED",
            "quantity_kg": 0,
            "quantity_packets": packet_count,
            "channel": "FACTORY_FINISHED",
            "product_id": str(field(sku_product, "product_id")),
            "bulk_product_key": bulk_key,
            "product_name_snapshot": field(sku_product, "product_name"),
            "sku_snapshot": field(sku_product, "sku"),
            "pack_weight_g": weight_g,
        })

    try:
        for m in movements:
            row = {
                "movement_id": make_id("ProductionStockLedger"),
                "txn_datetime": now(),
                **m,
                "reference_id": pack_id,
                "created_by": actor,
                "notes": req.notes,
            }
            if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
                raise RuntimeError("Failed to append stock ledger movement")
    except Exception as exc:
        try:
            db.update_record("PackagingBatches", "packaging_id", pack_id, {"status": "INCOMPLETE", "notes": f"INCOMPLETE_STOCK_WRITE: {exc}"})
        except Exception:
            pass
        raise HTTPException(503, f"Packaging record saved but stock ledger writes failed ({exc}). Marked as INCOMPLETE. Reconcile before retrying.")

    db.log_audit(actor, "RECORD_PACKAGING", "PackagingBatches", pack_id, reason=f"Used {req.bulk_kg_used} kg, packed {total_packets} packets, variance {unexplained_variance:+.3f} kg")
    return rec


@router.post("/packaging/{packaging_id}/approve-discrepancy")
async def approve_packaging_discrepancy(packaging_id: str, req: DiscrepancyApprovalRequest, user: dict = Depends(get_current_user)):
    """
    Approve an unexplained packing discrepancy.
    Preserves original quantities, saves explanation, records approving Owner, and posts stock movements if pending.
    """
    actor, _ = require_owner(user)
    require_persistent_store()

    batch = next((p for p in db.get_records("PackagingBatches") if str(field(p, "packaging_id")) == packaging_id), None)
    if not batch:
        raise HTTPException(404, "Packaging batch not found")

    ledger = db.get_records("ProductionStockLedger")
    bulk_key = str(field(batch, "product_name_snapshot")).strip().lower()
    bulk_kg = float(field(batch, "bulk_kg_used", default=0) or 0)
    p200 = int(float(field(batch, "packets_200g", default=0) or 0))
    p500 = int(float(field(batch, "packets_500g", default=0) or 0))
    p1000 = int(float(field(batch, "packets_1000g", default=0) or 0))

    # Ensure bulk stock deduction exists
    existing_bulk = next((m for m in ledger if str(field(m, "reference_id")) == packaging_id and str(field(m, "movement_type")).upper() == "BULK_PACKAGED"), None)
    if not existing_bulk:
        row = {
            "movement_id": make_id("ProductionStockLedger"),
            "txn_datetime": now(),
            "movement_type": "BULK_PACKAGED",
            "quantity_kg": bulk_kg,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
            "product_id": field(batch, "product_id"),
            "bulk_product_key": bulk_key,
            "product_name_snapshot": field(batch, "product_name_snapshot"),
            "reference_id": packaging_id,
            "created_by": actor,
            "notes": f"Discrepancy approved deduction: {req.explanation}",
        }
        if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
            raise HTTPException(503, "Could not record bulk stock deduction.")

    # Ensure finished packets exist
    for weight_g, count in [(200, p200), (500, p500), (1000, p1000)]:
        if count <= 0:
            continue
        sku_product = next((p for p in db.get_records("Products") if str(field(p, "product_name")).strip().lower() == bulk_key and int(float(field(p, "pack_weight_g", default=0) or 0)) == weight_g and truthy(field(p, "active", default="true"))), None)
        if sku_product:
            target_sku_id = str(field(sku_product, "product_id"))
            existing_sku = next((m for m in ledger if str(field(m, "reference_id")) == packaging_id and str(field(m, "product_id")) == target_sku_id and str(field(m, "movement_type")).upper() == "PACKETS_PACKAGED"), None)
            if not existing_sku:
                row = {
                    "movement_id": make_id("ProductionStockLedger"),
                    "txn_datetime": now(),
                    "movement_type": "PACKETS_PACKAGED",
                    "quantity_kg": 0,
                    "quantity_packets": count,
                    "channel": "FACTORY_FINISHED",
                    "product_id": target_sku_id,
                    "bulk_product_key": bulk_key,
                    "product_name_snapshot": field(sku_product, "product_name"),
                    "sku_snapshot": field(sku_product, "sku"),
                    "pack_weight_g": weight_g,
                    "reference_id": packaging_id,
                    "created_by": actor,
                    "notes": f"Discrepancy approved packet credit: {req.explanation}",
                }
                if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
                    raise HTTPException(503, "Could not record packet stock.")

    updates = {
        "status": "RECORDED",
        "difference_status": "APPROVED_DISCREPANCY",
        "discrepancy_approved": "true",
        "discrepancy_explanation": req.explanation.strip(),
        "discrepancy_approved_by": actor,
        "discrepancy_approved_at": now(),
    }
    db.update_record("PackagingBatches", "packaging_id", packaging_id, updates)
    db.log_audit(actor, "APPROVE_PACKAGING_DISCREPANCY", "PackagingBatches", packaging_id, reason=req.explanation.strip())

    return {"status": "SUCCESS", "packaging_id": packaging_id, "message": "Discrepancy approved and stock reconciled."}


# -------------------------------------------------------------
# Stock Dispatches (Transfers)
# -------------------------------------------------------------

@router.post("/dispatch")
async def dispatch(req: DispatchCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_owner(user)
    require_persistent_store()

    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == req.product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")
    if req.channel.upper() not in {"ECOMMERCE", "RETAIL", "SALESMAN", "WHOLESALE", "DISTRIBUTOR"}:
        raise HTTPException(400, "Unsupported distribution channel")

    ledger = db.get_records("ProductionStockLedger")
    available_packets = calculate_finished_stock_balance(ledger, req.product_id).get(req.product_id, 0)
    if req.quantity_packets > available_packets:
        raise HTTPException(400, f"Insufficient factory finished stock. Available: {available_packets} packets; Requested: {req.quantity_packets} packets.")

    # Idempotency & Incomplete Dispatch Recovery
    if req.reference and req.reference.strip():
        ref_clean = req.reference.strip()
        existing_disp = next((d for d in db.get_records("ProductionDispatches") if str(field(d, "reference")).strip() == ref_clean), None)
        if existing_disp:
            disp_id = str(field(existing_disp, "dispatch_id"))
            disp_status = str(field(existing_disp, "status")).upper()
            if disp_status == "DISPATCHED_NOT_SALE":
                return existing_disp

            # Reconcile incomplete dispatch
            existing_prod_mvt = next((m for m in ledger if str(field(m, "reference_id")) == disp_id and str(field(m, "movement_type")).upper() == "CHANNEL_DISPATCH"), None)
            if not existing_prod_mvt:
                movement = {
                    "movement_id": make_id("ProductionStockLedger"),
                    "txn_datetime": now(),
                    "movement_type": "CHANNEL_DISPATCH",
                    "product_id": req.product_id,
                    "product_name_snapshot": field(product, "product_name"),
                    "quantity_kg": 0,
                    "quantity_packets": req.quantity_packets,
                    "channel": req.channel.upper(),
                    "reference_id": disp_id,
                    "destination": req.destination,
                    "created_by": actor,
                    "notes": f"Reconciled retry: {req.notes}",
                }
                if not db.append_record("ProductionStockLedger", movement, raise_on_error=True):
                    raise HTTPException(503, "Production stock deduction failed during dispatch recovery.")

            if req.channel.upper() == "SALESMAN" and req.destination:
                salesman_ledger = db.get_records("SalesmanStockLedger")
                existing_salesman_mvt = next((m for m in salesman_ledger if str(field(m, "reference_id")) == disp_id), None)
                if not existing_salesman_mvt:
                    if not db.append_record("SalesmanStockLedger", {
                        "stock_txn_id": make_id("SalesmanStockLedger"),
                        "txn_datetime": now(),
                        "salesman_user_id": req.destination,
                        "product_id": req.product_id,
                        "sku_snapshot": field(product, "sku"),
                        "txn_type": "SALESMAN_POSITIVE_ADJUSTMENT",
                        "quantity": req.quantity_packets,
                        "unit": "PACKET",
                        "pack_weight_g": int(float(field(product, "pack_weight_g", default=0) or 0)),
                        "related_sale_id": "",
                        "issued_by_user_id": actor,
                        "received_by_user_id": req.destination,
                        "confirmed_by_user_id": actor,
                        "reference_id": disp_id,
                        "notes": "Factory dispatch to salesman (Reconciled retry).",
                    }, raise_on_error=True):
                        raise HTTPException(503, "Salesman stock movement failed during dispatch recovery.")

            db.update_record("ProductionDispatches", "dispatch_id", disp_id, {"status": "DISPATCHED_NOT_SALE", "notes": f"{req.notes} [RECONCILED]"})
            existing_disp["status"] = "DISPATCHED_NOT_SALE"
            db.log_audit(actor, "RECONCILE_DISPATCH", "ProductionDispatches", disp_id, reason=f"Recovered dispatch {disp_id} with reference {ref_clean}")
            return existing_disp

    disp_id = make_id("ProductionDispatches")
    rec = {
        "dispatch_id": disp_id,
        "dispatch_datetime": now(),
        "product_id": req.product_id,
        "product_name_snapshot": field(product, "product_name"),
        "channel": req.channel.upper(),
        "destination": req.destination,
        "quantity_packets": req.quantity_packets,
        "reference": req.reference,
        "status": "DISPATCHED_NOT_SALE",
        "created_by": actor,
        "notes": req.notes,
    }
    if not db.append_record("ProductionDispatches", rec, raise_on_error=True):
        raise HTTPException(503, "Could not save dispatch record")

    try:
        movement = {
            "movement_id": make_id("ProductionStockLedger"),
            "txn_datetime": now(),
            "movement_type": "CHANNEL_DISPATCH",
            "product_id": req.product_id,
            "product_name_snapshot": field(product, "product_name"),
            "quantity_kg": 0,
            "quantity_packets": req.quantity_packets,
            "channel": req.channel.upper(),
            "reference_id": disp_id,
            "destination": req.destination,
            "created_by": actor,
            "notes": req.notes,
        }
        if not db.append_record("ProductionStockLedger", movement, raise_on_error=True):
            raise RuntimeError("ProductionStockLedger append returned False")

        if req.channel.upper() == "SALESMAN" and req.destination:
            if not db.append_record("SalesmanStockLedger", {
                "stock_txn_id": make_id("SalesmanStockLedger"),
                "txn_datetime": now(),
                "salesman_user_id": req.destination,
                "product_id": req.product_id,
                "sku_snapshot": field(product, "sku"),
                "txn_type": "SALESMAN_POSITIVE_ADJUSTMENT",
                "quantity": req.quantity_packets,
                "unit": "PACKET",
                "pack_weight_g": int(float(field(product, "pack_weight_g", default=0) or 0)),
                "related_sale_id": "",
                "issued_by_user_id": actor,
                "received_by_user_id": req.destination,
                "confirmed_by_user_id": actor,
                "reference_id": disp_id,
                "notes": "Factory dispatch to salesman. This is a stock transfer, not a sale.",
            }, raise_on_error=True):
                raise RuntimeError("SalesmanStockLedger append returned False")
    except Exception as exc:
        try:
            db.update_record("ProductionDispatches", "dispatch_id", disp_id, {"status": "INCOMPLETE_STOCK_WRITE", "notes": f"INCOMPLETE_STOCK_WRITE: {exc}"})
        except Exception:
            pass
        raise HTTPException(503, f"Dispatch was saved but stock deduction failed ({exc}). Marked as INCOMPLETE. Reconcile before retrying.")

    db.log_audit(actor, "PRODUCTION_STOCK_DISPATCH", "ProductionDispatches", disp_id, reason=f"{req.quantity_packets} packets transferred to {req.channel}: {req.destination}")
    return rec


@router.get("/dispatches")
async def dispatches(user: dict = Depends(get_current_user)):
    require_owner(user)
    return db.get_records("ProductionDispatches")


# -------------------------------------------------------------
# Costing Endpoints
# -------------------------------------------------------------

@router.get("/costing/batch/{production_id}")
async def get_batch_costing(production_id: str, user: dict = Depends(get_current_user)):
    """
    Get attributable actual batch production cost from issued materials and attendance expenses.
    """
    require_owner(user)
    batch = next((b for b in db.get_records("ProductionBatches") if str(field(b, "production_id")) == production_id), None)
    if not batch:
        raise HTTPException(404, "Production batch not found")

    raw_ledger = db.get_records("RawMaterialLedger")
    materials_issued = [x for x in raw_ledger if str(field(x, "production_id")) == production_id and str(field(x, "movement_type")).upper() == "PRODUCTION_CONSUMPTION"]

    saleable_kg = float(field(batch, "net_quantity_kg", default=field(batch, "saleable_output_kg", default=0)) or 0)

    # Calculate labor cost accrued on batch date if applicable
    batch_date = str(field(batch, "production_date"))
    attendance_records = db.get_records("WorkerAttendance")
    labor_for_date = sum(float(field(a, "wage_accrued", default=0) or 0) for a in attendance_records if str(field(a, "attendance_date")) == batch_date)

    cost_result = calculate_batch_actual_cost(
        materials_issued=materials_issued,
        actual_saleable_output_kg=saleable_kg,
        labour_cost=labor_for_date,
    )

    return {
        "production_id": production_id,
        "product_id": field(batch, "product_id"),
        "product_name": field(batch, "product_name_snapshot"),
        "production_date": batch_date,
        **cost_result,
    }


@router.get("/costing/sku/{product_id}")
async def get_sku_costing(product_id: str, user: dict = Depends(get_current_user)):
    """
    Calculate finished packet cost for a given SKU based on its net weight and production cost.
    """
    require_owner(user)
    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")

    pack_weight = int(float(field(product, "pack_weight_g", default=0) or 0))

    # Standard production cost estimation or benchmark
    # Use 128.03/kg from Moong Master or calculate from approved recipe
    prod_name = str(field(product, "product_name")).strip().lower()
    recipe = next((r for r in db.get_records("Recipes") if str(field(r, "product_name_snapshot")).strip().lower() == prod_name and truthy(field(r, "approved"))), None)

    cost_per_kg = 128.03
    if recipe:
        items = json.loads(str(field(recipe, "items_json", default="[]")))
        yield_kg = float(field(recipe, "expected_yield_kg", default=1.2) or 1.2)
        cost_calc = calculate_recipe_cost(items, yield_kg)
        if cost_calc.get("cost_per_kg"):
            cost_per_kg = float(cost_calc["cost_per_kg"])

    # Packaging material cost estimates: ~₹1.50 per pouch
    sku_cost = calculate_finished_sku_cost(
        pack_weight_grams=pack_weight,
        production_cost_per_saleable_kg=cost_per_kg,
        packaging_material_cost_per_packet=1.50,
        packing_labour_per_packet=0.50,
    )

    return {
        "product_id": product_id,
        "product_name": field(product, "product_name"),
        "sku": field(product, "sku"),
        "benchmark_production_cost_per_kg": cost_per_kg,
        **sku_cost,
    }
