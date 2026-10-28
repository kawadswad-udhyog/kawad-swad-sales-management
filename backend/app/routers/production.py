import logging
import re
import hashlib
from app.timeutil import business_today, now_iso
from typing import Any, Dict, List, Optional
import json
import threading
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.auth import get_current_user
from app.sheets import db
from app.config import SALES_GOOGLE_SPREADSHEET_ID
from app.models import BulkAttendanceCreate, BulkAttendanceResponse, BulkAttendanceItem
from app.recipes_master import (
    MASTER_RECIPES_DEFINITION,
    RAW_MATERIALS_SEED,
    STANDARD_RATES,
    calculate_recipe_cost,
    normalize_quantity_to_std_unit,
)

logger = logging.getLogger(__name__)
_ATTENDANCE_LOCK = threading.Lock()
from app.calculations import (
    to_decimal,
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
    calculate_consolidated_finished_goods_register,
    DEFAULT_PACKING_TOLERANCE_KG,
)

router = APIRouter(prefix="/api/production", tags=["Production"])

# Role permissions: Owner has full control including approvals; PA has data entry & operational access.
OWNER_ROLES = {"OWNER", "OWNER_ADMIN", "ADMIN"}
PRODUCTION_ROLES = {"OWNER", "OWNER_ADMIN", "ADMIN", "PA"}


def actor_info(user: dict):
    return str(user.get("user_id", "")), str(user.get("role", "")).upper()


def require_owner(user: dict):
    """Enforce strict Owner-only access for sensitive approval and recipe confirmation endpoints."""
    actor, role = actor_info(user)
    if role not in OWNER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only the Owner can approve batches, recipes, or discrepancies."
        )
    return actor, role


def require_production_access(user: dict):
    """Allow Owner or PA to access production data entry, attendance, packaging, and overview."""
    actor, role = actor_info(user)
    if role not in PRODUCTION_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only the Owner or PA can access production operations."
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


class AttendanceUpdate(BaseModel):
    status: str
    notes: Optional[str] = ""


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


class RawMaterialReceiveRequest(BaseModel):
    raw_material_id: Optional[str] = None
    material_id: Optional[str] = None  # alias
    material_name: Optional[str] = None
    quantity: float = Field(gt=0, description="Inward quantity in kg or L (must be > 0)")
    unit: str = Field("kg", description="Quantity unit (kg, g, L, ml)")
    purchase_rate: float = Field(gt=0, description="Base supplier purchase rate per unit")
    supplier_id: Optional[str] = ""
    supplier_name: Optional[str] = ""
    invoice_number: Optional[str] = None
    invoice_reference: Optional[str] = None  # alias
    line_number: Optional[int] = Field(1, ge=1, description="Invoice line item number (default 1)")
    receipt_date: Optional[str] = ""
    freight_amount: Optional[float] = Field(0.0, ge=0, description="Freight / transport expenses")
    other_expenses_amount: Optional[float] = Field(0.0, ge=0, description="Other landed expenses (unloading, cartage)")
    other_expenses: Optional[float] = None  # alias
    gst_amount: Optional[float] = Field(0.0, ge=0, description="GST amount charged")
    gst_treatment: Optional[str] = Field("RECOVERABLE_ITC", description="RECOVERABLE_ITC, CAPITALIZED_TO_COST, or EXEMPT_NIL_RATED")
    idempotency_key: Optional[str] = Field(None, description="Unique client idempotency key")
    notes: Optional[str] = ""


class RawMaterialReceiveResponse(BaseModel):
    success: bool
    status: str
    raw_material_txn_id: str
    transaction_id: Optional[str] = None
    raw_material_id: str
    material_id: Optional[str] = None
    material_name: str
    quantity_received: float
    quantity: Optional[float] = None
    unit: str
    base_purchase_value: float
    base_value: Optional[float] = None
    freight_amount: float
    other_expenses_amount: float
    other_expenses: Optional[float] = None
    gst_amount: float
    gst_treatment: str
    total_landed_cost: float
    effective_unit_cost: float
    landed_rate_per_unit: Optional[float] = None
    previous_available_stock: float
    new_available_stock: float
    is_replay: bool = False
    message: str


class RawMaterialBalanceItem(BaseModel):
    raw_material_id: str
    material_name: str
    category: str
    unit: str
    opening_stock: float
    consumed: float
    received: float
    available_stock: float
    latest_landed_rate: Optional[float] = None
    rate_status: str


class DalMillingCreate(BaseModel):
    source_material_id: str = Field(..., description="Whole Dal ID (e.g. RM-WHOLE-MOONG-DAL)")
    input_quantity_kg: float = Field(..., description="Gross Whole Dal quantity fed into mill (kg)")
    flour_output_kg: float = Field(..., description="Actual Flour output produced from mill (kg)")
    milling_expenses: Optional[float] = Field(0.0, description="Actual processing/milling expenses (₹)")
    milling_date: Optional[str] = Field("", description="Milling batch date (YYYY-MM-DD)")
    batch_reference: Optional[str] = Field("", description="External batch ref or machine run number")
    idempotency_key: Optional[str] = Field(None, description="Unique client idempotency key")
    notes: Optional[str] = Field("", description="Operator/machine notes")


class DalMillingResponse(BaseModel):
    success: bool
    status: str
    milling_batch_id: str
    input_txn_id: str
    output_txn_id: str
    source_material_id: str
    source_material_name: str
    input_quantity_kg: float
    target_flour_id: str
    target_flour_name: str
    flour_output_kg: float
    processing_loss_kg: float
    loss_percentage: float
    source_unit_rate: float
    milling_expenses: float
    total_flour_cost: float
    flour_unit_cost: float
    new_whole_stock: float
    new_flour_stock: float
    is_replay: bool = False
    message: str


class DalMillingHistoryItem(BaseModel):
    milling_batch_id: str
    milling_date: str
    source_material_id: str
    source_material_name: str
    input_quantity_kg: float
    target_flour_id: str
    target_flour_name: str
    flour_output_kg: float
    processing_loss_kg: float
    loss_percentage: float
    source_unit_rate: float
    milling_expenses: float
    total_flour_cost: float
    flour_unit_cost: float
    batch_reference: str
    created_by: str
    notes: str


DAL_TO_FLOUR_MAPPING = {
    "RM-WHOLE-MOONG-DAL": {
        "target_flour_id": "RM-MOONG-FLOUR",
        "target_flour_name": "Moong Dal Flour",
        "canonical_dal_name": "Whole Moong Dal",
    },
    "RM-WHOLE-URAD-DAL": {
        "target_flour_id": "RM-URAD-FLOUR",
        "target_flour_name": "Urad Dal Flour",
        "canonical_dal_name": "Whole Urad Dal",
    },
    "RM-WHOLE-CHANA-DAL": {
        "target_flour_id": "RM-CHANA-FLOUR",
        "target_flour_name": "Chana Dal Flour",
        "canonical_dal_name": "Whole Chana Dal",
    },
}


def resolve_dal_flour_pair(mat_key: str):
    k = (mat_key or "").strip().lower()
    for dal_id, mapping in DAL_TO_FLOUR_MAPPING.items():
        if dal_id.lower() == k or mapping["canonical_dal_name"].lower() == k:
            return dal_id, mapping
    return None, None


_RAW_MATERIAL_MUTEX = threading.RLock()


# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------

@router.get("/raw-materials", response_model=List[RawMaterialBalanceItem])
async def list_raw_materials(user: dict = Depends(get_current_user)):
    require_production_access(user)
    raw_master = db.get_records("RawMaterials", fresh=False)
    if not raw_master:
        raw_master = RAW_MATERIALS_SEED

    known_names = {str(field(r, "material_name", "name", default="")).strip().lower() for r in raw_master}
    combined_master = list(raw_master)
    for s in RAW_MATERIALS_SEED:
        if s["material_name"].strip().lower() not in known_names:
            combined_master.append(s)
            known_names.add(s["material_name"].strip().lower())

    raw_ledger = db.get_records("RawMaterialLedger", fresh=False)

    results = []
    for rm in combined_master:
        mat_id = str(field(rm, "raw_material_id", default="")).strip()
        mat_name = str(field(rm, "material_name", "name", default="")).strip()
        cat = str(field(rm, "category", default="RAW_MATERIAL")).strip()
        unit = str(field(rm, "unit", default="kg")).strip()

        bal = calculate_raw_material_balance(mat_name, combined_master, raw_ledger)
        rate_info = get_latest_purchase_rate(mat_name, combined_master, raw_ledger)
        latest_rate = rate_info.get("rate_per_canonical_unit")
        rate_status = rate_info.get("status", "CONFIRMED") if latest_rate is not None else "PENDING"

        results.append(RawMaterialBalanceItem(
            raw_material_id=mat_id,
            material_name=mat_name,
            category=cat,
            unit=unit,
            opening_stock=float(bal.get("opening_stock", 0.0)),
            consumed=float(bal.get("consumed", 0.0)),
            received=float(bal.get("received", 0.0)),
            available_stock=float(bal.get("available", 0.0)),
            latest_landed_rate=float(latest_rate) if latest_rate is not None else None,
            rate_status=rate_status,
        ))

    return results


get_raw_material_balances = list_raw_materials


@router.post("/raw-materials/receive", response_model=RawMaterialReceiveResponse)
async def receive_raw_material(req: RawMaterialReceiveRequest, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
    require_persistent_store()

    # 1. Input sanitization and basic validations
    clean_mat_id = (req.raw_material_id or req.material_id or req.material_name or "").strip()
    if not clean_mat_id:
        raise HTTPException(422, "Raw material identification is required.")

    inv_raw = (req.invoice_number or req.invoice_reference or "").strip()
    if not inv_raw:
        raise HTTPException(422, "Invoice or bill reference number is required.")
    clean_invoice = inv_raw.upper()

    line_no = int(req.line_number or 1)
    clean_idemp_key = (req.idempotency_key or f"IDEMP:{clean_invoice}:L:{line_no}").strip()
    treatment = (req.gst_treatment or "RECOVERABLE_ITC").strip().upper()

    if treatment not in {"RECOVERABLE_ITC", "CAPITALIZED_TO_COST", "EXEMPT_NIL_RATED"}:
        raise HTTPException(422, "gst_treatment must be RECOVERABLE_ITC, CAPITALIZED_TO_COST, or EXEMPT_NIL_RATED")

    if req.quantity <= 0:
        raise HTTPException(422, "Quantity must be strictly greater than zero")

    if req.purchase_rate <= 0:
        raise HTTPException(422, "Purchase rate must be strictly greater than zero")

    freight_val = float(req.freight_amount or 0.0)
    other_val = float(req.other_expenses if req.other_expenses is not None else (req.other_expenses_amount or 0.0))
    gst_val = float(req.gst_amount or 0.0)

    if freight_val < 0 or other_val < 0 or gst_val < 0:
        raise HTTPException(422, "Expenses and GST amounts cannot be negative")

    # Standardize unit
    try:
        std_qty, std_unit = normalize_to_canonical_unit(req.quantity, req.unit)
    except Exception as unit_err:
        raise HTTPException(422, f"Invalid unit or quantity: {unit_err}")

    # Build canonical fingerprint payload dict for idempotency comparison
    payload_dict = {
        "raw_material_id": clean_mat_id,
        "quantity": round_stock(std_qty),
        "unit": std_unit,
        "purchase_rate": round_money(req.purchase_rate),
        "freight_amount": round_money(freight_val),
        "other_expenses_amount": round_money(other_val),
        "gst_amount": round_money(gst_val),
        "gst_treatment": treatment,
        "invoice_number": clean_invoice,
        "line_number": line_no,
        "supplier_id": (req.supplier_id or "").strip(),
        "supplier_name": (req.supplier_name or "").strip(),
    }
    payload_hash = hashlib.sha256(json.dumps(payload_dict, sort_keys=True).encode("utf-8")).hexdigest()
    line_key = f"INV:{clean_invoice}:L:{line_no}"

    with _RAW_MATERIAL_MUTEX:
        # 2. Resolve material in master data
        raw_master = db.get_records("RawMaterials", fresh=True)
        mat_row = next(
            (r for r in raw_master
             if str(field(r, "raw_material_id", default="")).strip().lower() == clean_mat_id.lower()
             or str(field(r, "material_name", default="")).strip().lower() == clean_mat_id.lower()),
            None
        )

        # Fallback to RAW_MATERIALS_SEED if master has not been seeded with this item yet
        if not mat_row:
            seed_row = next(
                (s for s in RAW_MATERIALS_SEED
                 if s["raw_material_id"].strip().lower() == clean_mat_id.lower()
                 or s["material_name"].strip().lower() == clean_mat_id.lower()),
                None
            )
            if seed_row:
                new_row = {
                    "raw_material_id": seed_row["raw_material_id"],
                    "material_name": seed_row["material_name"],
                    "current_stock": 0.0,
                    "unit": seed_row["unit"],
                    "rate_per_unit": seed_row["rate_per_unit"] if seed_row["rate_per_unit"] is not None else "",
                    "rate_status": seed_row["rate_status"],
                    "category": seed_row["category"],
                    "created_at": now(),
                    "created_by": actor,
                }
                db.append_record("RawMaterials", new_row, raise_on_error=True)
                raw_master = db.get_records("RawMaterials", fresh=True)
                mat_row = new_row
            else:
                raise HTTPException(422, f"Raw material '{clean_mat_id}' not found in RawMaterials master.")

        resolved_mat_id = str(field(mat_row, "raw_material_id", default=clean_mat_id)).strip()
        canonical_mat_name = str(field(mat_row, "material_name", default=clean_mat_id)).strip()

        # 3. Check IncompleteTransactions for idempotency key
        incomp_records = db.get_records("IncompleteTransactions", fresh=True)
        existing_txn = next((t for t in incomp_records if str(t.get("idempotency_key", "")).strip() == clean_idemp_key), None)
        if existing_txn:
            stored_payload_str = str(existing_txn.get("payload_json", "")).strip()
            stored_hash = None
            try:
                stored_data = json.loads(stored_payload_str)
                stored_hash = stored_data.get("payload_hash")
            except Exception:
                pass

            if stored_hash and stored_hash != payload_hash:
                raise HTTPException(409, "Conflict: Idempotency key reused with conflicting request payload parameters.")

        # 4. Check RawMaterialLedger for existing line
        raw_ledger = db.get_records("RawMaterialLedger", fresh=True)
        existing_line = next(
            (r for r in raw_ledger
             if str(r.get("issue_txn_id", "")).strip() == line_key
             and (str(r.get("raw_material_id", "")).strip().lower() == resolved_mat_id.lower()
                  or str(r.get("material_name", "")).strip().lower() == canonical_mat_name.lower())
             and str(r.get("movement_type", "")).strip().upper() == "PURCHASE_RECEIPT"),
            None
        )

        if existing_line:
            notes_str = str(existing_line.get("notes", ""))
            stored_hash = None
            try:
                meta = json.loads(notes_str)
                stored_hash = meta.get("payload_hash")
            except Exception:
                pass

            if stored_hash and stored_hash != payload_hash:
                raise HTTPException(409, f"Conflict: Invoice line '{line_key}' already recorded with different details.")

            cur_bal = calculate_raw_material_balance(canonical_mat_name, raw_master, raw_ledger)
            existing_rate = float(existing_line.get("rate_per_unit", 0) or 0)
            existing_qty = float(existing_line.get("quantity", 0) or 0)
            return RawMaterialReceiveResponse(
                success=True,
                status="ALREADY_RECORDED",
                raw_material_txn_id=str(existing_line.get("raw_material_txn_id", "")),
                transaction_id=str(existing_line.get("raw_material_txn_id", "")),
                raw_material_id=resolved_mat_id,
                material_id=resolved_mat_id,
                material_name=canonical_mat_name,
                quantity_received=existing_qty,
                quantity=existing_qty,
                unit=str(existing_line.get("unit", std_unit)),
                base_purchase_value=round_money(existing_qty * float(req.purchase_rate)),
                base_value=round_money(existing_qty * float(req.purchase_rate)),
                freight_amount=freight_val,
                other_expenses_amount=other_val,
                other_expenses=other_val,
                gst_amount=gst_val,
                gst_treatment=treatment,
                total_landed_cost=round_money(existing_qty * existing_rate),
                effective_unit_cost=existing_rate,
                landed_rate_per_unit=existing_rate,
                previous_available_stock=float(cur_bal.get("available", 0.0)),
                new_available_stock=float(cur_bal.get("available", 0.0)),
                is_replay=True,
                message=f"Consignment already recorded in ledger as {existing_line.get('raw_material_txn_id')}. No duplicate stock added.",
            )

        # 5. Compute Landed Cost Math
        base_value_dec = to_decimal(round_money(to_decimal(req.quantity) * to_decimal(req.purchase_rate)))
        freight_dec = to_decimal(freight_val)
        other_dec = to_decimal(other_val)
        gst_dec = to_decimal(gst_val)

        if treatment == "CAPITALIZED_TO_COST":
            total_landed_dec = base_value_dec + freight_dec + other_dec + gst_dec
        else:
            total_landed_dec = base_value_dec + freight_dec + other_dec

        effective_unit_rate = round_money(total_landed_dec / to_decimal(std_qty))

        bal_before = calculate_raw_material_balance(canonical_mat_name, raw_master, raw_ledger)
        prev_avail = float(bal_before.get("available", 0.0))

        # 6. Record in-flight intent in IncompleteTransactions
        incomp_txn_id = make_id("IncompleteTransactions")
        intent_payload = {
            "payload_hash": payload_hash,
            "raw_material_id": resolved_mat_id,
            "material_name": canonical_mat_name,
            "quantity": std_qty,
            "unit": std_unit,
            "effective_unit_cost": effective_unit_rate,
            "invoice_number": clean_invoice,
            "line_number": line_no,
            "line_key": line_key,
        }
        try:
            if not db.append_record("IncompleteTransactions", {
                "transaction_id": incomp_txn_id,
                "transaction_type": "RAW_MATERIAL_RECEIPT",
                "idempotency_key": clean_idemp_key,
                "status": "IN_PROGRESS",
                "payload_json": json.dumps(intent_payload),
                "error_details": "",
                "created_at": now(),
                "updated_at": now(),
                "resolved_by": "",
                "resolved_at": "",
            }, raise_on_error=True):
                raise RuntimeError("Failed to record intent in IncompleteTransactions.")
        except Exception as incomp_err:
            logger.error("Failed to record intent in IncompleteTransactions: %s", incomp_err)
            raise HTTPException(503, f"Storage error recording transaction intent: {incomp_err}. Safe to retry.")

        # 7. Append single row to RawMaterialLedger
        ledger_txn_id = db.generate_id("RawMaterialLedger")
        notes_metadata = json.dumps({
            "_v": 1,
            "kind": "PURCHASE_RECEIPT",
            "request_id": clean_idemp_key,
            "payload_hash": payload_hash,
            "supplier_name": (req.supplier_name or "").strip(),
            "supplier_id": (req.supplier_id or "").strip(),
            "invoice_number": clean_invoice,
            "line_number": line_no,
            "supplier_unit_rate": float(req.purchase_rate),
            "base_purchase_value": float(base_value_dec),
            "freight_amount": float(freight_dec),
            "other_expenses_amount": float(other_dec),
            "gst_amount": float(gst_dec),
            "gst_treatment": treatment,
            "total_landed_cost": float(total_landed_dec),
            "effective_unit_cost": float(effective_unit_rate),
            "operator_remarks": (req.notes or "").strip(),
        })

        ledger_row = {
            "raw_material_txn_id": ledger_txn_id,
            "txn_datetime": req.receipt_date or now(),
            "material_name": canonical_mat_name,
            "raw_material_id": resolved_mat_id,
            "movement_type": "PURCHASE_RECEIPT",
            "quantity": std_qty,
            "unit": std_unit,
            "rate_per_unit": effective_unit_rate,
            "production_id": "",
            "issue_txn_id": line_key,
            "created_by": actor,
            "notes": notes_metadata,
        }

        try:
            if not db.append_record("RawMaterialLedger", ledger_row, raise_on_error=True):
                raise RuntimeError("Failed to append raw material receiving transaction to ledger.")
        except Exception as write_err:
            try:
                db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                    "status": "PARTIAL_FAILED",
                    "error_details": str(write_err),
                    "updated_at": now(),
                })
            except Exception:
                pass
            raise HTTPException(503, f"Storage write error recording raw material receipt: {write_err}. Safe to retry.")

        # 8. Post-write verification
        raw_ledger_after = db.get_records("RawMaterialLedger", fresh=True)
        verified_row = next((r for r in raw_ledger_after if str(r.get("raw_material_txn_id", "")).strip() == ledger_txn_id), None)
        if not verified_row:
            raise HTTPException(503, "Verification failed: appended ledger row could not be confirmed. Safe to retry.")

        # 9. Compute new balance
        bal_after = calculate_raw_material_balance(canonical_mat_name, raw_master, raw_ledger_after)
        new_avail = float(bal_after.get("available", 0.0))

        # 10. Mark IncompleteTransactions completed
        try:
            db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                "status": "COMPLETED",
                "resolved_by": actor,
                "resolved_at": now(),
                "updated_at": now(),
            })
        except Exception as comp_err:
            logger.debug("Non-fatal: IncompleteTransactions complete update error: %s", comp_err)

        # 11. Audit log
        db.log_audit(
            actor,
            "RECEIVE_RAW_MATERIAL",
            "RawMaterialLedger",
            ledger_txn_id,
            reason=f"Received {std_qty} {std_unit} of {canonical_mat_name} (Invoice {clean_invoice}, Line {line_no}) at landed rate ₹{effective_unit_rate}/{std_unit}"
        )

        return RawMaterialReceiveResponse(
            success=True,
            status="SUCCESS",
            raw_material_txn_id=ledger_txn_id,
            transaction_id=ledger_txn_id,
            raw_material_id=resolved_mat_id,
            material_id=resolved_mat_id,
            material_name=canonical_mat_name,
            quantity_received=std_qty,
            quantity=std_qty,
            unit=std_unit,
            base_purchase_value=float(base_value_dec),
            base_value=float(base_value_dec),
            freight_amount=float(freight_dec),
            other_expenses_amount=float(other_dec),
            other_expenses=float(other_dec),
            gst_amount=float(gst_dec),
            gst_treatment=treatment,
            total_landed_cost=float(total_landed_dec),
            effective_unit_cost=float(effective_unit_rate),
            landed_rate_per_unit=float(effective_unit_rate),
            previous_available_stock=prev_avail,
            new_available_stock=new_avail,
            is_replay=False,
            message=f"Successfully received {std_qty} {std_unit} of {canonical_mat_name} at landed rate ₹{effective_unit_rate}/{std_unit}."
        )


@router.post("/milling/record", response_model=DalMillingResponse)
async def record_dal_milling_batch(req: DalMillingCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
    require_persistent_store()

    # 1. Resolve source Dal and target Flour
    dal_id, mapping = resolve_dal_flour_pair(req.source_material_id)
    if not dal_id or not mapping:
        raise HTTPException(
            422,
            f"Unsupported milling material '{req.source_material_id}'. Must be Whole Moong Dal, Whole Urad Dal, or Whole Chana Dal."
        )

    if req.input_quantity_kg <= 0:
        raise HTTPException(422, "Input quantity must be strictly greater than zero.")

    if req.flour_output_kg <= 0:
        raise HTTPException(422, "Flour output quantity must be strictly greater than zero.")

    if req.flour_output_kg > req.input_quantity_kg:
        raise HTTPException(
            422,
            f"Flour output ({req.flour_output_kg} kg) cannot exceed whole dal input ({req.input_quantity_kg} kg). Processing loss cannot be negative."
        )

    milling_exp = round_money(max(0.0, float(req.milling_expenses or 0.0)))
    clean_batch_ref = (req.batch_reference or "").strip()
    milling_date = (req.milling_date or now()[:10]).strip()
    clean_idemp_key = (req.idempotency_key or f"MIL:{clean_batch_ref or milling_date}:{dal_id}:{round_stock(req.input_quantity_kg)}:{round_stock(req.flour_output_kg)}").strip()

    payload_dict = {
        "source_material_id": dal_id,
        "input_quantity_kg": round_stock(req.input_quantity_kg),
        "flour_output_kg": round_stock(req.flour_output_kg),
        "milling_expenses": round_money(milling_exp),
        "milling_date": milling_date,
        "batch_reference": clean_batch_ref,
    }
    payload_hash = hashlib.sha256(json.dumps(payload_dict, sort_keys=True).encode("utf-8")).hexdigest()

    with _RAW_MATERIAL_MUTEX:
        raw_master = db.get_records("RawMaterials", fresh=True)
        raw_ledger = db.get_records("RawMaterialLedger", fresh=True)

        # 2. Check Idempotency and Replay in RawMaterialLedger
        existing_milling_out = next(
            (r for r in raw_ledger
             if str(r.get("movement_type", "")).strip().upper() == "MILLING_OUTPUT"
             and (str(r.get("issue_txn_id", "")).strip() == clean_idemp_key or
                  (clean_batch_ref and str(r.get("issue_txn_id", "")).strip() == clean_batch_ref) or
                  (clean_idemp_key in str(r.get("notes", ""))))),
            None
        )

        if existing_milling_out:
            stored_notes = str(existing_milling_out.get("notes", ""))
            stored_hash = None
            try:
                meta = json.loads(stored_notes)
                stored_hash = meta.get("payload_hash")
            except Exception:
                pass

            if stored_hash and stored_hash != payload_hash:
                raise HTTPException(409, f"Conflict: Milling batch '{clean_idemp_key}' already recorded with different parameters.")

            existing_batch_id = str(existing_milling_out.get("issue_txn_id", ""))
            existing_out_id = str(existing_milling_out.get("raw_material_txn_id", ""))
            existing_in_row = next((r for r in raw_ledger if str(r.get("issue_txn_id", "")) == existing_batch_id and str(r.get("movement_type", "")).upper() == "MILLING_CONSUMPTION"), None)
            existing_in_id = str(existing_in_row.get("raw_material_txn_id", "")) if existing_in_row else ""

            cur_whole = calculate_raw_material_balance(mapping["canonical_dal_name"], raw_master, raw_ledger)
            cur_flour = calculate_raw_material_balance(mapping["target_flour_name"], raw_master, raw_ledger)

            return DalMillingResponse(
                success=True,
                status="ALREADY_RECORDED",
                milling_batch_id=existing_batch_id,
                input_txn_id=existing_in_id,
                output_txn_id=existing_out_id,
                source_material_id=dal_id,
                source_material_name=mapping["canonical_dal_name"],
                input_quantity_kg=float(req.input_quantity_kg),
                target_flour_id=mapping["target_flour_id"],
                target_flour_name=mapping["target_flour_name"],
                flour_output_kg=float(existing_milling_out.get("quantity", req.flour_output_kg)),
                processing_loss_kg=round_stock(float(req.input_quantity_kg) - float(existing_milling_out.get("quantity", req.flour_output_kg))),
                loss_percentage=round(((float(req.input_quantity_kg) - float(existing_milling_out.get("quantity", req.flour_output_kg))) / float(req.input_quantity_kg)) * 100, 2),
                source_unit_rate=float(existing_in_row.get("rate_per_unit", 0) if existing_in_row else 0),
                milling_expenses=milling_exp,
                total_flour_cost=round_money(float(existing_milling_out.get("quantity", req.flour_output_kg)) * float(existing_milling_out.get("rate_per_unit", 0))),
                flour_unit_cost=float(existing_milling_out.get("rate_per_unit", 0)),
                new_whole_stock=float(cur_whole.get("available", 0.0)),
                new_flour_stock=float(cur_flour.get("available", 0.0)),
                is_replay=True,
                message=f"[Idempotent Replay] Milling batch already recorded as {existing_batch_id}. Stock balance intact.",
            )

        # 3. Check Stock Availability
        cur_whole_bal = calculate_raw_material_balance(mapping["canonical_dal_name"], raw_master, raw_ledger)
        available_whole = float(cur_whole_bal.get("available", 0.0))
        if float(req.input_quantity_kg) > available_whole:
            raise HTTPException(
                400,
                f"Insufficient {mapping['canonical_dal_name']} stock: requested {req.input_quantity_kg} kg but available balance is {available_whole} kg."
            )

        # 4. Check IncompleteTransactions for conflict
        incomp_records = db.get_records("IncompleteTransactions", fresh=True)
        existing_txn = next((t for t in incomp_records if str(t.get("idempotency_key", "")).strip() == clean_idemp_key), None)
        if existing_txn:
            stored_payload_str = str(existing_txn.get("payload_json", "")).strip()
            stored_hash = None
            try:
                stored_data = json.loads(stored_payload_str)
                stored_hash = stored_data.get("payload_hash")
            except Exception:
                pass
            if stored_hash and stored_hash != payload_hash:
                raise HTTPException(409, "Conflict: Idempotency key reused with conflicting request payload parameters.")

        # 5. Compute Landed Cost Math
        dal_rate_info = get_latest_purchase_rate(mapping["canonical_dal_name"], raw_master, raw_ledger)
        dal_unit_rate = float(dal_rate_info.get("rate_per_canonical_unit") or 110.0)
        total_dal_cost = round_money(float(req.input_quantity_kg) * dal_unit_rate)
        total_flour_cost = round_money(total_dal_cost + milling_exp)
        flour_unit_rate = round_money(total_flour_cost / float(req.flour_output_kg))
        loss_kg = round_stock(float(req.input_quantity_kg) - float(req.flour_output_kg))
        loss_pct = round((loss_kg / float(req.input_quantity_kg)) * 100, 2)

        # 6. Allocate IDs
        incomp_txn_id = make_id("IncompleteTransactions")
        input_txn_id = db.generate_id("RawMaterialLedger")
        output_txn_id = db.generate_id("RawMaterialLedger")
        milling_batch_id = f"MIL-{input_txn_id.replace('RML-', '')}"

        # 7. Record Intent in IncompleteTransactions
        intent_payload = {
            "payload_hash": payload_hash,
            "milling_batch_id": milling_batch_id,
            "source_material_id": dal_id,
            "input_quantity_kg": float(req.input_quantity_kg),
            "target_flour_id": mapping["target_flour_id"],
            "flour_output_kg": float(req.flour_output_kg),
            "milling_expenses": float(milling_exp),
            "flour_unit_cost": float(flour_unit_rate),
            "input_txn_id": input_txn_id,
            "output_txn_id": output_txn_id,
            "idempotency_key": clean_idemp_key,
        }
        try:
            if not db.append_record("IncompleteTransactions", {
                "transaction_id": incomp_txn_id,
                "transaction_type": "DAL_MILLING",
                "idempotency_key": clean_idemp_key,
                "status": "IN_PROGRESS",
                "payload_json": json.dumps(intent_payload),
                "error_details": "",
                "created_at": now(),
                "updated_at": now(),
                "resolved_by": "",
                "resolved_at": "",
            }, raise_on_error=True):
                raise RuntimeError("Failed to record milling intent in IncompleteTransactions.")
        except Exception as incomp_err:
            logger.error("Failed to record milling intent: %s", incomp_err)
            raise HTTPException(503, f"Storage error recording milling intent: {incomp_err}. Safe to retry.")

        # 8. Leg 1: Deduct Whole Dal from RawMaterialLedger
        input_notes = json.dumps({
            "_v": 1,
            "kind": "MILLING_CONSUMPTION",
            "milling_batch_id": milling_batch_id,
            "idempotency_key": clean_idemp_key,
            "payload_hash": payload_hash,
            "target_flour_id": mapping["target_flour_id"],
            "target_flour_name": mapping["target_flour_name"],
            "input_quantity_kg": float(req.input_quantity_kg),
            "flour_output_kg": float(req.flour_output_kg),
            "processing_loss_kg": float(loss_kg),
            "loss_percentage": float(loss_pct),
            "source_unit_rate": float(dal_unit_rate),
            "total_dal_cost": float(total_dal_cost),
            "milling_expenses": float(milling_exp),
            "batch_reference": clean_batch_ref,
            "operator_notes": (req.notes or "").strip(),
        })
        leg1_row = {
            "raw_material_txn_id": input_txn_id,
            "txn_datetime": milling_date,
            "material_name": mapping["canonical_dal_name"],
            "raw_material_id": dal_id,
            "movement_type": "MILLING_CONSUMPTION",
            "quantity": float(req.input_quantity_kg),
            "unit": "kg",
            "rate_per_unit": float(dal_unit_rate),
            "production_id": "",
            "issue_txn_id": milling_batch_id,
            "created_by": actor,
            "notes": input_notes,
        }
        try:
            if not db.append_record("RawMaterialLedger", leg1_row, raise_on_error=True):
                raise RuntimeError("Failed to append whole dal deduction row to RawMaterialLedger.")
        except Exception as leg1_err:
            try:
                db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                    "status": "PARTIAL_FAILED",
                    "error_details": f"Leg 1 failure: {leg1_err}",
                    "updated_at": now(),
                })
            except Exception:
                pass
            raise HTTPException(503, f"Storage error during dal deduction: {leg1_err}. Safe to retry.")

        # Update intent status to INPUT_COMMITTED
        try:
            db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                "status": "INPUT_COMMITTED",
                "updated_at": now(),
            })
        except Exception:
            pass

        # 9. Leg 2: Credit Flour to RawMaterialLedger
        output_notes = json.dumps({
            "_v": 1,
            "kind": "MILLING_OUTPUT",
            "milling_batch_id": milling_batch_id,
            "idempotency_key": clean_idemp_key,
            "payload_hash": payload_hash,
            "source_material_id": dal_id,
            "source_material_name": mapping["canonical_dal_name"],
            "input_quantity_kg": float(req.input_quantity_kg),
            "flour_output_kg": float(req.flour_output_kg),
            "processing_loss_kg": float(loss_kg),
            "loss_percentage": float(loss_pct),
            "source_unit_rate": float(dal_unit_rate),
            "total_dal_cost": float(total_dal_cost),
            "milling_expenses": float(milling_exp),
            "total_flour_cost": float(total_flour_cost),
            "flour_unit_cost": float(flour_unit_rate),
            "batch_reference": clean_batch_ref,
            "operator_notes": (req.notes or "").strip(),
        })
        leg2_row = {
            "raw_material_txn_id": output_txn_id,
            "txn_datetime": milling_date,
            "material_name": mapping["target_flour_name"],
            "raw_material_id": mapping["target_flour_id"],
            "movement_type": "MILLING_OUTPUT",
            "quantity": float(req.flour_output_kg),
            "unit": "kg",
            "rate_per_unit": float(flour_unit_rate),
            "production_id": "",
            "issue_txn_id": milling_batch_id,
            "created_by": actor,
            "notes": output_notes,
        }
        try:
            if not db.append_record("RawMaterialLedger", leg2_row, raise_on_error=True):
                raise RuntimeError("Failed to append flour output row to RawMaterialLedger.")
        except Exception as leg2_err:
            try:
                db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                    "status": "PARTIAL_FAILED",
                    "error_details": f"Leg 2 failure: {leg2_err}",
                    "updated_at": now(),
                })
            except Exception:
                pass
            raise HTTPException(503, f"Storage error during flour receipt: {leg2_err}. Safe to retry.")

        # 10. Mark IncompleteTransactions COMPLETED
        try:
            db.update_record("IncompleteTransactions", "transaction_id", incomp_txn_id, {
                "status": "COMPLETED",
                "resolved_by": actor,
                "resolved_at": now(),
                "updated_at": now(),
            })
        except Exception:
            pass

        # 11. Audit Log
        db.log_audit(
            actor,
            "RECORD_MILLING_BATCH",
            "RawMaterialLedger",
            milling_batch_id,
            reason=f"Milled {req.input_quantity_kg} kg of {mapping['canonical_dal_name']} into {req.flour_output_kg} kg of {mapping['target_flour_name']} (Loss: {loss_kg} kg / {loss_pct}%) at ₹{flour_unit_rate}/kg"
        )

        # 12. Calculate post-milling balances
        raw_ledger_after = db.get_records("RawMaterialLedger", fresh=True)
        post_whole = calculate_raw_material_balance(mapping["canonical_dal_name"], raw_master, raw_ledger_after)
        post_flour = calculate_raw_material_balance(mapping["target_flour_name"], raw_master, raw_ledger_after)

        return DalMillingResponse(
            success=True,
            status="SUCCESS",
            milling_batch_id=milling_batch_id,
            input_txn_id=input_txn_id,
            output_txn_id=output_txn_id,
            source_material_id=dal_id,
            source_material_name=mapping["canonical_dal_name"],
            input_quantity_kg=float(req.input_quantity_kg),
            target_flour_id=mapping["target_flour_id"],
            target_flour_name=mapping["target_flour_name"],
            flour_output_kg=float(req.flour_output_kg),
            processing_loss_kg=float(loss_kg),
            loss_percentage=float(loss_pct),
            source_unit_rate=float(dal_unit_rate),
            milling_expenses=float(milling_exp),
            total_flour_cost=float(total_flour_cost),
            flour_unit_cost=float(flour_unit_rate),
            new_whole_stock=float(post_whole.get("available", 0.0)),
            new_flour_stock=float(post_flour.get("available", 0.0)),
            is_replay=False,
            message=f"✓ Milled {req.input_quantity_kg} kg {mapping['canonical_dal_name']} into {req.flour_output_kg} kg {mapping['target_flour_name']} (Batch: {milling_batch_id}, Loss: {loss_kg} kg / {loss_pct}%). Landed flour rate: ₹{flour_unit_rate}/kg.",
        )


@router.get("/milling/history", response_model=List[DalMillingHistoryItem])
async def list_milling_history(user: dict = Depends(get_current_user)):
    require_production_access(user)
    raw_ledger = db.get_records("RawMaterialLedger", fresh=False)
    milling_outputs = [r for r in raw_ledger if str(r.get("movement_type", "")).strip().upper() == "MILLING_OUTPUT"]

    items: List[DalMillingHistoryItem] = []
    for row in milling_outputs:
        batch_id = str(row.get("issue_txn_id", ""))
        notes_str = str(row.get("notes", ""))
        meta = {}
        try:
            meta = json.loads(notes_str)
        except Exception:
            pass

        items.append(DalMillingHistoryItem(
            milling_batch_id=batch_id,
            milling_date=str(row.get("txn_datetime") or meta.get("milling_date") or ""),
            source_material_id=str(meta.get("source_material_id") or ""),
            source_material_name=str(meta.get("source_material_name") or ""),
            input_quantity_kg=float(meta.get("input_quantity_kg", 0.0)),
            target_flour_id=str(row.get("raw_material_id", "")),
            target_flour_name=str(row.get("material_name", "")),
            flour_output_kg=float(row.get("quantity", 0.0)),
            processing_loss_kg=float(meta.get("processing_loss_kg", 0.0)),
            loss_percentage=float(meta.get("loss_percentage", 0.0)),
            source_unit_rate=float(meta.get("source_unit_rate", 0.0)),
            milling_expenses=float(meta.get("milling_expenses", 0.0)),
            total_flour_cost=float(meta.get("total_flour_cost", 0.0)),
            flour_unit_cost=float(row.get("rate_per_unit", 0.0)),
            batch_reference=str(meta.get("batch_reference") or ""),
            created_by=str(row.get("created_by") or ""),
            notes=str(meta.get("operator_notes") or ""),
        ))

    items.sort(key=lambda x: x.milling_date or "", reverse=True)
    return items


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    require_production_access(user)
    ledger = db.get_records("ProductionStockLedger")
    products_records = db.get_records("Products")
    salesman_ledger = db.get_records("SalesmanStockLedger")
    users_records = db.get_records("Users")
    sale_items = db.get_records("SaleItems")

    bulk_balances = calculate_bulk_stock_balance(ledger)
    reg_data = calculate_consolidated_finished_goods_register(
        products_master=products_records,
        production_stock_ledger=ledger,
        salesman_stock_ledger=salesman_ledger,
        users_master=users_records,
        sale_items_records=sale_items,
    )

    bulk_stock_list = []
    for bulk_key, qty in bulk_balances.items():
        name_match = next((field(p, "product_name") for p in products_records if str(field(p, "product_name")).strip().lower() == bulk_key), bulk_key.title())
        bulk_stock_list.append({
            "product_id": bulk_key,
            "product_name": name_match,
            "quantity_kg": round_stock(qty),
        })

    # Consolidated finished stock list: includes EVERY active packet SKU (even with 0 stock)
    finished_stock_list = []
    for r in reg_data["register"]:
        finished_stock_list.append({
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": f"{r['product_name']} ({r['sku']})" if r.get("sku") else r["product_name"],
            "quantity_packets": r["factory_stock"],
            "warehouse_stock": r["warehouse_stock"],
            "salesmen_stock": r["salesmen_stock"],
            "total_internal_on_hand": r["total_internal_on_hand"],
            "pack_weight_g": r["pack_weight_g"],
            "category": r["category"],
            "status": r["status"],
        })

    return {
        "bulk_stock": bulk_stock_list,
        "finished_stock": finished_stock_list,
        "finished_goods_register": reg_data["register"],
        "register_summary": reg_data["summary"],
        "workers_active": sum(1 for w in db.get_records("Workers") if truthy(field(w, "active", default="true"))),
        "wage_accrued_today": round(sum(float(field(a, "wage_accrued", default=0) or 0) for a in db.get_records("WorkerAttendance") if str(field(a, "attendance_date")) == business_today()), 2),
        "pending_production": sum(1 for b in db.get_records("ProductionBatches") if str(field(b, "status")).upper() == "PENDING"),
    }


@router.get("/finished-goods-register")
async def get_finished_goods_register(user: dict = Depends(get_current_user)):
    require_production_access(user)
    products_records = db.get_records("Products", fresh=True)
    production_ledger = db.get_records("ProductionStockLedger", fresh=True)
    salesman_ledger = db.get_records("SalesmanStockLedger", fresh=True)
    users_records = db.get_records("Users", fresh=True)
    sale_items = db.get_records("SaleItems", fresh=True)

    return calculate_consolidated_finished_goods_register(
        products_master=products_records,
        production_stock_ledger=production_ledger,
        salesman_stock_ledger=salesman_ledger,
        users_master=users_records,
        sale_items_records=sale_items,
    )


@router.get("/workers")
async def workers(user: dict = Depends(get_current_user)):
    require_production_access(user)
    return db.get_records("Workers")


@router.post("/workers")
async def add_worker(req: WorkerCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
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
    require_production_access(user)
    records = db.get_records("WorkerAttendance") or []
    # Count occurrences of (worker_id, attendance_date) to detect duplicate rows in sheet
    counts: Dict[tuple, int] = {}
    for r in records:
        w_id = str(field(r, "worker_id")).strip()
        a_dt = str(field(r, "attendance_date")).strip()
        if w_id and a_dt:
            counts[(w_id, a_dt)] = counts.get((w_id, a_dt), 0) + 1

    annotated = []
    for r in records:
        w_id = str(field(r, "worker_id")).strip()
        a_dt = str(field(r, "attendance_date")).strip()
        rec_copy = dict(r)
        rec_copy["is_duplicate"] = counts.get((w_id, a_dt), 0) > 1
        annotated.append(rec_copy)
    return annotated


@router.post("/attendance")
async def record_attendance(req: AttendanceCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
    require_persistent_store()
    status_value = req.status.strip().upper()
    if status_value not in {"PRESENT", "ABSENT", "HALF_DAY"}:
        raise HTTPException(400, "Attendance must be PRESENT, ABSENT, or HALF_DAY")
    
    worker_id_clean = req.worker_id.strip()
    date_clean = req.attendance_date.strip()

    worker = next((w for w in (db.get_records("Workers", fresh=True) or []) if str(field(w, "worker_id")).strip() == worker_id_clean), None)
    if not worker:
        raise HTTPException(404, "Worker not found")

    with _ATTENDANCE_LOCK:
        existing = next((a for a in (db.get_records("WorkerAttendance", fresh=True) or [])
                         if str(field(a, "worker_id")).strip() == worker_id_clean
                         and str(field(a, "attendance_date")).strip() == date_clean), None)
        if existing:
            raise HTTPException(409, f"Attendance is already recorded for worker '{field(worker, 'worker_name')}' on {date_clean}. Use the correction workflow to adjust.")

        daily_wage = float(field(worker, "daily_wage", default=0) or 0)
        payable = daily_wage if status_value == "PRESENT" else daily_wage * 0.5 if status_value == "HALF_DAY" else 0
        rec = {
            "attendance_id": make_id("WorkerAttendance"),
            "worker_id": worker_id_clean,
            "worker_name_snapshot": field(worker, "worker_name"),
            "attendance_date": date_clean,
            "status": status_value,
            "daily_wage_snapshot": daily_wage,
            "wage_accrued": round(payable, 2),
            "notes": req.notes.strip(),
            "created_at": now(),
            "created_by": actor,
        }
        if not db.append_record("WorkerAttendance", rec, raise_on_error=True):
            raise HTTPException(503, "Could not save attendance")
        db.log_audit(actor, "RECORD_WORKER_ATTENDANCE", "WorkerAttendance", rec["attendance_id"], reason=f"{rec['worker_name_snapshot']} {status_value} on {date_clean}")
        return rec


@router.post("/attendance/bulk", response_model=BulkAttendanceResponse)
async def record_bulk_attendance(req: BulkAttendanceCreate, user: dict = Depends(get_current_user)):
    """
    Mark bulk attendance for multiple active workers on a single date.
    Prevents duplicate attendance records, validates active workers, calculates daily wages,
    and returns a summary of saved vs skipped records.
    """
    actor, _ = require_production_access(user)
    require_persistent_store()

    date_clean = req.attendance_date.strip()
    if not date_clean:
        raise HTTPException(400, "attendance_date is required")

    if not req.records:
        raise HTTPException(400, "No worker attendance records provided")

    with _ATTENDANCE_LOCK:
        workers = db.get_records("Workers", fresh=True) or []
        workers_by_id = {str(field(w, "worker_id")).strip(): w for w in workers}
        
        attendance_records = db.get_records("WorkerAttendance", fresh=True) or []
        existing_worker_ids = {
            str(field(a, "worker_id")).strip()
            for a in attendance_records
            if str(field(a, "attendance_date")).strip() == date_clean
        }

        saved_records = []
        skipped_workers = []

        for item in req.records:
            w_id = str(item.worker_id).strip()
            status_value = str(item.status or "PRESENT").strip().upper()
            if status_value not in {"PRESENT", "ABSENT", "HALF_DAY"}:
                skipped_workers.append({"worker_id": w_id, "reason": f"Invalid status: {status_value}"})
                continue

            worker = workers_by_id.get(w_id)
            if not worker:
                skipped_workers.append({"worker_id": w_id, "reason": "Worker not found"})
                continue

            if not truthy(field(worker, "active", default="true")):
                skipped_workers.append({
                    "worker_id": w_id,
                    "worker_name": field(worker, "worker_name"),
                    "reason": "Worker is inactive"
                })
                continue

            if w_id in existing_worker_ids:
                skipped_workers.append({
                    "worker_id": w_id,
                    "worker_name": field(worker, "worker_name"),
                    "reason": f"Attendance already recorded on {date_clean}"
                })
                continue

            daily_wage = float(field(worker, "daily_wage", default=0) or 0)
            payable = daily_wage if status_value == "PRESENT" else (daily_wage * 0.5 if status_value == "HALF_DAY" else 0.0)

            att_id = make_id("WorkerAttendance")
            rec = {
                "attendance_id": att_id,
                "worker_id": w_id,
                "worker_name_snapshot": field(worker, "worker_name"),
                "attendance_date": date_clean,
                "status": status_value,
                "daily_wage_snapshot": daily_wage,
                "wage_accrued": round(payable, 2),
                "notes": (item.notes or "").strip(),
                "created_at": now(),
                "created_by": actor,
            }

            if not db.append_record("WorkerAttendance", rec, raise_on_error=True):
                raise HTTPException(503, f"Could not save attendance for worker {field(worker, 'worker_name')}")

            existing_worker_ids.add(w_id)
            saved_records.append(rec)

        db.log_audit(
            actor,
            "RECORD_BULK_WORKER_ATTENDANCE",
            "WorkerAttendance",
            f"{len(saved_records)}_workers",
            reason=f"Bulk attendance on {date_clean}: {len(saved_records)} saved, {len(skipped_workers)} skipped"
        )

        msg = f"Successfully marked attendance for {len(saved_records)} worker(s)."
        if skipped_workers:
            msg += f" {len(skipped_workers)} worker(s) were skipped (already recorded or invalid)."

        return BulkAttendanceResponse(
            status="SUCCESS",
            attendance_date=date_clean,
            saved_count=len(saved_records),
            skipped_count=len(skipped_workers),
            saved_records=saved_records,
            skipped_workers=skipped_workers,
            message=msg,
        )


@router.put("/attendance/{attendance_id}")
async def update_attendance(attendance_id: str, req: AttendanceUpdate, user: dict = Depends(get_current_user)):
    """Audited correction workflow for existing attendance records."""
    actor, _ = require_production_access(user)
    require_persistent_store()
    records = db.get_records("WorkerAttendance", fresh=True) or []
    existing = next((r for r in records if str(field(r, "attendance_id")).strip() == attendance_id.strip()), None)
    if not existing:
        raise HTTPException(404, "Attendance record not found")
    new_status = req.status.strip().upper()
    if new_status not in {"PRESENT", "ABSENT", "HALF_DAY"}:
        raise HTTPException(400, "Status must be PRESENT, ABSENT, or HALF_DAY")

    daily_wage = float(field(existing, "daily_wage_snapshot", default=0) or 0)
    payable = daily_wage if new_status == "PRESENT" else daily_wage * 0.5 if new_status == "HALF_DAY" else 0
    updates = {
        "status": new_status,
        "wage_accrued": round(payable, 2),
        "notes": f"{field(existing, 'notes')} | Corrected by {actor}: {req.notes}".strip(" | "),
        "updated_at": now(),
        "updated_by": actor,
    }
    if not db.update_record("WorkerAttendance", "attendance_id", attendance_id, updates, raise_on_error=True):
        raise HTTPException(503, "Could not update attendance record")
    db.log_audit(actor, "CORRECT_WORKER_ATTENDANCE", "WorkerAttendance", attendance_id, reason=f"Changed status from {field(existing, 'status')} to {new_status}: {req.notes}")
    return {**existing, **updates}


@router.delete("/attendance/{attendance_id}")
async def delete_duplicate_attendance(attendance_id: str, user: dict = Depends(get_current_user)):
    """Owner audited cleanup workflow for duplicate attendance records."""
    actor, _ = require_owner(user)
    require_persistent_store()
    records = db.get_records("WorkerAttendance", fresh=True) or []
    existing = next((r for r in records if str(field(r, "attendance_id")).strip() == attendance_id.strip()), None)
    if not existing:
        raise HTTPException(404, "Attendance record not found")
    
    # Check if this record is indeed a duplicate (same worker and date exists)
    w_id = str(field(existing, "worker_id")).strip()
    a_dt = str(field(existing, "attendance_date")).strip()
    duplicates = [r for r in records if str(field(r, "worker_id")).strip() == w_id and str(field(r, "attendance_date")).strip() == a_dt]
    if len(duplicates) <= 1:
        raise HTTPException(400, "Cannot delete unique attendance record. Use update/correction workflow to adjust.")
    
    if not db.delete_record("WorkerAttendance", "attendance_id", attendance_id, raise_on_error=True):
        raise HTTPException(503, "Could not remove attendance record")
    db.log_audit(actor, "REMOVE_DUPLICATE_ATTENDANCE", "WorkerAttendance", attendance_id, reason=f"Removed duplicate attendance row for {field(existing, 'worker_name_snapshot')} on {a_dt}")
    return {"status": "DELETED", "attendance_id": attendance_id}


@router.get("/recipes")
async def recipes(user: dict = Depends(get_current_user)):
    require_production_access(user)
    return db.get_records("Recipes")


@router.post("/recipes")
async def save_recipe(req: RecipeSave, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
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
    require_production_access(user)
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
    require_production_access(user)
    return calculate_recipe_cost(req.items, req.expected_yield_kg)


# -------------------------------------------------------------
# Production Batches & Material Issue Lifecycle
# -------------------------------------------------------------

@router.get("/batches")
async def batches(user: dict = Depends(get_current_user)):
    require_production_access(user)
    return db.get_records("ProductionBatches")


@router.post("/batches")
async def create_batch(req: ProductionCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
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
        "batch_id": batch_id,
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
    
    # Also link to ApprovalRequests for Owner dashboard visibility
    try:
        from app.routers.approvals import create_approval_request
        create_approval_request(
            request_type="PRODUCTION_BATCH",
            target_user_id=batch_id,
            payload={
                "production_id": batch_id,
                "batch_id": batch_id,
                "product_id": req.product_id,
                "product_name": field(product, "product_name"),
                "net_quantity_kg": reconciliation["saleable_output_kg"],
                "recipe_id": req.recipe_id or "",
                "notes": req.notes,
            },
            requested_by=actor,
            requested_by_name=str(user.get("full_name") or actor),
        )
    except Exception as exc:
        logger.warning(f"Could not link ApprovalRequest for batch {batch_id}: {exc}")

    return rec


_BATCH_LOCKS: Dict[str, threading.RLock] = {}
_BATCH_LOCKS_GUARD = threading.Lock()


def get_batch_lock(production_id: str) -> threading.RLock:
    with _BATCH_LOCKS_GUARD:
        clean_id = str(production_id).strip()
        if clean_id not in _BATCH_LOCKS:
            _BATCH_LOCKS[clean_id] = threading.RLock()
        return _BATCH_LOCKS[clean_id]


def execute_material_issue(
    production_id: str,
    actor: str,
    notes: str = "",
    force_recipe_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Idempotent and recoverable raw-material issuance engine.
    Ensures:
    1. Single-flight process-local serialization per batch via get_batch_lock.
    2. Multi-process concurrency tracking via IncompleteTransactions.
    3. Re-entry safety: Returns ALREADY_ISSUED if already complete, without duplicating deductions.
    4. Partial-failure recovery: Resumes missing work after an interrupted issuance.
    5. Unit normalization (g -> kg, ml -> L) and duplicate recipe line aggregation.
    6. All-or-nothing stock pre-flight check before appending any new ledger rows.
    7. Recipe version consistency check: Blocks silent formulation drift on retries.
    8. Verification of ledger completeness before updating batch materials_issued status.
    """
    prod_id_clean = str(production_id or "").strip()
    if not prod_id_clean:
        raise HTTPException(400, "production_id is required")

    with get_batch_lock(prod_id_clean):
        # 1. Fetch batch
        batches = db.get_records("ProductionBatches", fresh=True)
        batch = next(
            (b for b in batches if str(field(b, "production_id", "batch_id", default="")).strip() == prod_id_clean),
            None
        )
        if not batch:
            raise HTTPException(404, f"Production batch '{prod_id_clean}' not found")

        prod_id = str(field(batch, "product_id", default="")).strip()
        prod_name = str(field(batch, "product_name_snapshot", default="")).strip()
        production_kg = float(field(batch, "net_quantity_kg", "saleable_output_kg", "quantity_kg", default=0) or 0)
        batch_recipe_id = str(field(batch, "recipe_id", default="")).strip()
        is_materials_issued = truthy(field(batch, "materials_issued"))
        existing_issue_txn_id = str(field(batch, "material_issue_txn_id", default="")).strip()

        # 2. Inspect existing consumption rows in RawMaterialLedger
        raw_ledger = db.get_records("RawMaterialLedger", fresh=True)
        existing_deductions = [
            x for x in raw_ledger
            if str(field(x, "production_id", default="")).strip() == prod_id_clean
            and str(field(x, "movement_type", default="")).strip().upper() == "PRODUCTION_CONSUMPTION"
        ]

        # 3. Identify and lock the recipe
        locked_recipe_id = force_recipe_id or batch_recipe_id
        if not locked_recipe_id and existing_deductions:
            for row in existing_deductions:
                row_notes = str(field(row, "notes", default=""))
                match = re.search(r'Recipe\s+([A-Za-z0-9_\-]+)', row_notes)
                if match:
                    locked_recipe_id = match.group(1).strip()
                    break

        all_recipes = db.get_records("Recipes", fresh=True)
        approved_recipes = [
            r for r in all_recipes
            if (
                (prod_id and str(field(r, "product_id", default="")).strip() == prod_id)
                or (prod_name and str(field(r, "product_name_snapshot", default="")).strip().lower() == prod_name.lower())
            )
            and truthy(field(r, "approved"))
        ]

        active_recipe = None
        if approved_recipes:
            active_recipe = sorted(approved_recipes, key=lambda r: int(float(field(r, "version", default=0) or 0)))[-1]
        else:
            master_match = next(
                (m for m in MASTER_RECIPES_DEFINITION if (prod_id and m.get("product_id") == prod_id) or m.get("product_name", "").strip().lower() == prod_name.lower()),
                None
            )
            if master_match:
                active_recipe = master_match

        if not active_recipe and not locked_recipe_id:
            raise HTTPException(400, "No approved recipe exists for this product. Save and approve recipe before issuing materials.")

        target_recipe = None
        if locked_recipe_id:
            target_recipe = next((r for r in all_recipes if str(field(r, "recipe_id", default="")).strip() == locked_recipe_id), None)
            if not target_recipe:
                target_recipe = next((m for m in MASTER_RECIPES_DEFINITION if m.get("recipe_id") == locked_recipe_id), None)

        if not target_recipe:
            target_recipe = active_recipe

        if not target_recipe:
            raise HTTPException(400, f"Referenced recipe '{locked_recipe_id}' could not be resolved.")

        # Check for recipe formulation conflict if partial deductions already exist
        current_active_id = str(field(active_recipe, "recipe_id", default="") or active_recipe.get("recipe_id", "")).strip() if active_recipe else ""
        target_recipe_id = str(field(target_recipe, "recipe_id", default="") or target_recipe.get("recipe_id", "")).strip()
        target_recipe_ver = str(field(target_recipe, "version", default="1") or target_recipe.get("version", "1")).strip()

        if existing_deductions and current_active_id and target_recipe_id != current_active_id:
            logger.warning("Recipe version mismatch for batch %s: locked=%s, active=%s", prod_id_clean, target_recipe_id, current_active_id)
            raise HTTPException(
                409,
                f"Recipe change detected: Batch {prod_id_clean} was initiated with recipe '{target_recipe_id}', "
                f"but active recipe for {prod_name or prod_id} is now '{current_active_id}'. "
                f"Cannot silently mix formulations during retry. Manual reconciliation required."
            )

        # 4. Parse and normalize recipe items
        raw_items = []
        if isinstance(target_recipe.get("items_json"), str):
            try:
                raw_items = json.loads(target_recipe["items_json"])
            except Exception as exc:
                logger.error("Failed to parse items_json for recipe %s: %s", target_recipe_id, exc)
                raw_items = []
        elif isinstance(target_recipe.get("items"), list):
            raw_items = target_recipe["items"]

        if not raw_items:
            raise HTTPException(400, f"Recipe '{target_recipe_id}' contains no ingredient items.")

        raw_master = db.get_records("RawMaterials", fresh=True)
        aggregated: Dict[str, Dict[str, Any]] = {}

        for item in raw_items:
            item_name = str(item.get("material_name", "")).strip()
            if not item_name:
                continue

            mat_row = next(
                (r for r in raw_master
                 if str(field(r, "material_name", "raw_material_name", "name", default="")).strip().lower() == item_name.lower()
                 or str(field(r, "raw_material_id", default="")).strip().lower() == item_name.lower()),
                None
            )
            if not mat_row:
                raise HTTPException(400, f"Raw material '{item_name}' is missing from RawMaterials master. Add it before issuing materials.")

            raw_mat_id = str(field(mat_row, "raw_material_id", default="")).strip() or item_name
            canonical_name = str(field(mat_row, "material_name", default=item_name)).strip()
            stock_unit = str(field(mat_row, "unit", default="kg")).strip()

            if item.get("quantity_per_kg") is not None:
                item_qty_per_kg = float(item["quantity_per_kg"] or 0)
                item_unit = str(item.get("unit", stock_unit)).strip()
            elif item.get("quantity") is not None:
                exp_yield = float(field(target_recipe, "expected_yield_kg", default=1.2) or 1.2)
                item_qty_per_kg = float(item["quantity"] or 0) / exp_yield if exp_yield > 0 else float(item["quantity"] or 0)
                item_unit = str(item.get("unit", stock_unit)).strip()
            else:
                item_qty_per_kg = 0.0
                item_unit = stock_unit

            # Standard unit conversions
            iu_low = item_unit.lower()
            su_low = stock_unit.lower()
            if iu_low in {"g", "gram", "grams", "ml", "milliliter", "milliliters", "millilitres"}:
                if su_low in {"kg", "kilogram", "kgs", "l", "liter", "litres", "litre"}:
                    item_qty_per_kg = item_qty_per_kg / 1000.0
            elif iu_low in {"kg", "kilogram", "kgs", "l", "liter", "litres", "litre"}:
                if su_low in {"g", "gram", "grams", "ml", "milliliter", "milliliters", "millilitres"}:
                    item_qty_per_kg = item_qty_per_kg * 1000.0

            required_qty = round(item_qty_per_kg * production_kg, 4)

            agg_key = raw_mat_id.lower()
            if agg_key not in aggregated:
                rate_info = get_latest_purchase_rate(canonical_name, raw_master, raw_ledger)
                aggregated[agg_key] = {
                    "raw_material_id": raw_mat_id,
                    "material_name": canonical_name,
                    "stock_unit": stock_unit,
                    "required_qty": 0.0,
                    "rate_per_unit": rate_info.get("rate_per_canonical_unit") or "",
                }
            aggregated[agg_key]["required_qty"] = round(aggregated[agg_key]["required_qty"] + required_qty, 4)

        # 5. Calculate remaining deductions (partial completion check)
        missing_plans: Dict[str, Dict[str, Any]] = {}
        for agg_key, plan in aggregated.items():
            existing_for_mat = [
                x for x in existing_deductions
                if str(field(x, "raw_material_id", default="")).strip().lower() == agg_key
                or str(field(x, "material_name", default="")).strip().lower() == plan["material_name"].lower()
            ]
            already_deducted = round(sum(float(field(x, "quantity", default=0) or 0) for x in existing_for_mat), 4)
            total_required = round(plan["required_qty"], 4)
            needed = round(total_required - already_deducted, 4)

            if already_deducted > total_required + 0.001:
                raise HTTPException(
                    409,
                    f"Deduction anomaly for '{plan['material_name']}': already deducted {already_deducted} {plan['stock_unit']}, "
                    f"exceeding required {total_required} {plan['stock_unit']}. Manual reconciliation required."
                )

            if needed > 0.0001:
                missing_plans[agg_key] = {
                    **plan,
                    "already_deducted_qty": already_deducted,
                    "needed_qty": needed,
                }

        # 6. If no deductions needed:
        if not missing_plans:
            if not is_materials_issued:
                issue_txn_id = existing_issue_txn_id or f"RML-ISSUE-{prod_id_clean}"
                try:
                    db.update_record("ProductionBatches", "production_id", prod_id_clean, {
                        "materials_issued": "true",
                        "material_issue_txn_id": issue_txn_id,
                        "recipe_id": target_recipe_id,
                        "recipe_version": str(target_recipe_ver),
                    }, raise_on_error=True)
                except Exception as recov_exc:
                    logger.error("Failed to update status on recovery for %s: %s", prod_id_clean, recov_exc)
                    raise HTTPException(503, "Could not update batch status during recovery. Safe to retry.")
                db.log_audit(actor, "RECOVER_RAW_MATERIALS_STATUS", "ProductionBatches", prod_id_clean, reason="Marked materials_issued after verifying complete ledger entries.")

            return {
                "status": "ALREADY_ISSUED",
                "production_id": prod_id_clean,
                "material_issue_txn_id": existing_issue_txn_id or f"RML-ISSUE-{prod_id_clean}",
                "issued_items_count": len(existing_deductions),
                "message": "Raw materials were already issued for this batch. No duplicate deduction made.",
            }

        # 7. Pre-flight stock availability check for all remaining items
        for agg_key, plan in missing_plans.items():
            name = plan["material_name"]
            needed = plan["needed_qty"]
            stock_bal = calculate_raw_material_balance(name, raw_master, raw_ledger, exclude_production_id=prod_id_clean)
            current_avail = round(stock_bal["available"] - plan["already_deducted_qty"], 4)
            if current_avail < needed:
                raise HTTPException(
                    400,
                    f"Insufficient stock for {name}: need {needed} {plan['stock_unit']}, available {max(0.0, current_avail)}."
                )

        # 8. Record in-flight intent in IncompleteTransactions
        issue_txn_id = existing_issue_txn_id or f"RML-ISSUE-{prod_id_clean}"
        idempotency_key = f"RAW_ISSUE_{prod_id_clean}"
        try:
            db.append_record("IncompleteTransactions", {
                "transaction_id": make_id("IncompleteTransactions"),
                "transaction_type": "RAW_MATERIAL_ISSUE",
                "idempotency_key": idempotency_key,
                "status": "IN_PROGRESS",
                "payload_json": json.dumps({"production_id": prod_id_clean, "recipe_id": target_recipe_id, "needed": {k: p["needed_qty"] for k, p in missing_plans.items()}}),
                "error_details": "",
                "created_at": now(),
                "updated_at": now(),
                "resolved_by": "",
                "resolved_at": "",
            })
        except Exception as exc:
            logger.debug("Non-fatal: IncompleteTransactions logging bypassed: %s", exc)

        # 9. Append missing deduction rows
        appended_rows = []
        try:
            for agg_key, plan in missing_plans.items():
                needed = plan["needed_qty"]
                if needed <= 0:
                    continue

                mat_clean = re.sub(r'[^a-zA-Z0-9]', '', plan['raw_material_id'] or plan['material_name'])[:10]
                existing_count = len([x for x in existing_deductions if str(field(x, "raw_material_id", default="")).strip().lower() == agg_key])
                suffix = f"-{existing_count + 1}" if existing_count > 0 else ""
                txn_id = f"RML-{prod_id_clean}-{mat_clean}{suffix}"

                row = {
                    "raw_material_txn_id": txn_id,
                    "txn_datetime": now(),
                    "material_name": plan["material_name"],
                    "raw_material_id": plan["raw_material_id"],
                    "movement_type": "PRODUCTION_CONSUMPTION",
                    "quantity": needed,
                    "unit": plan["stock_unit"],
                    "rate_per_unit": plan["rate_per_unit"],
                    "production_id": prod_id_clean,
                    "issue_txn_id": issue_txn_id,
                    "created_by": actor,
                    "notes": f"Batch {prod_id_clean} material issue under Recipe {target_recipe_id} (v{target_recipe_ver})",
                }
                if not db.append_record("RawMaterialLedger", row, raise_on_error=True):
                    raise RuntimeError(f"Could not record raw material deduction for '{plan['material_name']}' in ledger.")
                appended_rows.append(row)
        except Exception as exc:
            logger.error("Error during raw material deduction appends for batch %s: %s", prod_id_clean, exc)
            try:
                db.append_record("IncompleteTransactions", {
                    "transaction_id": make_id("IncompleteTransactions"),
                    "transaction_type": "RAW_MATERIAL_ISSUE",
                    "idempotency_key": idempotency_key,
                    "status": "PARTIAL_FAILED",
                    "payload_json": json.dumps({"production_id": prod_id_clean, "appended_count": len(appended_rows)}),
                    "error_details": str(exc),
                    "created_at": now(),
                    "updated_at": now(),
                    "resolved_by": "",
                    "resolved_at": "",
                })
            except Exception:
                pass
            raise HTTPException(503, f"Raw material deduction interrupted: {exc}. Safe to retry; existing deductions are preserved.")

        # 10. Post-deduction verification
        raw_ledger_after = db.get_records("RawMaterialLedger", fresh=True)
        all_deductions_after = [
            x for x in raw_ledger_after
            if str(field(x, "production_id", default="")).strip() == prod_id_clean
            and str(field(x, "movement_type", default="")).strip().upper() == "PRODUCTION_CONSUMPTION"
        ]

        for agg_key, plan in aggregated.items():
            total_deducted = round(sum(
                float(field(x, "quantity", default=0) or 0)
                for x in all_deductions_after
                if str(field(x, "raw_material_id", default="")).strip().lower() == agg_key
                or str(field(x, "material_name", default="")).strip().lower() == plan["material_name"].lower()
            ), 4)
            if abs(total_deducted - plan["required_qty"]) > 0.001:
                raise HTTPException(
                    503,
                    f"Material issuance verification failed for '{plan['material_name']}': "
                    f"deducted {total_deducted} != required {plan['required_qty']}. Safe to retry."
                )

        # 11. Update batch materials_issued status
        batch_updates = {
            "materials_issued": "true",
            "material_issue_txn_id": issue_txn_id,
            "recipe_id": target_recipe_id,
            "recipe_version": str(target_recipe_ver),
        }
        try:
            saved = db.update_record("ProductionBatches", "production_id", prod_id_clean, batch_updates, raise_on_error=True)
            if not saved:
                saved = db.update_record("ProductionBatches", "batch_id", prod_id_clean, batch_updates, raise_on_error=True)
        except Exception as upd_exc:
            logger.error("Failed to update ProductionBatches for %s: %s", prod_id_clean, upd_exc)
            saved = False

        if not saved:
            raise HTTPException(
                503,
                "Material deductions succeeded and verified, but failed to update batch status. "
                "Safe to retry; retry will update status without duplicating deductions."
            )

        try:
            db.append_record("IncompleteTransactions", {
                "transaction_id": make_id("IncompleteTransactions"),
                "transaction_type": "RAW_MATERIAL_ISSUE",
                "idempotency_key": idempotency_key,
                "status": "COMPLETED",
                "payload_json": json.dumps({"production_id": prod_id_clean, "issue_txn_id": issue_txn_id}),
                "error_details": "",
                "created_at": now(),
                "updated_at": now(),
                "resolved_by": actor,
                "resolved_at": now(),
            })
        except Exception:
            pass

        db.log_audit(actor, "ISSUE_RAW_MATERIALS", "ProductionBatches", prod_id_clean, reason=f"Issued raw materials for {production_kg} kg papad under Recipe {target_recipe_id}")

        return {
            "status": "MATERIALS_ISSUED",
            "production_id": prod_id_clean,
            "material_issue_txn_id": issue_txn_id,
            "recipe_id": target_recipe_id,
            "recipe_version": target_recipe_ver,
            "deductions_appended": len(appended_rows),
            "total_items_issued": len(aggregated),
            "deductions": [
                {
                    "material_name": r["material_name"],
                    "raw_material_id": r["raw_material_id"],
                    "quantity": r["required_qty"],
                    "unit": r["stock_unit"],
                    "rate_per_unit": r["rate_per_unit"],
                }
                for r in aggregated.values()
            ],
        }


@router.post("/batches/{production_id}/issue-materials")
async def issue_materials(
    production_id: str,
    user: Any = Depends(get_current_user),
    req: Optional[MaterialIssueRequest] = None,
):
    """
    Issue raw materials to a production batch.
    Deducts raw materials exactly once, snapshots purchase rates, and assigns a unique transaction ID.
    Idempotent and recoverable:
    - Re-calling for an already issued batch returns ALREADY_ISSUED without re-deducting.
    - Interrupted / partially issued batches resume missing items without duplicating.
    - Pre-flight stock check verifies full remaining requirement before any write.
    """
    actual_user = user
    notes = ""
    if isinstance(user, MaterialIssueRequest):
        notes = user.notes
        actual_user = req if req is not None else {}
    elif req is not None:
        notes = req.notes

    actor, _ = require_production_access(actual_user)
    require_persistent_store()
    return execute_material_issue(production_id, actor, notes=notes)


@router.post("/batches/{production_id}/approval")
async def approve_batch(production_id: str, req: ApprovalRequest, user: dict = Depends(get_current_user)):
    """
    Approve production batch.
    - If materials were already issued, DO NOT deduct them again.
    - If not issued, issues them idempotently.
    - Crediting bulk output to inventory occurs exactly once.
    """
    actor, _ = require_owner(user)
    require_persistent_store()

    prod_id_clean = str(production_id or "").strip()
    with get_batch_lock(prod_id_clean):
        batches = db.get_records("ProductionBatches", fresh=True)
        rec = next(
            (b for b in batches if str(field(b, "production_id", "batch_id", default="")).strip() == prod_id_clean),
            None
        )
        if not rec:
            raise HTTPException(404, f"Production batch '{production_id}' not found")

        current_status = str(field(rec, "status", default="PENDING")).upper()
        if current_status != "PENDING":
            raise HTTPException(409, "This batch has already been reviewed")

        if not req.approved:
            updates = {"status": "REJECTED", "approved_by": actor, "approved_at": now(), "approval_notes": req.notes}
            saved = db.update_record("ProductionBatches", "production_id", prod_id_clean, updates)
            if not saved:
                saved = db.update_record("ProductionBatches", "batch_id", prod_id_clean, updates)
            if not saved:
                raise HTTPException(503, "Rejection was not saved.")
            
            # Also sync corresponding ApprovalRequests
            try:
                for app_req in db.get_records("ApprovalRequests"):
                    if str(app_req.get("target_user_id", "")).strip() == prod_id_clean and str(app_req.get("status", "")).upper() == "PENDING":
                        db.update_record("ApprovalRequests", "request_id", str(app_req.get("request_id")), {
                            "status": "REJECTED",
                            "decided_by": actor,
                            "decided_at": now(),
                            "decision_notes": req.notes or "Rejected by Owner",
                        })
            except Exception as sync_err:
                logger.warning(f"Could not sync ApprovalRequest rejection for batch {prod_id_clean}: {sync_err}")

            db.log_audit(actor, "REJECT_PRODUCTION", "ProductionBatches", prod_id_clean, reason=req.notes)
            return {**rec, **updates}

        # Ensure materials are issued idempotently and recoverably
        is_issued = truthy(field(rec, "materials_issued"))
        if not is_issued:
            execute_material_issue(prod_id_clean, actor)

        production_kg = float(field(rec, "net_quantity_kg", "saleable_output_kg", "quantity_kg", default=0) or 0)

        # Post bulk output to inventory exactly once
        existing_bulk = next((x for x in db.get_records("ProductionStockLedger", fresh=True) if str(field(x, "reference_id")) == prod_id_clean and str(field(x, "movement_type")).upper() == "BULK_PRODUCED"), None)
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
                "reference_id": prod_id_clean,
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
            "materials_issued": "true",
        }
        saved = db.update_record("ProductionBatches", "production_id", prod_id_clean, updates)
        if not saved:
            saved = db.update_record("ProductionBatches", "batch_id", prod_id_clean, updates)
        if not saved:
            raise HTTPException(503, "Batch status could not be saved. Existing ledger entries remain safe.")

        # Also sync corresponding ApprovalRequests
        try:
            for app_req in db.get_records("ApprovalRequests"):
                if str(app_req.get("target_user_id", "")).strip() == prod_id_clean and str(app_req.get("status", "")).upper() == "PENDING":
                    db.update_record("ApprovalRequests", "request_id", str(app_req.get("request_id")), {
                        "status": "EXECUTED",
                        "decided_by": actor,
                        "decided_at": now(),
                        "executed_at": now(),
                        "decision_notes": req.notes or "Approved by Owner",
                    })
        except Exception as sync_err:
            logger.warning(f"Could not sync ApprovalRequest for batch {prod_id_clean}: {sync_err}")

        db.log_audit(actor, "APPROVE_PRODUCTION", "ProductionBatches", prod_id_clean, reason=f"Approved {production_kg} kg and credited bulk inventory.")
        return {**rec, **updates}


# -------------------------------------------------------------
# Packaging Batches with Discrepancy Blocking
# -------------------------------------------------------------

@router.get("/packaging")
async def packaging(user: dict = Depends(get_current_user)):
    require_production_access(user)
    return db.get_records("PackagingBatches")


@router.post("/packaging")
async def create_packaging(req: PackagingCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_production_access(user)
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
            # Reject conflicting reuse of idempotency reference
            old_pid = str(field(existing_pack, "product_id", default="")).strip()
            old_bulk = float(field(existing_pack, "bulk_kg_used", default=0) or 0)
            old_p200 = int(float(field(existing_pack, "packets_200g", default=0) or 0))
            old_p500 = int(float(field(existing_pack, "packets_500g", default=0) or 0))
            old_p1000 = int(float(field(existing_pack, "packets_1000g", default=0) or 0))

            if (old_pid != req.product_id.strip() or
                abs(old_bulk - req.bulk_kg_used) > 0.005 or
                old_p200 != req.packets_200g or
                old_p500 != req.packets_500g or
                old_p1000 != req.packets_1000g):
                raise HTTPException(
                    status_code=409,
                    detail="This packaging reference has already been used with conflicting payload data. Start a new packaging batch with a unique reference."
                )

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

    # Pre-validate all requested SKU products and assemble movements BEFORE writing to PackagingBatches
    all_products = db.get_records("Products")
    sku_movements = []
    for weight_g, packet_count in [(200, req.packets_200g), (500, req.packets_500g), (1000, req.packets_1000g)]:
        if packet_count <= 0:
            continue
        sku_product = next((p for p in all_products if str(field(p, "product_name")).strip().lower() == bulk_key and int(float(field(p, "pack_weight_g", default=0) or 0)) == weight_g and truthy(field(p, "active", default="true"))), None)
        if not sku_product:
            raise HTTPException(400, f"No active {weight_g} g SKU product found for '{field(product, 'product_name')}'. Please create/activate that pack-size product in Products before packaging.")
        sku_movements.append({
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

    movements = [{
        "movement_type": "BULK_PACKAGED",
        "quantity_kg": req.bulk_kg_used,
        "quantity_packets": 0,
        "channel": "FACTORY_BULK",
        "product_id": req.product_id,
        "bulk_product_key": bulk_key,
        "product_name_snapshot": field(product, "product_name"),
    }] + sku_movements

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


@router.post("/packaging/{packaging_id}/recover")
async def recover_packaging(packaging_id: str, user: dict = Depends(get_current_user)):
    """
    Recover an INCOMPLETE packaging batch by idempotently posting any missing stock movements.
    """
    actor, _ = require_production_access(user)
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

    # Check existing bulk deduction
    existing_bulk = next((m for m in ledger if str(field(m, "reference_id")) == packaging_id and str(field(m, "movement_type")).upper() == "BULK_PACKAGED"), None)
    if not existing_bulk and bulk_kg > 0:
        row = {
            "movement_id": make_id("ProductionStockLedger"),
            "txn_datetime": now(),
            "movement_type": "BULK_PACKAGED",
            "quantity_kg": bulk_kg,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
            "product_id": str(field(batch, "product_id")),
            "bulk_product_key": bulk_key,
            "product_name_snapshot": field(batch, "product_name_snapshot"),
            "reference_id": packaging_id,
            "created_by": actor,
            "notes": "Recovered bulk deduction for incomplete batch",
        }
        if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
            raise HTTPException(503, "Could not append recovered bulk movement.")

    # Check packet movements
    all_prods = db.get_records("Products")
    for weight_g, count in [(200, p200), (500, p500), (1000, p1000)]:
        if count <= 0:
            continue
        sku_prod = next((p for p in all_prods if str(field(p, "product_name")).strip().lower() == bulk_key and int(float(field(p, "pack_weight_g", default=0) or 0)) == weight_g and truthy(field(p, "active", default="true"))), None)
        if sku_prod:
            target_id = str(field(sku_prod, "product_id"))
            existing_sku = next((m for m in ledger if str(field(m, "reference_id")) == packaging_id and str(field(m, "product_id")) == target_id and str(field(m, "movement_type")).upper() == "PACKETS_PACKAGED"), None)
            if not existing_sku:
                row = {
                    "movement_id": make_id("ProductionStockLedger"),
                    "txn_datetime": now(),
                    "movement_type": "PACKETS_PACKAGED",
                    "quantity_kg": 0,
                    "quantity_packets": count,
                    "channel": "FACTORY_FINISHED",
                    "product_id": target_id,
                    "bulk_product_key": bulk_key,
                    "product_name_snapshot": field(sku_prod, "product_name"),
                    "sku_snapshot": field(sku_prod, "sku"),
                    "pack_weight_g": weight_g,
                    "reference_id": packaging_id,
                    "created_by": actor,
                    "notes": "Recovered packet movement for incomplete batch",
                }
                if not db.append_record("ProductionStockLedger", row, raise_on_error=True):
                    raise HTTPException(503, f"Could not append recovered {weight_g}g packet movement.")

    db.update_record("PackagingBatches", "packaging_id", packaging_id, {"status": "RECORDED", "notes": f"{field(batch, 'notes')} [RECOVERED]"})
    db.log_audit(actor, "RECOVER_PACKAGING", "PackagingBatches", packaging_id, reason="Recovered missing ledger movements for packaging batch")
    return {"status": "RECORDED", "packaging_id": packaging_id, "message": "Incomplete packaging movements recovered."}


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
    actor, _ = require_production_access(user)
    require_persistent_store()

    product = next((p for p in db.get_records("Products") if str(field(p, "product_id")) == req.product_id), None)
    if not product:
        raise HTTPException(404, "Product not found")
    if req.channel.upper() not in {"ECOMMERCE", "RETAIL", "SALESMAN", "WHOLESALE", "DISTRIBUTOR", "WAREHOUSE"}:
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
            # Reject conflicting reuse of idempotency reference
            old_pid = str(field(existing_disp, "product_id", default="")).strip()
            old_chan = str(field(existing_disp, "channel", default="")).strip().upper()
            old_dest = str(field(existing_disp, "destination", default="")).strip()
            old_qty = int(float(field(existing_disp, "quantity_packets", default=0) or 0))

            if (old_pid != req.product_id.strip() or
                old_chan != req.channel.strip().upper() or
                old_dest != (req.destination or "").strip() or
                old_qty != req.quantity_packets):
                raise HTTPException(
                    status_code=409,
                    detail="This dispatch reference has already been used with conflicting payload data. Start a new dispatch with a unique reference."
                )

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

            if req.channel.upper() == "WAREHOUSE":
                salesman_ledger = db.get_records("SalesmanStockLedger")
                existing_wh_mvt = next((m for m in salesman_ledger if str(field(m, "reference_id")) == disp_id and str(field(m, "txn_type")).upper() == "COMPANY_RECEIPT"), None)
                if not existing_wh_mvt:
                    if not db.append_record("SalesmanStockLedger", {
                        "stock_txn_id": make_id("SalesmanStockLedger"),
                        "txn_datetime": now(),
                        "salesman_user_id": "",
                        "product_id": req.product_id,
                        "sku_snapshot": field(product, "sku"),
                        "txn_type": "COMPANY_RECEIPT",
                        "quantity": req.quantity_packets,
                        "unit": "PACKET",
                        "pack_weight_g": int(float(field(product, "pack_weight_g", default=0) or 0)),
                        "related_sale_id": "",
                        "issued_by_user_id": actor,
                        "received_by_user_id": "WAREHOUSE",
                        "confirmed_by_user_id": actor,
                        "reference_id": disp_id,
                        "notes": f"Factory dispatch to Warehouse: {req.destination or 'Central Warehouse'} (Reconciled retry).",
                    }, raise_on_error=True):
                        raise HTTPException(503, "Warehouse stock movement failed during dispatch recovery.")

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

        if req.channel.upper() == "WAREHOUSE":
            if not db.append_record("SalesmanStockLedger", {
                "stock_txn_id": make_id("SalesmanStockLedger"),
                "txn_datetime": now(),
                "salesman_user_id": "",
                "product_id": req.product_id,
                "sku_snapshot": field(product, "sku"),
                "txn_type": "COMPANY_RECEIPT",
                "quantity": req.quantity_packets,
                "unit": "PACKET",
                "pack_weight_g": int(float(field(product, "pack_weight_g", default=0) or 0)),
                "related_sale_id": "",
                "issued_by_user_id": actor,
                "received_by_user_id": "WAREHOUSE",
                "confirmed_by_user_id": actor,
                "reference_id": disp_id,
                "notes": f"Factory dispatch to Warehouse: {req.destination or 'Central Warehouse'}. Internal stock transfer.",
            }, raise_on_error=True):
                raise RuntimeError("SalesmanStockLedger append returned False for WAREHOUSE dispatch")

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
    require_production_access(user)
    return db.get_records("ProductionDispatches")


# -------------------------------------------------------------
# Costing Endpoints
# -------------------------------------------------------------

@router.get("/costing/batch/{production_id}")
async def get_batch_costing(production_id: str, user: dict = Depends(get_current_user)):
    """
    Get attributable actual batch production cost from issued materials and attendance expenses.
    """
    require_production_access(user)
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
    require_production_access(user)
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
