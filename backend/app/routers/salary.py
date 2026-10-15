from typing import List
from fastapi import APIRouter, Depends
from app.models import SalaryRecord
from app.sheets import db
from app.auth import get_current_user

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
            approval_status=str(r.get("approval_status", "PROPOSED")),
            approved_by_user_id=str(r.get("approved_by_user_id", "")),
            paid_datetime=str(r.get("paid_datetime", "")),
            payment_reference=str(r.get("payment_reference", "")),
            notes=str(r.get("notes", "")),
        ))
    salaries.reverse()
    return salaries
