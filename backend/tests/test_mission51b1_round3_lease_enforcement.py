"""
Kawad Swad ERP — Mission 51B-1 Repair Round 3 Verification Suite (TX-AUDIT-04 & TX-AUDIT-05).

Direct SQLite-backed coordinator failure-injection tests covering EVERY mandatory case A through Q:
  - Case A: Valid current worker succeeds (expected_correlation_id, expected_attempt, expected_version, active lease)
  - Case B: Missing expected_correlation_id rejected (including exact Round 2 expired-lease bypass repro!)
  - Case C: Missing expected_attempt rejected (None and bool)
  - Case D: Missing expected_version rejected (None and bool)
  - Case E: Expired lease rejected (even with valid correlation_id, lease_owner, attempt, version)
  - Case F: Wrong worker rejected (WORKER-2 vs WORKER-1)
  - Case G: Persisted correlation_id mismatch rejected (even if lease_owner matches caller)
  - Case H: Persisted lease_owner mismatch rejected (even if correlation_id matches caller)
  - Case I: NULL / empty lease_owner rejected
  - Case J: NULL / empty / malformed lease_expires_at rejected
  - Case K: Wrong expected_attempt rejected
  - Case L: Wrong expected_version rejected
  - Case M: Stale worker after retry rejected (Worker 2's row completely untouched)
  - Case N: Stale worker after commit rejected (Worker 2's COMMITTED row completely untouched)
  - Case O: Exhaustive 16-column byte-for-byte zero-mutation audit across EVERY rejection vector
  - Case P: Concurrent race (valid vs stale & valid vs expired, threaded + multiprocessing) -> at most 1 valid winner
  - Case Q: Legitimate RECOVERY, SECONDARY_QUARANTINE, and RECONCILIATION transitions still succeed cleanly
  - Bonus Matrix Sweep: All 9 requires_lease_owner=True rules in LEGAL_TRANSITION_MATRIX reject omitted identity under ORDINARY
"""

import json
import multiprocessing
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

# Ensure backend root is importable
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import tests  # noqa: F401 - activates offline fastapi shim when fastapi is absent

from app.accounting.transaction_coordinator import TransactionCoordinator
from app.transaction_safety import (
    InvalidStateTransitionError,
    LEGAL_TRANSITION_MATRIX,
    TransactionState,
    TransitionAuthority,
    compute_deterministic_payload_hash,
)

# Exact 16 persisted columns verified byte-for-byte for zero mutation on EVERY rejection
AUDITED_DB_COLUMNS = (
    "lifecycle_state",
    "previous_state",
    "last_authority",
    "bridge_status",
    "failure_category",
    "error_code",
    "allocated_id",
    "correlation_id",
    "attempt_count",
    "version",
    "lease_owner",
    "lease_expires_at",
    "steps_json",
    "message",
    "recovery_decision",
    "updated_at",
)


def _mp_race_worker_commit(
    db_path: str,
    nonce: str,
    corr_id: str,
    attempt: int,
    version: int,
    allocated_id: str,
    barrier_file: str,
):
    """Top-level multiprocessing worker for Case P cross-process CAS verification."""
    coord = TransactionCoordinator(db_path=db_path, testing=True, auto_recover_stale_leases=False)
    deadline = time.time() + 5.0
    while not os.path.exists(barrier_file) and time.time() < deadline:
        time.sleep(0.01)
    try:
        res = coord.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id=allocated_id,
            message=f"Commit by {corr_id}",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=version,
            expected_correlation_id=corr_id,
            expected_attempt=attempt,
        )
        return ("OK", corr_id, (res or {}).get("allocated_id"), (res or {}).get("version"))
    except InvalidStateTransitionError as exc:
        return ("REJECTED", corr_id, exc.code, None)


class TestMission51B1Round3LeaseEnforcement(unittest.TestCase):
    """TX-AUDIT-04 & TX-AUDIT-05: Direct SQLite-backed Coordinator Lease & Worker Identity Tests A–Q."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_r3_lease_")
        self.db_path = os.path.join(self.tmp_dir, "coord_round3.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.payload_hash = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload={"amount": 1200, "voucher": "JV-R3-TEST"},
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _begin(self, nonce: str, corr_id: str = "WORKER-1", lease_seconds: int = 90):
        return self.coord.begin_governed_transaction(
            nonce=nonce,
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id=corr_id,
            lease_seconds=lease_seconds,
        )

    def _read_db_row(self, nonce: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (nonce,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def _raw_sql_update(self, sql: str, params: tuple):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _assert_zero_db_mutation(self, nonce: str, before_row: dict, label: str = ""):
        """Strictly verify all 16 persisted columns + full row dict remain byte-for-byte identical."""
        after_row = self._read_db_row(nonce)
        self.assertIsNotNone(after_row, f"[{label}] Row vanished unexpectedly for nonce={nonce}")
        for col in AUDITED_DB_COLUMNS:
            self.assertEqual(
                after_row[col],
                before_row[col],
                f"[{label}] Column '{col}' mutated on rejected transition! "
                f"before={before_row[col]!r}, after={after_row[col]!r}",
            )
        self.assertEqual(after_row, before_row, f"[{label}] Full persisted SQLite row mutated on rejection!")

    # ------------------------------------------------------------------
    # Case A: Valid current worker succeeds
    # ------------------------------------------------------------------
    def test_case_a_valid_current_worker_succeeds(self):
        status, tx = self._begin("NONCE-R3-A", corr_id="WORKER-1", lease_seconds=90)
        self.assertEqual(status, "ACQUIRED")
        self.assertEqual(tx["lifecycle_state"], "EXECUTING")
        self.assertEqual(tx["correlation_id"], "WORKER-1")
        self.assertEqual(tx["lease_owner"], "WORKER-1")
        self.assertEqual(tx["attempt_count"], 1)
        self.assertEqual(tx["version"], 1)
        self.assertIsNotNone(tx["lease_expires_at"])

        updated = self.coord.transition_governed_transaction(
            nonce="NONCE-R3-A",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-R3-A001",
            message="Valid active worker commit",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=1,
            expected_correlation_id="WORKER-1",
            expected_attempt=1,
        )
        self.assertIsNotNone(updated)
        row = self._read_db_row("NONCE-R3-A")
        self.assertEqual(row["lifecycle_state"], "COMMITTED")
        self.assertEqual(row["previous_state"], "EXECUTING")
        self.assertEqual(row["last_authority"], "ORDINARY")
        self.assertEqual(row["allocated_id"], "JV-R3-A001")
        self.assertEqual(row["version"], 2)
        self.assertIsNone(row["lease_owner"])
        self.assertIsNone(row["lease_expires_at"])

    # ------------------------------------------------------------------
    # Case B: Missing expected_correlation_id rejected (incl. exact Round 2 bypass repro!)
    # ------------------------------------------------------------------
    def test_case_b_missing_expected_correlation_id_rejected(self):
        # B1: Active lease but omitted / None / blank expected_correlation_id
        self._begin("NONCE-R3-B1", corr_id="WORKER-1", lease_seconds=90)
        before_b1 = self._read_db_row("NONCE-R3-B1")
        time.sleep(0.01)

        for bad_corr in (None, "", "   "):
            with self.subTest(bad_corr=bad_corr):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-B1",
                        lifecycle_state=TransactionState.COMMITTED,
                        bridge_status="CONFIRMED",
                        allocated_id="TEST-BYPASS-B1",
                        error_code="SHOULD_NOT_WRITE",
                        message="Attempted bypass without expected_correlation_id",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=1,
                        expected_correlation_id=bad_corr,
                        expected_attempt=1,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_WORKER_CORRELATION_ID")
                self._assert_zero_db_mutation("NONCE-R3-B1", before_b1, f"CaseB1 corr={bad_corr!r}")

        # B2: Exact verbatim Round 2 independent audit reproduction (expired lease + omitted correlation/attempt/version)
        self._begin("NONCE-R3-B2-EXACT-REPRO", corr_id="WORKER-1", lease_seconds=60)
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-B2-EXACT-REPRO"),
        )
        before_b2 = self._read_db_row("NONCE-R3-B2-EXACT-REPRO")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx_repro:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-B2-EXACT-REPRO",
                lifecycle_state="COMMITTED",
                bridge_status="CONFIRMED",
                allocated_id="TEST-1",
                authority="ORDINARY",
            )
        self.assertEqual(ctx_repro.exception.code, "MISSING_WORKER_CORRELATION_ID")
        self._assert_zero_db_mutation("NONCE-R3-B2-EXACT-REPRO", before_b2, "CaseB2-ExactRound2Repro")

    # ------------------------------------------------------------------
    # Case C: Missing expected_attempt rejected
    # ------------------------------------------------------------------
    def test_case_c_missing_expected_attempt_rejected(self):
        self._begin("NONCE-R3-C", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-C")
        time.sleep(0.01)

        for bad_attempt in (None, True, False):
            with self.subTest(bad_attempt=bad_attempt):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-C",
                        lifecycle_state=TransactionState.COMMITTED,
                        bridge_status="CONFIRMED",
                        allocated_id="TEST-C",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=1,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=bad_attempt,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_WORKER_ATTEMPT")
                self._assert_zero_db_mutation("NONCE-R3-C", before, f"CaseC attempt={bad_attempt!r}")

    # ------------------------------------------------------------------
    # Case D: Missing expected_version rejected
    # ------------------------------------------------------------------
    def test_case_d_missing_expected_version_rejected(self):
        self._begin("NONCE-R3-D", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-D")
        time.sleep(0.01)

        for bad_ver in (None, True, False):
            with self.subTest(bad_ver=bad_ver):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-D",
                        lifecycle_state=TransactionState.COMMITTED,
                        bridge_status="CONFIRMED",
                        allocated_id="TEST-D",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=bad_ver,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=1,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_EXPECTED_VERSION")
                self._assert_zero_db_mutation("NONCE-R3-D", before, f"CaseD version={bad_ver!r}")

    # ------------------------------------------------------------------
    # Case E: Expired lease rejected (even with valid worker identity)
    # ------------------------------------------------------------------
    def test_case_e_expired_lease_rejected_even_with_valid_worker_identity(self):
        self._begin("NONCE-R3-E", corr_id="WORKER-1", lease_seconds=60)
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-E"),
        )
        before = self._read_db_row("NONCE-R3-E")
        time.sleep(0.01)

        for target in (TransactionState.COMMITTED, TransactionState.FAILED, TransactionState.UNKNOWN):
            with self.subTest(target=target.value):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-E",
                        lifecycle_state=target,
                        bridge_status="CONFIRMED" if target == TransactionState.COMMITTED else "REJECTED",
                        allocated_id="TEST-EXPIRED",
                        error_code="SHOULD_NOT_MUTATE",
                        message="Expired worker attempt",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=1,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=1,
                    )
                self.assertEqual(ctx.exception.code, "STALE_LEASE_EXPIRED")
                self._assert_zero_db_mutation("NONCE-R3-E", before, f"CaseE target={target.value}")

    # ------------------------------------------------------------------
    # Case F: Wrong worker rejected (WORKER-2 vs WORKER-1)
    # ------------------------------------------------------------------
    def test_case_f_wrong_worker_rejected(self):
        self._begin("NONCE-R3-F", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-F")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-F",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="TEST-WRONG-WORKER",
                message="Impostor worker commit",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=1,
                expected_correlation_id="WORKER-2",
                expected_attempt=1,
            )
        self.assertEqual(ctx.exception.code, "STALE_WORKER_CORRELATION_MISMATCH")
        self._assert_zero_db_mutation("NONCE-R3-F", before, "CaseF-WrongWorker")

    # ------------------------------------------------------------------
    # Case G: Persisted correlation_id mismatch rejected (even if lease_owner matches caller)
    # ------------------------------------------------------------------
    def test_case_g_correlation_id_mismatch_rejected(self):
        self._begin("NONCE-R3-G", corr_id="WORKER-1", lease_seconds=90)
        # Corrupt/skew persisted correlation_id while leaving lease_owner = WORKER-1
        self._raw_sql_update(
            "UPDATE governed_transactions SET correlation_id = ? WHERE nonce = ?",
            ("WORKER-OTHER", "NONCE-R3-G"),
        )
        before = self._read_db_row("NONCE-R3-G")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-G",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="TEST-G",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=1,
                expected_correlation_id="WORKER-1",
                expected_attempt=1,
            )
        self.assertEqual(ctx.exception.code, "STALE_WORKER_CORRELATION_MISMATCH")
        self._assert_zero_db_mutation("NONCE-R3-G", before, "CaseG-CorrelationMismatch")

    # ------------------------------------------------------------------
    # Case H: Persisted lease_owner mismatch rejected (even if correlation_id matches caller)
    # ------------------------------------------------------------------
    def test_case_h_lease_owner_mismatch_rejected(self):
        self._begin("NONCE-R3-H", corr_id="WORKER-1", lease_seconds=90)
        # Skew lease_owner to WORKER-OTHER while keeping correlation_id = WORKER-1
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_owner = ? WHERE nonce = ?",
            ("WORKER-OTHER", "NONCE-R3-H"),
        )
        before = self._read_db_row("NONCE-R3-H")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-H",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="TEST-H",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=1,
                expected_correlation_id="WORKER-1",
                expected_attempt=1,
            )
        self.assertEqual(ctx.exception.code, "STALE_LEASE_OWNER")
        self._assert_zero_db_mutation("NONCE-R3-H", before, "CaseH-LeaseOwnerMismatch")

    # ------------------------------------------------------------------
    # Case I: NULL or blank lease_owner rejected
    # ------------------------------------------------------------------
    def test_case_i_null_and_empty_lease_owner_rejected(self):
        for idx, bad_owner in enumerate((None, "", "   ")):
            nonce = f"NONCE-R3-I-{idx}"
            self._begin(nonce, corr_id="WORKER-1", lease_seconds=90)
            self._raw_sql_update(
                "UPDATE governed_transactions SET lease_owner = ? WHERE nonce = ?",
                (bad_owner, nonce),
            )
            before = self._read_db_row(nonce)
            time.sleep(0.01)

            with self.subTest(bad_owner=bad_owner):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce=nonce,
                        lifecycle_state=TransactionState.COMMITTED,
                        bridge_status="CONFIRMED",
                        allocated_id="TEST-I",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=1,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=1,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_ACTIVE_LEASE_OWNER")
                self._assert_zero_db_mutation(nonce, before, f"CaseI owner={bad_owner!r}")

    # ------------------------------------------------------------------
    # Case J: NULL, empty, or malformed lease_expires_at rejected
    # ------------------------------------------------------------------
    def test_case_j_null_and_malformed_lease_expires_at_rejected(self):
        for idx, bad_exp in enumerate((None, "", "   ", "NOT-A-TIMESTAMP")):
            nonce = f"NONCE-R3-J-{idx}"
            self._begin(nonce, corr_id="WORKER-1", lease_seconds=90)
            self._raw_sql_update(
                "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
                (bad_exp, nonce),
            )
            before = self._read_db_row(nonce)
            time.sleep(0.01)

            with self.subTest(bad_exp=bad_exp):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce=nonce,
                        lifecycle_state=TransactionState.COMMITTED,
                        bridge_status="CONFIRMED",
                        allocated_id="TEST-J",
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=1,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=1,
                    )
                self.assertEqual(ctx.exception.code, "MISSING_OR_INVALID_LEASE_EXPIRATION")
                self._assert_zero_db_mutation(nonce, before, f"CaseJ lease_exp={bad_exp!r}")

    # ------------------------------------------------------------------
    # Case K: Wrong expected_attempt rejected
    # ------------------------------------------------------------------
    def test_case_k_wrong_expected_attempt_rejected(self):
        self._begin("NONCE-R3-K", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-K")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-K",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="TEST-K",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=1,
                expected_correlation_id="WORKER-1",
                expected_attempt=2,
            )
        self.assertEqual(ctx.exception.code, "STALE_WORKER_ATTEMPT_MISMATCH")
        self._assert_zero_db_mutation("NONCE-R3-K", before, "CaseK-WrongAttempt")

    # ------------------------------------------------------------------
    # Case L: Wrong expected_version rejected
    # ------------------------------------------------------------------
    def test_case_l_wrong_expected_version_rejected(self):
        self._begin("NONCE-R3-L", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-L")
        time.sleep(0.01)

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R3-L",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="TEST-L",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=99,
                expected_correlation_id="WORKER-1",
                expected_attempt=1,
            )
        self.assertEqual(ctx.exception.code, "CAS_VERSION_MISMATCH")
        self._assert_zero_db_mutation("NONCE-R3-L", before, "CaseL-WrongVersion")

    # ------------------------------------------------------------------
    # Case M: Stale worker after retry rejected (Worker 2's active lease untouched)
    # ------------------------------------------------------------------
    def test_case_m_stale_worker_after_retry_rejected_worker2_untouched(self):
        st1, tx1 = self._begin("NONCE-R3-M", corr_id="WORKER-1", lease_seconds=10)
        self.assertEqual(st1, "ACQUIRED")
        self.assertEqual(tx1["attempt_count"], 1)
        self.assertEqual(tx1["version"], 1)

        # Expire Worker 1's lease -> Worker 2 recovers UNKNOWN -> PENDING -> RETRY_ACQUIRED
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-M"),
        )
        st2, _ = self._begin("NONCE-R3-M", corr_id="WORKER-2")
        self.assertEqual(st2, "RECOVERY_CHECK_REQUIRED")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R3-M",
            lifecycle_state=TransactionState.PENDING,
            bridge_status="PENDING_UNKNOWN",
            authority=TransitionAuthority.RECOVERY,
            expected_from_state=TransactionState.UNKNOWN,
            actor="SYSTEM_RECOVERY",
            reason="Verified absent in Sheets before retry",
            evidence={"sheets_found": False},
        )
        st3, tx3 = self._begin("NONCE-R3-M", corr_id="WORKER-2", lease_seconds=120)
        self.assertEqual(st3, "RETRY_ACQUIRED")
        self.assertEqual(tx3["attempt_count"], 2)
        self.assertEqual(tx3["correlation_id"], "WORKER-2")
        self.assertEqual(tx3["lease_owner"], "WORKER-2")

        worker2_snapshot = self._read_db_row("NONCE-R3-M")
        time.sleep(0.01)

        # Stale Worker 1 attempts COMMITTED & FAILED with its old identity (and even guessing current version!)
        for target_state, guess_ver in [
            (TransactionState.COMMITTED, tx1["version"]),
            (TransactionState.FAILED, tx1["version"]),
            (TransactionState.COMMITTED, worker2_snapshot["version"]),
            (TransactionState.FAILED, worker2_snapshot["version"]),
            (TransactionState.COMMITTED, None),
        ]:
            with self.subTest(target=target_state.value, guess_ver=guess_ver):
                with self.assertRaises(InvalidStateTransitionError):
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-M",
                        lifecycle_state=target_state,
                        bridge_status="CONFIRMED" if target_state == TransactionState.COMMITTED else "REJECTED",
                        allocated_id="JV-STALE-W1",
                        error_code="STALE_W1_ERR",
                        message="Stale Worker 1 clobber attempt",
                        step_event={"step": "STALE_POISON"},
                        authority=TransitionAuthority.ORDINARY,
                        expected_from_state=TransactionState.EXECUTING,
                        expected_version=guess_ver,
                        expected_correlation_id="WORKER-1",
                        expected_attempt=1,
                    )
                self._assert_zero_db_mutation("NONCE-R3-M", worker2_snapshot, f"CaseM {target_state.value}/{guess_ver}")

    # ------------------------------------------------------------------
    # Case N: Stale worker after commit rejected (Worker 2's COMMITTED row untouched)
    # ------------------------------------------------------------------
    def test_case_n_stale_worker_after_commit_rejected(self):
        _, tx1 = self._begin("NONCE-R3-N", corr_id="WORKER-1", lease_seconds=10)
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-N"),
        )
        self._begin("NONCE-R3-N", corr_id="WORKER-2")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R3-N",
            lifecycle_state=TransactionState.PENDING,
            bridge_status="PENDING_UNKNOWN",
            authority=TransitionAuthority.RECOVERY,
            expected_from_state=TransactionState.UNKNOWN,
            actor="SYSTEM_RECOVERY",
            reason="Verified absent in Sheets",
            evidence={"sheets_found": False},
        )
        _, tx2 = self._begin("NONCE-R3-N", corr_id="WORKER-2", lease_seconds=120)
        self.coord.transition_governed_transaction(
            nonce="NONCE-R3-N",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-WINNER-W2",
            message="Worker 2 committed cleanly",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=tx2["version"],
            expected_correlation_id="WORKER-2",
            expected_attempt=2,
        )
        committed_snapshot = self._read_db_row("NONCE-R3-N")
        self.assertEqual(committed_snapshot["lifecycle_state"], "COMMITTED")
        self.assertEqual(committed_snapshot["allocated_id"], "JV-WINNER-W2")
        time.sleep(0.01)

        # Stale Worker 1 attempts FAILED, UNKNOWN, COMMITTED (with and without expected_from_state)
        for target in (TransactionState.FAILED, TransactionState.UNKNOWN, TransactionState.COMMITTED):
            for exp_from in (TransactionState.EXECUTING, None):
                with self.subTest(target=target.value, exp_from=exp_from):
                    with self.assertRaises(InvalidStateTransitionError):
                        self.coord.transition_governed_transaction(
                            nonce="NONCE-R3-N",
                            lifecycle_state=target,
                            bridge_status="REJECTED",
                            allocated_id="JV-STALE-OVERWRITE",
                            error_code="STALE_OVERWRITE",
                            message="Stale Worker 1 post-commit clobber",
                            step_event={"step": "POST_COMMIT_POISON"},
                            authority=TransitionAuthority.ORDINARY,
                            expected_from_state=exp_from,
                            expected_version=tx1["version"],
                            expected_correlation_id="WORKER-1",
                            expected_attempt=1,
                        )
                    self._assert_zero_db_mutation("NONCE-R3-N", committed_snapshot, f"CaseN {target.value}")

    # ------------------------------------------------------------------
    # Case O: Comprehensive 16-column zero-mutation verification across EVERY rejection vector
    # ------------------------------------------------------------------
    def test_case_o_all_16_columns_strictly_immutable_on_every_rejection_vector(self):
        self.assertEqual(len(AUDITED_DB_COLUMNS), 16)
        self._begin("NONCE-R3-O", corr_id="WORKER-1", lease_seconds=90)
        before = self._read_db_row("NONCE-R3-O")
        time.sleep(0.02)

        poison_payload = dict(
            bridge_status="CONFIRMED",
            failure_category="NETWORK_TIMEOUT",
            error_code="POISON_ERR",
            allocated_id="JV-POISON-999",
            message="POISONED_MESSAGE",
            recovery_decision="POISON_DECISION",
            step_event={"step": "POISON_STEP", "injected": True},
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
        )

        # Sequence of distinct rejection vectors all targeting the same active row
        vectors = [
            ("missing_corr", dict(expected_correlation_id=None, expected_attempt=1, expected_version=1)),
            ("blank_corr", dict(expected_correlation_id="  ", expected_attempt=1, expected_version=1)),
            ("missing_attempt", dict(expected_correlation_id="WORKER-1", expected_attempt=None, expected_version=1)),
            ("bool_attempt", dict(expected_correlation_id="WORKER-1", expected_attempt=True, expected_version=1)),
            ("missing_version", dict(expected_correlation_id="WORKER-1", expected_attempt=1, expected_version=None)),
            ("bool_version", dict(expected_correlation_id="WORKER-1", expected_attempt=1, expected_version=True)),
            ("wrong_worker", dict(expected_correlation_id="WORKER-99", expected_attempt=1, expected_version=1)),
            ("wrong_attempt", dict(expected_correlation_id="WORKER-1", expected_attempt=7, expected_version=1)),
            ("wrong_version", dict(expected_correlation_id="WORKER-1", expected_attempt=1, expected_version=7)),
        ]

        for name, kwargs in vectors:
            with self.subTest(vector=name):
                with self.assertRaises(InvalidStateTransitionError):
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R3-O",
                        lifecycle_state=TransactionState.COMMITTED,
                        **poison_payload,
                        **kwargs,
                    )
                self._assert_zero_db_mutation("NONCE-R3-O", before, f"CaseO-{name}")

        # Verify steps_json still has only the original acquisition entry
        self.assertEqual(json.loads(self._read_db_row("NONCE-R3-O")["steps_json"]), json.loads(before["steps_json"]))

    # ------------------------------------------------------------------
    # Case P: Concurrent race (valid vs stale AND valid vs expired; threads + OS processes)
    # ------------------------------------------------------------------
    def test_case_p_concurrent_race_valid_vs_stale_and_expired_workers(self):
        # P1 (Threaded): 1 valid current worker vs 4 stale/missing-identity/wrong-attempt/wrong-version workers
        self._begin("NONCE-R3-P1", corr_id="WORKER-VALID", lease_seconds=90)
        barrier = threading.Barrier(5)

        def run_worker(name, kwargs):
            barrier.wait()
            try:
                res = self.coord.transition_governed_transaction(
                    nonce="NONCE-R3-P1",
                    lifecycle_state=TransactionState.COMMITTED,
                    bridge_status="CONFIRMED",
                    allocated_id=f"JV-{name}",
                    message=f"Race from {name}",
                    authority=TransitionAuthority.ORDINARY,
                    expected_from_state=TransactionState.EXECUTING,
                    **kwargs,
                )
                return (name, "OK", (res or {}).get("allocated_id"))
            except InvalidStateTransitionError as exc:
                return (name, "REJECTED", exc.code)

        racers = [
            ("VALID", dict(expected_correlation_id="WORKER-VALID", expected_attempt=1, expected_version=1)),
            ("OMITTED_CORR", dict(expected_correlation_id=None, expected_attempt=1, expected_version=1)),
            ("STALE_WORKER", dict(expected_correlation_id="WORKER-STALE", expected_attempt=1, expected_version=1)),
            ("WRONG_ATTEMPT", dict(expected_correlation_id="WORKER-VALID", expected_attempt=9, expected_version=1)),
            ("WRONG_VERSION", dict(expected_correlation_id="WORKER-VALID", expected_attempt=1, expected_version=9)),
        ]
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = [f.result() for f in [pool.submit(run_worker, n, kw) for n, kw in racers]]

        winners = [r for r in results if r[1] == "OK"]
        self.assertEqual(len(winners), 1, f"Exactly 1 valid worker must win; got {results}")
        self.assertEqual(winners[0][0], "VALID")
        row_p1 = self._read_db_row("NONCE-R3-P1")
        self.assertEqual(row_p1["lifecycle_state"], "COMMITTED")
        self.assertEqual(row_p1["allocated_id"], "JV-VALID")
        self.assertEqual(row_p1["version"], 2)

        # P2 (Threaded): Expired lease — 4 competing workers (valid identity + omitted identity) -> 0 winners!
        self._begin("NONCE-R3-P2", corr_id="WORKER-EXPIRED", lease_seconds=60)
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-P2"),
        )
        before_p2 = self._read_db_row("NONCE-R3-P2")
        barrier2 = threading.Barrier(4)

        def run_expired_racer(name, kwargs):
            barrier2.wait()
            try:
                self.coord.transition_governed_transaction(
                    nonce="NONCE-R3-P2",
                    lifecycle_state=TransactionState.COMMITTED,
                    bridge_status="CONFIRMED",
                    allocated_id=f"JV-{name}",
                    authority=TransitionAuthority.ORDINARY,
                    expected_from_state=TransactionState.EXECUTING,
                    **kwargs,
                )
                return (name, "OK")
            except InvalidStateTransitionError as exc:
                return (name, exc.code)

        expired_racers = [
            ("EXP_VALID_1", dict(expected_correlation_id="WORKER-EXPIRED", expected_attempt=1, expected_version=1)),
            ("EXP_VALID_2", dict(expected_correlation_id="WORKER-EXPIRED", expected_attempt=1, expected_version=1)),
            ("EXP_NO_CORR", dict(expected_correlation_id=None, expected_attempt=1, expected_version=1)),
            ("EXP_NO_VER", dict(expected_correlation_id="WORKER-EXPIRED", expected_attempt=1, expected_version=None)),
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            exp_results = [f.result() for f in [pool.submit(run_expired_racer, n, kw) for n, kw in expired_racers]]
        self.assertEqual(sum(1 for r in exp_results if r[1] == "OK"), 0, f"Expired lease must have 0 winners: {exp_results}")
        self._assert_zero_db_mutation("NONCE-R3-P2", before_p2, "CaseP2-ExpiredRaceZeroWinners")

        # P3 (Cross-process multiprocessing): Valid worker process vs stale worker process
        self._begin("NONCE-R3-P3", corr_id="MP-VALID", lease_seconds=90)
        barrier_file = os.path.join(self.tmp_dir, "p3_go.flag")
        mp_ctx = multiprocessing.get_context("spawn")
        with mp_ctx.Pool(processes=2) as pool:
            a_valid = pool.apply_async(
                _mp_race_worker_commit,
                (self.db_path, "NONCE-R3-P3", "MP-VALID", 1, 1, "JV-MP-VALID", barrier_file),
            )
            a_stale = pool.apply_async(
                _mp_race_worker_commit,
                (self.db_path, "NONCE-R3-P3", "MP-STALE", 1, 1, "JV-MP-STALE", barrier_file),
            )
            time.sleep(0.15)
            with open(barrier_file, "w", encoding="utf-8") as fh:
                fh.write("GO")
            res_valid = a_valid.get(timeout=15)
            res_stale = a_stale.get(timeout=15)

        self.assertEqual(res_valid[0], "OK", f"Valid OS process must win; got {res_valid}, {res_stale}")
        self.assertEqual(res_stale[0], "REJECTED")
        row_p3 = self._read_db_row("NONCE-R3-P3")
        self.assertEqual(row_p3["lifecycle_state"], "COMMITTED")
        self.assertEqual(row_p3["allocated_id"], "JV-MP-VALID")
        self.assertEqual(row_p3["version"], 2)

    # ------------------------------------------------------------------
    # Case Q: Legitimate RECOVERY, SECONDARY_QUARANTINE, and RECONCILIATION transitions still work
    # ------------------------------------------------------------------
    def test_case_q_legitimate_recovery_quarantine_and_reconciliation_still_work(self):
        # Q1: RECOVERY authority on an expired EXECUTING row (EXECUTING -> UNKNOWN -> COMMITTED)
        self._begin("NONCE-R3-Q1", corr_id="WORKER-DEAD", lease_seconds=10)
        expired_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        self._raw_sql_update(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_ts, "NONCE-R3-Q1"),
        )
        # Recovery moves expired EXECUTING -> UNKNOWN without requiring active ordinary worker lease
        unk = self.coord.transition_governed_transaction(
            nonce="NONCE-R3-Q1",
            lifecycle_state=TransactionState.UNKNOWN,
            bridge_status="PENDING_UNKNOWN",
            error_code="STALE_EXECUTION_LEASE",
            message="Recovery detected expired lease",
            authority=TransitionAuthority.RECOVERY,
            expected_from_state=TransactionState.EXECUTING,
            actor="SYSTEM_RECOVERY",
            reason="Lease expired prior to confirmation",
            evidence={"expired_at": expired_ts},
            clear_lease=True,
        )
        self.assertEqual(unk["lifecycle_state"], "UNKNOWN")
        self.assertEqual(unk["last_authority"], "RECOVERY")

        # Recovery confirms UNKNOWN -> COMMITTED based on Google Sheets evidence
        confirmed = self.coord.transition_governed_transaction(
            nonce="NONCE-R3-Q1",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-REC-Q1",
            message="Recovered from Sheets IdAllocations + target row",
            authority=TransitionAuthority.RECOVERY,
            expected_from_state=TransactionState.UNKNOWN,
            actor="SYSTEM_RECOVERY",
            reason="Verified intact in Google Sheets",
            evidence={"allocated_id": "JV-REC-Q1", "lines_verified": True},
        )
        self.assertEqual(confirmed["lifecycle_state"], "COMMITTED")
        self.assertEqual(confirmed["allocated_id"], "JV-REC-Q1")

        # Q2: SECONDARY_QUARANTINE (COMMITTED -> RECOVERY_REQUIRED) + RECONCILIATION (RECOVERY_REQUIRED -> RECONCILED)
        quarantined = self.coord.transition_governed_transaction(
            nonce="NONCE-R3-Q1",
            lifecycle_state=TransactionState.RECOVERY_REQUIRED,
            bridge_status="RECOVERY_REQUIRED",
            error_code="SECONDARY_JOURNAL_FAILED",
            message="Primary committed; secondary journal failed",
            authority=TransitionAuthority.SECONDARY_QUARANTINE,
            expected_from_state=TransactionState.COMMITTED,
            actor="USR-OWNER-001",
            reason="Secondary accounting journal failed",
            evidence={"primary_id": "JV-REC-Q1"},
        )
        self.assertEqual(quarantined["lifecycle_state"], "RECOVERY_REQUIRED")

        reconciled = self.coord.mark_transaction_reconciled(
            nonce="NONCE-R3-Q1",
            actor_user_id="USR-OWNER-001",
            resolution_notes="Manually posted secondary journal and verified trial balance",
            final_allocated_id="JV-REC-Q1",
        )
        self.assertEqual(reconciled["lifecycle_state"], "RECONCILED")
        self.assertEqual(reconciled["last_authority"], "RECONCILIATION")

    # ------------------------------------------------------------------
    # Matrix Sweep: ALL 9 requires_lease_owner=True rules reject omitted identity under ORDINARY
    # ------------------------------------------------------------------
    def test_all_requires_lease_owner_rules_enforce_mandatory_identity_under_ordinary(self):
        lease_protected_rules = [
            (src, dst, rule)
            for (src, dst), rule in LEGAL_TRANSITION_MATRIX.items()
            if rule.requires_lease_owner and TransitionAuthority.ORDINARY in rule.allowed_authorities
        ]
        # Verify we cover all 9 lease-protected ordinary matrix rules
        self.assertEqual(len(lease_protected_rules), 9)

        for idx, (src, dst, rule) in enumerate(lease_protected_rules):
            nonce = f"NONCE-R3-MAT-{idx}"
            self._begin(nonce, corr_id="WORKER-MAT", lease_seconds=90)
            # Position row in exact source state (INITIATED / VALIDATING / EXECUTING) with active lease
            self._raw_sql_update(
                "UPDATE governed_transactions SET lifecycle_state = ? WHERE nonce = ?",
                (src.value, nonce),
            )
            before = self._read_db_row(nonce)
            with self.subTest(transition=f"{src.value}->{dst.value}"):
                # Omitting expected_correlation_id MUST be rejected with ZERO DB mutation
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce=nonce,
                        lifecycle_state=dst,
                        bridge_status="CONFIRMED" if dst == TransactionState.COMMITTED else "REJECTED",
                        allocated_id="JV-MAT-BYPASS" if dst == TransactionState.COMMITTED else None,
                        authority=TransitionAuthority.ORDINARY,
                        reason="Matrix sweep check",
                        evidence={"sweep": True},
                    )
                self.assertEqual(ctx.exception.code, "MISSING_WORKER_CORRELATION_ID")
                self._assert_zero_db_mutation(nonce, before, f"MatrixSweep-{src.value}->{dst.value}")


if __name__ == "__main__":
    unittest.main()
