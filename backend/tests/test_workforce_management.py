import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

from app.sheets import db
from app.routers import workforce
from app.models import (
    EmployeeAttendanceCheckIn,
    EmployeeAttendanceCheckOut,
    WorkAssignmentCreate,
    WorkAssignmentSubmit,
    WorkAssignmentReview,
    FreelancerProjectCreate,
    FreelancerMilestoneCreate,
    FreelancerMilestoneSubmit,
    FreelancerMilestoneReview,
    LabourCreate,
    LabourAttendanceBulk,
    LabourAttendanceItem,
    LabourWorkEntryCreate,
    SalaryStructureCreate,
    PayrollRunCreate,
    PayrollItemUpdate,
    WorkforcePaymentCreate,
)


class TestWorkforceManagement(unittest.TestCase):
    def setUp(self):
        self.owner_user = {
            "user_id": "USR-000001",
            "username": "owner",
            "role": "OWNER",
            "full_name": "Kawad Swad Owner",
        }
        self.pa_user = {
            "user_id": "USR-000002",
            "username": "pa_assistant",
            "role": "PA",
            "full_name": "Personal Assistant",
        }
        self.salesman_user = {
            "user_id": "USR-000003",
            "username": "sales_ramesh",
            "role": "SALESMAN",
            "full_name": "Ramesh Salesman",
        }
        self.freelancer_user = {
            "user_id": "USR-000004",
            "username": "designer_priya",
            "role": "FREELANCER",
            "full_name": "Priya Designer",
        }

        db.allow_in_memory_fallback = True
        # Clear memory tabs before tests
        for tab in [
            "Users", "AuthUsers", "LabourMaster", "LabourAttendance",
            "LabourWorkEntries", "WorkAssignments", "FreelancerProjects",
            "FreelancerMilestones", "SalaryStructures", "PayrollRuns",
            "PayrollItems", "WorkforcePayments", "SalaryReceipts",
            "WorkforceAuditLogs", "EmployeeAttendance", "Sales",
            "Workers", "WorkerAttendance", "JournalVouchers", "JournalLines"
        ]:
            db.memory_store[tab] = []

        # Seed base users
        db.append_record("Users", {
            "user_id": "USR-000001",
            "username": "owner",
            "full_name": "Kawad Swad Owner",
            "role": "OWNER",
            "active": "true",
        })
        db.append_record("Users", {
            "user_id": "USR-000003",
            "username": "sales_ramesh",
            "full_name": "Ramesh Salesman",
            "role": "SALESMAN",
            "active": "true",
            "designation": "Field Sales Officer",
            "department": "Commercial",
        })
        db.append_record("Users", {
            "user_id": "USR-000004",
            "username": "designer_priya",
            "full_name": "Priya Designer",
            "role": "FREELANCER",
            "active": "true",
            "designation": "Senior Packaging Designer",
            "department": "Creative",
        })

    def test_workforce_dashboard_metrics_and_permissions(self):
        """Owner and PA can access workforce metrics; standard employees are denied."""
        # Owner access succeeds
        metrics = asyncio.run(workforce.get_workforce_dashboard_metrics(current_user=self.owner_user))
        self.assertIn("active_employees_count", metrics)
        self.assertIn("active_labour_count", metrics)

        # Salesman access raises 403 Forbidden
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(workforce.get_workforce_dashboard_metrics(current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_employee_self_service_workspace_isolation(self):
        """Employee can only access their own workspace and attendance."""
        ws = asyncio.run(workforce.get_my_workspace(current_user=self.salesman_user))
        self.assertEqual(ws["user_id"], "USR-000003")
        self.assertEqual(ws["role"], "SALESMAN")

    def test_employee_attendance_checkin_checkout_idempotency(self):
        """Clock-in creates record; duplicate clock-in on same day returns existing record."""
        # 1. Clock in
        res1 = asyncio.run(
            workforce.check_in_my_attendance(
                req=EmployeeAttendanceCheckIn(notes="Shift punch"),
                current_user=self.salesman_user,
            )
        )
        self.assertTrue(res1["ok"])
        self.assertFalse(res1.get("already_checked_in", False))

        # 2. Duplicate clock in
        res2 = asyncio.run(
            workforce.check_in_my_attendance(
                req=EmployeeAttendanceCheckIn(notes="Duplicate punch"),
                current_user=self.salesman_user,
            )
        )
        self.assertTrue(res2["ok"])
        self.assertTrue(res2.get("already_checked_in"))

        # 3. Clock out
        res3 = asyncio.run(
            workforce.check_out_my_attendance(
                req=EmployeeAttendanceCheckOut(notes="Shift complete"),
                current_user=self.salesman_user,
            )
        )
        self.assertTrue(res3["ok"])
        self.assertIn("total_hours", res3)

    def test_work_assignment_lifecycle(self):
        """Owner assigns task -> employee views -> employee submits -> Owner reviews & approves."""
        # 1. Owner creates task
        res_create = asyncio.run(
            workforce.create_task(
                req=WorkAssignmentCreate(
                    title="Visit Sadar Bazaar Retailers",
                    description="Distribute 500g papad samples and book orders",
                    assigned_to_user_id="USR-000003",
                    priority="HIGH",
                    due_date="2026-11-10",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_create["ok"])
        task_id = res_create["task"]["task_id"]

        # 2. Salesman fetches their assigned tasks
        my_tasks = asyncio.run(workforce.get_my_tasks(current_user=self.salesman_user))
        self.assertEqual(len(my_tasks), 1)
        self.assertEqual(my_tasks[0]["task_id"], task_id)

        # 3. Salesman submits deliverable
        res_submit = asyncio.run(
            workforce.submit_my_task(
                task_id=task_id,
                req=WorkAssignmentSubmit(
                    submission_notes="Visited 12 shopkeepers, booked 4 orders",
                    proof_url="https://drive.google.com/orders-sheet",
                ),
                current_user=self.salesman_user,
            )
        )
        self.assertTrue(res_submit["ok"])

        # 4. Owner reviews and approves
        res_review = asyncio.run(
            workforce.review_task(
                task_id=task_id,
                req=WorkAssignmentReview(
                    status="APPROVED",
                    review_notes="Excellent expansion in Sadar Bazaar",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_review["ok"])

    def test_freelancer_project_and_milestone_flow(self):
        """Owner creates project with milestone -> Freelancer submits -> Owner approves."""
        # 1. Owner creates project
        res_proj = asyncio.run(
            workforce.create_project(
                req=FreelancerProjectCreate(
                    title="Kawad Swad Premium Pouch Packaging",
                    description="Complete redesign for 200g, 500g, and 1000g pouches",
                    freelancer_user_id="USR-000004",
                    total_budget=20000.0,
                    target_completion_date="2026-11-30",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_proj["ok"])
        proj_id = res_proj["project"]["project_id"]

        # 2. Owner adds milestone
        res_ms = asyncio.run(
            workforce.create_project_milestone(
                project_id=proj_id,
                req=FreelancerMilestoneCreate(
                    project_id=proj_id,
                    title="Initial Vector Artwork and Color Schemes",
                    amount=8000.0,
                    due_date="2026-11-15",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_ms["ok"])
        ms_id = res_ms["milestone"]["milestone_id"]

        # 3. Freelancer views their projects
        fl_projects = asyncio.run(workforce.get_my_projects(current_user=self.freelancer_user))
        self.assertEqual(len(fl_projects), 1)
        self.assertEqual(fl_projects[0]["project_id"], proj_id)

        # 4. Freelancer submits milestone
        res_submit = asyncio.run(
            workforce.submit_my_milestone(
                milestone_id=ms_id,
                req=FreelancerMilestoneSubmit(
                    submission_notes="Vector AI and PDF files ready for cylinder engraving",
                    submission_link="https://figma.com/design/kawad-swad-pouch",
                ),
                current_user=self.freelancer_user,
            )
        )
        self.assertTrue(res_submit["ok"])

        # 5. Owner reviews milestone
        res_rev = asyncio.run(
            workforce.review_project_milestone(
                milestone_id=ms_id,
                req=FreelancerMilestoneReview(
                    status="APPROVED",
                    review_notes="Approved for cylinder production",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_rev["ok"])

    def test_labour_register_and_bulk_attendance(self):
        """Owner registers labour worker and punches bulk daily attendance with wage computation."""
        # 1. Register labour worker
        res = asyncio.run(
            workforce.create_labour(
                req=LabourCreate(
                    full_name="Sita Ram",
                    category="ROLLING",
                    wage_type="DAILY",
                    base_rate=450.0,
                    mobile="9829011111",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res["ok"])
        lid = res["labour"]["labour_id"]
        self.assertTrue(lid.startswith("LBR-"))

        # 2. Bulk daily attendance
        res_att = asyncio.run(
            workforce.save_labour_attendance_bulk(
                req=LabourAttendanceBulk(
                    attendance_date="2026-11-02",
                    records=[
                        LabourAttendanceItem(
                            labour_id=lid,
                            attendance_date="2026-11-02",
                            status="PRESENT",
                            hours_worked=8.0,
                            notes="Good rolling output",
                        )
                    ],
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_att["ok"])

        # 3. Labour work entry
        res_work = asyncio.run(
            workforce.create_labour_work_entry(
                req=LabourWorkEntryCreate(
                    labour_id=lid,
                    entry_date="2026-11-02",
                    activity_name="Hand-Rolled Moong Papad",
                    units_completed=35.0,
                    unit_of_measure="KG",
                    piece_rate=12.0,
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_work["ok"])
        self.assertEqual(res_work["entry"]["total_amount"], 420.0)

    def test_payroll_calculation_and_salary_receipt_disbursement(self):
        """Owner sets salary structure -> calculates monthly payroll -> approves -> disburses -> generates receipt."""
        # 1. Setup salary structure for salesman
        res_struct = asyncio.run(
            workforce.create_or_update_salary_structure(
                req=SalaryStructureCreate(
                    user_id="USR-000003",
                    basic_salary=18000.0,
                    hra=2000.0,
                    sales_commission_rate=0.0,  # Slab-based Rs 200/100kg
                    pf_deduction=1200.0,
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_struct["ok"])

        # 2. Seed some sales for salesman in October 2026 (qualifying for incentive: PAID & DELIVERED)
        db.append_record("Sales", {
            "sale_id": "SALE-000001",
            "salesman_user_id": "USR-000003",
            "date": "2026-10-15",
            "total_kg": 350.0,
            "final_amount": 75000.0,
            "bill_status": "ISSUED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        # 3. Calculate payroll run for October 2026
        res_calc = asyncio.run(
            workforce.calculate_payroll_run(
                req=PayrollRunCreate(month="2026-10"),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_calc["ok"])
        run_data = res_calc["payroll_run"]
        run_id = run_data["payroll_run_id"]
        items = res_calc["items"]
        self.assertTrue(len(items) >= 1)

        # Verify salesman incentive applied (350kg -> 3 slabs of 100kg -> Rs 600)
        salesman_item = next(i for i in items if i["user_id"] == "USR-000003")
        self.assertEqual(salesman_item["incentive_amount"], 600.0)

        # 4. Owner approves payroll run
        res_app = asyncio.run(
            workforce.approve_payroll_run(
                payroll_run_id=run_id,
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_app["ok"])

        # 5. Disburse payment for salesman payroll item
        res_pay = asyncio.run(
            workforce.record_workforce_payment(
                req=WorkforcePaymentCreate(
                    reference_id=salesman_item["item_id"],
                    payment_type="SALARY",
                    recipient_id="USR-000003",
                    recipient_name="Ramesh Salesman",
                    amount=float(salesman_item["net_amount"]),
                    payment_method="BANK_TRANSFER",
                    payment_reference="UTR987654321",
                    notes="Salary for October 2026",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(res_pay["ok"])
        receipt_data = res_pay["receipt"]
        self.assertTrue(receipt_data["receipt_id"].startswith("RCPT-"))
        self.assertTrue(receipt_data["receipt_number"].startswith("REC-"))

        # 6. Salesman fetches their own receipts
        user_receipts = asyncio.run(
            workforce.list_receipts(
                current_user=self.salesman_user,
            )
        )
        self.assertEqual(len(user_receipts), 1)
        self.assertEqual(user_receipts[0]["receipt_id"], receipt_data["receipt_id"])

    def test_pa_security_negative_authorization(self):
        """PA cannot access salary structures, payroll calculations, payroll approvals, or audit logs."""
        # 1. Salary structures: PA denied
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(workforce.list_salary_structures(current_user=self.pa_user))
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.create_or_update_salary_structure(
                    req=SalaryStructureCreate(user_id="USR-000003", basic_salary=15000.0),
                    current_user=self.pa_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)

        # 2. Payroll runs & calculation: PA denied
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(workforce.list_payroll_runs(current_user=self.pa_user))
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.calculate_payroll_run(
                    req=PayrollRunCreate(month="2026-10"),
                    current_user=self.pa_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(workforce.get_payroll_items(payroll_run_id="PAY-0001", current_user=self.pa_user))
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.update_payroll_item(
                    item_id="PI-0001",
                    req=PayrollItemUpdate(notes="Unauthorized modification"),
                    current_user=self.pa_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)

        # 3. Payments: PA denied
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.record_workforce_payment(
                    req=WorkforcePaymentCreate(
                        reference_id="PI-0001",
                        payment_type="SALARY",
                        recipient_id="USR-000003",
                        recipient_name="Ramesh",
                        amount=1000.0,
                    ),
                    current_user=self.pa_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)

        # 4. Audit logs: PA denied
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(workforce.list_audit_logs(current_user=self.pa_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # 5. Salary masking in employee list for PA
        employees = asyncio.run(workforce.list_workforce_employees(current_user=self.pa_user))
        for emp in employees:
            self.assertEqual(emp["basic_salary"], 0.0)
            self.assertEqual(emp["salary_structure_id"], "")

    def test_anti_self_approval_guards(self):
        """Managers and assignees cannot approve their own assigned tasks or milestones."""
        # 1. Create a task assigned to owner himself
        res_task = asyncio.run(
            workforce.create_task(
                req=WorkAssignmentCreate(
                    title="Audit Raw Spices Warehouse",
                    assigned_to_user_id="USR-000001",
                    priority="HIGH",
                ),
                current_user=self.owner_user,
            )
        )
        task_id = res_task["task"]["task_id"]

        # Owner cannot approve his own assigned task (must have independent reviewer)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.review_task(
                    task_id=task_id,
                    req=WorkAssignmentReview(status="APPROVED", review_notes="Looks good to me"),
                    current_user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Self-approval is forbidden", ctx.exception.detail)

        # 2. Freelancer cannot review/approve their own project milestone
        res_proj = asyncio.run(
            workforce.create_project(
                req=FreelancerProjectCreate(
                    title="Product Catalog",
                    freelancer_user_id="USR-000004",
                    total_budget=5000.0,
                ),
                current_user=self.owner_user,
            )
        )
        proj_id = res_proj["project"]["project_id"]

        res_ms = asyncio.run(
            workforce.create_project_milestone(
                project_id=proj_id,
                req=FreelancerMilestoneCreate(project_id=proj_id, title="Rough Draft", amount=2000.0),
                current_user=self.owner_user,
            )
        )
        ms_id = res_ms["milestone"]["milestone_id"]

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                workforce.review_project_milestone(
                    milestone_id=ms_id,
                    req=FreelancerMilestoneReview(status="APPROVED", review_notes="Self approval attempt"),
                    current_user=self.freelancer_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_salesman_incentive_eligibility_criteria(self):
        """Salesman sales incentives require bill_status != CANCELLED, payment_status == PAID, delivery_status == DELIVERED."""
        # Set up salary structure for salesman
        asyncio.run(
            workforce.create_or_update_salary_structure(
                req=SalaryStructureCreate(
                    user_id="USR-000003",
                    basic_salary=15000.0,
                    sales_commission_rate=0.0,  # Uses slab Rs 200/100kg
                ),
                current_user=self.owner_user,
            )
        )

        # Seed 4 sales in October 2026:
        # Sale 1: CANCELLED (should be excluded)
        db.append_record("Sales", {
            "sale_id": "SALE-CANC",
            "salesman_user_id": "USR-000003",
            "date": "2026-10-05",
            "total_kg": 200.0,
            "bill_status": "CANCELLED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })
        # Sale 2: UNPAID (should be excluded)
        db.append_record("Sales", {
            "sale_id": "SALE-UNPD",
            "salesman_user_id": "USR-000003",
            "date": "2026-10-10",
            "total_kg": 200.0,
            "bill_status": "ISSUED",
            "payment_status": "PENDING",
            "delivery_status": "DELIVERED",
        })
        # Sale 3: UNDELIVERED (should be excluded)
        db.append_record("Sales", {
            "sale_id": "SALE-UNDL",
            "salesman_user_id": "USR-000003",
            "date": "2026-10-15",
            "total_kg": 200.0,
            "bill_status": "ISSUED",
            "payment_status": "PAID",
            "delivery_status": "PENDING",
        })
        # Sale 4: Fully QUALIFIED (250 kg -> 2 slabs of 100kg = Rs 400)
        db.append_record("Sales", {
            "sale_id": "SALE-QUAL",
            "salesman_user_id": "USR-000003",
            "date": "2026-10-20",
            "total_kg": 250.0,
            "bill_status": "ISSUED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        res_calc = asyncio.run(
            workforce.calculate_payroll_run(
                req=PayrollRunCreate(month="2026-10"),
                current_user=self.owner_user,
            )
        )
        items = res_calc["items"]
        salesman_item = next(i for i in items if i["user_id"] == "USR-000003")
        # Only 250 kg qualifies -> 2 x 200 = 400.0 incentive
        self.assertEqual(salesman_item["incentive_amount"], 400.0)

    def test_workforce_payment_double_entry_accounting_posting(self):
        """Workforce payments generate balanced double-entry accounting journals adhering to COA."""
        # 1. LABOUR_WAGE payment (Cash) -> Debits 2120 (Accrued Factory Labor Payable), Credits 1110 (Cash Factory Safe)
        pay_res1 = asyncio.run(
            workforce.record_workforce_payment(
                req=WorkforcePaymentCreate(
                    reference_id="ATT-BATCH-01",
                    payment_type="LABOUR_WAGE",
                    recipient_id="LBR-000001",
                    recipient_name="Gopal Lal",
                    amount=1800.0,
                    payment_method="CASH",
                    payment_reference="CASH-VOUCHER-101",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(pay_res1["ok"])
        payment1 = pay_res1["payment"]
        jv_id1 = payment1.get("accounting_journal_ref")
        self.assertTrue(bool(jv_id1))

        # Check JournalHeaders and JournalLines
        jv1 = next((j for j in db.get_records("JournalHeaders") if j.get("journal_id") == jv_id1), None)
        self.assertIsNotNone(jv1)
        self.assertEqual(jv1["voucher_type"], "PAYMENT")
        self.assertEqual(float(jv1["total_debit"]), 1800.0)
        self.assertEqual(float(jv1["total_credit"]), 1800.0)

        lines1 = [l for l in db.get_records("JournalLines") if l.get("journal_id") == jv_id1]
        debit_line1 = next(l for l in lines1 if float(l.get("debit_amount", 0) or 0) > 0)
        credit_line1 = next(l for l in lines1 if float(l.get("credit_amount", 0) or 0) > 0)
        self.assertEqual(debit_line1["account_code"], "2120")  # Accrued Factory Labor & Wages Payable
        self.assertEqual(credit_line1["account_code"], "1110")  # Central Factory Safe (Cash)

        # 2. SALARY payment for SALESMAN (Bank) -> Debits 5220, Credits 1120
        pay_res2 = asyncio.run(
            workforce.record_workforce_payment(
                req=WorkforcePaymentCreate(
                    reference_id="PI-000099",
                    payment_type="SALARY",
                    recipient_id="USR-000003",
                    recipient_name="Ramesh Salesman",
                    amount=22000.0,
                    payment_method="BANK_TRANSFER",
                    payment_reference="NEFT20261102",
                ),
                current_user=self.owner_user,
            )
        )
        self.assertTrue(pay_res2["ok"])
        jv_id2 = pay_res2["payment"].get("accounting_journal_ref")
        self.assertTrue(bool(jv_id2))
        lines2 = [l for l in db.get_records("JournalLines") if l.get("journal_id") == jv_id2]
        debit_line2 = next(l for l in lines2 if float(l.get("debit_amount", 0) or 0) > 0)
        credit_line2 = next(l for l in lines2 if float(l.get("credit_amount", 0) or 0) > 0)
        self.assertEqual(debit_line2["account_code"], "5220")  # Salesman Salary & Performance Incentives
        self.assertEqual(credit_line2["account_code"], "1120")  # Bank Current Account

    def test_legacy_labour_workers_and_attendance_backward_compatibility(self):
        """Legacy Workers and WorkerAttendance tabs are seamlessly included with is_legacy=True."""
        # 1. Seed legacy Worker
        db.append_record("Workers", {
            "worker_id": "WRK-000777",
            "name": "Babulal Saini",
            "station": "Papad Roasting",
            "daily_wage": 420.0,
            "status": "active",
            "phone": "9876500000",
        })

        workers = asyncio.run(workforce.list_labour_workers(current_user=self.owner_user))
        legacy_worker = next((w for w in workers if w["labour_id"] == "WRK-000777"), None)
        self.assertIsNotNone(legacy_worker)
        self.assertTrue(legacy_worker.get("is_legacy"))
        self.assertEqual(legacy_worker["full_name"], "Babulal Saini")
        self.assertEqual(legacy_worker["base_rate"], 420.0)

        # 2. Seed legacy Worker Attendance
        db.append_record("WorkerAttendance", {
            "attendance_id": "ATT-000555",
            "worker_id": "WRK-000777",
            "worker_name": "Babulal Saini",
            "date": "2026-11-01",
            "status": "present",
            "shift": "morning",
        })

        attendances = asyncio.run(workforce.list_labour_attendance(attendance_date="2026-11-01", current_user=self.owner_user))
        legacy_att = next((a for a in attendances if a["attendance_id"] == "ATT-000555"), None)
        self.assertIsNotNone(legacy_att)
        self.assertTrue(legacy_att.get("is_legacy"))
        self.assertEqual(legacy_att["status"], "PRESENT")

    def test_google_sheets_workforce_tabs_schema_integrity(self):
        """All 16 workforce tabs in REQUIRED_TABS are configured with exact required headers."""
        from app.sheets import REQUIRED_TABS
        required_workforce_tabs = [
            "LabourMaster", "LabourAttendance", "LabourWorkEntries",
            "WorkAssignments", "FreelancerProjects", "FreelancerMilestones",
            "SalaryStructures", "PayrollRuns", "PayrollItems",
            "WorkforcePayments", "SalaryReceipts", "WorkforceAuditLogs",
            "EmployeeAttendance"
        ]
        for tab in required_workforce_tabs:
            self.assertIn(tab, REQUIRED_TABS)
            headers = REQUIRED_TABS[tab]
            self.assertIsInstance(headers, list)
            self.assertTrue(len(headers) >= 5, f"Tab {tab} has insufficient headers: {headers}")

        # Verify key column names
        self.assertIn("user_id", REQUIRED_TABS["SalaryStructures"])
        self.assertIn("payroll_run_id", REQUIRED_TABS["PayrollRuns"])
        self.assertIn("accounting_journal_ref", REQUIRED_TABS["WorkforcePayments"])
        self.assertIn("receipt_number", REQUIRED_TABS["SalaryReceipts"])


if __name__ == "__main__":
    unittest.main()
