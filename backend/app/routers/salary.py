from datetime import datetime
from typing import List, Union
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import SalaryRecord, SalaryCreateRequest, SalaryApproveRequest, SalaryPayRequest
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection

router = APIRouter(prefix="/api/salary", tags=["Salary & Incentives"])

@router.get("", response_model=List[SalaryRecord])
async def list_salary_records(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("user_id")
    role = current_user.get("role", "").upper()

    records = db.get_records("SalaryIncentives")
    salaries = []
    for r in records:
        s_user = str(r.get("salesman_user_id", ""))
        if role not in ["OWNER", "OWNER_ADMIN", "PA"] and s_user != user_id:
            continue
        salaries.append(SalaryRecord(
            record_id=str(r.get("record_id", "")),
            period_start=str(r.get("period_start", "")),
            period_end=str(r.get("period_end", "")),
            salesman_user_id=s_user,
            record_type=str(r.get("record_type", "INCENTIVE")),
            eligible_kg=float(r.get("eligible_kg", 0.0) or 0.0),
            completed_100kg_blocks=int(r.get("completed_100kg_blocks", 0) or 0),
            rate=float(r.get("rate", 0.0) or 0.0),
            calculated_amount=float(r.get("calculated_amount", 0.0) or 0.0),
            approved_amount=float(r.get("approved_amount", 0.0) or 0.0),
            approval_status="PENDING" if str(r.get("approval_status", "PROPOSED")).upper() == "PROPOSED" else str(r.get("approval_status", "PENDING")),
            approved_by_user_id=str(r.get("approved_by_user_id", "")),
            paid_datetime=str(r.get("paid_datetime", "")),
            payment_reference=str(r.get("payment_reference", "")),
            notes=str(r.get("notes", "")),
        ))
    salaries.reverse()
    return salaries

@router.post("", response_model=List[SalaryRecord], dependencies=[Depends(require_sheets_connection)])
async def propose_salary_records(
    req: Union[SalaryCreateRequest, List[SalaryCreateRequest]],
    current_user: dict = Depends(get_current_user)
):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can calculate payroll")

    user_id = current_user.get("user_id")
    items = req if isinstance(req, list) else [req]
    existing = db.get_records("SalaryIncentives")
    existing_keys = {
        f"{r.get('period_start')}_{r.get('period_end')}_{r.get('salesman_user_id')}_{r.get('record_type')}"
        for r in existing
    }

    users_records = db.get_records("Users")
    known_users = {str(u.get("user_id", "")).strip(): u for u in users_records}

    created_records: List[SalaryRecord] = []
    for item in items:
        # Validate period dates
        if item.period_start > item.period_end:
            raise HTTPException(status_code=422, detail=f"Invalid date period: period_start ({item.period_start}) cannot be after period_end ({item.period_end})")

        # Validate employee exists
        s_user = str(item.salesman_user_id).strip()
        if known_users and s_user not in known_users:
            raise HTTPException(status_code=404, detail=f"Employee {s_user} does not exist in the Users registry")

        # Finding 7: Validate incentive calculation math on server
        rec_type = str(item.record_type).upper()
        if rec_type in {"MONTHLY_INCENTIVE", "INCENTIVE"}:
            expected_blocks = int(item.eligible_kg // 100) if item.eligible_kg > 0 else 0
            if item.completed_100kg_blocks != expected_blocks and item.eligible_kg > 0:
                item.completed_100kg_blocks = expected_blocks
            expected_amount = round(item.completed_100kg_blocks * item.rate, 2)
            if item.rate > 0 and abs(item.calculated_amount - expected_amount) > 0.05:
                raise HTTPException(
                    status_code=422,
                    detail=f"Payroll validation error: Calculated amount ₹{item.calculated_amount} does not match {item.completed_100kg_blocks} × 100kg blocks at ₹{item.rate}/block (expected ₹{expected_amount})."
                )
        elif rec_type == "TRIAL_INCENTIVE":
            expected_amount = round(item.eligible_kg * item.rate, 2)
            if item.rate > 0 and abs(item.calculated_amount - expected_amount) > 0.05:
                raise HTTPException(
                    status_code=422,
                    detail=f"Payroll validation error: Calculated amount ₹{item.calculated_amount} does not match {item.eligible_kg} kg at ₹{item.rate}/kg (expected ₹{expected_amount})."
                )

        key = f"{item.period_start}_{item.period_end}_{item.salesman_user_id}_{item.record_type}"
        if key in existing_keys:
            # Skip duplicate period calculation
            continue

        record_id = db.generate_id("SalaryIncentives")
        rec_data = {
            "record_id": record_id,
            "period_start": item.period_start,
            "period_end": item.period_end,
            "salesman_user_id": item.salesman_user_id,
            "record_type": item.record_type,
            "eligible_kg": item.eligible_kg,
            "completed_100kg_blocks": item.completed_100kg_blocks,
            "rate": item.rate,
            "calculated_amount": item.calculated_amount,
            "approved_amount": item.approved_amount if item.approved_amount is not None else item.calculated_amount,
            "approval_status": "PENDING",
            "approved_by_user_id": "",
            "paid_datetime": "",
            "payment_reference": "",
            "notes": item.notes or "",
        }
        if not db.append_record("SalaryIncentives", rec_data, raise_on_error=True):
            raise HTTPException(status_code=503, detail="The salary record was not saved.")
        created_records.append(SalaryRecord(**rec_data))

        db.log_audit(
            actor=user_id,
            action="CALCULATE_SALARY",
            entity_type="SalaryIncentives",
            entity_id=record_id,
            reason=f"Calculated {item.record_type} ₹{item.calculated_amount} for {item.salesman_user_id}"
        )

    return created_records

@router.post("/{record_id}/approve", response_model=SalaryRecord, dependencies=[Depends(require_sheets_connection)])
async def approve_salary_record(
    record_id: str,
    req: SalaryApproveRequest,
    current_user: dict = Depends(get_current_user)
):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can approve salary/incentives")

    user_id = current_user.get("user_id")
    records = db.get_records("SalaryIncentives")
    matched = next((r for r in records if str(r.get("record_id")) == record_id), None)
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Salary record {record_id} not found")

    # Protection: Already paid salary records cannot be altered without a controlled adjustment
    if str(matched.get("paid_datetime", "")).strip():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Salary record {record_id} has already been paid on {matched.get('paid_datetime')} and cannot be modified.")

    approved_amt = req.approved_amount if req.approved_amount is not None else float(matched.get("calculated_amount", 0.0) or 0.0)
    updates = {
        "approval_status": "APPROVED",
        "approved_amount": approved_amt,
        "approved_by_user_id": user_id,
    }
    if req.notes:
        updates["notes"] = req.notes

    if not db.update_record("SalaryIncentives", "record_id", record_id, updates, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Salary approval was not saved.")
    matched.update(updates)

    db.log_audit(
        actor=user_id,
        action="APPROVE_SALARY",
        entity_type="SalaryIncentives",
        entity_id=record_id,
        reason=f"Approved amount ₹{approved_amt} for record {record_id}"
    )

    return SalaryRecord(
        record_id=record_id,
        period_start=str(matched.get("period_start", "")),
        period_end=str(matched.get("period_end", "")),
        salesman_user_id=str(matched.get("salesman_user_id", "")),
        record_type=str(matched.get("record_type", "INCENTIVE")),
        eligible_kg=float(matched.get("eligible_kg", 0.0) or 0.0),
        completed_100kg_blocks=int(matched.get("completed_100kg_blocks", 0) or 0),
        rate=float(matched.get("rate", 0.0) or 0.0),
        calculated_amount=float(matched.get("calculated_amount", 0.0) or 0.0),
        approved_amount=approved_amt,
        approval_status="APPROVED",
        approved_by_user_id=user_id,
        paid_datetime=str(matched.get("paid_datetime", "")),
        payment_reference=str(matched.get("payment_reference", "")),
        notes=str(matched.get("notes", "")),
    )

@router.post("/{record_id}/pay", response_model=SalaryRecord, dependencies=[Depends(require_sheets_connection)])
async def mark_salary_paid(
    record_id: str,
    req: SalaryPayRequest,
    current_user: dict = Depends(get_current_user)
):
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can mark salary as paid")

    user_id = current_user.get("user_id")
    records = db.get_records("SalaryIncentives")
    matched = next((r for r in records if str(r.get("record_id")) == record_id), None)
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Salary record {record_id} not found")

    # Protection: Record must be approved before paying
    if str(matched.get("approval_status", "")).upper() != "APPROVED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only approved salary records can be paid. Approve this record first.")

    # Protection: Cannot pay an already paid record
    if str(matched.get("paid_datetime", "")).strip():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Salary record {record_id} has already been paid on {matched.get('paid_datetime')}.")

    now_iso = datetime.utcnow().isoformat()
    updates = {
        "paid_datetime": now_iso,
        "payment_reference": req.payment_reference,
    }
    if req.notes:
        updates["notes"] = req.notes

    if not db.update_record("SalaryIncentives", "record_id", record_id, updates, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Salary payment was not saved.")
    matched.update(updates)

    db.log_audit(
        actor=user_id,
        action="PAY_SALARY",
        entity_type="SalaryIncentives",
        entity_id=record_id,
        reason=f"Recorded payment ref {req.payment_reference} for salary record {record_id}"
    )

    return SalaryRecord(
        record_id=record_id,
        period_start=str(matched.get("period_start", "")),
        period_end=str(matched.get("period_end", "")),
        salesman_user_id=str(matched.get("salesman_user_id", "")),
        record_type=str(matched.get("record_type", "INCENTIVE")),
        eligible_kg=float(matched.get("eligible_kg", 0.0) or 0.0),
        completed_100kg_blocks=int(matched.get("completed_100kg_blocks", 0) or 0),
        rate=float(matched.get("rate", 0.0) or 0.0),
        calculated_amount=float(matched.get("calculated_amount", 0.0) or 0.0),
        approved_amount=float(matched.get("approved_amount", 0.0) or 0.0),
        approval_status=str(matched.get("approval_status", "APPROVED")),
        approved_by_user_id=str(matched.get("approved_by_user_id", "")),
        paid_datetime=now_iso,
        payment_reference=req.payment_reference,
        notes=str(matched.get("notes", "")),
    )
