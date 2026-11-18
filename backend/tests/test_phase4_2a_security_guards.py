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


if __name__ == "__main__":
    unittest.main()
