from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any
import calendar
import logging
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.sheets import db
from app.auth import get_current_user
from app.permissions import (
    is_owner, is_manager, require_manager, require_owner,
    role_of, is_employee, EMPLOYEE_ROLES
)
from app.models import (
    EmployeeAttendanceRecord,
    EmployeeAttendanceCheckIn,
    EmployeeAttendanceCheckOut,
    WorkAssignmentModel,
    WorkAssignmentCreate,
    WorkAssignmentUpdate,
    WorkAssignmentSubmit,
    WorkAssignmentReview,
    FreelancerProjectModel,
    FreelancerProjectCreate,
    FreelancerMilestoneModel,
    FreelancerMilestoneCreate,
    FreelancerMilestoneSubmit,
    FreelancerMilestoneReview,
    LabourMasterModel,
    LabourCreate,
    LabourUpdate,
    LabourAttendanceItem,
    LabourAttendanceBulk,
    LabourWorkEntryCreate,
    SalaryStructureModel,
    SalaryStructureCreate,
    PayrollRunCreate,
    PayrollItemUpdate,
    WorkforcePaymentCreate,
    SalaryReceiptModel,
)

logger = logging.getLogger("kawad_swad.workforce")
router = APIRouter(prefix="/api/workforce", tags=["Workforce & HR"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return date.today().isoformat()


def _log_workforce_audit(action: str, entity_type: str, entity_id: str, actor_id: str, details: str = "") -> None:
    try:
        db.append_record("WorkforceAuditLogs", {
            "audit_id": db.get_next_id("WorkforceAuditLogs"),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": actor_id,
            "details": details,
            "created_at": _now_iso(),
        })
    except Exception as exc:
        logger.warning(f"Failed to append workforce audit log: {exc}")


# ============================================================================
# EMPLOYEE SELF-SERVICE WORKSPACE (STRICTLY SCOPED TO CURRENT USER)
# ============================================================================

@router.get("/my-workspace")
async def get_my_workspace(current_user: dict = Depends(get_current_user)):
    """Role-scoped personal workspace for employees."""
    uid = str(current_user.get("user_id") or "").strip()
    c_role = role_of(current_user)

    # 1. Fetch user's own profile
    users = db.get_records("Users", fresh=True) or []
    profile = next((u for u in users if str(u.get("user_id") or "").strip() == uid), {})

    # 2. Check today's attendance
    today = _today_str()
    attendances = db.get_records("EmployeeAttendance", fresh=True) or []
    my_attendances = [a for a in attendances if str(a.get("employee_id") or "").strip() == uid]
    today_att = next((a for a in my_attendances if str(a.get("attendance_date") or "").strip() == today), None)

    # 3. Tasks assigned to this user
    tasks = db.get_records("WorkAssignments", fresh=True) or []
    my_tasks = [t for t in tasks if str(t.get("assigned_to_user_id") or "").strip() == uid]
    pending_tasks = [t for t in my_tasks if str(t.get("status") or "").upper() in {"PENDING", "IN_PROGRESS"}]

    # 4. Recent salary receipts
    receipts = db.get_records("SalaryReceipts", fresh=True) or []
    my_receipts = [r for r in receipts if str(r.get("recipient_id") or "").strip() == uid]
    my_receipts.sort(key=lambda x: str(x.get("payment_date") or ""), reverse=True)

    # 5. Role-specific context
    role_context: Dict[str, Any] = {}
    if c_role == "SALESMAN":
        # Check sales today or customer visit count
        sales = db.get_records("Sales", fresh=True) or []
        today_sales = [s for s in sales if str(s.get("salesman_user_id") or "").strip() == uid and str(s.get("date") or "").startswith(today)]
        role_context["today_sales_count"] = len(today_sales)
        role_context["today_sales_amount"] = sum(float(s.get("final_amount") or 0.0) for s in today_sales)
    elif c_role == "FREELANCER":
        projects = db.get_records("FreelancerProjects", fresh=True) or []
        my_projects = [p for p in projects if str(p.get("freelancer_user_id") or "").strip() == uid]
        milestones = db.get_records("FreelancerMilestones", fresh=True) or []
        my_project_ids = {str(p.get("project_id") or "").strip() for p in my_projects}
        my_milestones = [m for m in milestones if str(m.get("project_id") or "").strip() in my_project_ids]
        role_context["active_projects_count"] = len([p for p in my_projects if str(p.get("status") or "").upper() == "IN_PROGRESS"])
        role_context["pending_milestones_count"] = len([m for m in my_milestones if str(m.get("status") or "").upper() in {"PENDING", "IN_PROGRESS"}])

    return {
        "user_id": uid,
        "full_name": profile.get("full_name") or current_user.get("full_name"),
        "role": c_role,
        "designation": profile.get("designation") or c_role,
        "department": profile.get("department") or "",
        "today_attendance": today_att,
        "pending_tasks_count": len(pending_tasks),
        "recent_tasks": my_tasks[:5],
        "recent_receipts": my_receipts[:3],
        "role_context": role_context,
    }


@router.get("/my-tasks")
async def get_my_tasks(current_user: dict = Depends(get_current_user)):
    """Fetch tasks assigned specifically to the logged-in employee."""
    uid = str(current_user.get("user_id") or "").strip()
    tasks = db.get_records("WorkAssignments", fresh=True) or []
    my_tasks = [t for t in tasks if str(t.get("assigned_to_user_id") or "").strip() == uid]
    my_tasks.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return my_tasks


@router.post("/my-tasks/{task_id}/submit")
async def submit_my_task(task_id: str, req: WorkAssignmentSubmit, current_user: dict = Depends(get_current_user)):
    """Employee submits completed task with notes and proof."""
    uid = str(current_user.get("user_id") or "").strip()
    tasks = db.get_records("WorkAssignments", fresh=True) or []
    target = next((t for t in tasks if str(t.get("task_id") or "").strip() == task_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Task not found.")

    if str(target.get("assigned_to_user_id") or "").strip() != uid and not is_manager(current_user):
        raise HTTPException(status_code=403, detail="You can only submit tasks assigned to you.")

    now_str = _now_iso()
    updates = {
        "status": "SUBMITTED",
        "submission_notes": req.submission_notes,
        "proof_url": req.proof_url or "",
        "completed_at": now_str,
    }
    db.update_record("WorkAssignments", "task_id", task_id, updates)
    _log_workforce_audit("SUBMIT_TASK", "WorkAssignments", task_id, uid, f"Task {task_id} submitted for review")
    return {"ok": True, "message": "Task submitted successfully for review.", "task_id": task_id}


@router.get("/my-attendance")
async def get_my_attendance(current_user: dict = Depends(get_current_user)):
    """Get attendance records for current user."""
    uid = str(current_user.get("user_id") or "").strip()
    records = db.get_records("EmployeeAttendance", fresh=True) or []
    my_records = [r for r in records if str(r.get("employee_id") or "").strip() == uid]
    my_records.sort(key=lambda x: str(x.get("attendance_date") or ""), reverse=True)
    return my_records


@router.post("/my-attendance/check-in")
async def check_in_my_attendance(req: EmployeeAttendanceCheckIn, current_user: dict = Depends(get_current_user)):
    """Clock in for today. Prevents duplicate check-in."""
    uid = str(current_user.get("user_id") or "").strip()
    user_name = str(current_user.get("full_name") or uid)
    today = _today_str()
    now_time = datetime.now().strftime("%H:%M:%S")

    records = db.get_records("EmployeeAttendance", fresh=True) or []
    existing = next((r for r in records if str(r.get("employee_id") or "").strip() == uid and str(r.get("attendance_date") or "").strip() == today), None)
    if existing:
        return {
            "ok": True,
            "already_checked_in": True,
            "message": f"Already checked in today at {existing.get('check_in_time')}.",
            "record": existing,
        }

    att_id = db.get_next_id("EmployeeAttendance")
    new_record = {
        "attendance_id": att_id,
        "employee_id": uid,
        "employee_name": user_name,
        "attendance_date": today,
        "check_in_time": now_time,
        "check_out_time": "",
        "total_hours": 0.0,
        "status": "PRESENT",
        "notes": req.notes or "",
        "verified_by": "SELF_CHECK_IN",
        "created_at": _now_iso(),
    }
    db.append_record("EmployeeAttendance", new_record)
    _log_workforce_audit("CHECK_IN", "EmployeeAttendance", att_id, uid, f"Check in on {today} at {now_time}")
    return {"ok": True, "message": f"Checked in successfully at {now_time}.", "record": new_record}


@router.post("/my-attendance/check-out")
async def check_out_my_attendance(req: EmployeeAttendanceCheckOut, current_user: dict = Depends(get_current_user)):
    """Clock out for today and calculate total hours."""
    uid = str(current_user.get("user_id") or "").strip()
    today = _today_str()
    now_time = datetime.now().strftime("%H:%M:%S")

    records = db.get_records("EmployeeAttendance", fresh=True) or []
    existing = next((r for r in records if str(r.get("employee_id") or "").strip() == uid and str(r.get("attendance_date") or "").strip() == today), None)
    if not existing:
        raise HTTPException(status_code=400, detail="Cannot check out: No check-in record found for today.")

    in_time_str = str(existing.get("check_in_time") or "").strip()
    total_hours = 8.0
    if in_time_str:
        try:
            t_in = datetime.strptime(in_time_str, "%H:%M:%S")
            t_out = datetime.strptime(now_time, "%H:%M:%S")
            diff = (t_out - t_in).total_seconds() / 3600.0
            total_hours = max(0.0, round(diff, 2))
        except Exception:
            total_hours = 8.0

    notes = str(existing.get("notes") or "")
    if req.notes:
        notes = f"{notes} | Out: {req.notes}".strip(" |")

    updates = {
        "check_out_time": now_time,
        "total_hours": total_hours,
        "notes": notes,
    }
    db.update_record("EmployeeAttendance", "attendance_id", existing.get("attendance_id"), updates)
    _log_workforce_audit("CHECK_OUT", "EmployeeAttendance", existing.get("attendance_id"), uid, f"Check out on {today} at {now_time} ({total_hours} hrs)")
    return {"ok": True, "message": f"Checked out successfully at {now_time}. Total hours: {total_hours}.", "total_hours": total_hours}


@router.get("/my-salary")
async def get_my_salary(current_user: dict = Depends(get_current_user)):
    """Get salary structure, payroll history, and salary receipts for current user."""
    uid = str(current_user.get("user_id") or "").strip()

    structures = db.get_records("SalaryStructures", fresh=True) or []
    my_structure = next((s for s in structures if str(s.get("user_id") or "").strip() == uid), None)

    payroll_items = db.get_records("PayrollItems", fresh=True) or []
    my_payroll_items = [p for p in payroll_items if str(p.get("user_id") or "").strip() == uid]
    my_payroll_items.sort(key=lambda x: str(x.get("payroll_run_id") or ""), reverse=True)

    receipts = db.get_records("SalaryReceipts", fresh=True) or []
    my_receipts = [r for r in receipts if str(r.get("recipient_id") or "").strip() == uid]
    my_receipts.sort(key=lambda x: str(x.get("payment_date") or ""), reverse=True)

    return {
        "salary_structure": my_structure,
        "payroll_items": my_payroll_items,
        "receipts": my_receipts,
    }


@router.get("/my-profile")
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Fetch profile of current logged-in employee."""
    uid = str(current_user.get("user_id") or "").strip()
    users = db.get_records("Users", fresh=True) or []
    target = next((u for u in users if str(u.get("user_id") or "").strip() == uid), None)
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return target


class EmployeeSelfProfileUpdate(BaseModel):
    mobile: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None
    bank_details: Optional[str] = None


@router.put("/my-profile")
async def update_my_profile(req: EmployeeSelfProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Employee updates own personal details (mobile, email, address, bank details)."""
    uid = str(current_user.get("user_id") or "").strip()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        return {"ok": True, "message": "No changes submitted."}

    updates["updated_at"] = _now_iso()
    db.update_record("Users", "user_id", uid, updates)
    _log_workforce_audit("UPDATE_SELF_PROFILE", "Users", uid, uid, f"Self-updated fields: {list(updates.keys())}")
    return {"ok": True, "message": "Profile updated successfully."}


@router.get("/my-projects")
async def get_my_projects(current_user: dict = Depends(get_current_user)):
    """For Freelancers: list assigned projects and milestones."""
    uid = str(current_user.get("user_id") or "").strip()
    projects = db.get_records("FreelancerProjects", fresh=True) or []
    my_projects = [p for p in projects if str(p.get("freelancer_user_id") or "").strip() == uid]

    milestones = db.get_records("FreelancerMilestones", fresh=True) or []
    project_ids = {str(p.get("project_id") or "").strip() for p in my_projects}
    my_milestones = [m for m in milestones if str(m.get("project_id") or "").strip() in project_ids]

    # Group milestones by project
    ms_by_proj: Dict[str, List[dict]] = {}
    for m in my_milestones:
        pid = str(m.get("project_id") or "").strip()
        ms_by_proj.setdefault(pid, []).append(m)

    for p in my_projects:
        pid = str(p.get("project_id") or "").strip()
        p["milestones"] = ms_by_proj.get(pid, [])

    return my_projects


@router.post("/my-projects/milestones/{milestone_id}/submit")
async def submit_my_milestone(milestone_id: str, req: FreelancerMilestoneSubmit, current_user: dict = Depends(get_current_user)):
    """Freelancer submits deliverable for a milestone."""
    uid = str(current_user.get("user_id") or "").strip()
    milestones = db.get_records("FreelancerMilestones", fresh=True) or []
    target_ms = next((m for m in milestones if str(m.get("milestone_id") or "").strip() == milestone_id.strip()), None)
    if not target_ms:
        raise HTTPException(status_code=404, detail="Milestone not found.")

    pid = str(target_ms.get("project_id") or "").strip()
    projects = db.get_records("FreelancerProjects", fresh=True) or []
    proj = next((p for p in projects if str(p.get("project_id") or "").strip() == pid), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Associated project not found.")

    if str(proj.get("freelancer_user_id") or "").strip() != uid and not is_manager(current_user):
        raise HTTPException(status_code=403, detail="You can only submit milestones for your own projects.")

    updates = {
        "status": "SUBMITTED",
        "submission_notes": req.submission_notes,
        "submission_link": req.submission_link or "",
    }
    db.update_record("FreelancerMilestones", "milestone_id", milestone_id, updates)
    _log_workforce_audit("SUBMIT_MILESTONE", "FreelancerMilestones", milestone_id, uid, f"Submitted milestone {milestone_id}")
    return {"ok": True, "message": "Milestone submitted successfully for Owner review.", "milestone_id": milestone_id}


# ============================================================================
# OWNER & PA WORKFORCE MANAGEMENT
# ============================================================================

@router.get("/dashboard-metrics")
async def get_workforce_dashboard_metrics(current_user: dict = Depends(get_current_user)):
    """Summary metrics for Owner/PA workforce management dashboard."""
    require_manager(current_user)

    users = db.get_records("Users", fresh=True) or []
    auth_users = db.get_records("AuthUsers", fresh=True) or []
    labour = db.get_records("LabourMaster", fresh=True) or []
    tasks = db.get_records("WorkAssignments", fresh=True) or []
    payroll_runs = db.get_records("PayrollRuns", fresh=True) or []
    emp_att = db.get_records("EmployeeAttendance", fresh=True) or []
    lbr_att = db.get_records("LabourAttendance", fresh=True) or []
    milestones = db.get_records("FreelancerMilestones", fresh=True) or []

    today = _today_str()
    active_employees = [u for u in users if str(u.get("active", "true")).lower() in {"true", "1", "yes"} and str(u.get("role", "")).upper() not in {"OWNER", "OWNER_ADMIN"}]
    active_labour = [l for l in labour if str(l.get("active", "true")).lower() in {"true", "1", "yes"}]

    emp_present_today = len([a for a in emp_att if str(a.get("attendance_date") or "").strip() == today and str(a.get("status") or "").upper() == "PRESENT"])
    lbr_present_today = len([a for a in lbr_att if str(a.get("attendance_date") or "").strip() == today and str(a.get("status") or "").upper() == "PRESENT"])

    pending_tasks = [t for t in tasks if str(t.get("status") or "").upper() in {"PENDING", "IN_PROGRESS"}]
    submitted_tasks = [t for t in tasks if str(t.get("status") or "").upper() == "SUBMITTED"]
    pending_milestones = [m for m in milestones if str(m.get("status") or "").upper() == "SUBMITTED"]
    draft_payrolls = [p for p in payroll_runs if str(p.get("status") or "").upper() == "DRAFT"]

    return {
        "active_employees_count": len(active_employees),
        "active_labour_count": len(active_labour),
        "employees_present_today": emp_present_today,
        "labour_present_today": lbr_present_today,
        "pending_tasks_count": len(pending_tasks),
        "submitted_tasks_for_review": len(submitted_tasks),
        "pending_milestones_for_review": len(pending_milestones),
        "draft_payrolls_count": len(draft_payrolls),
    }


# --- Employee Management ---

@router.get("/employees")
async def list_employees(current_user: dict = Depends(get_current_user)):
    """List all employees with full workforce details (Users + AuthUsers)."""
    require_manager(current_user)
    users = db.get_records("Users", fresh=True) or []
    auth_users = db.get_records("AuthUsers", fresh=True) or []
    structures = db.get_records("SalaryStructures", fresh=True) or []

    auth_map = {str(a.get("user_id") or "").strip(): a for a in auth_users}
    struct_map = {str(s.get("user_id") or "").strip(): s for s in structures}

    result = []
    for u in users:
        uid = str(u.get("user_id") or "").strip()
        auth = auth_map.get(uid, {})
        struct = struct_map.get(uid, {})
        result.append({
            "user_id": uid,
            "username": auth.get("username") or u.get("username") or uid,
            "full_name": u.get("full_name") or "",
            "role": auth.get("role") or u.get("role") or "SALESMAN",
            "employment_type": u.get("employment_type") or "SALARIED",
            "designation": u.get("designation") or u.get("role") or "",
            "department": u.get("department") or "",
            "reporting_manager_id": u.get("reporting_manager_id") or "",
            "joining_date": u.get("joining_date") or "",
            "employment_status": u.get("employment_status") or "ACTIVE",
            "salary_frequency": u.get("salary_frequency") or "MONTHLY",
            "salary_structure_id": (u.get("salary_structure_id") or struct.get("structure_id") or "") if is_owner(current_user) else "",
            "basic_salary": float(struct.get("basic_salary") or 0.0) if is_owner(current_user) else 0.0,
            "mobile": u.get("mobile") or "",
            "email": u.get("email") or "",
            "address": u.get("address") or "",
            "emergency_contact": u.get("emergency_contact") or "",
            "bank_details": u.get("bank_details") or "",
            "active": str(u.get("active", "true")).lower() in {"true", "1", "yes"},
            "created_at": u.get("created_at") or "",
            "notes": u.get("notes") or "",
        })
    return result


@router.get("/employees/{user_id}")
async def get_employee_details(user_id: str, current_user: dict = Depends(get_current_user)):
    """Full detail of an employee including attendance, tasks, and salary structure (Owner only for structure)."""
    require_manager(current_user)
    users = db.get_records("Users", fresh=True) or []
    target = next((u for u in users if str(u.get("user_id") or "").strip() == user_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found.")

    structures = db.get_records("SalaryStructures", fresh=True) or []
    structure = next((s for s in structures if str(s.get("user_id") or "").strip() == user_id.strip()), None)

    attendances = db.get_records("EmployeeAttendance", fresh=True) or []
    emp_att = [a for a in attendances if str(a.get("employee_id") or "").strip() == user_id.strip()]
    emp_att.sort(key=lambda x: str(x.get("attendance_date") or ""), reverse=True)

    tasks = db.get_records("WorkAssignments", fresh=True) or []
    emp_tasks = [t for t in tasks if str(t.get("assigned_to_user_id") or "").strip() == user_id.strip()]
    emp_tasks.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)

    return {
        "profile": target,
        "salary_structure": structure if is_owner(current_user) else None,
        "recent_attendance": emp_att[:15],
        "tasks": emp_tasks,
    }


# --- Labour Management ---

@router.get("/labour")
async def list_labour(current_user: dict = Depends(get_current_user)):
    """List all factory and contract labour workers from LabourMaster and legacy Workers."""
    require_manager(current_user)
    records = db.get_records("LabourMaster", fresh=True) or []
    existing_ids = {str(l.get("labour_id") or "").strip() for l in records}
    existing_names = {str(l.get("full_name") or l.get("worker_name") or l.get("name") or "").strip().lower() for l in records}

    # Backward compatibility: include legacy Workers if not yet registered in LabourMaster
    legacy_workers = db.get_records("Workers", fresh=True) or []
    for w in legacy_workers:
        wid = str(w.get("worker_id") or "").strip()
        wname = str(w.get("worker_name") or w.get("name") or "").strip()
        if wid and wid not in existing_ids and wname.lower() not in existing_names:
            records.append({
                "labour_id": wid,
                "full_name": wname,
                "category": "GENERAL",
                "wage_type": "DAILY",
                "base_rate": float(w.get("daily_wage") or w.get("base_rate") or 0.0),
                "daily_expected_hours": 8.0,
                "mobile": w.get("mobile") or w.get("phone") or "",
                "emergency_contact": "",
                "address": "",
                "bank_account_no": "",
                "bank_ifsc": "",
                "active": str(w.get("active", w.get("status", "true"))).lower() in {"true", "1", "yes", "active"},
                "notes": w.get("notes") or "Legacy worker record",
                "is_legacy": True,
                "created_at": w.get("created_at") or "",
            })
    records.sort(key=lambda x: str(x.get("full_name") or x.get("worker_name") or ""))
    return records


@router.post("/labour")
async def create_labour(req: LabourCreate, current_user: dict = Depends(get_current_user)):
    """Create a new labour master profile (generates LBR ID)."""
    require_manager(current_user)
    if not req.full_name or len(req.full_name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Labour worker full name is required.")

    actor_id = str(current_user.get("user_id") or "")
    labour_id = db.get_next_id("LabourMaster")

    new_labour = {
        "labour_id": labour_id,
        "full_name": req.full_name.strip(),
        "category": req.category or "GENERAL",
        "wage_type": req.wage_type or "DAILY",
        "base_rate": float(req.base_rate or 0.0),
        "daily_expected_hours": float(req.daily_expected_hours or 8.0),
        "mobile": req.mobile or "",
        "emergency_contact": req.emergency_contact or "",
        "address": req.address or "",
        "bank_account_no": req.bank_account_no or "",
        "bank_ifsc": req.bank_ifsc or "",
        "active": "true",
        "notes": req.notes or "",
        "created_at": _now_iso(),
    }
    db.append_record("LabourMaster", new_labour)
    _log_workforce_audit("CREATE_LABOUR", "LabourMaster", labour_id, actor_id, f"Created labour {req.full_name}")
    return {"ok": True, "message": f"Labour worker {req.full_name} registered successfully.", "labour": new_labour}


@router.put("/labour/{labour_id}")
async def update_labour(labour_id: str, req: LabourUpdate, current_user: dict = Depends(get_current_user)):
    """Update labour worker master details."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    records = db.get_records("LabourMaster", fresh=True) or []
    target = next((l for l in records if str(l.get("labour_id") or "").strip() == labour_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Labour record not found.")

    updates = {k: v for k, v in req.dict().items() if v is not None}
    if "active" in updates:
        updates["active"] = "true" if updates["active"] else "false"

    db.update_record("LabourMaster", "labour_id", labour_id, updates)
    _log_workforce_audit("UPDATE_LABOUR", "LabourMaster", labour_id, actor_id, f"Updated labour {labour_id}")
    return {"ok": True, "message": f"Labour {labour_id} updated successfully."}


@router.get("/labour/attendance")
async def list_labour_attendance(
    date_str: Optional[str] = None,
    attendance_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get labour attendance records (optional filter by date), including legacy WorkerAttendance."""
    require_manager(current_user)
    target_date = (attendance_date or date_str or "").strip()
    records = db.get_records("LabourAttendance", fresh=True) or []
    if target_date:
        records = [r for r in records if str(r.get("attendance_date") or "").strip() == target_date]

    # Backward compatibility: include legacy WorkerAttendance
    legacy_att = db.get_records("WorkerAttendance", fresh=True) or []
    if target_date:
        legacy_att = [
            a for a in legacy_att
            if str(a.get("attendance_date") or a.get("date") or "").strip() == target_date
        ]

    existing_att_keys = {f"{r.get('labour_id')}_{r.get('attendance_date')}" for r in records}
    for la in legacy_att:
        att_d = str(la.get("attendance_date") or la.get("date") or "").strip()
        wid = str(la.get("worker_id") or "").strip()
        key = f"{wid}_{att_d}"
        if key not in existing_att_keys:
            wname = str(la.get("worker_name_snapshot") or la.get("worker_name") or la.get("name") or wid).strip()
            status_val = str(la.get("status") or "PRESENT").strip().upper()
            daily_w = float(la.get("daily_wage_snapshot") or la.get("daily_wage") or 0.0)
            wage_acc = float(la.get("wage_accrued") or la.get("wage") or (daily_w if status_val == "PRESENT" else 0.0))
            records.append({
                "attendance_id": la.get("attendance_id"),
                "labour_id": wid,
                "labour_name": wname,
                "attendance_date": att_d,
                "status": status_val,
                "hours_worked": 8.0,
                "overtime_hours": 0.0,
                "wage_type": "DAILY",
                "daily_rate": daily_w,
                "earned_wage": wage_acc,
                "verified_by": la.get("created_by") or "LEGACY",
                "notes": la.get("notes") or "Legacy attendance record",
                "is_legacy": True,
                "created_at": la.get("created_at") or "",
            })

    records.sort(key=lambda x: str(x.get("attendance_date") or ""), reverse=True)
    return records


@router.post("/labour/attendance/bulk")
async def save_labour_attendance_bulk(req: LabourAttendanceBulk, current_user: dict = Depends(get_current_user)):
    """Save bulk daily attendance for labour workers."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")
    att_date = req.attendance_date.strip()

    labour_records = db.get_records("LabourMaster", fresh=True) or []
    labour_map = {str(l.get("labour_id") or "").strip(): l for l in labour_records}

    existing_att = db.get_records("LabourAttendance", fresh=True) or []
    existing_map = {
        str(r.get("labour_id") or "").strip(): r
        for r in existing_att
        if str(r.get("attendance_date") or "").strip() == att_date
    }

    saved_count = 0
    for item in req.records:
        lid = item.labour_id.strip()
        labour = labour_map.get(lid)
        if not labour:
            continue

        lname = str(labour.get("full_name") or "")
        wage_type = str(labour.get("wage_type") or "DAILY")
        base_rate = float(labour.get("base_rate") or 0.0)

        # Calculate earned wage
        earned_wage = 0.0
        status_val = str(item.status or "PRESENT").upper()
        if status_val == "PRESENT":
            earned_wage = base_rate
        elif status_val == "HALF_DAY":
            earned_wage = round(base_rate * 0.5, 2)
        elif status_val == "ABSENT":
            earned_wage = 0.0

        if wage_type == "HOURLY":
            earned_wage = round(base_rate * float(item.hours_worked or 0.0), 2)

        record_data = {
            "labour_id": lid,
            "labour_name": lname,
            "attendance_date": att_date,
            "status": status_val,
            "hours_worked": float(item.hours_worked or 8.0),
            "overtime_hours": float(item.overtime_hours or 0.0),
            "wage_type": wage_type,
            "daily_rate": base_rate,
            "earned_wage": earned_wage,
            "verified_by": actor_id,
            "notes": item.notes or "",
        }

        if lid in existing_map:
            # Update existing
            old_rec = existing_map[lid]
            att_id = str(old_rec.get("attendance_id") or "")
            db.update_record("LabourAttendance", "attendance_id", att_id, record_data)
        else:
            # Insert new
            att_id = db.get_next_id("LabourAttendance")
            record_data["attendance_id"] = att_id
            record_data["created_at"] = _now_iso()
            db.append_record("LabourAttendance", record_data)

        saved_count += 1

    _log_workforce_audit("BULK_LABOUR_ATTENDANCE", "LabourAttendance", att_date, actor_id, f"Saved {saved_count} labour attendance records for {att_date}")
    return {"ok": True, "message": f"Successfully recorded attendance for {saved_count} workers on {att_date}."}


@router.get("/labour/work-entries")
async def list_labour_work_entries(current_user: dict = Depends(get_current_user)):
    """List piece-rate and production work logs for labour."""
    require_manager(current_user)
    entries = db.get_records("LabourWorkEntries", fresh=True) or []
    entries.sort(key=lambda x: str(x.get("entry_date") or ""), reverse=True)
    return entries


@router.post("/labour/work-entries")
async def create_labour_work_entry(req: LabourWorkEntryCreate, current_user: dict = Depends(get_current_user)):
    """Record piece-rate or task-based work entry for a labour worker."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    labour_records = db.get_records("LabourMaster", fresh=True) or []
    target = next((l for l in labour_records if str(l.get("labour_id") or "").strip() == req.labour_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Labour worker not found.")

    entry_id = db.get_next_id("LabourWorkEntries")
    total_amount = round(float(req.units_completed or 0.0) * float(req.piece_rate or 0.0), 2)

    entry = {
        "entry_id": entry_id,
        "labour_id": req.labour_id.strip(),
        "labour_name": str(target.get("full_name") or ""),
        "entry_date": req.entry_date or _today_str(),
        "category": req.category or str(target.get("category") or "GENERAL"),
        "activity_name": req.activity_name,
        "batch_id": req.batch_id or "",
        "units_completed": float(req.units_completed or 0.0),
        "unit_of_measure": req.unit_of_measure or "KG",
        "piece_rate": float(req.piece_rate or 0.0),
        "total_amount": total_amount,
        "hours_logged": float(req.hours_logged or 0.0),
        "approved_by": actor_id,
        "notes": req.notes or "",
        "created_at": _now_iso(),
    }
    db.append_record("LabourWorkEntries", entry)
    _log_workforce_audit("CREATE_WORK_ENTRY", "LabourWorkEntries", entry_id, actor_id, f"Work entry {entry_id} for {req.labour_id} (Rs {total_amount})")
    return {"ok": True, "message": f"Work entry recorded. Total: Rs {total_amount}.", "entry": entry}


# --- Work Tasks & Assignments ---

@router.get("/tasks")
async def list_tasks(status: Optional[str] = None, user_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """List all work assignments."""
    require_manager(current_user)
    tasks = db.get_records("WorkAssignments", fresh=True) or []
    if status:
        tasks = [t for t in tasks if str(t.get("status") or "").upper() == status.upper()]
    if user_id:
        tasks = [t for t in tasks if str(t.get("assigned_to_user_id") or "").strip() == user_id.strip()]
    tasks.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return tasks


@router.post("/tasks")
async def create_task(req: WorkAssignmentCreate, current_user: dict = Depends(get_current_user)):
    """Assign a work task to an employee."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    users = db.get_records("Users", fresh=True) or []
    assignee = next((u for u in users if str(u.get("user_id") or "").strip() == req.assigned_to_user_id.strip()), None)
    assignee_name = str(assignee.get("full_name") or req.assigned_to_user_id) if assignee else req.assigned_to_user_id
    assignee_role = str(assignee.get("role") or req.role or "") if assignee else (req.role or "")

    task_id = db.get_next_id("WorkAssignments")
    task_record = {
        "task_id": task_id,
        "title": req.title,
        "description": req.description or "",
        "assigned_to_user_id": req.assigned_to_user_id.strip(),
        "assigned_to_name": assignee_name,
        "role": assignee_role,
        "priority": req.priority or "MEDIUM",
        "status": "PENDING",
        "due_date": req.due_date or "",
        "created_by": actor_id,
        "submission_notes": "",
        "proof_url": "",
        "review_notes": "",
        "created_at": _now_iso(),
        "completed_at": "",
    }
    db.append_record("WorkAssignments", task_record)
    _log_workforce_audit("ASSIGN_TASK", "WorkAssignments", task_id, actor_id, f"Assigned task '{req.title}' to {assignee_name}")
    return {"ok": True, "message": f"Task '{req.title}' assigned successfully.", "task": task_record}


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, req: WorkAssignmentUpdate, current_user: dict = Depends(get_current_user)):
    """Update a task assignment."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    tasks = db.get_records("WorkAssignments", fresh=True) or []
    target = next((t for t in tasks if str(t.get("task_id") or "").strip() == task_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Task not found.")

    updates = {k: v for k, v in req.dict().items() if v is not None}
    db.update_record("WorkAssignments", "task_id", task_id, updates)
    _log_workforce_audit("UPDATE_TASK", "WorkAssignments", task_id, actor_id, f"Updated task {task_id}")
    return {"ok": True, "message": f"Task {task_id} updated."}


@router.post("/tasks/{task_id}/review")
async def review_task(task_id: str, req: WorkAssignmentReview, current_user: dict = Depends(get_current_user)):
    """Review submitted task: approve or reject."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    tasks = db.get_records("WorkAssignments", fresh=True) or []
    target = next((t for t in tasks if str(t.get("task_id") or "").strip() == task_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Task not found.")

    if str(target.get("assigned_to_user_id") or "").strip() == actor_id:
        raise HTTPException(status_code=403, detail="Self-approval is forbidden. Another manager or the Owner must review this task.")

    new_status = req.status.upper()
    if new_status not in {"APPROVED", "REJECTED", "COMPLETED"}:
        raise HTTPException(status_code=422, detail="Review status must be APPROVED, REJECTED, or COMPLETED.")

    updates = {
        "status": new_status,
        "review_notes": req.review_notes or "",
    }
    if new_status in {"APPROVED", "COMPLETED"}:
        updates["completed_at"] = _now_iso()

    db.update_record("WorkAssignments", "task_id", task_id, updates)
    _log_workforce_audit("REVIEW_TASK", "WorkAssignments", task_id, actor_id, f"Reviewed task {task_id}: {new_status}")
    return {"ok": True, "message": f"Task {task_id} marked as {new_status}."}


# --- Freelancer Projects & Milestones ---

@router.get("/projects")
async def list_projects(current_user: dict = Depends(get_current_user)):
    """List all freelancer projects with milestones."""
    require_manager(current_user)
    projects = db.get_records("FreelancerProjects", fresh=True) or []
    milestones = db.get_records("FreelancerMilestones", fresh=True) or []

    ms_by_proj: Dict[str, List[dict]] = {}
    for m in milestones:
        pid = str(m.get("project_id") or "").strip()
        ms_by_proj.setdefault(pid, []).append(m)

    for p in projects:
        pid = str(p.get("project_id") or "").strip()
        p["milestones"] = ms_by_proj.get(pid, [])

    projects.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return projects


@router.post("/projects")
async def create_project(req: FreelancerProjectCreate, current_user: dict = Depends(get_current_user)):
    """Create a new freelancer project."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    users = db.get_records("Users", fresh=True) or []
    fl = next((u for u in users if str(u.get("user_id") or "").strip() == req.freelancer_user_id.strip()), None)
    fl_name = str(fl.get("full_name") or req.freelancer_user_id) if fl else req.freelancer_user_id

    project_id = db.get_next_id("FreelancerProjects")
    project = {
        "project_id": project_id,
        "title": req.title,
        "description": req.description or "",
        "freelancer_user_id": req.freelancer_user_id.strip(),
        "freelancer_name": fl_name,
        "total_budget": float(req.total_budget or 0.0),
        "currency": "INR",
        "start_date": req.start_date or _today_str(),
        "target_completion_date": req.target_completion_date or "",
        "status": "IN_PROGRESS",
        "deliverables_summary": req.deliverables_summary or "",
        "notes": req.notes or "",
        "created_at": _now_iso(),
    }
    db.append_record("FreelancerProjects", project)
    _log_workforce_audit("CREATE_PROJECT", "FreelancerProjects", project_id, actor_id, f"Created project '{req.title}' for {fl_name}")
    return {"ok": True, "message": f"Project '{req.title}' created.", "project": project}


@router.get("/projects/{project_id}/milestones")
async def list_project_milestones(project_id: str, current_user: dict = Depends(get_current_user)):
    """List milestones for a project."""
    milestones = db.get_records("FreelancerMilestones", fresh=True) or []
    proj_ms = [m for m in milestones if str(m.get("project_id") or "").strip() == project_id.strip()]
    return proj_ms


@router.post("/projects/{project_id}/milestones")
async def create_project_milestone(project_id: str, req: FreelancerMilestoneCreate, current_user: dict = Depends(get_current_user)):
    """Add a milestone to a freelancer project."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    milestone_id = db.get_next_id("FreelancerMilestones")
    ms = {
        "milestone_id": milestone_id,
        "project_id": project_id.strip(),
        "title": req.title,
        "description": req.description or "",
        "amount": float(req.amount or 0.0),
        "due_date": req.due_date or "",
        "status": "PENDING",
        "submission_notes": "",
        "submission_link": "",
        "review_notes": "",
        "approved_at": "",
        "created_at": _now_iso(),
    }
    db.append_record("FreelancerMilestones", ms)
    _log_workforce_audit("CREATE_MILESTONE", "FreelancerMilestones", milestone_id, actor_id, f"Added milestone '{req.title}' to {project_id}")
    return {"ok": True, "message": f"Milestone '{req.title}' created.", "milestone": ms}


@router.post("/milestones/{milestone_id}/review")
async def review_project_milestone(milestone_id: str, req: FreelancerMilestoneReview, current_user: dict = Depends(get_current_user)):
    """Owner/PA reviews freelancer milestone."""
    require_manager(current_user)
    actor_id = str(current_user.get("user_id") or "")

    milestones = db.get_records("FreelancerMilestones", fresh=True) or []
    target = next((m for m in milestones if str(m.get("milestone_id") or "").strip() == milestone_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Milestone not found.")

    pid = str(target.get("project_id") or "").strip()
    projects = db.get_records("FreelancerProjects", fresh=True) or []
    proj = next((p for p in projects if str(p.get("project_id") or "").strip() == pid), None)
    if proj and str(proj.get("freelancer_user_id") or "").strip() == actor_id:
        raise HTTPException(status_code=403, detail="Self-approval is forbidden. Another manager or the Owner must review this milestone.")

    new_status = req.status.upper()
    if new_status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Status must be APPROVED or REJECTED.")

    updates = {
        "status": new_status,
        "review_notes": req.review_notes or "",
    }
    if new_status == "APPROVED":
        updates["approved_at"] = _now_iso()

    db.update_record("FreelancerMilestones", "milestone_id", milestone_id, updates)
    _log_workforce_audit("REVIEW_MILESTONE", "FreelancerMilestones", milestone_id, actor_id, f"Reviewed milestone {milestone_id}: {new_status}")
    return {"ok": True, "message": f"Milestone {milestone_id} marked as {new_status}."}


# --- Salary Structures & Payroll Engine ---

@router.get("/salary-structures")
async def list_salary_structures(current_user: dict = Depends(get_current_user)):
    """List all employee salary structures (Owner only)."""
    require_owner(current_user)
    structures = db.get_records("SalaryStructures", fresh=True) or []
    return structures


@router.post("/salary-structures")
async def create_or_update_salary_structure(req: SalaryStructureCreate, current_user: dict = Depends(get_current_user)):
    """Owner creates/updates salary structure (Owner only)."""
    require_owner(current_user)
    actor_id = str(current_user.get("user_id") or "")

    uid = req.user_id.strip()
    users = db.get_records("Users", fresh=True) or []
    user_target = next((u for u in users if str(u.get("user_id") or "").strip() == uid), None)
    if not user_target:
        raise HTTPException(status_code=404, detail=f"Employee {uid} not found.")

    structures = db.get_records("SalaryStructures", fresh=True) or []
    existing = next((s for s in structures if str(s.get("user_id") or "").strip() == uid), None)

    struct_data = {
        "user_id": uid,
        "basic_salary": float(req.basic_salary or 0.0),
        "hra": float(req.hra or 0.0),
        "transport_allowance": float(req.transport_allowance or 0.0),
        "special_allowance": float(req.special_allowance or 0.0),
        "sales_commission_rate": float(req.sales_commission_rate or 0.0),
        "pf_deduction": float(req.pf_deduction or 0.0),
        "tds_deduction": float(req.tds_deduction or 0.0),
        "other_deductions": float(req.other_deductions or 0.0),
        "payment_mode": req.payment_mode or "BANK_TRANSFER",
        "effective_from": req.effective_from or _today_str(),
        "notes": req.notes or "",
    }

    if existing:
        sid = str(existing.get("structure_id") or "")
        db.update_record("SalaryStructures", "structure_id", sid, struct_data)
        struct_data["structure_id"] = sid
        _log_workforce_audit("UPDATE_SALARY_STRUCTURE", "SalaryStructures", sid, actor_id, f"Updated structure for {uid}")
        msg = f"Salary structure updated for {user_target.get('full_name')}."
    else:
        sid = db.get_next_id("SalaryStructures")
        struct_data["structure_id"] = sid
        struct_data["created_at"] = _now_iso()
        db.append_record("SalaryStructures", struct_data)
        # Also update user record with structure_id
        db.update_record("Users", "user_id", uid, {"salary_structure_id": sid})
        _log_workforce_audit("CREATE_SALARY_STRUCTURE", "SalaryStructures", sid, actor_id, f"Created structure for {uid}")
        msg = f"Salary structure created for {user_target.get('full_name')}."

    return {"ok": True, "message": msg, "salary_structure": struct_data}


@router.get("/payroll")
async def list_payroll_runs(current_user: dict = Depends(get_current_user)):
    """List all monthly payroll runs (Owner only)."""
    require_owner(current_user)
    runs = db.get_records("PayrollRuns", fresh=True) or []
    runs.sort(key=lambda x: str(x.get("month") or ""), reverse=True)
    return runs


@router.post("/payroll/calculate")
async def calculate_payroll_run(req: PayrollRunCreate, current_user: dict = Depends(get_current_user)):
    """
    Calculate and generate a draft payroll run for a month (e.g. '2026-10') (Owner only).
    Calculates pro-rata base salary, salesman sales commissions/incentives (verifying PAID and DELIVERED),
    deductions, and creates itemized records in PayrollItems.
    """
    require_owner(current_user)
    actor_id = str(current_user.get("user_id") or "")
    run_month = req.month.strip()  # Format YYYY-MM

    # Validate month format
    try:
        yr, mo = map(int, run_month.split("-"))
        _, days_in_month = calendar.monthrange(yr, mo)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid month format. Expected 'YYYY-MM'.")

    # Check for existing run for this month
    existing_runs = db.get_records("PayrollRuns", fresh=True) or []
    dup_run = next((r for r in existing_runs if str(r.get("month") or "").strip() == run_month), None)
    if dup_run and str(dup_run.get("status") or "").upper() == "APPROVED":
        raise HTTPException(status_code=400, detail=f"Payroll for {run_month} has already been approved and cannot be recalculated.")

    users = db.get_records("Users", fresh=True) or []
    structures = db.get_records("SalaryStructures", fresh=True) or []
    struct_map = {str(s.get("user_id") or "").strip(): s for s in structures}

    attendances = db.get_records("EmployeeAttendance", fresh=True) or []
    sales = db.get_records("Sales", fresh=True) or []
    all_sale_items = db.get_records("SaleItems", fresh=False) or []

    run_id = dup_run.get("payroll_run_id") if dup_run else db.get_next_id("PayrollRuns")

    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0
    items_to_save = []

    # Filter active non-owner employees
    active_employees = [
        u for u in users
        if str(u.get("active", "true")).lower() in {"true", "1", "yes"}
        and str(u.get("role", "")).upper() not in {"OWNER", "OWNER_ADMIN"}
    ]

    for emp in active_employees:
        uid = str(emp.get("user_id") or "").strip()
        uname = str(emp.get("full_name") or uid)
        role = str(emp.get("role") or "SALESMAN").upper()

        struct = struct_map.get(uid, {})
        base_monthly = float(struct.get("basic_salary") or 0.0)
        hra = float(struct.get("hra") or 0.0)
        transport = float(struct.get("transport_allowance") or 0.0)
        special = float(struct.get("special_allowance") or 0.0)
        commission_rate = float(struct.get("sales_commission_rate") or 0.0)
        pf = float(struct.get("pf_deduction") or 0.0)
        tds = float(struct.get("tds_deduction") or 0.0)
        other_ded = float(struct.get("other_deductions") or 0.0)

        # Count attendance in this month
        month_prefix = f"{run_month}-"
        emp_att_records = [
            a for a in attendances
            if str(a.get("employee_id") or "").strip() == uid
            and str(a.get("attendance_date") or "").startswith(month_prefix)
        ]
        present_days = len([a for a in emp_att_records if str(a.get("status") or "").upper() == "PRESENT"])
        half_days = len([a for a in emp_att_records if str(a.get("status") or "").upper() == "HALF_DAY"])
        effective_days = present_days + (half_days * 0.5)

        # If no attendance records found (e.g., salaried office staff or PA without daily clock-in),
        # default to full month unless marked absent
        if not emp_att_records and base_monthly > 0:
            effective_days = float(days_in_month)

        # Calculate earned base
        daily_rate = base_monthly / float(days_in_month) if days_in_month > 0 else 0.0
        earned_basic = round(daily_rate * effective_days, 2)
        earned_allowances = round(hra + transport + special, 2)

        # Sales incentives: Enforce consistent rules with salary.py (PAID, DELIVERED, NOT CANCELLED)
        salesman_incentive = 0.0
        if role in {"SALESMAN", "FIELD_SALESMAN"}:
            emp_sales = [
                s for s in sales
                if str(s.get("salesman_user_id") or "").strip() == uid
                and str(s.get("date") or "").startswith(month_prefix)
                and str(s.get("bill_status", "")).upper() != "CANCELLED"
                and str(s.get("payment_status", "")).upper() == "PAID"
                and str(s.get("delivery_status", "")).upper() == "DELIVERED"
            ]
            monthly_sales_amount = sum(float(s.get("final_amount", 0) or s.get("bill_total", 0) or 0.0) for s in emp_sales)
            emp_sale_ids = {str(s.get("sale_id")) for s in emp_sales}
            qualifying_items = [i for i in all_sale_items if str(i.get("sale_id", "")) in emp_sale_ids]
            if qualifying_items:
                monthly_kg_sold = sum(float(i.get("qualifying_kg", 0) or i.get("quantity", 0) or 0.0) for i in qualifying_items)
            else:
                monthly_kg_sold = sum(float(s.get("total_kg") or 0.0) for s in emp_sales)

            if commission_rate > 0:
                salesman_incentive = round(monthly_sales_amount * (commission_rate / 100.0), 2)
            else:
                # Default Kawad Swad incentive: Rs 200 per 100 kg sold
                slabs = int(monthly_kg_sold // 100)
                salesman_incentive = round(slabs * 200.0, 2)

        gross_pay = round(earned_basic + earned_allowances + salesman_incentive, 2)
        total_emp_ded = round(pf + tds + other_ded, 2)
        net_pay = round(max(0.0, gross_pay - total_emp_ded), 2)

        total_gross += gross_pay
        total_deductions += total_emp_ded
        total_net += net_pay

        item_id = db.get_next_id("PayrollItems")
        items_to_save.append({
            "item_id": item_id,
            "payroll_run_id": run_id,
            "user_id": uid,
            "employee_name": uname,
            "role": role,
            "base_salary": base_monthly,
            "working_days": days_in_month,
            "present_days": effective_days,
            "earned_basic": earned_basic,
            "allowances": earned_allowances,
            "incentive_amount": salesman_incentive,
            "bonus_amount": 0.0,
            "deductions": total_emp_ded,
            "adjustment_amount": 0.0,
            "gross_amount": gross_pay,
            "net_amount": net_pay,
            "payment_status": "UNPAID",
            "payment_id": "",
            "notes": f"Attendance: {effective_days}/{days_in_month} days",
        })

    payroll_run_record = {
        "payroll_run_id": run_id,
        "month": run_month,
        "run_date": req.run_date or _today_str(),
        "total_employees": len(items_to_save),
        "total_gross": round(total_gross, 2),
        "total_deductions": round(total_deductions, 2),
        "total_net": round(total_net, 2),
        "status": "DRAFT",
        "created_by": actor_id,
        "approved_by": "",
        "notes": req.notes or f"Calculated payroll run for {run_month}",
        "created_at": _now_iso(),
    }

    if dup_run:
        # Update run header and replace existing items
        db.update_record("PayrollRuns", "payroll_run_id", run_id, payroll_run_record)
        # Delete old items for this run
        existing_items = db.get_records("PayrollItems", fresh=True) or []
        for old_it in existing_items:
            if str(old_it.get("payroll_run_id") or "").strip() == run_id:
                db.delete_record("PayrollItems", "item_id", old_it.get("item_id"))
    else:
        db.append_record("PayrollRuns", payroll_run_record)

    for it in items_to_save:
        db.append_record("PayrollItems", it)

    _log_workforce_audit("CALCULATE_PAYROLL", "PayrollRuns", run_id, actor_id, f"Calculated payroll {run_month} for {len(items_to_save)} employees (Rs {round(total_net, 2)})")
    return {
        "ok": True,
        "message": f"Draft payroll calculated for {run_month} ({len(items_to_save)} employees).",
        "payroll_run": payroll_run_record,
        "items": items_to_save,
    }


@router.get("/payroll/{payroll_run_id}/items")
async def get_payroll_run_items(payroll_run_id: str, current_user: dict = Depends(get_current_user)):
    """Get all line items in a payroll run (Owner only)."""
    require_owner(current_user)
    items = db.get_records("PayrollItems", fresh=True) or []
    run_items = [i for i in items if str(i.get("payroll_run_id") or "").strip() == payroll_run_id.strip()]
    return run_items


@router.put("/payroll/items/{item_id}")
async def update_payroll_item(item_id: str, req: PayrollItemUpdate, current_user: dict = Depends(get_current_user)):
    """Adjust deductions, incentives, bonus, or adjustments on a draft payroll item (Owner only)."""
    require_owner(current_user)
    actor_id = str(current_user.get("user_id") or "")

    items = db.get_records("PayrollItems", fresh=True) or []
    target = next((i for i in items if str(i.get("item_id") or "").strip() == item_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Payroll item not found.")

    run_id = str(target.get("payroll_run_id") or "")
    runs = db.get_records("PayrollRuns", fresh=True) or []
    run = next((r for r in runs if str(r.get("payroll_run_id") or "").strip() == run_id), None)
    if run and str(run.get("status") or "").upper() == "APPROVED":
        raise HTTPException(status_code=400, detail="Cannot edit line items in an already approved payroll run.")

    earned_basic = float(target.get("earned_basic") or 0.0)
    allowances = float(target.get("allowances") or 0.0)

    incentive = float(req.incentive_amount) if req.incentive_amount is not None else float(target.get("incentive_amount") or 0.0)
    bonus = float(req.bonus_amount) if req.bonus_amount is not None else float(target.get("bonus_amount") or 0.0)
    deductions = float(req.deductions) if req.deductions is not None else float(target.get("deductions") or 0.0)
    adjustment = float(req.adjustment_amount) if req.adjustment_amount is not None else float(target.get("adjustment_amount") or 0.0)

    gross = round(earned_basic + allowances + incentive + bonus, 2)
    net = round(max(0.0, gross - deductions + adjustment), 2)

    updates = {
        "incentive_amount": incentive,
        "bonus_amount": bonus,
        "deductions": deductions,
        "adjustment_amount": adjustment,
        "gross_amount": gross,
        "net_amount": net,
    }
    if req.notes is not None:
        updates["notes"] = req.notes

    db.update_record("PayrollItems", "item_id", item_id, updates)
    _log_workforce_audit("UPDATE_PAYROLL_ITEM", "PayrollItems", item_id, actor_id, f"Adjusted payroll item {item_id}")
    return {"ok": True, "message": f"Payroll item {item_id} updated.", "net_amount": net}


@router.post("/payroll/{payroll_run_id}/approve")
async def approve_payroll_run(payroll_run_id: str, current_user: dict = Depends(get_current_user)):
    """Owner approves a draft payroll run."""
    require_owner(current_user)
    actor_id = str(current_user.get("user_id") or "")

    runs = db.get_records("PayrollRuns", fresh=True) or []
    target = next((r for r in runs if str(r.get("payroll_run_id") or "").strip() == payroll_run_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Payroll run not found.")

    if str(target.get("status") or "").upper() == "APPROVED":
        return {"ok": True, "message": "Payroll run is already approved."}

    updates = {
        "status": "APPROVED",
        "approved_by": actor_id,
        "approved_at": _now_iso(),
    }
    db.update_record("PayrollRuns", "payroll_run_id", payroll_run_id, updates)
    _log_workforce_audit("APPROVE_PAYROLL", "PayrollRuns", payroll_run_id, actor_id, f"Owner approved payroll {payroll_run_id}")
    return {"ok": True, "message": f"Payroll run {payroll_run_id} approved successfully."}


# --- Payments & Salary Receipts ---

@router.post("/payments")
async def record_workforce_payment(req: WorkforcePaymentCreate, current_user: dict = Depends(get_current_user)):
    """
    Record payment for:
    - Payroll Item (SALARY)
    - Labour Wage (LABOUR_WAGE)
    - Freelancer Milestone (FREELANCER_MILESTONE)
    Generates an Accounting Journal posting, a SalaryReceipts record, and marks the source item as PAID (Owner only).
    """
    require_owner(current_user)
    actor_id = str(current_user.get("user_id") or "")
    pay_type = req.payment_type.upper()
    pay_amount = float(req.amount or 0.0)
    pay_date = req.payment_date or _today_str()

    if pay_amount <= 0:
        raise HTTPException(status_code=422, detail="Payment amount must be greater than zero.")

    # 1. Create Payment record in WorkforcePayments
    pay_id = db.get_next_id("WorkforcePayments")
    payment_record = {
        "payment_id": pay_id,
        "reference_id": req.reference_id,
        "payment_type": pay_type,
        "recipient_id": req.recipient_id,
        "recipient_name": req.recipient_name,
        "amount": pay_amount,
        "payment_method": req.payment_method or "BANK_TRANSFER",
        "payment_reference": req.payment_reference or "",
        "payment_date": pay_date,
        "bank_account_credited": req.bank_account_credited or "",
        "recorded_by": actor_id,
        "accounting_journal_ref": "",
        "notes": req.notes or "",
        "created_at": _now_iso(),
    }
    db.append_record("WorkforcePayments", payment_record)

    # 2. Update source item status
    role_or_category = "EMPLOYEE"
    gross = pay_amount
    deductions = 0.0

    if pay_type == "SALARY":
        payroll_items = db.get_records("PayrollItems", fresh=True) or []
        target_item = next((i for i in payroll_items if str(i.get("item_id") or "").strip() == req.reference_id.strip()), None)
        if target_item:
            db.update_record("PayrollItems", "item_id", req.reference_id, {"payment_status": "PAID", "payment_id": pay_id})
            role_or_category = str(target_item.get("role") or "SALARIED")
            gross = float(target_item.get("gross_amount") or pay_amount)
            deductions = float(target_item.get("deductions") or 0.0)
        
        # Check recipient profile for role resolution if not determined from payroll item
        if (not target_item or role_or_category in {"EMPLOYEE", "SALARIED", "GENERAL"}) and req.recipient_id:
            users = db.get_records("Users", fresh=True) or []
            u_rec = next((u for u in users if str(u.get("user_id") or "").strip() == req.recipient_id.strip()), None)
            if u_rec and u_rec.get("role"):
                role_or_category = str(u_rec.get("role")).upper()
            else:
                auth_users = db.get_records("AuthUsers", fresh=True) or []
                a_rec = next((a for a in auth_users if str(a.get("user_id") or "").strip() == req.recipient_id.strip()), None)
                if a_rec and a_rec.get("role"):
                    role_or_category = str(a_rec.get("role")).upper()
    elif pay_type == "FREELANCER_MILESTONE":
        milestones = db.get_records("FreelancerMilestones", fresh=True) or []
        target_ms = next((m for m in milestones if str(m.get("milestone_id") or "").strip() == req.reference_id.strip()), None)
        if target_ms:
            db.update_record("FreelancerMilestones", "milestone_id", req.reference_id, {"status": "PAID", "payment_id": pay_id})
            role_or_category = "FREELANCER"
    elif pay_type == "LABOUR_WAGE":
        role_or_category = "LABOUR"

    # 3. Post balanced double-entry accounting journal
    journal_ref = ""
    try:
        from app.accounting.postings import post_workforce_payment_journal
        post_res = post_workforce_payment_journal({
            "payment_id": pay_id,
            "payment_type": pay_type,
            "recipient_id": req.recipient_id,
            "recipient_name": req.recipient_name,
            "role_or_category": role_or_category,
            "amount": pay_amount,
            "payment_method": req.payment_method or "BANK_TRANSFER",
            "payment_date": pay_date,
        }, actor=actor_id)
        if post_res and post_res.get("journal_id"):
            journal_ref = str(post_res["journal_id"])
            payment_record["accounting_journal_ref"] = journal_ref
            db.update_record("WorkforcePayments", "payment_id", pay_id, {"accounting_journal_ref": journal_ref})
    except Exception as exc:
        logger.error(f"Failed to post accounting journal for workforce payment {pay_id}: {exc}")

    # 4. Generate official Salary Receipt
    receipt_id = db.get_next_id("SalaryReceipts")
    receipt_number = f"REC-{datetime.now().strftime('%Y%m')}-{receipt_id.replace('RCPT', '')}"
    receipt_record = {
        "receipt_id": receipt_id,
        "receipt_number": receipt_number,
        "payment_id": pay_id,
        "recipient_id": req.recipient_id,
        "recipient_name": req.recipient_name,
        "recipient_type": pay_type,
        "role_or_category": role_or_category,
        "period_start": f"{pay_date[:7]}-01",
        "period_end": pay_date,
        "payment_date": pay_date,
        "payment_method": req.payment_method or "BANK_TRANSFER",
        "payment_reference": req.payment_reference or "",
        "gross_earnings": gross,
        "total_deductions": deductions,
        "net_paid": pay_amount,
        "notes": req.notes or f"Disbursed {pay_type} via {req.payment_method}",
        "created_at": _now_iso(),
    }
    db.append_record("SalaryReceipts", receipt_record)

    _log_workforce_audit("RECORD_PAYMENT", "WorkforcePayments", pay_id, actor_id, f"Disbursed Rs {pay_amount} to {req.recipient_name} ({pay_type}) [Journal: {journal_ref}]")

    return {
        "ok": True,
        "message": f"Payment of Rs {pay_amount} recorded for {req.recipient_name}.",
        "payment": payment_record,
        "receipt": receipt_record,
        "accounting_journal_ref": journal_ref,
    }


@router.get("/receipts")
async def list_receipts(recipient_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """List receipts. Non-owners can only view their own."""
    uid = str(current_user.get("user_id") or "").strip()
    receipts = db.get_records("SalaryReceipts", fresh=True) or []

    if not is_owner(current_user):
        # Strictly restricted to current user (including for PA)
        receipts = [r for r in receipts if str(r.get("recipient_id") or "").strip() == uid]
    elif recipient_id:
        receipts = [r for r in receipts if str(r.get("recipient_id") or "").strip() == recipient_id.strip()]

    receipts.sort(key=lambda x: str(x.get("payment_date") or ""), reverse=True)
    return receipts


@router.get("/receipts/{receipt_id}")
async def get_receipt(receipt_id: str, current_user: dict = Depends(get_current_user)):
    """Get single receipt by ID (Non-owners restricted to own receipt)."""
    uid = str(current_user.get("user_id") or "").strip()
    receipts = db.get_records("SalaryReceipts", fresh=True) or []
    target = next((r for r in receipts if str(r.get("receipt_id") or "").strip() == receipt_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Receipt not found.")

    if not is_owner(current_user) and str(target.get("recipient_id") or "").strip() != uid:
        raise HTTPException(status_code=403, detail="You can only view your own receipts.")

    return target


@router.get("/audit-logs")
async def list_workforce_audit_logs(current_user: dict = Depends(get_current_user)):
    """Audit logs for workforce actions (Owner only)."""
    require_owner(current_user)
    logs = db.get_records("WorkforceAuditLogs", fresh=True) or []
    logs.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return logs[:100]


# Backward compatibility aliases for internal references and tests
list_labour_workers = list_labour
get_payroll_items = get_payroll_run_items
list_audit_logs = list_workforce_audit_logs
list_workforce_employees = list_employees
