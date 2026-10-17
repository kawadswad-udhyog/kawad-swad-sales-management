from app.timeutil import business_today, now_iso
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.auth import get_current_user
from app.sheets import db
from app.config import SALES_GOOGLE_SPREADSHEET_ID

router = APIRouter(prefix="/api/production", tags=["Production"])
ADMIN_ROLES = {"OWNER", "OWNER_ADMIN", "PA"}

def actor_info(user: dict):
    return str(user.get("user_id", "")), str(user.get("role", "")).upper()

def require_admin(user: dict):
    actor, role = actor_info(user)
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Owner or authorised PA permission required")
    return actor, role

def require_persistent_store():
    # Production and stock writes must not silently land only in process memory when Sheets is configured.
    if SALES_GOOGLE_SPREADSHEET_ID and not (db.is_connected and db.spreadsheet):
        raise HTTPException(status_code=503, detail="Google Sheets is disconnected. Production and stock changes are blocked until the connection is restored.")

def make_id(tab: str):
    return db.generate_id(tab)

def now(): return now_iso()
def truthy(v): return str(v).strip().lower() in {"true", "1", "yes", "active", "y"}
def field(row: dict, *keys, default=""):
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for k in keys:
        if k in row and row[k] not in (None, ""): return row[k]
        if k.lower() in low and low[k.lower()] not in (None, ""): return low[k.lower()]
    return default

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
    notes: str = ""

class ProductionCreate(BaseModel):
    product_id: str
    production_date: str
    quantity_kg: float = Field(gt=0)
    wastage_kg: float = Field(ge=0, default=0)
    notes: str = ""

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
    notes: str = ""

class DispatchCreate(BaseModel):
    product_id: str
    channel: str
    destination: str = ""
    quantity_packets: int = Field(gt=0)
    reference: str = ""
    notes: str = ""

@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    require_admin(user)
    ledger = db.get_records("ProductionStockLedger")
    bulk = {}
    packets = {}
    for r in ledger:
        pid = str(field(r, "product_id")); typ = str(field(r, "movement_type")).upper()
        kg = float(field(r, "quantity_kg", default=0) or 0)
        qty = int(float(field(r, "quantity_packets", default=0) or 0))
        bulk_key = str(field(r, "bulk_product_key", default=field(r, "product_name_snapshot", default=pid))).strip().lower()
        if typ == "BULK_PRODUCED": bulk[bulk_key] = bulk.get(bulk_key, 0) + kg
        elif typ == "BULK_PACKAGED": bulk[bulk_key] = bulk.get(bulk_key, 0) - kg
        elif typ == "PACKETS_PACKAGED": packets[pid] = packets.get(pid, 0) + qty
        elif typ == "CHANNEL_DISPATCH": packets[pid] = packets.get(pid, 0) - qty
        elif typ == "PACKET_RETURN": packets[pid] = packets.get(pid, 0) + qty
    products = {str(field(p, "product_id")): p for p in db.get_records("Products")}
    bulk_names = {}
    for r in ledger:
        key = str(field(r, "bulk_product_key", default=field(r, "product_name_snapshot", default=field(r,"product_id")))).strip().lower()
        if key: bulk_names[key] = str(field(r,"product_name_snapshot",default=key))
    return {"bulk_stock": [{"product_id": p, "product_name": bulk_names.get(p, str(field(products.get(p, {}), "product_name", default=p))), "quantity_kg": round(v, 3)} for p,v in bulk.items()],
            "finished_stock": [{"product_id": p, "product_name": str(field(products.get(p, {}), "product_name", default=p)), "quantity_packets": v} for p,v in packets.items()],
            "workers_active": sum(1 for w in db.get_records("Workers") if truthy(field(w,"active",default="true"))),
            "wage_accrued_today": round(sum(float(field(a,"wage_accrued",default=0) or 0) for a in db.get_records("WorkerAttendance") if str(field(a,"attendance_date")) == business_today()),2),
            "pending_production": sum(1 for b in db.get_records("ProductionBatches") if str(field(b,"status")).upper()=="PENDING")}

@router.get("/workers")
async def workers(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("Workers")

@router.post("/workers")
async def add_worker(req: WorkerCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    if any(str(field(w,"worker_name")).strip().lower() == req.worker_name.strip().lower() and truthy(field(w,"active",default="true")) for w in db.get_records("Workers")):
        raise HTTPException(409, "An active worker with this name already exists")
    rec = {"worker_id": make_id("Workers"), "worker_name": req.worker_name.strip(), "mobile": req.mobile.strip(), "daily_wage": req.daily_wage, "active": str(req.active).lower(), "notes": req.notes.strip(), "created_at": now(), "created_by": actor}
    if not db.append_record("Workers", rec, raise_on_error=True): raise HTTPException(503, "Could not save worker")
    db.log_audit(actor,"CREATE_WORKER","Workers",rec["worker_id"],reason=f"Created worker {rec['worker_name']}")
    return rec

@router.get("/attendance")
async def attendance(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("WorkerAttendance")

@router.post("/attendance")
async def record_attendance(req: AttendanceCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    status_value = req.status.strip().upper()
    if status_value not in {"PRESENT", "ABSENT", "HALF_DAY"}:
        raise HTTPException(400, "Attendance must be PRESENT, ABSENT, or HALF_DAY")
    worker = next((w for w in db.get_records("Workers") if str(field(w,"worker_id")) == req.worker_id), None)
    if not worker:
        raise HTTPException(404, "Worker not found")
    existing = next((a for a in db.get_records("WorkerAttendance") if str(field(a,"worker_id")) == req.worker_id and str(field(a,"attendance_date")) == req.attendance_date), None)
    if existing:
        raise HTTPException(409, "Attendance is already recorded for this worker and date. Ask Owner to correct it through an audited correction workflow.")
    daily_wage = float(field(worker,"daily_wage",default=0) or 0)
    payable = daily_wage if status_value == "PRESENT" else daily_wage * 0.5 if status_value == "HALF_DAY" else 0
    rec={"attendance_id":make_id("WorkerAttendance"),"worker_id":req.worker_id,"worker_name_snapshot":field(worker,"worker_name"),"attendance_date":req.attendance_date,"status":status_value,"daily_wage_snapshot":daily_wage,"wage_accrued":round(payable,2),"notes":req.notes,"created_at":now(),"created_by":actor}
    if not db.append_record("WorkerAttendance",rec,raise_on_error=True): raise HTTPException(503,"Could not save attendance")
    db.log_audit(actor,"RECORD_WORKER_ATTENDANCE","WorkerAttendance",rec["attendance_id"],reason=f"{rec['worker_name_snapshot']} {status_value} on {req.attendance_date}")
    return rec

@router.get("/recipes")
async def recipes(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("Recipes")

@router.post("/recipes")
async def save_recipe(req: RecipeSave, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    product = next((p for p in db.get_records("Products") if str(field(p,"product_id")) == req.product_id), None)
    if not product: raise HTTPException(404, "Product not found")
    if not truthy(field(product,"active",default="true")): raise HTTPException(400,"Cannot create a recipe for an inactive product")
    # Replace recipe by creating a new version; prior recipe and production history remain intact.
    version = 1 + sum(1 for r in db.get_records("Recipes") if str(field(r,"product_id")) == req.product_id)
    recipe_id = make_id("Recipes")
    rec = {"recipe_id": recipe_id, "product_id": req.product_id, "product_name_snapshot": field(product,"product_name"), "version": version, "approved": str(req.approved).lower(), "items_json": __import__('json').dumps([i.model_dump() if hasattr(i,'model_dump') else i.dict() for i in req.items]), "notes": req.notes, "created_at": now(), "created_by": actor}
    if not db.append_record("Recipes", rec, raise_on_error=True): raise HTTPException(503,"Could not save recipe")
    db.log_audit(actor,"CREATE_RECIPE","Recipes",recipe_id,reason=f"Recipe version {version} for {field(product,'product_name')}")
    return rec

@router.get("/batches")
async def batches(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("ProductionBatches")

@router.post("/batches")
async def create_batch(req: ProductionCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    product = next((p for p in db.get_records("Products") if str(field(p,"product_id")) == req.product_id), None)
    if not product: raise HTTPException(404,"Product not found")
    if not truthy(field(product,"active",default="true")): raise HTTPException(400,"Inactive products cannot be produced")
    if req.wastage_kg >= req.quantity_kg: raise HTTPException(400,"Wastage must be less than produced quantity")
    rec = {"production_id": make_id("ProductionBatches"), "production_date": req.production_date, "product_id": req.product_id, "product_name_snapshot": field(product,"product_name"), "quantity_kg": req.quantity_kg, "wastage_kg": req.wastage_kg, "net_quantity_kg": round(req.quantity_kg-req.wastage_kg,3), "status":"PENDING", "notes":req.notes, "created_at":now(), "created_by":actor, "approved_by":"", "approved_at":""}
    if not db.append_record("ProductionBatches", rec, raise_on_error=True): raise HTTPException(503,"Could not save production batch")
    db.log_audit(actor,"CREATE_PRODUCTION_BATCH","ProductionBatches",rec["production_id"],reason=f"{rec['net_quantity_kg']} kg {rec['product_name_snapshot']}; pending approval")
    return rec

@router.post("/batches/{production_id}/approval")
async def approve_batch(production_id: str, req: ApprovalRequest, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    batches = db.get_records("ProductionBatches")
    rec = next((b for b in batches if str(field(b,"production_id")) == production_id), None)
    if not rec: raise HTTPException(404,"Production batch not found")
    if str(field(rec,"status")).upper() != "PENDING": raise HTTPException(409,"This batch has already been reviewed")
    if not req.approved:
        updates={"status":"REJECTED","approved_by":actor,"approved_at":now(),"approval_notes":req.notes}
        if not db.update_record("ProductionBatches","production_id",production_id,updates):
            raise HTTPException(503, "Rejection was not saved.")
        db.log_audit(actor,"REJECT_PRODUCTION","ProductionBatches",production_id,reason=req.notes)
        return {**rec,**updates}
    recipe_rows = [r for r in db.get_records("Recipes") if str(field(r,"product_name_snapshot")).strip().lower() == str(field(rec,"product_name_snapshot")).strip().lower() and truthy(field(r,"approved"))]
    if not recipe_rows: raise HTTPException(400,"No approved recipe exists for this product. Save and approve its recipe before approving production.")
    recipe = sorted(recipe_rows,key=lambda r:int(float(field(r,"version",default=0) or 0)))[-1]
    import json
    items = json.loads(str(field(recipe,"items_json",default="[]")))
    production_kg = float(field(rec,"net_quantity_kg",default=0) or 0)
    # Check material stock from RawMaterials before any deduction. Repeated retries reuse existing ledger entries.
    raw = db.get_records("RawMaterials")
    raw_ledger = db.get_records("RawMaterialLedger")
    deductions=[]
    for item in items:
        name=str(item.get("material_name", "")).strip()
        required=round(float(item.get("quantity_per_kg",0))*production_kg,4)
        stock_row=next((r for r in raw if str(field(r,"material_name","raw_material_name","name")).strip().lower()==name.lower() or str(field(r,"raw_material_id")).strip().lower()==name.lower()),None)
        if not stock_row: raise HTTPException(400,f"Raw material '{name}' is missing from the RawMaterials sheet. Add its current stock before approving production.")
        opening=float(field(stock_row,"current_stock","stock_quantity","quantity","opening_stock",default=0) or 0)
        total_used=sum(float(field(x,"quantity",default=0) or 0) for x in raw_ledger if str(field(x,"material_name")).strip().lower()==name.lower() and str(field(x,"movement_type")).upper()=="PRODUCTION_CONSUMPTION")
        used_by_this_batch=sum(float(field(x,"quantity",default=0) or 0) for x in raw_ledger if str(field(x,"material_name")).strip().lower()==name.lower() and str(field(x,"movement_type")).upper()=="PRODUCTION_CONSUMPTION" and str(field(x,"production_id"))==production_id)
        available=opening-(total_used-used_by_this_batch)
        remaining=round(max(0,required-used_by_this_batch),4)
        unit=str(item.get("unit","kg")).strip()
        if available < remaining: raise HTTPException(400,f"Insufficient stock for {name}: need {remaining} {unit} more, available {available} after other production consumption.")
        deductions.append({"material_name":name,"quantity":remaining,"unit":unit,"raw_material_id":str(field(stock_row,"raw_material_id"))})
    for d in deductions:
        if d["quantity"] <= 0: continue
        ledger_row={"raw_material_txn_id":make_id("RawMaterialLedger"),"txn_datetime":now(),"material_name":d["material_name"],"raw_material_id":d["raw_material_id"],"movement_type":"PRODUCTION_CONSUMPTION","quantity":d["quantity"],"unit":d["unit"],"production_id":production_id,"created_by":actor,"notes":f"Recipe {field(recipe,'recipe_id')}"}
        if not db.append_record("RawMaterialLedger",ledger_row,raise_on_error=True): raise HTTPException(503,"Could not record raw material consumption")
    existing_bulk = next((x for x in db.get_records("ProductionStockLedger") if str(field(x,"reference_id"))==production_id and str(field(x,"movement_type")).upper()=="BULK_PRODUCED"),None)
    if not existing_bulk:
        stock={"movement_id":make_id("ProductionStockLedger"),"txn_datetime":now(),"movement_type":"BULK_PRODUCED","product_id":field(rec,"product_id"),"bulk_product_key":str(field(rec,"product_name_snapshot")).strip().lower(),"product_name_snapshot":field(rec,"product_name_snapshot"),"quantity_kg":production_kg,"quantity_packets":0,"channel":"FACTORY_BULK","reference_id":production_id,"created_by":actor,"notes":req.notes}
        if not db.append_record("ProductionStockLedger",stock,raise_on_error=True): raise HTTPException(503,"Could not record bulk stock. Keep this batch pending and retry only after checking the stock ledger.")
    updates={"status":"APPROVED","approved_by":actor,"approved_at":now(),"approval_notes":req.notes,"recipe_id":field(recipe,"recipe_id")}
    if not db.update_record("ProductionBatches","production_id",production_id,updates):
        raise HTTPException(503, "Materials were recorded but the batch could not be marked approved. Retry the same approval; existing ledger rows will be reused.")
    db.log_audit(actor,"APPROVE_PRODUCTION","ProductionBatches",production_id,reason=f"Approved {production_kg} kg and deducted recipe materials")
    return {**rec,**updates}

@router.get("/packaging")
async def packaging(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("PackagingBatches")

@router.post("/packaging")
async def create_packaging(req: PackagingCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    require_persistent_store()
    product = next((p for p in db.get_records("Products") if str(field(p,"product_id")) == req.product_id), None)
    if not product: raise HTTPException(404,"Product not found")
    if not truthy(field(product,"active",default="true")): raise HTTPException(400,"Inactive products cannot be packaged")
    total_packets=req.packets_200g+req.packets_500g+req.packets_1000g
    if total_packets <= 0: raise HTTPException(400,"Enter at least one packet quantity")
    expected_kg=(req.packets_200g*.2)+(req.packets_500g*.5)+(req.packets_1000g*1.0)
    difference=round(req.bulk_kg_used-expected_kg,3)
    ledger=db.get_records("ProductionStockLedger")
    bulk_key=str(field(product,"product_name")).strip().lower()
    balance=sum(float(field(r,"quantity_kg",default=0) or 0) if str(field(r,"movement_type")).upper()=="BULK_PRODUCED" and str(field(r,"bulk_product_key",default=field(r,"product_name_snapshot"))).strip().lower()==bulk_key else -float(field(r,"quantity_kg",default=0) or 0) if str(field(r,"movement_type")).upper()=="BULK_PACKAGED" and str(field(r,"bulk_product_key",default=field(r,"product_name_snapshot"))).strip().lower()==bulk_key else 0 for r in ledger)
    if req.bulk_kg_used > balance + 0.0001: raise HTTPException(400,f"Insufficient unpackaged stock. Available {balance:.3f} kg; requested {req.bulk_kg_used:.3f} kg.")
    rec={"packaging_id":make_id("PackagingBatches"),"packaging_date":req.packaging_date,"product_id":req.product_id,"product_name_snapshot":field(product,"product_name"),"bulk_kg_used":req.bulk_kg_used,"packets_200g":req.packets_200g,"packets_500g":req.packets_500g,"packets_1000g":req.packets_1000g,"total_packets":total_packets,"expected_kg":round(expected_kg,3),"difference_kg":difference,"difference_status":"MATCH" if abs(difference)<0.001 else "REVIEW_REQUIRED","status":"RECORDED","notes":req.notes,"created_at":now(),"created_by":actor}
    if not db.append_record("PackagingBatches",rec,raise_on_error=True): raise HTTPException(503,"Could not save packaging record")
    movements=[{"movement_type":"BULK_PACKAGED","quantity_kg":req.bulk_kg_used,"quantity_packets":0,"channel":"FACTORY_BULK","product_id":req.product_id,"bulk_product_key":bulk_key,"product_name_snapshot":field(product,"product_name")}]
    # Each packet size must map to its own product/SKU row. Never combine different pack sizes under one SKU.
    for weight_g, packet_count in [(200,req.packets_200g),(500,req.packets_500g),(1000,req.packets_1000g)]:
        if packet_count <= 0: continue
        sku_product=next((p for p in db.get_records("Products") if str(field(p,"product_name")).strip().lower()==bulk_key and int(float(field(p,"pack_weight_g",default=0) or 0))==weight_g and truthy(field(p,"active",default="true"))),None)
        if not sku_product: raise HTTPException(400,f"No active {weight_g} g SKU found for {field(product,'product_name')}. Create/activate that pack-size product first.")
        movements.append({"movement_type":"PACKETS_PACKAGED","quantity_kg":0,"quantity_packets":packet_count,"channel":"FACTORY_FINISHED","product_id":str(field(sku_product,"product_id")),"bulk_product_key":bulk_key,"product_name_snapshot":field(sku_product,"product_name"),"sku_snapshot":field(sku_product,"sku"),"pack_weight_g":weight_g})
    for m in movements:
        row={"movement_id":make_id("ProductionStockLedger"),"txn_datetime":now(),**m,"reference_id":rec["packaging_id"],"created_by":actor,"notes":req.notes}
        if not db.append_record("ProductionStockLedger",row,raise_on_error=True): raise HTTPException(503,"Packaging record saved but stock ledger is incomplete. Reconcile before retrying.")
    db.log_audit(actor,"RECORD_PACKAGING","PackagingBatches",rec["packaging_id"],reason=f"Used {req.bulk_kg_used} kg, produced {total_packets} packets, difference {difference} kg")
    return rec

@router.post("/dispatch")
async def dispatch(req: DispatchCreate, user: dict = Depends(get_current_user)):
    actor, _ = require_admin(user)
    product=next((p for p in db.get_records("Products") if str(field(p,"product_id"))==req.product_id),None)
    if not product: raise HTTPException(404,"Product not found")
    if req.channel.upper() not in {"ECOMMERCE","RETAIL","SALESMAN","WHOLESALE","DISTRIBUTOR"}: raise HTTPException(400,"Unsupported distribution channel")
    ledger=db.get_records("ProductionStockLedger")
    available=sum(int(float(field(r,"quantity_packets",default=0) or 0)) if str(field(r,"movement_type")).upper() in {"PACKETS_PACKAGED","PACKET_RETURN"} and str(field(r,"product_id"))==req.product_id else -int(float(field(r,"quantity_packets",default=0) or 0)) if str(field(r,"movement_type")).upper()=="CHANNEL_DISPATCH" and str(field(r,"product_id"))==req.product_id else 0 for r in ledger)
    if req.quantity_packets>available: raise HTTPException(400,f"Insufficient factory finished stock. Available {available} packets.")
    rec={"dispatch_id":make_id("ProductionDispatches"),"dispatch_datetime":now(),"product_id":req.product_id,"product_name_snapshot":field(product,"product_name"),"channel":req.channel.upper(),"destination":req.destination,"quantity_packets":req.quantity_packets,"reference":req.reference,"status":"DISPATCHED_NOT_SALE","created_by":actor,"notes":req.notes}
    if not db.append_record("ProductionDispatches",rec,raise_on_error=True): raise HTTPException(503,"Could not save dispatch")
    movement={"movement_id":make_id("ProductionStockLedger"),"txn_datetime":now(),"movement_type":"CHANNEL_DISPATCH","product_id":req.product_id,"product_name_snapshot":field(product,"product_name"),"quantity_kg":0,"quantity_packets":req.quantity_packets,"channel":req.channel.upper(),"reference_id":rec["dispatch_id"],"destination":req.destination,"created_by":actor,"notes":req.notes}
    if not db.append_record("ProductionStockLedger",movement,raise_on_error=True): raise HTTPException(503,"Dispatch saved but stock ledger write failed. Reconcile before retrying.")
    if req.channel.upper() == "SALESMAN" and req.destination:
        db.append_record("SalesmanStockLedger", {
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
            "reference_id": rec["dispatch_id"],
            "notes": "Factory dispatch to salesman. This is not a sale.",
        }, raise_on_error=True)
    db.log_audit(actor,"PRODUCTION_STOCK_DISPATCH","ProductionDispatches",rec["dispatch_id"],reason=f"{req.quantity_packets} packets to {req.channel}: {req.destination}")
    return rec

@router.get("/dispatches")
async def dispatches(user: dict = Depends(get_current_user)):
    require_admin(user)
    return db.get_records("ProductionDispatches")
