"""Tests for token revocation logging, persistence failure handling, and in-memory blacklist."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from app.auth import (
    create_access_token,
    revoke_token,
    revoke_all_user_sessions,
    is_token_revoked,
    _REVOKED_TOKENS,
    _USER_REVOKED_AT,
)
from app.sheets import db


class TokenRevocationTests(unittest.TestCase):
    def setUp(self):
        db.is_connected = False
        db._fail_once.clear()
        for key in list(db.memory_store):
            db.memory_store[key] = []
        db.memory_store["RevokedTokens"] = []
        db.memory_store["AuthUsers"] = [{
            "auth_id": "AUTH-000001",
            "user_id": "USR-REV-01",
            "username": "testuser",
            "password_hash": "hash",
            "role": "SALESMAN",
            "active": "true",
            "must_change_password": "false",
        }]
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

    def test_revoke_token_successful(self):
        token = create_access_token({"sub": "USR-REV-01", "role": "SALESMAN"})
        self.assertFalse(is_token_revoked(token))

        success = revoke_token(token, "USR-REV-01", reason="User logout")
        self.assertTrue(success)
        self.assertTrue(is_token_revoked(token))
        self.assertEqual(len(db.memory_store["RevokedTokens"]), 1)
        self.assertEqual(db.memory_store["RevokedTokens"][0]["user_id"], "USR-REV-01")

    def test_revoke_token_persistence_failure_soft(self):
        token = create_access_token({"sub": "USR-REV-01", "role": "SALESMAN"})

        with patch("app.sheets.db.append_record", side_effect=RuntimeError("Google Sheets network timeout")):
            with self.assertLogs("kawad_swad.auth", level="ERROR") as cm:
                success = revoke_token(token, "USR-REV-01", reason="User logout", raise_on_failure=False)
                self.assertFalse(success)
                # Confirm logging occurred and did NOT leak raw token in log message
                self.assertTrue(any("Failed to persist token revocation for user USR-REV-01" in log for log in cm.output))
                self.assertFalse(any(token in log for log in cm.output))

        # Crucially, in-memory revocation still took effect to protect user session
        self.assertTrue(is_token_revoked(token))

    def test_revoke_token_persistence_failure_strict(self):
        token = create_access_token({"sub": "USR-REV-01", "role": "SALESMAN"})

        with patch("app.sheets.db.append_record", side_effect=RuntimeError("Hard disk write error")):
            with self.assertRaises(RuntimeError):
                revoke_token(token, "USR-REV-01", reason="Admin revocation", raise_on_failure=True)

        # In-memory revocation still took effect immediately
        self.assertTrue(is_token_revoked(token))

    def test_revoke_all_user_sessions_persistence_failure_soft(self):
        with patch("app.sheets.db.update_record", side_effect=RuntimeError("Sheets quota exceeded")):
            with self.assertLogs("kawad_swad.auth", level="ERROR") as cm:
                success = revoke_all_user_sessions("USR-REV-01", raise_on_failure=False)
                self.assertFalse(success)
                self.assertTrue(any("Failed to persist user-wide revocation for USR-REV-01" in log for log in cm.output))

        # In-memory revocation timestamp is set
        self.assertIn("usr-rev-01", _USER_REVOKED_AT)


if __name__ == "__main__":
    unittest.main()
