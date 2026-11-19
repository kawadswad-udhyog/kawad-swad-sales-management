"""
Kawad Swad ERP — Blueprint v2.1 API Router (/api/v2).

Enforces:
- 12 exact role codes + default-deny module/action RBAC
- Confidential payroll/bank/personal field & endpoint gating
  (OWNER_ADMIN full; ACCOUNTS minimal advance-disbursement only; absent for PA & others)
- Filtered/searchable/paginated read APIs backed by Google Sheets
- Signed Apps Script Single-Write-Owner forwarding for governed mutations
  preserving client `nonce` unchanged
- Fail-closed report bindings for RPT_TrialBalance, RPT_StockStatus, RPT_SalesAndReceivables
- CA/Owner pending policy governance (PENDING_CA_APPROVAL)
"""

import json
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.accounting.journal_engine import validate_journal_lines
from app.apps_script_bridge import AppsScriptBridge, BridgeResult, apps_script_bridge
from app.auth import get_current_user, require_sheets_connection
from app.permissions import (
    TWELVE_ROLES,
    V2_ROLE_PERMISSIONS,
    filter_confidential_records,
    has_permission,
    is_owner,
    require_module_action,
    require_owner,
    require_roles,
    role_v2_of,
)
from app.schema_registry import (
    CONFIDENTIAL_TABS_NO_CACHE,
    DATABASE_GROUPS_15,
    DISCONTINUED_RETAIL_PACK_WEIGHTS_G,
    FORBIDDEN_SCRATCH_PREFIXES,
    GIG_WORKER_STATUSES,
    LOCKED_32_ID_PREFIXES,
    LOT_QUALITY_STATES,
    PENDING_OWNER_MAPPING_TABS,
    TAB_RECONCILIATION_CONFLICTS,
    VALID_RETAIL_PACK_WEIGHTS_G,
    assert_ca_policy_approved,
    get_ca_policies,
    get_table_schema_registry,
    is_forbidden_scratch_tab,
    quantize_money,
    quantize_weight_kg,
    set_ca_policy_override,
)
from app.sheets import db
from app.timeutil import now_iso

router = APIRouter(prefix="/api/v2", tags=["ERP v2 Blueprint"])


# ---------------------------------------------------------------------------
# Typed Request / Response Models
# ---------------------------------------------------------------------------
class V2ErrorDetail(BaseModel):
    status: str = "ERROR"
    error_code: str
    message: str
    correlation_id: str
    retryable: bool = False
    nonce: Optional[str] = None


class PolicyUpdateRequest(BaseModel):
    status: Literal["APPROVED", "PENDING_CA_APPROVAL"]
    value: Optional[str] = None
    notes: Optional[str] = ""
    nonce: Optional[str] = Field(None, min_length=8, max_length=128)


class GovernedPackagingCreateRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    packaging_date: Optional[str] = ""
    product_id: str = Field(..., min_length=2)
    bulk_batch_id: Optional[str] = ""
    lot_id: Optional[str] = ""
    bulk_kg_used: Decimal = Field(..., gt=0)
    packets_200g: int = Field(0, ge=0)
    packets_500g: int = Field(0, ge=0)
    packets_1000g: int = Field(0, ge=0)
    packing_loss_kg: Decimal = Field(Decimal("0.000"), ge=0)
    loss_reason: Optional[str] = ""
    notes: Optional[str] = ""


class GovernedDispatchCreateRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    dispatch_date: Optional[str] = ""
    product_id: str = Field(..., min_length=2)
    lot_id: str = Field(..., min_length=2)
    channel: Literal["WAREHOUSE", "VAN_ROUTE", "DISTRIBUTOR", "WHOLESALE", "RETAIL", "ECOMMERCE"]
    destination: str = Field(..., min_length=2)
    van_number: Optional[str] = ""
    salesman_user_id: Optional[str] = ""
    quantity_packets: int = Field(..., gt=0)
    notes: Optional[str] = ""


class GovernedMarketplaceSettlementRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    channel_name: str = Field(..., min_length=2)
    settlement_ref: str = Field(..., min_length=2)
    settlement_date: Optional[str] = ""
    gross_sales_amount: Decimal = Field(..., ge=0)
    marketplace_fees: Decimal = Field(Decimal("0.00"), ge=0)
    net_settlement_amount: Decimal = Field(..., ge=0)
    apply_automated_gst_posting: bool = False
    notes: Optional[str] = ""


class GovernedComplianceRecordRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    record_type: Literal["FSSAI_AUDIT", "HYGIENE_LOG", "STATUTORY_FILING", "EQUIPMENT_CALIBRATION", "CORRECTIVE_ACTION"]
    title: str = Field(..., min_length=3)
    due_date: Optional[str] = ""
    status: Literal["OPEN", "VERIFIED", "EXPIRED"] = "OPEN"
    notes: Optional[str] = ""


class GovernedAssetMaintenanceRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    asset_code: str = Field(..., min_length=2)
    asset_name: str = Field(..., min_length=2)
    maintenance_type: Literal["PREVENTIVE", "BREAKDOWN", "INSPECTION"] = "PREVENTIVE"
    cost_amount: Decimal = Field(Decimal("0.00"), ge=0)
    scheduled_date: Optional[str] = ""
    notes: Optional[str] = ""


class GigWorkSubmitRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    worker_id: str = Field(..., min_length=2)
    work_date: Optional[str] = ""
    batch_id: Optional[str] = ""
    activity_name: str = Field(..., min_length=2)
    units_completed: Decimal = Field(..., gt=0)
    unit_of_measure: Literal["KG", "SHIFT", "PACKET", "HOUR"] = "KG"
    piece_rate: Decimal = Field(..., ge=0)
    notes: Optional[str] = ""


class GigWorkTransitionRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    payment_method: Optional[str] = "CASH"
    payment_reference: Optional[str] = ""
    notes: Optional[str] = ""


class AdvanceDisburseRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    payment_method: Literal["BANK_TRANSFER", "UPI", "CASH"] = "BANK_TRANSFER"
    payment_reference: str = Field(..., min_length=2)
    notes: Optional[str] = ""


class GovernedPurchaseOrderRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    supplier_id: str = Field(..., min_length=2)
    supplier_name: Optional[str] = ""
    order_date: Optional[str] = ""
    expected_delivery_date: Optional[str] = ""
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    total_amount: Decimal = Field(..., ge=0)
    notes: Optional[str] = ""


class GovernedGoodsReceiptRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    po_id: Optional[str] = ""
    supplier_id: str = Field(..., min_length=2)
    supplier_name: Optional[str] = ""
    receipt_date: Optional[str] = ""
    invoice_number: Optional[str] = ""
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    freight_amount: Decimal = Field(Decimal("0.00"), ge=0)
    gst_amount: Decimal = Field(Decimal("0.00"), ge=0)
    notes: Optional[str] = ""


class GovernedStockAdjustmentRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    product_id: str = Field(..., min_length=2)
    ledger_type: Literal["RAW_MATERIAL", "PRODUCTION_STOCK", "FINISHED_GOODS"] = "FINISHED_GOODS"
    adjustment_qty: Decimal = Field(...)
    reason: str = Field(..., min_length=3)
    notes: Optional[str] = ""


class GovernedMillingBatchRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    milling_date: Optional[str] = ""
    source_material_id: str = Field(..., min_length=2)
    source_material_name: Optional[str] = ""
    input_quantity_kg: Decimal = Field(..., gt=0)
    flour_output_kg: Decimal = Field(..., gt=0)
    milling_expenses: Decimal = Field(Decimal("0.00"), ge=0)
    notes: Optional[str] = ""


class GovernedProductionBatchRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    production_date: Optional[str] = ""
    product_id: str = Field(..., min_length=2)
    recipe_id: Optional[str] = ""
    planned_quantity_kg: Decimal = Field(..., gt=0)
    net_quantity_kg: Optional[Decimal] = Field(None, ge=0)
    shift: Optional[str] = "MORNING"
    notes: Optional[str] = ""


class GovernedSalesOrderRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    customer_id: str = Field(..., min_length=2)
    customer_name: Optional[str] = ""
    order_date: Optional[str] = ""
    delivery_date: Optional[str] = ""
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    notes: Optional[str] = ""


class GovernedSalesInvoiceRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    customer_id: str = Field(..., min_length=2)
    customer_name: Optional[str] = ""
    sale_date: Optional[str] = ""
    salesman_user_id: Optional[str] = ""
    so_id: Optional[str] = ""
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    payment_method: Literal["CASH", "UPI", "BANK_TRANSFER", "CREDIT"] = "CASH"
    cash_collected: Decimal = Field(Decimal("0.00"), ge=0)
    notes: Optional[str] = ""


class GovernedJournalLineInput(BaseModel):
    account_code: str = Field(..., min_length=2)
    debit_amount: Decimal = Field(Decimal("0.00"), ge=0)
    credit_amount: Decimal = Field(Decimal("0.00"), ge=0)
    entity_type: Optional[str] = ""
    entity_id: Optional[str] = ""
    notes: Optional[str] = ""


class GovernedJournalVoucherRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)
    journal_date: Optional[str] = ""
    voucher_type: str = Field("JOURNAL", min_length=2)
    reference_type: str = Field(..., min_length=2)
    reference_id: str = Field(..., min_length=1)
    narration: str = Field(..., min_length=3)
    lines: List[GovernedJournalLineInput] = Field(..., min_length=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _raise_storage_error(exc: Exception, source_tab: str) -> None:
    corr = f"CORR-{uuid.uuid4().hex[:10].upper()}"
    msg = str(exc)
    if "not found" in msg.lower() or "worksheetnotfound" in exc.__class__.__name__.lower():
        raise HTTPException(
            status_code=503,
            detail={
                "status": "UNAVAILABLE",
                "error_code": "WORKSHEET_NOT_MAPPED_OR_MISSING",
                "message": (
                    f"Tab '{source_tab}' is not present or awaiting owner header mapping (PENDING_OWNER_MAPPING). "
                    "Read failed closed cleanly without guessing columns or creating unverified tabs."
                ),
                "correlation_id": corr,
                "retryable": False,
            },
        )
    raise HTTPException(
        status_code=503,
        detail={
            "status": "STORAGE_UNAVAILABLE",
            "error_code": "GOOGLE_SHEETS_UNAVAILABLE",
            "message": f"Google Sheets storage is unavailable while reading '{source_tab}': {msg}",
            "correlation_id": corr,
            "retryable": True,
        },
    )


def _handle_bridge_result(res: BridgeResult) -> Dict[str, Any]:
    if res.status == "CONFIRMED":
        return {
            "status": "CONFIRMED",
            "correlation_id": res.correlation_id,
            "nonce": res.nonce,
            "allocated_id": res.allocated_id,
            "record": res.record,
            "message": res.message,
        }
    raise HTTPException(
        status_code=res.http_status,
        detail={
            "status": res.status,
            "error_code": res.error_code or "GOVERNED_WRITE_NOT_CONFIRMED",
            "message": res.message,
            "correlation_id": res.correlation_id,
            "nonce": res.nonce,
            "retryable": res.retryable,
            "allocated_id": res.allocated_id,
        },
    )


def _safe_query_tab(
    tab_name: str,
    *,
    fresh: bool = True,
    search: str = "",
    filters: Optional[Dict[str, Any]] = None,
    date_field: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    if is_forbidden_scratch_tab(tab_name):
        raise HTTPException(
            status_code=403,
            detail={
                "status": "FORBIDDEN",
                "error_code": "SCRATCH_TAB_FORBIDDEN",
                "message": f"Access to legacy scratch tab '{tab_name}' is strictly prohibited.",
                "correlation_id": f"CORR-{uuid.uuid4().hex[:10].upper()}",
                "retryable": False,
            },
        )
    try:
        return db.query_records(
            tab_name,
            fresh=fresh,
            search=search,
            filters=filters,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        _raise_storage_error(exc, tab_name)


# ---------------------------------------------------------------------------
# Meta, Capabilities & CA Policies
# ---------------------------------------------------------------------------
@router.get("/meta/capabilities")
async def get_erp_capabilities(current_user: dict = Depends(get_current_user)):
    v2_role = role_v2_of(current_user)
    matrix = V2_ROLE_PERMISSIONS.get(v2_role, {})
    return {
        "role": v2_role,
        "all_roles": list(TWELVE_ROLES),
        "module_permissions": matrix,
        "database_groups": DATABASE_GROUPS_15,
        "locked_id_prefixes": LOCKED_32_ID_PREFIXES,
        "valid_retail_pack_weights_g": list(VALID_RETAIL_PACK_WEIGHTS_G),
        "discontinued_retail_pack_weights_g": list(DISCONTINUED_RETAIL_PACK_WEIGHTS_G),
        "lot_quality_states": list(LOT_QUALITY_STATES),
        "gig_worker_statuses": list(GIG_WORKER_STATUSES),
        "apps_script_bridge_configured": apps_script_bridge.is_configured(),
        "google_sheets_connected": bool(db.is_connected),
        "persistent_writes_enabled": bool(db.is_connected and db.spreadsheet is not None and apps_script_bridge.is_configured()),
        "pending_ca_policies": get_ca_policies(),
    }


@router.get("/meta/schema-registry")
async def get_schema_registry_metadata(current_user: dict = Depends(get_current_user)):
    require_module_action(current_user, "control", "view")
    table_registry = get_table_schema_registry()
    owner_user = is_owner(current_user)
    if owner_user:
        exposed_registry = table_registry
    else:
        exposed_registry = {
            tab: (
                {**meta, "headers": "REDACTED_NON_OWNER"}
                if meta.get("confidential") and meta.get("headers") is not None
                else meta
            )
            for tab, meta in table_registry.items()
        }
    status_counts: Dict[str, int] = {}
    for meta in table_registry.values():
        st = str(meta.get("status", "UNKNOWN"))
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "cleaned_tab_baseline": 255,
        "database_groups": DATABASE_GROUPS_15,
        "locked_32_id_prefixes": LOCKED_32_ID_PREFIXES,
        "forbidden_scratch_prefixes": list(FORBIDDEN_SCRATCH_PREFIXES),
        "confidential_no_cache_tabs": sorted(CONFIDENTIAL_TABS_NO_CACHE) if owner_user else ["REDACTED_NON_OWNER"],
        "pending_owner_mapping_tabs": sorted(PENDING_OWNER_MAPPING_TABS),
        "tab_reconciliation_conflicts": TAB_RECONCILIATION_CONFLICTS,
        "table_registry_summary": {
            "total_catalogued_tabs": len(table_registry),
            "status_counts": status_counts,
        },
        "table_schema_registry": exposed_registry,
    }


@router.get("/meta/policies")
async def list_ca_policies(current_user: dict = Depends(get_current_user)):
    require_roles(current_user, {"OWNER_ADMIN", "PA", "ACCOUNTS", "AUDITOR"})
    return {
        "policies": get_ca_policies(),
        "timestamp": now_iso(),
    }


@router.put("/meta/policies/{policy_key}", dependencies=[Depends(require_sheets_connection)])
async def update_ca_policy(
    policy_key: str,
    req: PolicyUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    actor_id, v2_role = require_owner(current_user)
    policies = get_ca_policies()
    if policy_key not in policies:
        raise HTTPException(status_code=422, detail=f"Unknown policy_key: {policy_key}")
    allowed = policies[policy_key].get("allowed_values", [])
    if req.status == "APPROVED" and req.value not in allowed:
        raise HTTPException(status_code=422, detail=f"Approved value for {policy_key} must be one of {allowed}")

    client_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    if not client_nonce:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "REJECTED",
                "error_code": "MISSING_IDEMPOTENCY_NONCE",
                "message": "Client idempotency nonce (body nonce or X-KS-Idempotency-Key header) is required.",
                "retryable": False,
            },
        )
    setting_key = f"CA_POLICY_{policy_key.upper()}"
    setting_value = json.dumps(
        {
            "policy_key": policy_key,
            "status": req.status,
            "value": req.value,
            "approved_by": actor_id,
            "notes": req.notes or "",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    res = apps_script_bridge.execute_governed_write(
        action="UPDATE_CA_POLICY",
        target_tab="Settings",
        payload={
            "setting_key": setting_key,
            "setting_value": setting_value,
            "description": (req.notes or policies[policy_key].get("label") or policy_key).strip(),
            "policy_key": policy_key,
            "status": req.status,
            "value": req.value,
            "approved_by": actor_id,
            "notes": req.notes or "",
        },
        nonce=client_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="setting_key",
        invalidate_tabs=["Settings"],
    )
    handled = _handle_bridge_result(res)
    try:
        updated = set_ca_policy_override(
            policy_key,
            status=req.status,
            value=req.value,
            approved_by=actor_id,
            notes=req.notes or "",
        )
        db.log_audit(actor_id, "UPDATE_CA_POLICY", "Settings", policy_key, new_val=f"{req.status}:{req.value}", reason=req.notes or "")
        return {"ok": True, "policy": updated, **handled}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Official Reports (RPT_TrialBalance, RPT_StockStatus, RPT_SalesAndReceivables)
# ---------------------------------------------------------------------------
def _read_official_report_tab(tab_name: str, report_title: str) -> Dict[str, Any]:
    try:
        rows = db.get_records(tab_name, fresh=True)
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "report_title": report_title,
            "source_tab": tab_name,
            "period": None,
            "generated_at": None,
            "balance_status": "UNAVAILABLE",
            "stale": True,
            "unavailable_reason": f"Sheet '{tab_name}' unavailable or pending owner mapping: {exc}",
            "rows": [],
            "row_count": 0,
        }

    period = None
    generated_at = None
    balance_status = "REPORTED"
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")

    if rows:
        first = rows[0]
        period = first.get("period") or first.get("period_month") or first.get("as_of_date") or ""
        generated_at = first.get("generated_at") or first.get("updated_at") or first.get("timestamp") or ""
        if tab_name == "RPT_TrialBalance":
            for r in rows:
                d_val = r.get("debit") if r.get("debit") is not None else r.get("debit_amount")
                c_val = r.get("credit") if r.get("credit") is not None else r.get("credit_amount")
                try:
                    total_debit += quantize_money(d_val or 0)
                    total_credit += quantize_money(c_val or 0)
                except Exception:
                    pass
            balance_status = "BALANCED" if abs(total_debit - total_credit) <= Decimal("0.01") else "UNBALANCED"

    return {
        "status": "AVAILABLE" if rows else "EMPTY",
        "report_title": report_title,
        "source_tab": tab_name,
        "period": period or "CURRENT",
        "generated_at": generated_at or None,
        "balance_status": balance_status,
        "total_debit": str(total_debit) if tab_name == "RPT_TrialBalance" else None,
        "total_credit": str(total_credit) if tab_name == "RPT_TrialBalance" else None,
        "stale": False if rows else True,
        "unavailable_reason": None if rows else f"No pre-computed rows found in '{tab_name}'. Run Apps Script closing report generator.",
        "rows": rows,
        "row_count": len(rows),
    }


@router.get("/reports/trial-balance")
async def get_v2_trial_balance_report(current_user: dict = Depends(get_current_user)):
    require_module_action(current_user, "reports", "view")
    return _read_official_report_tab("RPT_TrialBalance", "Official Trial Balance")


@router.get("/reports/stock-status")
async def get_v2_stock_status_report(current_user: dict = Depends(get_current_user)):
    require_module_action(current_user, "reports", "view")
    return _read_official_report_tab("RPT_StockStatus", "Official Warehouse & Factory Stock Status")


@router.get("/reports/sales-receivables")
async def get_v2_sales_receivables_report(current_user: dict = Depends(get_current_user)):
    require_module_action(current_user, "reports", "view")
    return _read_official_report_tab("RPT_SalesAndReceivables", "Official Sales & Receivables Aging")


# ---------------------------------------------------------------------------
# Packaging & Quality-Gated Dispatch / Logistics
# ---------------------------------------------------------------------------
@router.get("/packaging/batches")
async def list_v2_packaging_batches(
    search: str = Query(""),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "packaging", "view")
    return _safe_query_tab(
        "PackagingBatches",
        fresh=True,
        search=search,
        filters={"status": status} if status else None,
        page=page,
        page_size=page_size,
    )


@router.post("/packaging/batches", dependencies=[Depends(require_sheets_connection)])
async def create_v2_packaging_batch(req: GovernedPackagingCreateRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "packaging", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)

    if (req.packets_200g + req.packets_500g + req.packets_1000g) <= 0:
        raise HTTPException(status_code=422, detail="At least one retail SKU quantity (200g, 500g, or 1000g) must be > 0.")

    # Enforce lot quality RELEASED gate before delegating write to Apps Script
    lot_ref = str(req.lot_id or req.bulk_batch_id or "").strip()
    if lot_ref:
        try:
            lots = db.get_records("ProductLots", fresh=True)
            matched = [
                l for l in lots
                if str(l.get("lot_id", "")).strip() == lot_ref or str(l.get("production_id", "")).strip() == lot_ref
            ]
            blocked = next((l for l in matched if str(l.get("quality_status", "")).strip().upper() != "RELEASED"), None)
            if blocked:
                raise HTTPException(
                    status_code=409,
                    detail=f"Packaging blocked: Lot '{blocked.get('lot_id')}' has quality_status='{blocked.get('quality_status')}'. Only RELEASED lots may be packaged.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            _raise_storage_error(exc, "ProductLots")

    res = apps_script_bridge.execute_governed_write(
        action="RECORD_PACKAGING_BATCH",
        target_tab="PackagingBatches",
        payload={
            "packaging_date": req.packaging_date or now_iso()[:10],
            "product_id": req.product_id.strip(),
            "bulk_batch_id": (req.bulk_batch_id or "").strip(),
            "lot_id": (req.lot_id or "").strip(),
            "bulk_kg_used": str(quantize_weight_kg(req.bulk_kg_used)),
            "packets_200g": req.packets_200g,
            "packets_500g": req.packets_500g,
            "packets_1000g": req.packets_1000g,
            "packing_loss_kg": str(quantize_weight_kg(req.packing_loss_kg)),
            "loss_reason": (req.loss_reason or "").strip(),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="packaging_id",
        invalidate_tabs=["PackagingBatches", "ProductionStockLedger", "ProductLots"],
    )
    return _handle_bridge_result(res)


@router.get("/logistics/dispatches")
async def list_v2_dispatches(
    search: str = Query(""),
    channel: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    if role_v2_of(current_user) == "FIELD_SALESMAN":
        # Field salesman sees only their own route dispatches / van passes
        res = _safe_query_tab(
            "VanLoadingPasses",
            fresh=True,
            search=search,
            filters={"salesman_user_id": current_user.get("user_id")},
            page=page,
            page_size=page_size,
        )
        return res
    require_module_action(current_user, "logistics", "view")
    return _safe_query_tab(
        "ProductionDispatches",
        fresh=True,
        search=search,
        filters={"channel": channel} if channel else None,
        page=page,
        page_size=page_size,
    )


@router.post("/logistics/dispatches", dependencies=[Depends(require_sheets_connection)])
async def create_v2_dispatch(req: GovernedDispatchCreateRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "logistics", "dispatch")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)

    # Enforce strict lot quality gate: block dispatch unless lot quality_status == "RELEASED"
    try:
        lots = db.get_records("ProductLots", fresh=True)
    except Exception as exc:
        _raise_storage_error(exc, "ProductLots")

    lot = next((l for l in lots if str(l.get("lot_id", "")).strip() == req.lot_id.strip() or str(l.get("lot_number", "")).strip() == req.lot_id.strip()), None)
    if not lot:
        raise HTTPException(status_code=404, detail=f"Product lot '{req.lot_id}' not found; dispatch cannot proceed without traceable RELEASED lot.")
    if str(lot.get("quality_status", "")).strip().upper() != "RELEASED":
        raise HTTPException(
            status_code=409,
            detail=f"Dispatch blocked: Lot '{lot.get('lot_id')}' quality_status is '{lot.get('quality_status')}'. Only RELEASED lots can be dispatched.",
        )

    res = apps_script_bridge.execute_governed_write(
        action="RECORD_DISTRIBUTION_DISPATCH",
        target_tab="ProductionDispatches",
        payload={
            "dispatch_date": req.dispatch_date or now_iso()[:10],
            "product_id": req.product_id.strip(),
            "lot_id": str(lot.get("lot_id")),
            "channel": req.channel,
            "destination": req.destination.strip(),
            "van_number": (req.van_number or "").strip(),
            "salesman_user_id": (req.salesman_user_id or "").strip(),
            "quantity_packets": req.quantity_packets,
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="dispatch_id",
        invalidate_tabs=["ProductionDispatches", "VanLoadingPasses", "ProductionStockLedger", "SalesmanStockLedger", "ProductLots"],
    )
    return _handle_bridge_result(res)


# ---------------------------------------------------------------------------
# E-Commerce & Marketplace Channel Settlements (Group 10)
# ---------------------------------------------------------------------------
@router.get("/channels/settlements")
async def list_marketplace_settlements(
    search: str = Query(""),
    channel_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "channels", "view")
    return _safe_query_tab(
        "MarketplaceSettlements",
        fresh=True,
        search=search,
        filters={"channel_name": channel_name} if channel_name else None,
        page=page,
        page_size=page_size,
    )


@router.post("/channels/settlements", dependencies=[Depends(require_sheets_connection)])
async def create_marketplace_settlement(req: GovernedMarketplaceSettlementRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "channels", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)

    if req.apply_automated_gst_posting:
        try:
            assert_ca_policy_approved("hsn_gst_tax_rates")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    res = apps_script_bridge.execute_governed_write(
        action="RECORD_MARKETPLACE_SETTLEMENT",
        target_tab="MarketplaceSettlements",
        payload={
            "channel_name": req.channel_name.strip(),
            "settlement_ref": req.settlement_ref.strip(),
            "settlement_date": req.settlement_date or now_iso()[:10],
            "gross_sales_amount": str(quantize_money(req.gross_sales_amount)),
            "marketplace_fees": str(quantize_money(req.marketplace_fees)),
            "net_settlement_amount": str(quantize_money(req.net_settlement_amount)),
            "apply_automated_gst_posting": req.apply_automated_gst_posting,
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="settlement_id",
        invalidate_tabs=["MarketplaceSettlements", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


# ---------------------------------------------------------------------------
# Compliance, Statutory & Assets / Maintenance (Group 13)
# ---------------------------------------------------------------------------
@router.get("/compliance/records")
async def list_compliance_records(
    search: str = Query(""),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "compliance_assets", "view")
    return _safe_query_tab(
        "ComplianceRecords",
        fresh=True,
        search=search,
        filters={"status": status} if status else None,
        page=page,
        page_size=page_size,
    )


@router.post("/compliance/records", dependencies=[Depends(require_sheets_connection)])
async def create_compliance_record(req: GovernedComplianceRecordRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "compliance_assets", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="RECORD_COMPLIANCE_ITEM",
        target_tab="ComplianceRecords",
        payload={
            "record_type": req.record_type,
            "title": req.title.strip(),
            "due_date": (req.due_date or "").strip(),
            "status": req.status,
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="compliance_id",
        invalidate_tabs=["ComplianceRecords"],
    )
    return _handle_bridge_result(res)


@router.get("/assets/maintenance")
async def list_asset_maintenance(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "compliance_assets", "view")
    return _safe_query_tab("AssetsMaintenance", fresh=True, search=search, page=page, page_size=page_size)


@router.post("/assets/maintenance", dependencies=[Depends(require_sheets_connection)])
async def create_asset_maintenance(req: GovernedAssetMaintenanceRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "compliance_assets", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="RECORD_ASSET_MAINTENANCE",
        target_tab="AssetsMaintenance",
        payload={
            "asset_code": req.asset_code.strip(),
            "asset_name": req.asset_name.strip(),
            "maintenance_type": req.maintenance_type,
            "cost_amount": str(quantize_money(req.cost_amount)),
            "scheduled_date": req.scheduled_date or now_iso()[:10],
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="maintenance_id",
        invalidate_tabs=["AssetsMaintenance"],
    )
    return _handle_bridge_result(res)


# ---------------------------------------------------------------------------
# Workforce Separation: Confidential Payroll vs Gig Worker Workflow
# ---------------------------------------------------------------------------
@router.get("/workforce/confidential/salary-payments")
async def list_confidential_salary_payments(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_owner(current_user)
    return _safe_query_tab("WorkforcePayments", fresh=True, search=search, page=page, page_size=page_size)


@router.get("/workforce/advances")
async def list_employee_advances(
    search: str = Query(""),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """
    Strictly confidential advances view:
    - OWNER_ADMIN: full view
    - ACCOUNTS: minimal disbursement view ONLY (never PA, HR, or AUDITOR)
    """
    require_roles(
        current_user,
        {"OWNER_ADMIN", "ACCOUNTS"},
        detail="EmployeeAdvances are strictly restricted to OWNER_ADMIN (and ACCOUNTS minimal disbursement view).",
    )
    raw_page = _safe_query_tab(
        "EmployeeAdvances",
        fresh=True,
        search=search,
        filters={"status": status} if status else None,
        page=page,
        page_size=page_size,
    )
    raw_page["items"] = filter_confidential_records(
        raw_page["items"],
        current_user,
        tab_name="EmployeeAdvances",
        workflow_context="APPROVED_ADVANCE_DISBURSEMENT",
    )
    return raw_page


@router.post("/workforce/advances/{advance_id}/disburse", dependencies=[Depends(require_sheets_connection)])
async def disburse_approved_employee_advance(
    advance_id: str,
    req: AdvanceDisburseRequest,
    current_user: dict = Depends(get_current_user),
    request: Request = None,
):
    """OWNER_ADMIN or ACCOUNTS may disburse ONLY pre-approved advances; delegates to Apps Script."""
    actor_id, v2_role = require_roles(
        current_user,
        {"OWNER_ADMIN", "ACCOUNTS"},
        detail="Only OWNER_ADMIN or ACCOUNTS may disburse approved advances.",
    )
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="DISBURSE_APPROVED_ADVANCE",
        target_tab="EmployeeAdvances",
        payload={
            "advance_id": advance_id.strip(),
            "payment_method": req.payment_method,
            "payment_reference": req.payment_reference.strip(),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="advance_id",
        invalidate_tabs=["EmployeeAdvances", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


@router.get("/workforce/gig-entries")
async def list_gig_worker_entries(
    search: str = Query(""),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_roles(current_user, {"OWNER_ADMIN", "PA", "HR", "PRODUCTION", "AUDITOR"})
    return _safe_query_tab(
        "LabourWorkEntries",
        fresh=True,
        search=search,
        filters={"status": status} if status else None,
        page=page,
        page_size=page_size,
    )


@router.post("/workforce/gig-entries", dependencies=[Depends(require_sheets_connection)])
async def submit_gig_worker_entry(req: GigWorkSubmitRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    """Gig worker production work entry submission -> SUBMITTED state via Apps Script."""
    actor_id, v2_role = require_roles(current_user, {"OWNER_ADMIN", "PA", "HR", "PRODUCTION"})
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="SUBMIT_GIG_WORK_ENTRY",
        target_tab="LabourWorkEntries",
        payload={
            "worker_id": req.worker_id.strip(),
            "work_date": req.work_date or now_iso()[:10],
            "batch_id": (req.batch_id or "").strip(),
            "activity_name": req.activity_name.strip(),
            "units_completed": str(quantize_weight_kg(req.units_completed)),
            "unit_of_measure": req.unit_of_measure,
            "piece_rate": str(quantize_money(req.piece_rate)),
            "status": "SUBMITTED",
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="entry_id",
        invalidate_tabs=["LabourWorkEntries"],
    )
    return _handle_bridge_result(res)


@router.post("/workforce/gig-entries/{entry_id}/verify", dependencies=[Depends(require_sheets_connection)])
async def verify_gig_worker_entry(entry_id: str, req: GigWorkTransitionRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    """Verify submitted gig work entry -> VERIFIED state via Apps Script."""
    actor_id, v2_role = require_roles(current_user, {"OWNER_ADMIN", "HR"})
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="VERIFY_GIG_WORK_ENTRY",
        target_tab="LabourWorkEntries",
        payload={
            "entry_id": entry_id.strip(),
            "target_status": "VERIFIED",
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="entry_id",
        invalidate_tabs=["LabourWorkEntries"],
    )
    return _handle_bridge_result(res)


@router.post("/workforce/gig-entries/{entry_id}/pay", dependencies=[Depends(require_sheets_connection)])
async def pay_gig_worker_entry(entry_id: str, req: GigWorkTransitionRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    """Pay verified gig work entry -> PAID state (OWNER_ADMIN only) via Apps Script."""
    actor_id, v2_role = require_owner(current_user)
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="PAY_GIG_WORK_ENTRY",
        target_tab="LabourWorkEntries",
        payload={
            "entry_id": entry_id.strip(),
            "target_status": "PAID",
            "payment_method": req.payment_method or "CASH",
            "payment_reference": (req.payment_reference or "").strip(),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="entry_id",
        invalidate_tabs=["LabourWorkEntries", "WorkforcePayments", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


# ---------------------------------------------------------------------------
# Procurement, Store, Milling, Production, Sales & Accounting Governed Routes
# ---------------------------------------------------------------------------
@router.post("/procurement/purchase-orders", dependencies=[Depends(require_sheets_connection)])
async def create_v2_purchase_order(req: GovernedPurchaseOrderRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "procurement", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="CREATE_PURCHASE_ORDER",
        target_tab="PurchaseOrders",
        payload={
            "supplier_id": req.supplier_id.strip(),
            "supplier_name": (req.supplier_name or "").strip(),
            "order_date": req.order_date or now_iso()[:10],
            "expected_delivery_date": (req.expected_delivery_date or "").strip(),
            "items": req.items,
            "total_amount": str(quantize_money(req.total_amount)),
            "status": "OPEN",
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="po_id",
        invalidate_tabs=["PurchaseOrders", "PurchaseOrderItems"],
    )
    return _handle_bridge_result(res)


@router.post("/procurement/goods-receipts", dependencies=[Depends(require_sheets_connection)])
async def create_v2_goods_receipt(req: GovernedGoodsReceiptRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "procurement", "receive")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="CREATE_GOODS_RECEIPT",
        target_tab="GoodsReceipts",
        payload={
            "po_id": (req.po_id or "").strip(),
            "supplier_id": req.supplier_id.strip(),
            "supplier_name": (req.supplier_name or "").strip(),
            "receipt_date": req.receipt_date or now_iso()[:10],
            "invoice_number": (req.invoice_number or "").strip(),
            "items": req.items,
            "freight_amount": str(quantize_money(req.freight_amount)),
            "gst_amount": str(quantize_money(req.gst_amount)),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="receipt_id",
        invalidate_tabs=["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "PurchaseOrders", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


@router.get("/store/ledger")
async def list_v2_store_ledger(
    ledger_type: Literal["RAW_MATERIAL", "PRODUCTION", "LOT_MOVEMENTS"] = Query("PRODUCTION"),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "store", "view")
    tab_map = {
        "RAW_MATERIAL": "RawMaterialLedger",
        "PRODUCTION": "ProductionStockLedger",
        "LOT_MOVEMENTS": "LotMovements",
    }
    return _safe_query_tab(tab_map[ledger_type], fresh=True, search=search, page=page, page_size=page_size)


@router.post("/store/stock-adjustments", dependencies=[Depends(require_sheets_connection)])
async def create_v2_stock_adjustment(req: GovernedStockAdjustmentRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "store", "adjust_request")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    if req.adjustment_qty == Decimal("0"):
        raise HTTPException(status_code=422, detail="adjustment_qty must be non-zero.")
    res = apps_script_bridge.execute_governed_write(
        action="REQUEST_STOCK_ADJUSTMENT",
        target_tab="StockDiscrepancies",
        payload={
            "product_id": req.product_id.strip(),
            "ledger_type": req.ledger_type,
            "adjustment_qty": str(quantize_weight_kg(req.adjustment_qty)),
            "reason": req.reason.strip(),
            "status": "PENDING_OWNER_APPROVAL",
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="discrepancy_id",
        invalidate_tabs=["StockDiscrepancies", "ApprovalRequests"],
    )
    return _handle_bridge_result(res)


@router.post("/milling/batches", dependencies=[Depends(require_sheets_connection)])
async def create_v2_milling_batch(req: GovernedMillingBatchRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "production", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    if req.flour_output_kg > req.input_quantity_kg:
        raise HTTPException(status_code=422, detail="flour_output_kg cannot exceed input_quantity_kg.")
    res = apps_script_bridge.execute_governed_write(
        action="RECORD_MILLING_BATCH",
        target_tab="MillingBatches",
        payload={
            "milling_date": req.milling_date or now_iso()[:10],
            "source_material_id": req.source_material_id.strip(),
            "source_material_name": (req.source_material_name or "").strip(),
            "input_quantity_kg": str(quantize_weight_kg(req.input_quantity_kg)),
            "flour_output_kg": str(quantize_weight_kg(req.flour_output_kg)),
            "milling_loss_kg": str(quantize_weight_kg(req.input_quantity_kg - req.flour_output_kg)),
            "milling_expenses": str(quantize_money(req.milling_expenses)),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="milling_batch_id",
        invalidate_tabs=["MillingBatches", "RawMaterialLedger", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


@router.post("/production/batches", dependencies=[Depends(require_sheets_connection)])
async def create_v2_production_batch(req: GovernedProductionBatchRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "production", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="CREATE_PRODUCTION_BATCH",
        target_tab="ProductionBatches",
        payload={
            "production_date": req.production_date or now_iso()[:10],
            "product_id": req.product_id.strip(),
            "recipe_id": (req.recipe_id or "").strip(),
            "planned_quantity_kg": str(quantize_weight_kg(req.planned_quantity_kg)),
            "net_quantity_kg": str(quantize_weight_kg(req.net_quantity_kg)) if req.net_quantity_kg is not None else "",
            "shift": (req.shift or "MORNING").strip(),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="production_id",
        invalidate_tabs=["ProductionBatches", "ProductLots", "ProductionStockLedger"],
    )
    return _handle_bridge_result(res)


@router.post("/sales/orders", dependencies=[Depends(require_sheets_connection)])
async def create_v2_sales_order(req: GovernedSalesOrderRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "sales", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    res = apps_script_bridge.execute_governed_write(
        action="CREATE_SALES_ORDER",
        target_tab="SalesOrders",
        payload={
            "customer_id": req.customer_id.strip(),
            "customer_name": (req.customer_name or "").strip(),
            "order_date": req.order_date or now_iso()[:10],
            "delivery_date": (req.delivery_date or "").strip(),
            "items": req.items,
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="so_id",
        invalidate_tabs=["SalesOrders", "SalesOrderItems"],
    )
    return _handle_bridge_result(res)


@router.post("/sales/invoices", dependencies=[Depends(require_sheets_connection)])
async def create_v2_sales_invoice(req: GovernedSalesInvoiceRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "sales", "create")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)

    # Enforce strict lot quality gate for any lot-referenced sale line
    lot_refs = {str(it.get("lot_id", "")).strip() for it in req.items if str(it.get("lot_id", "")).strip()}
    if lot_refs:
        try:
            lots = db.get_records("ProductLots", fresh=True)
        except Exception as exc:
            _raise_storage_error(exc, "ProductLots")
        for ref in lot_refs:
            lot = next((l for l in lots if str(l.get("lot_id", "")).strip() == ref), None)
            if lot and str(lot.get("quality_status", "")).strip().upper() != "RELEASED":
                raise HTTPException(
                    status_code=409,
                    detail=f"Invoice blocked: Lot '{ref}' has quality_status='{lot.get('quality_status')}'. Only RELEASED lots may be billed.",
                )

    res = apps_script_bridge.execute_governed_write(
        action="CREATE_SALES_INVOICE",
        target_tab="Sales",
        payload={
            "customer_id": req.customer_id.strip(),
            "customer_name": (req.customer_name or "").strip(),
            "sale_date": req.sale_date or now_iso()[:10],
            "salesman_user_id": (req.salesman_user_id or actor_id).strip(),
            "so_id": (req.so_id or "").strip(),
            "items": req.items,
            "payment_method": req.payment_method,
            "cash_collected": str(quantize_money(req.cash_collected)),
            "notes": (req.notes or "").strip(),
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="sale_id",
        invalidate_tabs=["Sales", "SaleItems", "SalesmanStockLedger", "ProductionStockLedger", "Customers", "JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


@router.post("/accounting/journals", dependencies=[Depends(require_sheets_connection)])
async def create_v2_journal_voucher(req: GovernedJournalVoucherRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    actor_id, v2_role = require_module_action(current_user, "accounting", "create_vouchers")
    active_nonce = apps_script_bridge.extract_request_nonce(request=request, explicit_nonce=req.nonce)
    lines_payload = [
        {
            "account_code": l.account_code.strip(),
            "debit_amount": str(quantize_money(l.debit_amount)),
            "credit_amount": str(quantize_money(l.credit_amount)),
            "entity_type": (l.entity_type or "").strip(),
            "entity_id": (l.entity_id or "").strip(),
            "notes": (l.notes or "").strip(),
        }
        for l in req.lines
    ]
    try:
        total_debit, total_credit = validate_journal_lines(lines_payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    res = apps_script_bridge.execute_governed_write(
        action="POST_JOURNAL_VOUCHER",
        target_tab="JournalHeaders",
        payload={
            "journal_date": req.journal_date or now_iso()[:10],
            "voucher_type": req.voucher_type.strip().upper(),
            "reference_type": req.reference_type.strip().upper(),
            "reference_id": req.reference_id.strip(),
            "narration": req.narration.strip(),
            "total_debit": str(quantize_money(total_debit)),
            "total_credit": str(quantize_money(total_credit)),
            "lines": lines_payload,
        },
        nonce=active_nonce,
        actor_user_id=actor_id,
        actor_role=v2_role,
        id_field="journal_id",
        invalidate_tabs=["JournalHeaders", "JournalLines"],
    )
    return _handle_bridge_result(res)


# ---------------------------------------------------------------------------
# Governance Audit & Exception Logs (Group 00 / 12)
# ---------------------------------------------------------------------------
@router.get("/control/audit-logs")
async def list_v2_audit_logs(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "control", "view")
    return _safe_query_tab("AuditLog", fresh=True, search=search, page=page, page_size=page_size)


@router.get("/control/exceptions")
async def list_v2_exceptions(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    require_module_action(current_user, "control", "view")
    conflict = TAB_RECONCILIATION_CONFLICTS["EXC"]
    # Fail closed cleanly with explicit CONFLICT_RECONCILIATION_REQUIRED metadata while allowing read if snapshot tab exists
    for candidate_tab in (conflict["snapshot_tab"], conflict["draft_tab"]):
        try:
            res = db.query_records(candidate_tab, fresh=True, search=search, page=page, page_size=page_size)
            return {
                **res,
                "source_tab": candidate_tab,
                "status": conflict["status"],
                "reconciliation_conflict": conflict,
            }
        except Exception:
            continue
    return {
        "status": conflict["status"],
        "error_code": "CONFLICT_RECONCILIATION_REQUIRED",
        "reconciliation_conflict": conflict,
        "items": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
        "total_pages": 0,
    }
