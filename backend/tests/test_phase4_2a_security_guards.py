"""Regression tests for Phase 4.2-A security guards."""
import os
os.environ.setdefault("SALES_TESTING", "1")

import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import app.routers.auth as auth_router
import app.routers.audit as audit_router
import app.routers.approvals as approvals_router
import app.routers.users as users_router


class TestPublicBootstrapDisabled(unittest.TestCase):
    def test_no_public_owner_bootstrap_route(self):
        paths = [getattr(route, "path", "") for route in auth_router.router.routes]
        self.assertFalse(any("bootstrap-owner" in path for path in paths))


class TestAuditGuards(unittest.TestCase):
    def test_pa_cannot_read_audit_log(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(audit_router.list_audit_logs(current_user={"user_id": "pa-1", "role": "PA"}))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_client_authored_audit_post_is_gone(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(audit_router.create_audit_log(current_user={"user_id": "owner-1", "role": "OWNER"}))
        self.assertEqual(ctx.exception.status_code, 410)


class TestUserDirectoryRedaction(unittest.TestCase):
    def test_pa_gets_minimal_directory_not_contact_or_notes(self):
        users = [{
            "user_id": "USR-000001",
            "full_name": "Employee One",
            "username": "employee.one",
            "role": "SALESMAN",
            "mobile": "9876543210",
            "email": "employee@example.com",
            "active": True,
            "created_at": "2026-11-18T00:00:00Z",
            "notes": "Confidential note",
        }]
        with patch.object(users_router, "get_all_users_with_auth", return_value=users):
            result = asyncio.run(users_router.list_users(current_user={"user_id": "pa-1", "role": "PA"}))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].full_name, "Employee One")
        self.assertEqual(result[0].mobile, "")
        self.assertEqual(result[0].email, "")
        self.assertEqual(result[0].username, "")
        self.assertEqual(result[0].notes, "")

    def test_owner_retains_full_directory_view(self):
        users = [{
            "user_id": "USR-000001",
            "full_name": "Employee One",
            "username": "employee.one",
            "role": "SALESMAN",
            "mobile": "9876543210",
            "email": "employee@example.com",
            "active": True,
            "created_at": "2026-11-18T00:00:00Z",
            "notes": "Owner-only note",
        }]
        with patch.object(users_router, "get_all_users_with_auth", return_value=users):
            result = asyncio.run(users_router.list_users(current_user={"user_id": "owner-1", "role": "OWNER"}))
        self.assertEqual(result[0].mobile, "9876543210")
        self.assertEqual(result[0].email, "employee@example.com")


class TestApprovalGuards(unittest.TestCase):
    def test_sensitive_payload_fields_are_redacted(self):
        payload = {
            "full_name": "Employee One",
            "role": "SALESMAN",
            "mobile": "9876543210",
            "bank_details": {"account_number": "1234567890", "ifsc": "BANK0001"},
            "emergency_contact": {"mobile": "9999999999"},
            "password": "never-return-this",
        }
        redacted = json.loads(approvals_router._redact_approval_payload(json.dumps(payload)))
        self.assertEqual(redacted["full_name"], "Employee One")
        self.assertEqual(redacted["mobile"], "[REDACTED]")
        self.assertEqual(redacted["bank_details"], "[REDACTED]")
        self.assertEqual(redacted["emergency_contact"], "[REDACTED]")
        self.assertEqual(redacted["password"], "[REDACTED]")

    def test_pa_approval_list_redacts_sensitive_payload(self):
        rows = [{
            "request_id": "REQ-000001",
            "request_type": "CREATE_USER",
            "target_user_id": "",
            "requested_by": "pa-1",
            "requested_by_name": "PA",
            "requested_at": "2026-11-18T00:00:00Z",
            "payload_json": json.dumps({"full_name": "Employee One", "bank_details": "private"}),
            "status": "PENDING",
        }]
        with patch.object(approvals_router.db, "get_records", return_value=rows):
            result = asyncio.run(approvals_router.list_approval_requests(current_user={"user_id": "pa-1", "role": "PA"}))
        payload = json.loads(result[0].payload_json)
        self.assertEqual(payload["full_name"], "Employee One")
        self.assertEqual(payload["bank_details"], "[REDACTED]")

    def test_failed_execution_cannot_be_retried_automatically(self):
        rows = [{"request_id": "REQ-000001", "status": "EXECUTION_FAILED"}]
        with (
            patch.object(approvals_router.db, "get_records", return_value=rows),
            patch.object(approvals_router, "_run_request_execution", side_effect=AssertionError("must not execute")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(approvals_router.retry_failed_execution(
                    "REQ-000001", current_user={"user_id": "owner-1", "role": "OWNER"}
                ))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_review_required_request_cannot_be_decided_again(self):
        rows = [{"request_id": "REQ-000001", "status": "EXECUTION_REVIEW_REQUIRED"}]
        with (
            patch.object(approvals_router.db, "get_records", return_value=rows),
            patch.object(approvals_router, "_run_request_execution", side_effect=AssertionError("must not execute")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(approvals_router.decide_approval_request(
                    "REQ-000001",
                    approvals_router.ApprovalDecisionRequest(decision="APPROVED"),
                    current_user={"user_id": "owner-1", "role": "OWNER"},
                ))
        self.assertEqual(ctx.exception.status_code, 409)


class TestPrivateEmployeeFields(unittest.TestCase):
    def test_pa_create_request_does_not_include_private_or_compensation_fields(self):
        captured = {}
        class FakeRequest:
            request_id = "REQ-NEW"

        def fake_create_approval_request(**kwargs):
            captured.update(kwargs)
            return FakeRequest()

        req = users_router.UserCreate(
            username="new.staff",
            full_name="New Staff",
            role="SALESMAN",
            mobile="9876543210",
            email="staff@example.com",
            salary_frequency="MONTHLY",
            salary_structure_id="SST-001",
            address="Private address",
            emergency_contact="Private contact",
            bank_details="Private bank",
            notes="Private note",
        )
        with (
            patch.object(users_router, "validate_unique_username"),
            patch.object(users_router, "create_approval_request", side_effect=fake_create_approval_request),
        ):
            result = asyncio.run(users_router.create_user(
                req, current_user={"user_id": "pa-1", "full_name": "PA", "role": "PA"}
            ))

        self.assertTrue(result["pending_approval"])
        payload = captured["payload"]
        for key in (
            "mobile", "email", "salary_frequency", "salary_structure_id",
            "address", "emergency_contact", "bank_details", "notes",
        ):
            self.assertEqual(payload[key], "", f"{key} must not be included in a PA request")

    def test_pa_update_request_drops_private_fields(self):
        captured = {}
        class FakeRequest:
            request_id = "REQ-UPD"

        def fake_create_approval_request(**kwargs):
            captured.update(kwargs)
            return FakeRequest()

        req = users_router.UserUpdate(
            full_name="Updated Name",
            mobile="9876543210",
            email="staff@example.com",
            salary_structure_id="SST-001",
            bank_details="Private bank",
        )
        with (
            patch.object(users_router, "_get_target_user_role", return_value="SALESMAN"),
            patch.object(users_router, "create_approval_request", side_effect=fake_create_approval_request),
        ):
            result = asyncio.run(users_router.update_user(
                "USR-000001", req, current_user={"user_id": "pa-1", "full_name": "PA", "role": "PA"}
            ))
        self.assertTrue(result["pending_approval"])
        self.assertEqual(captured["payload"], {"full_name": "Updated Name"})


class TestApprovalExecutionClaim(unittest.TestCase):
    def test_action_failure_is_marked_for_manual_reconciliation(self):
        rows = [{
            "request_id": "REQ-000009",
            "request_type": "UPDATE_USER",
            "target_user_id": "USR-000001",
            "requested_by": "pa-1",
            "payload_json": "{}",
            "status": "PENDING",
        }]
        updates = []
        def fake_update(tab, key, value, values, **kwargs):
            updates.append(dict(values))
            return True

        with (
            patch.object(approvals_router.db, "get_records", return_value=rows),
            patch.object(approvals_router.db, "update_record", side_effect=fake_update),
            patch.object(approvals_router.db, "log_audit"),
            patch.object(approvals_router, "_run_request_execution", side_effect=RuntimeError("simulated ambiguous write")),
        ):
            result = asyncio.run(approvals_router.decide_approval_request(
                "REQ-000009",
                approvals_router.ApprovalDecisionRequest(decision="APPROVED"),
                current_user={"user_id": "owner-1", "role": "OWNER"},
            ))

        self.assertEqual([u.get("status") for u in updates], ["EXECUTING", "EXECUTION_REVIEW_REQUIRED"])
        self.assertEqual(result.status, "EXECUTION_REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
