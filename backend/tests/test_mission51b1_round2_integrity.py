"""
Kawad Swad ERP — Mission 51B-1 Repair Round 2 Verification Suite.

Covers every mandatory audit requirement from Mission 51B-1 Repair Round 2:
1. TX-AUDIT-01 — Transaction State-Transition Integrity (Tests A through M):
   - Legal transition EXECUTING -> COMMITTED (actual DB verification)
   - Rejected illegal transitions COMMITTED -> FAILED, COMMITTED -> EXECUTING, COMMITTED -> INITIATED
   - Strict immutability of RECONCILED against ordinary, recovery, and reconciliation calls
   - RECOVERY_REQUIRED cannot be bypassed by ordinary retry or ORDINARY authority
   - Concurrent worker races (commit vs fail, commit vs commit, fail vs fail) via atomic CAS
   - Stale worker (old correlation_id / attempt_count / expired lease) late failure rejected
   - CAS expected_from_state & expected_version enforcement
   - Constrained RECOVERY & SECONDARY_QUARANTINE authority paths require actor + evidence/reason
   - Rejected transition leaves DB metadata, error_code, allocated_id, version, updated_at, steps_json untouched
   - Repeated invalid transitions do not corrupt steps_json or history
   - Terminal protection survives coordinator restart

2. TX-AUDIT-02 — Transaction Coordinator Durability & Restart Safety (Tests 1 through 14):
   - Restart with preserved SQLite WAL DB retains transaction state, idempotency key, payload hash, terminal state
   - Startup stale-lease recovery automatically transitions expired EXECUTING leases to UNKNOWN
   - Production fails closed on missing TRANSACTION_DB_PATH, volatile /tmp or :memory: path, missing/unwritable dir,
     and horizontal scaling (instance_count > 1)
   - Governed bridge writes fail closed (HTTP 503, 0 gateway POSTs) when coordinator directory becomes unavailable
   - Two separate OS processes (`multiprocessing`) contend concurrently on same coordinator DB with atomic CAS isolation
   - Stale worker resuming after another worker commits is rejected cleanly without mutating DB
   - Post-coordinator-loss recovery: deleting/wiping local SQLite DB and re-presenting the same nonce inspects
     authoritative Google Sheets `IdAllocations` and auto-confirms (or quarantines orphan allocation) with 0 duplicate POSTs

3. TX-AUDIT-03 — Package Hygiene & Configuration Integrity:
   - Confirms accidental AI Studio prompt upload is removed and unreferenced across the repository
   - Confirms render.yaml & .env.example configure persistent disk and single-instance guards
   - Verifies scripts/verify_package_hygiene.py passes clean archives and rejects polluted archives
"""

import io
import json
import multiprocessing
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Ensure backend root is importable
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import tests  # noqa: F401 - activates offline fastapi shim when fastapi is absent

from app import apps_script_bridge as bridge_mod
from app import config as config_mod
from app import sheets as sheets_mod
from app.accounting import transaction_coordinator as tc_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.apps_script_bridge import AppsScriptBridge
from app.transaction_safety import (
    CoordinatorDurabilityError,
    CoordinatorDurabilityMode,
    InvalidStateTransitionError,
    LEGAL_TRANSITION_MATRIX,
    TERMINAL_STATES,
    TransactionState,
    TransitionAuthority,
    compute_deterministic_payload_hash,
    get_legal_transition_matrix_summary,
    validate_coordinator_durability,
    validate_state_transition,
)
from scripts.verify_package_hygiene import audit_zip_archive


def _mp_worker_race_acquire(db_path: str, nonce: str, payload_hash: str, worker_id: str, barrier_file: str):
    """Top-level multiprocessing worker for Test #11 (real cross-process SQLite WAL CAS)."""
    coord = TransactionCoordinator(db_path=db_path, testing=True, auto_recover_stale_leases=False)
    # Wait briefly until both processes have opened coordinator
    deadline = time.time() + 5.0
    while not os.path.exists(barrier_file) and time.time() < deadline:
        time.sleep(0.01)
    status, tx = coord.begin_governed_transaction(
        nonce=nonce,
        action="POST_JOURNAL_VOUCHER",
        target_tab="JournalHeaders",
        actor_user_id="USR-OWNER-001",
        payload_hash=payload_hash,
        correlation_id=f"CORR-MP-{worker_id}",
    )
    if status == "ACQUIRED":
        coord.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id=f"JV-MP-{worker_id}",
            message=f"Committed by {worker_id}",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id=f"CORR-MP-{worker_id}",
            expected_attempt=1,
        )
    return (worker_id, status, tx.get("lifecycle_state"))


def _mp_worker_transition_race(db_path: str, nonce: str, target_state: str, corr_id: str, expected_ver: int):
    """Top-level multiprocessing worker attempting a competing CAS transition."""
    coord = TransactionCoordinator(db_path=db_path, testing=True, auto_recover_stale_leases=False)
    try:
        res = coord.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=target_state,
            bridge_status="CONFIRMED" if target_state == "COMMITTED" else "REJECTED",
            allocated_id="JV-RACE-001" if target_state == "COMMITTED" else None,
            message=f"Transition to {target_state}",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=expected_ver,
            expected_correlation_id=corr_id,
            expected_attempt=1,
        )
        return ("OK", target_state, (res or {}).get("lifecycle_state"))
    except InvalidStateTransitionError as exc:
        return ("REJECTED", target_state, exc.code)


class _FakeHTTPResponse:
    def __init__(self, body_obj):
        self._raw = (body_obj if isinstance(body_obj, str) else json.dumps(body_obj)).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeOpener:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self._lock = threading.Lock()

    def open(self, req, timeout=15):
        envelope = json.loads(req.data.decode("utf-8"))
        with self._lock:
            self.calls.append(envelope)
            call_no = len(self.calls)
        return self.handler(envelope, call_no)


class TestMission51B1Round2StateIntegrity(unittest.TestCase):
    """TX-AUDIT-01: Mandatory State-Transition Integrity Tests A through M."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_r2_state_")
        self.db_path = os.path.join(self.tmp_dir, "coord_state.db")
        self.coord = TransactionCoordinator(db_path=self.db_path, testing=True)
        self.payload_hash = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload={"amount": 500, "item": "Dal"},
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _begin(self, nonce: str, corr_id: str = "CORR-W1", lease_seconds: int = 90):
        status, tx = self.coord.begin_governed_transaction(
            nonce=nonce,
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id=corr_id,
            lease_seconds=lease_seconds,
        )
        return status, tx

    def _read_db_row(self, nonce: str):
        """Read actual persisted row straight from SQLite to guarantee DB-level verification."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (nonce,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    # Test A: Legal transition EXECUTING -> COMMITTED succeeds
    def test_a_legal_executing_to_committed_succeeds_in_db(self):
        status, tx = self._begin("NONCE-R2-A", corr_id="CORR-A1")
        self.assertEqual(status, "ACQUIRED")
        self.assertEqual(tx["lifecycle_state"], "EXECUTING")
        self.assertEqual(tx["version"], 1)

        updated = self.coord.transition_governed_transaction(
            nonce="NONCE-R2-A",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000101",
            message="Committed and verified",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=1,
            expected_correlation_id="CORR-A1",
            expected_attempt=1,
        )
        self.assertIsNotNone(updated)
        db_row = self._read_db_row("NONCE-R2-A")
        self.assertEqual(db_row["lifecycle_state"], "COMMITTED")
        self.assertEqual(db_row["previous_state"], "EXECUTING")
        self.assertEqual(db_row["last_authority"], "ORDINARY")
        self.assertEqual(db_row["allocated_id"], "JV-000101")
        self.assertEqual(db_row["version"], 2)
        self.assertIsNone(db_row["lease_expires_at"])
        self.assertIsNone(db_row["lease_owner"])

    # Test B: Illegal transition COMMITTED -> FAILED is rejected (EXACT Round 1 defect!)
    def test_b_illegal_committed_to_failed_rejected_and_db_unchanged(self):
        self._begin("NONCE-R2-B", corr_id="CORR-B1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-B",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000102",
            message="Committed cleanly",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-B1",
            expected_attempt=1,
        )
        before = self._read_db_row("NONCE-R2-B")

        for auth in TransitionAuthority:
            with self.subTest(authority=auth.value):
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R2-B",
                        lifecycle_state=TransactionState.FAILED,
                        bridge_status="REJECTED",
                        error_code="LATE_FAILURE",
                        message="Attempted overwrite of committed tx",
                        authority=auth,
                        actor="USR-OWNER-001",
                        reason="Attempted downgrade",
                        evidence={"forced": True},
                    )
                self.assertEqual(ctx.exception.code, "TERMINAL_STATE_PROTECTED")

        after = self._read_db_row("NONCE-R2-B")
        self.assertEqual(after, before)
        self.assertEqual(after["lifecycle_state"], "COMMITTED")

    # Test C: Illegal transition COMMITTED -> EXECUTING is rejected
    def test_c_illegal_committed_to_executing_rejected(self):
        self._begin("NONCE-R2-C", corr_id="CORR-C1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-C",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000103",
            message="Committed",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-C1",
            expected_attempt=1,
        )
        before = self._read_db_row("NONCE-R2-C")
        for auth in TransitionAuthority:
            with self.assertRaises(InvalidStateTransitionError):
                self.coord.transition_governed_transaction(
                    nonce="NONCE-R2-C",
                    lifecycle_state=TransactionState.EXECUTING,
                    bridge_status="PENDING_UNKNOWN",
                    authority=auth,
                    actor="USR-OWNER-001",
                    reason="Illegal re-execution",
                )
        self.assertEqual(self._read_db_row("NONCE-R2-C"), before)

    # Test D: Illegal transition COMMITTED -> INITIATED (and VALIDATING/PENDING/UNKNOWN/RECONCILED) rejected
    def test_d_illegal_committed_to_initiated_and_other_forbidden_targets_rejected(self):
        self._begin("NONCE-R2-D", corr_id="CORR-D1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-D",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000104",
            message="Committed",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-D1",
            expected_attempt=1,
        )
        before = self._read_db_row("NONCE-R2-D")
        forbidden_targets = [
            TransactionState.INITIATED,
            TransactionState.VALIDATING,
            TransactionState.PENDING,
            TransactionState.EXECUTING,
            TransactionState.FAILED,
            TransactionState.UNKNOWN,
            TransactionState.RECONCILED,
            TransactionState.COMMITTED,
        ]
        for dst in forbidden_targets:
            with self.subTest(target=dst.value):
                with self.assertRaises(InvalidStateTransitionError):
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R2-D",
                        lifecycle_state=dst,
                        bridge_status="REJECTED",
                        authority=TransitionAuthority.RECOVERY,
                        actor="USR-OWNER-001",
                        reason="Attempted illegal transition",
                        evidence={"test": True},
                    )
        self.assertEqual(self._read_db_row("NONCE-R2-D"), before)

    # Test E: RECONCILED cannot be overwritten by ordinary execution, recovery, or reconciliation
    def test_e_reconciled_is_strictly_immutable(self):
        self._begin("NONCE-R2-E", corr_id="CORR-E1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-E",
            lifecycle_state=TransactionState.UNKNOWN,
            bridge_status="PENDING_UNKNOWN",
            error_code="TIMEOUT",
            message="Timed out",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-E1",
            expected_attempt=1,
        )
        rec = self.coord.mark_transaction_reconciled(
            nonce="NONCE-R2-E",
            actor_user_id="USR-OWNER-001",
            resolution_notes="Verified intact in Google Sheets",
            final_allocated_id="JV-000105",
        )
        self.assertEqual(rec["lifecycle_state"], "RECONCILED")
        before = self._read_db_row("NONCE-R2-E")

        for dst in TransactionState:
            for auth in TransitionAuthority:
                with self.assertRaises(InvalidStateTransitionError) as ctx:
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R2-E",
                        lifecycle_state=dst,
                        bridge_status="CONFIRMED",
                        authority=auth,
                        actor="USR-OWNER-001",
                        reason="Attempted overwrite of RECONCILED",
                        evidence={"force": True},
                    )
                self.assertEqual(ctx.exception.code, "TERMINAL_STATE_IMMUTABLE")

        # Also cannot re-acquire via begin_governed_transaction (returns ALREADY_COMMITTED)
        gate_status, tx = self._begin("NONCE-R2-E", corr_id="CORR-E2")
        self.assertEqual(gate_status, "ALREADY_COMMITTED")
        self.assertEqual(tx["lifecycle_state"], "RECONCILED")
        self.assertEqual(self._read_db_row("NONCE-R2-E"), before)

    # Test F: RECOVERY_REQUIRED cannot be bypassed by ordinary retry
    def test_f_recovery_required_cannot_be_bypassed_by_ordinary_retry(self):
        self._begin("NONCE-R2-F", corr_id="CORR-F1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-F",
            lifecycle_state=TransactionState.RECOVERY_REQUIRED,
            bridge_status="RECOVERY_REQUIRED",
            error_code="PARTIAL_WRITE",
            message="Missing child lines",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-F1",
            expected_attempt=1,
            reason="Missing JournalLines",
            evidence={"missing_rows": 2},
        )
        before = self._read_db_row("NONCE-R2-F")

        # Ordinary retry via begin_governed_transaction MUST NOT acquire EXECUTING
        gate_status, tx = self._begin("NONCE-R2-F", corr_id="CORR-F2")
        self.assertEqual(gate_status, "RECOVERY_CHECK_REQUIRED")
        self.assertEqual(tx["lifecycle_state"], "RECOVERY_REQUIRED")

        # Direct transition attempts under ORDINARY or RETRY authority MUST fail
        for dst, auth in [
            (TransactionState.EXECUTING, TransitionAuthority.RETRY),
            (TransactionState.EXECUTING, TransitionAuthority.ORDINARY),
            (TransactionState.PENDING, TransitionAuthority.RECOVERY),
            (TransactionState.FAILED, TransitionAuthority.ORDINARY),
            (TransactionState.FAILED, TransitionAuthority.RECOVERY),
            (TransactionState.COMMITTED, TransitionAuthority.ORDINARY),
            (TransactionState.UNKNOWN, TransitionAuthority.RECOVERY),
        ]:
            with self.subTest(dst=dst.value, auth=auth.value):
                with self.assertRaises(InvalidStateTransitionError):
                    self.coord.transition_governed_transaction(
                        nonce="NONCE-R2-F",
                        lifecycle_state=dst,
                        bridge_status="REJECTED",
                        authority=auth,
                        actor="USR-OWNER-001",
                        reason="Attempted bypass",
                        evidence={"bypass": True},
                    )
        self.assertEqual(self._read_db_row("NONCE-R2-F"), before)

    # Test G: Two competing workers attempt transitions concurrently
    def test_g_competing_workers_concurrent_transitions_atomic_cas(self):
        self._begin("NONCE-R2-G", corr_id="CORR-G1")
        barrier = threading.Barrier(2)

        def attempt_commit():
            barrier.wait()
            try:
                self.coord.transition_governed_transaction(
                    nonce="NONCE-R2-G",
                    lifecycle_state=TransactionState.COMMITTED,
                    bridge_status="CONFIRMED",
                    allocated_id="JV-G-001",
                    message="Worker committed",
                    authority=TransitionAuthority.ORDINARY,
                    expected_from_state=TransactionState.EXECUTING,
                    expected_version=1,
                    expected_correlation_id="CORR-G1",
                    expected_attempt=1,
                )
                return ("COMMIT", "OK")
            except InvalidStateTransitionError as exc:
                return ("COMMIT", exc.code)

        def attempt_fail():
            barrier.wait()
            try:
                self.coord.transition_governed_transaction(
                    nonce="NONCE-R2-G",
                    lifecycle_state=TransactionState.FAILED,
                    bridge_status="REJECTED",
                    error_code="COMPETING_FAIL",
                    message="Worker failed",
                    authority=TransitionAuthority.ORDINARY,
                    expected_from_state=TransactionState.EXECUTING,
                    expected_version=1,
                    expected_correlation_id="CORR-G1",
                    expected_attempt=1,
                )
                return ("FAIL", "OK")
            except InvalidStateTransitionError as exc:
                return ("FAIL", exc.code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt_commit)
            f2 = pool.submit(attempt_fail)
            r1, r2 = f1.result(), f2.result()

        outcomes = [r1[1], r2[1]]
        self.assertEqual(outcomes.count("OK"), 1, f"Exactly one transition must win CAS; got {r1}, {r2}")
        db_row = self._read_db_row("NONCE-R2-G")
        self.assertEqual(db_row["version"], 2)
        if r1[1] == "OK":
            self.assertEqual(db_row["lifecycle_state"], "COMMITTED")
        else:
            self.assertEqual(db_row["lifecycle_state"], "FAILED")

    # Test H: Stale worker attempts late failure after newer worker already committed
    def test_h_stale_worker_late_failure_after_newer_worker_commit_rejected(self):
        # Worker 1 acquires attempt 1
        st1, tx1 = self._begin("NONCE-R2-H", corr_id="CORR-STALE-1", lease_seconds=5)
        self.assertEqual(st1, "ACQUIRED")
        self.assertEqual(tx1["attempt_count"], 1)

        # Simulate lease expiration in DB so Worker 2 recovers and commits
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?", (past, "NONCE-R2-H"))
        conn.commit()
        conn.close()

        # Worker 2 sees expired lease -> RECOVERY_CHECK_REQUIRED (UNKNOWN) -> PENDING -> RETRY_ACQUIRED -> COMMITTED
        st2, _ = self._begin("NONCE-R2-H", corr_id="CORR-FRESH-2")
        self.assertEqual(st2, "RECOVERY_CHECK_REQUIRED")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-H",
            lifecycle_state=TransactionState.PENDING,
            bridge_status="PENDING_UNKNOWN",
            authority=TransitionAuthority.RECOVERY,
            expected_from_state=TransactionState.UNKNOWN,
            actor="SYSTEM_RECOVERY",
            reason="Verified absent in Sheets",
            evidence={"alloc_match": False},
        )
        st3, tx3 = self._begin("NONCE-R2-H", corr_id="CORR-FRESH-2")
        self.assertEqual(st3, "RETRY_ACQUIRED")
        self.assertEqual(tx3["attempt_count"], 2)

        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-H",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-FRESH-200",
            message="Fresh worker committed",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-FRESH-2",
            expected_attempt=2,
        )
        committed_snapshot = self._read_db_row("NONCE-R2-H")

        # Now stale Worker 1 wakes up and tries late FAILED transition!
        with self.assertRaises(InvalidStateTransitionError):
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-H",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                error_code="STALE_TIMEOUT",
                message="Stale worker woke up late",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_correlation_id="CORR-STALE-1",
                expected_attempt=1,
            )

        # Also test stale worker trying late failure while Worker 2 is STILL EXECUTING (before commit)
        self._begin("NONCE-R2-H2", corr_id="CORR-OLD-1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-H2",
            lifecycle_state=TransactionState.FAILED,
            bridge_status="REJECTED",
            message="Clean failure attempt 1",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-OLD-1",
            expected_attempt=1,
        )
        self._begin("NONCE-R2-H2", corr_id="CORR-NEW-2")
        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-H2",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                message="Old worker clobber attempt",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_correlation_id="CORR-OLD-1",
                expected_attempt=1,
            )
        self.assertEqual(ctx.exception.code, "STALE_WORKER_CORRELATION_MISMATCH")
        self.assertEqual(self._read_db_row("NONCE-R2-H"), committed_snapshot)
        self.assertEqual(self._read_db_row("NONCE-R2-H2")["lifecycle_state"], "EXECUTING")

    # Test I: CAS expected-state and expected-version validation rejects stale transition
    def test_i_cas_expected_state_and_version_validation(self):
        self._begin("NONCE-R2-I", corr_id="CORR-I1")
        with self.assertRaises(InvalidStateTransitionError) as ctx_state:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-I",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.PENDING,
            )
        self.assertEqual(ctx_state.exception.code, "CAS_STATE_MISMATCH")

        with self.assertRaises(InvalidStateTransitionError) as ctx_ver:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-I",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                authority=TransitionAuthority.ORDINARY,
                expected_from_state=TransactionState.EXECUTING,
                expected_version=99,
            )
        self.assertEqual(ctx_ver.exception.code, "CAS_VERSION_MISMATCH")
        self.assertEqual(self._read_db_row("NONCE-R2-I")["lifecycle_state"], "EXECUTING")
        self.assertEqual(self._read_db_row("NONCE-R2-I")["version"], 1)

    # Test J: Recovery-authorized & secondary-quarantine transitions follow only permitted paths
    def test_j_recovery_and_secondary_quarantine_authority_paths(self):
        self._begin("NONCE-R2-J", corr_id="CORR-J1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-J",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="INV-000501",
            message="Sale committed",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-J1",
            expected_attempt=1,
        )

        # COMMITTED -> RECOVERY_REQUIRED MUST fail without SECONDARY_QUARANTINE authority
        with self.assertRaises(InvalidStateTransitionError) as ctx_ord:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-J",
                lifecycle_state=TransactionState.RECOVERY_REQUIRED,
                bridge_status="RECOVERY_REQUIRED",
                authority=TransitionAuthority.ORDINARY,
                actor="USR-OWNER-001",
                reason="Missing authority",
            )
        self.assertEqual(ctx_ord.exception.code, "TERMINAL_STATE_PROTECTED")

        # COMMITTED -> RECOVERY_REQUIRED MUST fail under SECONDARY_QUARANTINE if actor or evidence missing
        with self.assertRaises(InvalidStateTransitionError) as ctx_no_actor:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-J",
                lifecycle_state=TransactionState.RECOVERY_REQUIRED,
                bridge_status="RECOVERY_REQUIRED",
                authority=TransitionAuthority.SECONDARY_QUARANTINE,
                expected_from_state=TransactionState.COMMITTED,
                reason="Secondary journal failed",
                evidence={"sale_id": "INV-000501"},
            )
        self.assertEqual(ctx_no_actor.exception.code, "TRANSITION_ACTOR_REQUIRED")

        with self.assertRaises(InvalidStateTransitionError) as ctx_no_ev:
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-J",
                lifecycle_state=TransactionState.RECOVERY_REQUIRED,
                bridge_status="RECOVERY_REQUIRED",
                authority=TransitionAuthority.SECONDARY_QUARANTINE,
                expected_from_state=TransactionState.COMMITTED,
                actor="USR-OWNER-001",
            )
        self.assertEqual(ctx_no_ev.exception.code, "TRANSITION_EVIDENCE_REQUIRED")

        # With SECONDARY_QUARANTINE + actor + reason/evidence -> permitted and audited!
        quarantined = self.coord.transition_governed_transaction(
            nonce="NONCE-R2-J",
            lifecycle_state=TransactionState.RECOVERY_REQUIRED,
            bridge_status="RECOVERY_REQUIRED",
            error_code="SECONDARY_JOURNAL_POSTING_FAILED",
            message="Sale committed; secondary journal failed",
            authority=TransitionAuthority.SECONDARY_QUARANTINE,
            expected_from_state=TransactionState.COMMITTED,
            actor="USR-OWNER-001",
            reason="Secondary post_sale_journal failed",
            evidence={"sale_id": "INV-000501", "error": "Journal bridge timeout"},
        )
        self.assertEqual(quarantined["lifecycle_state"], "RECOVERY_REQUIRED")
        self.assertEqual(quarantined["previous_state"], "COMMITTED")
        self.assertEqual(quarantined["last_authority"], "SECONDARY_QUARANTINE")

        # Owner reconciliation RECOVERY_REQUIRED -> RECONCILED succeeds
        reconciled = self.coord.mark_transaction_reconciled(
            nonce="NONCE-R2-J",
            actor_user_id="USR-OWNER-001",
            resolution_notes="Posted missing accounting journal manually and verified balance",
            final_allocated_id="INV-000501",
        )
        self.assertEqual(reconciled["lifecycle_state"], "RECONCILED")
        self.assertEqual(reconciled["last_authority"], "RECONCILIATION")

    # Test K: Rejected transition does NOT mutate transaction metadata, error fields, or history
    def test_k_rejected_transition_causes_zero_db_mutation(self):
        self._begin("NONCE-R2-K", corr_id="CORR-K1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-K",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000333",
            message="Original confirmed message",
            result_snapshot={"journal_id": "JV-000333", "amount": 500},
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-K1",
            expected_attempt=1,
        )
        before = self._read_db_row("NONCE-R2-K")
        time.sleep(0.02)

        with self.assertRaises(InvalidStateTransitionError):
            self.coord.transition_governed_transaction(
                nonce="NONCE-R2-K",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                failure_category="NETWORK_TIMEOUT",
                error_code="CORRUPT_OVERWRITE",
                allocated_id="JV-WRONG",
                message="Poisoned error message",
                recovery_decision="BAD_DECISION",
                step_event={"step": "POISON_STEP"},
                authority=TransitionAuthority.ORDINARY,
            )

        after = self._read_db_row("NONCE-R2-K")
        self.assertEqual(after, before)
        self.assertEqual(after["message"], "Original confirmed message")
        self.assertIsNone(after["error_code"])
        self.assertEqual(after["allocated_id"], "JV-000333")
        self.assertEqual(after["steps_json"], before["steps_json"])
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(after["version"], before["version"])

    # Test L: Repeated invalid transition attempts do not corrupt transaction history or steps
    def test_l_repeated_invalid_transitions_do_not_corrupt_steps_json(self):
        self._begin("NONCE-R2-L", corr_id="CORR-L1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-L",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-000444",
            message="Committed",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-L1",
            expected_attempt=1,
        )
        before_steps = json.loads(self._read_db_row("NONCE-R2-L")["steps_json"])
        before_version = self._read_db_row("NONCE-R2-L")["version"]

        for i in range(15):
            with self.assertRaises(InvalidStateTransitionError):
                self.coord.transition_governed_transaction(
                    nonce="NONCE-R2-L",
                    lifecycle_state=TransactionState.FAILED if i % 2 == 0 else TransactionState.EXECUTING,
                    bridge_status="REJECTED",
                    error_code=f"SPAM_{i}",
                    step_event={"step": f"ILLEGAL_{i}"},
                    authority=TransitionAuthority.ORDINARY,
                )

        after_row = self._read_db_row("NONCE-R2-L")
        self.assertEqual(json.loads(after_row["steps_json"]), before_steps)
        self.assertEqual(after_row["version"], before_version)
        self.assertEqual(after_row["lifecycle_state"], "COMMITTED")

    # Test M: Terminal protection survives coordinator restart
    def test_m_terminal_protection_survives_coordinator_restart(self):
        self._begin("NONCE-R2-M1", corr_id="CORR-M1")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-M1",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-M1",
            message="Committed before restart",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-M1",
            expected_attempt=1,
        )
        self._begin("NONCE-R2-M2", corr_id="CORR-M2")
        self.coord.transition_governed_transaction(
            nonce="NONCE-R2-M2",
            lifecycle_state=TransactionState.UNKNOWN,
            bridge_status="PENDING_UNKNOWN",
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-M2",
            expected_attempt=1,
        )
        self.coord.mark_transaction_reconciled(
            nonce="NONCE-R2-M2",
            actor_user_id="USR-OWNER-001",
            resolution_notes="Reconciled before restart",
            final_allocated_id="JV-M2",
        )

        # Simulate complete backend process restart with a brand-new coordinator instance
        restarted_coord = TransactionCoordinator(db_path=self.db_path, testing=True)

        with self.assertRaises(InvalidStateTransitionError):
            restarted_coord.transition_governed_transaction(
                nonce="NONCE-R2-M1",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                authority=TransitionAuthority.ORDINARY,
            )
        with self.assertRaises(InvalidStateTransitionError):
            restarted_coord.transition_governed_transaction(
                nonce="NONCE-R2-M2",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                authority=TransitionAuthority.RECOVERY,
                actor="USR-OWNER-001",
                reason="Attempted post-restart overwrite",
            )
        self.assertEqual(restarted_coord.get_governed_transaction("NONCE-R2-M1")["lifecycle_state"], "COMMITTED")
        self.assertEqual(restarted_coord.get_governed_transaction("NONCE-R2-M2")["lifecycle_state"], "RECONCILED")
        self.assertGreaterEqual(len(get_legal_transition_matrix_summary()), 20)


class TestMission51B1Round2DurabilityAndRestart(unittest.TestCase):
    """TX-AUDIT-02: Mandatory Durability & Restart Safety Tests 1 through 14."""

    def setUp(self):
        # Create persistent-like non-/tmp directory under workspace temp or test dir
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_r2_dur_")
        self.db_path = os.path.join(self.tmp_dir, "persistent_coord.db")
        self.payload = {
            "journal_header": {"entry_date": "2026-11-21", "description": "Durability test"},
            "journal_lines": [
                {"account_code": "1001", "debit": 250, "credit": 0},
                {"account_code": "4001", "debit": 0, "credit": 250},
            ],
        }
        self.payload_hash = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload=self.payload,
        )
        self.store = {
            "JournalHeaders": [],
            "JournalLines": [],
            "IdAllocations": [],
            "AuditLog": [],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # Tests 1, 2, 3, 4, 5: Restart with DB preserved retains state, idempotency key, payload hash, terminal state
    def test_01_to_05_restart_preserves_state_idempotency_payload_hash_and_terminal_state(self):
        c1 = TransactionCoordinator(db_path=self.db_path, testing=True)
        st, tx = c1.begin_governed_transaction(
            nonce="NONCE-DUR-001",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id="CORR-DUR-1",
        )
        self.assertEqual(st, "ACQUIRED")
        c1.transition_governed_transaction(
            nonce="NONCE-DUR-001",
            lifecycle_state=TransactionState.COMMITTED,
            bridge_status="CONFIRMED",
            allocated_id="JV-DUR-001",
            message="Committed before restart",
            result_snapshot={"journal_id": "JV-DUR-001"},
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_correlation_id="CORR-DUR-1",
            expected_attempt=1,
        )
        del c1

        # Restart: new TransactionCoordinator opens same persistent SQLite DB file
        c2 = TransactionCoordinator(db_path=self.db_path, testing=True)
        row = c2.get_governed_transaction("NONCE-DUR-001")
        # 1 & 2: Transaction state survives restart
        self.assertIsNotNone(row)
        self.assertEqual(row["lifecycle_state"], "COMMITTED")
        self.assertEqual(row["allocated_id"], "JV-DUR-001")
        # 3: Idempotency key survives restart (same payload -> ALREADY_COMMITTED)
        st_replay, tx_replay = c2.begin_governed_transaction(
            nonce="NONCE-DUR-001",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id="CORR-DUR-2",
        )
        self.assertEqual(st_replay, "ALREADY_COMMITTED")
        self.assertEqual(tx_replay["allocated_id"], "JV-DUR-001")
        # 4: Payload hash survives restart (different payload -> PAYLOAD_CONFLICT)
        diff_hash = compute_deterministic_payload_hash(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload={"different": True},
        )
        st_conflict, _ = c2.begin_governed_transaction(
            nonce="NONCE-DUR-001",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=diff_hash,
            correlation_id="CORR-DUR-3",
        )
        self.assertEqual(st_conflict, "PAYLOAD_CONFLICT")
        # 5: Terminal state survives restart
        with self.assertRaises(InvalidStateTransitionError):
            c2.transition_governed_transaction(
                nonce="NONCE-DUR-001",
                lifecycle_state=TransactionState.FAILED,
                bridge_status="REJECTED",
                authority=TransitionAuthority.ORDINARY,
            )

    # Test 6: Lease recovery survives restart (expired EXECUTING -> UNKNOWN automatically on startup)
    def test_06_stale_lease_recovery_runs_on_restart(self):
        c1 = TransactionCoordinator(db_path=self.db_path, testing=True)
        c1.begin_governed_transaction(
            nonce="NONCE-LEASE-RESTART",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id="CORR-CRASHED",
            lease_seconds=5,
        )
        # Backdate lease_expires_at to simulate worker crash while EXECUTING
        expired_iso = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?",
            (expired_iso, "NONCE-LEASE-RESTART"),
        )
        conn.commit()
        conn.close()
        del c1

        # Restart coordinator -> startup recovery automatically moves expired EXECUTING to UNKNOWN
        c2 = TransactionCoordinator(db_path=self.db_path, testing=True, auto_recover_stale_leases=True)
        row = c2.get_governed_transaction("NONCE-LEASE-RESTART")
        self.assertEqual(row["lifecycle_state"], "UNKNOWN")
        self.assertEqual(row["previous_state"], "EXECUTING")
        self.assertEqual(row["error_code"], "STALE_EXECUTION_LEASE")
        self.assertIsNone(row["lease_expires_at"])
        self.assertIsNone(row["lease_owner"])

    # Test 7: Coordinator path missing at startup in production -> fail closed
    def test_07_production_missing_coordinator_path_fails_closed(self):
        with patch.dict(os.environ, {"TRANSACTION_DB_PATH": "", "SALES_ENV": "production", "SALES_TESTING": "0"}, clear=False):
            with self.assertRaises(CoordinatorDurabilityError) as ctx:
                validate_coordinator_durability(db_path="", env="production", testing=False)
            self.assertEqual(ctx.exception.error_code, "COORDINATOR_PATH_UNCONFIGURED")
            self.assertEqual(ctx.exception.mode, CoordinatorDurabilityMode.MISCONFIGURED)

            # Direct TransactionCoordinator init in production without path also fails closed
            with self.assertRaises(CoordinatorDurabilityError) as ctx2:
                TransactionCoordinator(db_path="", env="production", testing=False)
            self.assertEqual(ctx2.exception.error_code, "COORDINATOR_PATH_UNCONFIGURED")

    # Test 8: Coordinator directory unavailable -> fail closed at startup AND at runtime mutation (HTTP 503)
    def test_08_coordinator_directory_unavailable_fails_closed(self):
        non_existent_path = os.path.join(REPO_ROOT, ".nonexistent_mount_dir_r2", "coord.db")
        with self.assertRaises(CoordinatorDurabilityError) as ctx:
            validate_coordinator_durability(db_path=non_existent_path, env="production", testing=False)
        self.assertEqual(ctx.exception.error_code, "COORDINATOR_DIRECTORY_UNAVAILABLE")
        self.assertEqual(ctx.exception.mode, CoordinatorDurabilityMode.UNAVAILABLE)

        # Runtime unavailability: coordinator configured on a directory that disappears before write -> HTTP 503, 0 POSTs
        vanishing_dir = tempfile.mkdtemp(prefix="ks_r2_vanish_")
        vanishing_db = os.path.join(vanishing_dir, "coord.db")
        vanishing_coord = TransactionCoordinator(db_path=vanishing_db, testing=True)
        shutil.rmtree(vanishing_dir)

        opener = _FakeOpener(lambda env, n: (_ for _ in ()).throw(AssertionError("Gateway must NOT be called")))
        bridge = AppsScriptBridge()
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod, "tx_coordinator", vanishing_coord), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(bridge_mod.db, "get_records", return_value=[]):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self.payload,
                nonce="NONCE-DUR-UNAVAIL",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
        self.assertEqual(res.status, "REJECTED")
        self.assertEqual(res.http_status, 503)
        self.assertEqual(res.error_code, "COORDINATOR_DIRECTORY_UNAVAILABLE")
        self.assertEqual(len(opener.calls), 0)

    # Test 9: Misconfigured persistent path (unwritable dir or horizontal scaling instance_count > 1) fails closed
    def test_09_misconfigured_persistent_path_and_multi_instance_fail_closed(self):
        # Multi-instance scaling guard (SQLite WAL is single-host only)
        with self.assertRaises(CoordinatorDurabilityError) as ctx_scale:
            validate_coordinator_durability(
                db_path=os.path.join(REPO_ROOT, "coord.db"),
                env="production",
                testing=False,
                instance_count=2,
            )
        self.assertEqual(ctx_scale.exception.error_code, "COORDINATOR_MULTI_INSTANCE_UNSUPPORTED")

        # Valid non-volatile persistent path in production passes cleanly
        pers_dir = os.path.join(REPO_ROOT, ".tmp_r2_persistent_test_dir")
        os.makedirs(pers_dir, exist_ok=True)
        try:
            pers_db = os.path.join(pers_dir, "coord.db")
            info = validate_coordinator_durability(db_path=pers_db, env="production", testing=False, instance_count=1)
            self.assertEqual(info["mode"], CoordinatorDurabilityMode.PERSISTENT.value)
            self.assertTrue(info["persistent"])
            self.assertTrue(info["single_host_only"])

            # Verify assert_runtime_config() integrates the check in production
            fake_sa = os.path.join(pers_dir, "sa.json")
            with open(fake_sa, "w", encoding="utf-8") as fh:
                fh.write("{}")
            with patch.object(config_mod, "SALES_ENV", "production"), \
                 patch.object(config_mod, "SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"), \
                 patch.object(config_mod, "SALES_GOOGLE_SPREADSHEET_ID", "sheet-123"), \
                 patch.object(config_mod, "SALES_GOOGLE_SERVICE_ACCOUNT_FILE", fake_sa), \
                 patch.dict(os.environ, {
                     "SALES_JWT_SECRET": "a" * 40,
                     "SALES_TESTING": "0",
                     "TRANSACTION_DB_PATH": "/tmp/bad_prod.db",
                 }, clear=False):
                with self.assertRaises(CoordinatorDurabilityError) as ctx_cfg:
                    config_mod.assert_runtime_config()
                self.assertEqual(ctx_cfg.exception.error_code, "COORDINATOR_VOLATILE_PATH_IN_PRODUCTION")
        finally:
            shutil.rmtree(pers_dir, ignore_errors=True)

        # Read-only directory fails closed (skip only if running as root where chmod 0555 stays writable)
        ro_dir = os.path.join(REPO_ROOT, ".tmp_r2_ro_test_dir")
        os.makedirs(ro_dir, exist_ok=True)
        try:
            os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)
            if not os.access(ro_dir, os.W_OK):
                with self.assertRaises(CoordinatorDurabilityError) as ctx_ro:
                    validate_coordinator_durability(
                        db_path=os.path.join(ro_dir, "coord.db"),
                        env="production",
                        testing=False,
                    )
                self.assertEqual(ctx_ro.exception.error_code, "COORDINATOR_DIRECTORY_NOT_WRITABLE")
        finally:
            os.chmod(ro_dir, stat.S_IRWXU)
            shutil.rmtree(ro_dir, ignore_errors=True)

    # Test 10: Volatile /tmp or :memory: path selected in production -> fails closed
    def test_10_volatile_tmp_and_memory_paths_rejected_in_production(self):
        for bad_path in ["/tmp/kawad_swad_tx_coord.db", "/var/tmp/tx.db", ":memory:", "file::memory:?cache=shared"]:
            with self.subTest(path=bad_path):
                with self.assertRaises(CoordinatorDurabilityError) as ctx:
                    validate_coordinator_durability(db_path=bad_path, env="production", testing=False)
                self.assertEqual(ctx.exception.error_code, "COORDINATOR_VOLATILE_PATH_IN_PRODUCTION")
                self.assertEqual(ctx.exception.mode, CoordinatorDurabilityMode.MISCONFIGURED)

    # Test 11: Two OS processes access coordinator concurrently -> atomic CAS isolation
    def test_11_two_os_processes_concurrent_access_atomic_cas(self):
        # Initialize DB before spawning processes
        TransactionCoordinator(db_path=self.db_path, testing=True)
        barrier_file = os.path.join(self.tmp_dir, "go.flag")

        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=2) as pool:
            a1 = pool.apply_async(
                _mp_worker_race_acquire,
                (self.db_path, "NONCE-MP-RACE", self.payload_hash, "P1", barrier_file),
            )
            a2 = pool.apply_async(
                _mp_worker_race_acquire,
                (self.db_path, "NONCE-MP-RACE", self.payload_hash, "P2", barrier_file),
            )
            time.sleep(0.15)
            with open(barrier_file, "w", encoding="utf-8") as fh:
                fh.write("GO")
            r1 = a1.get(timeout=15)
            r2 = a2.get(timeout=15)

        statuses = [r1[1], r2[1]]
        self.assertEqual(statuses.count("ACQUIRED"), 1, f"Exactly one OS process must acquire; got {r1}, {r2}")
        self.assertIn(
            [s for s in statuses if s != "ACQUIRED"][0],
            {"IN_PROGRESS", "ALREADY_COMMITTED"},
        )

        # Also test two OS processes racing to transition the SAME EXECUTING row (COMMITTED vs FAILED)
        c = TransactionCoordinator(db_path=self.db_path, testing=True)
        c.begin_governed_transaction(
            nonce="NONCE-MP-TXRACE",
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            actor_user_id="USR-OWNER-001",
            payload_hash=self.payload_hash,
            correlation_id="CORR-SHARED",
        )
        with ctx.Pool(processes=2) as pool:
            t1 = pool.apply_async(_mp_worker_transition_race, (self.db_path, "NONCE-MP-TXRACE", "COMMITTED", "CORR-SHARED", 1))
            t2 = pool.apply_async(_mp_worker_transition_race, (self.db_path, "NONCE-MP-TXRACE", "FAILED", "CORR-SHARED", 1))
            tr1 = t1.get(timeout=15)
            tr2 = t2.get(timeout=15)

        ok_count = sum(1 for r in (tr1, tr2) if r[0] == "OK")
        self.assertEqual(ok_count, 1, f"Exactly one OS process transition may win CAS; got {tr1}, {tr2}")

    # Test 12: Stale worker resumes in execute_governed_write after another worker commits
    def test_12_stale_worker_resumes_after_another_worker_commits_bridge_level(self):
        coord = TransactionCoordinator(db_path=self.db_path, testing=True)
        bridge = AppsScriptBridge()

        def slow_stale_gateway(envelope, call_no):
            # While Worker 1 is waiting on gateway, simulate lease expiry + Worker 2 committing the tx!
            past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
            conn = sqlite3.connect(self.db_path)
            conn.execute("UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?", (past, "NONCE-DUR-12"))
            conn.commit()
            conn.close()
            # Worker 2 recovers to COMMITTED
            coord.begin_governed_transaction(
                nonce="NONCE-DUR-12",
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                actor_user_id="USR-OWNER-001",
                payload_hash=self.payload_hash,
                correlation_id="CORR-WINNER-2",
            )
            coord.transition_governed_transaction(
                nonce="NONCE-DUR-12",
                lifecycle_state=TransactionState.COMMITTED,
                bridge_status="CONFIRMED",
                allocated_id="JV-WINNER-12",
                message="Winner committed",
                authority=TransitionAuthority.RECOVERY,
                expected_from_state=TransactionState.UNKNOWN,
                actor="SYSTEM_RECOVERY",
                reason="Verified committed in Sheets",
                evidence={"allocated_id": "JV-WINNER-12"},
            )
            # Now stale Worker 1 gets a gateway timeout error and tries to transition EXECUTING -> UNKNOWN/FAILED!
            raise TimeoutError("Stale worker gateway timeout")

        opener = _FakeOpener(slow_stale_gateway)
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod, "tx_coordinator", coord), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(bridge_mod.db, "get_records", return_value=[]):
            res = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self.payload,
                nonce="NONCE-DUR-12",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )

        # Stale worker rejected cleanly with 409, and DB MUST remain COMMITTED with JV-WINNER-12!
        self.assertEqual(res.status, "REJECTED")
        self.assertEqual(res.http_status, 409)
        self.assertEqual(res.transaction_state, "COMMITTED")
        self.assertEqual(res.allocated_id, "JV-WINNER-12")
        final_row = coord.get_governed_transaction("NONCE-DUR-12")
        self.assertEqual(final_row["lifecycle_state"], "COMMITTED")
        self.assertEqual(final_row["allocated_id"], "JV-WINNER-12")

    # Tests 13 & 14: Local coordinator DB is wiped/lost -> same nonce presented -> Sheets IdAllocations
    # check prevents blind duplicate gateway POST and cleanly recovers CONFIRMED or quarantines orphan!
    def test_13_and_14_coordinator_loss_recovery_does_not_duplicate_gateway_writes(self):
        bridge = AppsScriptBridge()

        def fake_get_records(tab_name, fresh=False):
            return list(self.store.get(tab_name, []))

        def commit_handler(env, call_no):
            alloc_id = "JV-LOSS-001"
            self.store["IdAllocations"].append({
                "nonce": env["nonce"],
                "allocated_id": alloc_id,
                "entity_type": "JournalHeaders",
            })
            self.store["JournalHeaders"].append({"journal_id": alloc_id, "entry_date": "2026-11-21"})
            self.store["JournalLines"].append({"journal_id": alloc_id, "debit": 250, "credit": 0})
            self.store["JournalLines"].append({"journal_id": alloc_id, "debit": 0, "credit": 250})
            return _FakeHTTPResponse({
                "status": "CONFIRMED",
                "correlation_id": env["correlation_id"],
                "nonce": env["nonce"],
                "action": env["action"],
                "target_tab": env["target_tab"],
                "allocated_id": alloc_id,
                "record": {"journal_id": alloc_id},
            })

        # Step 1: Initial write succeeds and commits to Google Sheets + coordinator DB #1
        c1 = TransactionCoordinator(db_path=self.db_path, testing=True)
        opener1 = _FakeOpener(commit_handler)
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod, "tx_coordinator", c1), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener1), \
             patch.object(bridge_mod.db, "get_records", side_effect=fake_get_records), \
             patch.object(bridge_mod.db, "invalidate_tab_cache"):
            res1 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self.payload,
                nonce="NONCE-LOSS-001",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
        self.assertEqual(res1.status, "CONFIRMED")
        self.assertEqual(len(opener1.calls), 1)
        del c1

        # Step 2: Simulate COMPLETE LOCAL COORDINATOR DB LOSS (delete DB + WAL + SHM files!)
        for suffix in ("", "-wal", "-shm"):
            p = self.db_path + suffix
            if os.path.exists(p):
                os.remove(p)

        # Fresh empty coordinator starts up with zero local history
        c_new = TransactionCoordinator(db_path=self.db_path, testing=True)
        self.assertIsNone(c_new.get_governed_transaction("NONCE-LOSS-001"))

        # Retry same nonce -> MUST inspect Sheets IdAllocations and auto-confirm with ZERO gateway POST!
        opener2 = _FakeOpener(lambda env, n: (_ for _ in ()).throw(AssertionError("Duplicate POST MUST NOT happen!")))
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod, "tx_coordinator", c_new), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener2), \
             patch.object(bridge_mod.db, "get_records", side_effect=fake_get_records), \
             patch.object(bridge_mod.db, "invalidate_tab_cache"):
            res2 = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self.payload,
                nonce="NONCE-LOSS-001",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
        self.assertEqual(res2.status, "CONFIRMED")
        self.assertTrue(res2.is_replay)
        self.assertEqual(res2.allocated_id, "JV-LOSS-001")
        self.assertEqual(res2.recovery_decision, "AUTO_CONFIRMED_FROM_SHEETS")
        self.assertEqual(len(opener2.calls), 0)
        # Reconstructed local coordinator state is now COMMITTED
        self.assertEqual(c_new.get_governed_transaction("NONCE-LOSS-001")["lifecycle_state"], "COMMITTED")

        # Step 3 (Test 14): Orphan allocation in Sheets after coordinator loss -> RECOVERY_REQUIRED, 0 duplicate POST!
        self.store["IdAllocations"].append({
            "nonce": "NONCE-LOSS-ORPHAN",
            "allocated_id": "JV-ORPHAN-999",
            "entity_type": "JournalHeaders",
        })
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod, "tx_coordinator", c_new), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=opener2), \
             patch.object(bridge_mod.db, "get_records", side_effect=fake_get_records), \
             patch.object(bridge_mod.db, "invalidate_tab_cache"):
            res_orphan = bridge.execute_governed_write(
                action="POST_JOURNAL_VOUCHER",
                target_tab="JournalHeaders",
                payload=self.payload,
                nonce="NONCE-LOSS-ORPHAN",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="journal_id",
            )
        self.assertEqual(res_orphan.status, "RECOVERY_REQUIRED")
        self.assertEqual(res_orphan.http_status, 409)
        self.assertFalse(res_orphan.retryable)
        self.assertEqual(len(opener2.calls), 0)
        self.assertEqual(c_new.get_governed_transaction("NONCE-LOSS-ORPHAN")["lifecycle_state"], "RECOVERY_REQUIRED")


class TestMission51B1Round2PackageHygiene(unittest.TestCase):
    """TX-AUDIT-03: Package Hygiene, Accidental Upload Removal & Deployment Config Verification."""

    def test_accidental_aistudio_prompt_artifact_removed(self):
        bad_file = os.path.join(
            REPO_ROOT, "public", "assets", "aistudio", "Paste_November_21__2026_-_11_52PM_b5cb8f2f"
        )
        self.assertFalse(os.path.exists(bad_file), "Accidental AI Studio prompt file must be deleted")
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "public", "assets", "aistudio")))

    def test_render_yaml_and_env_example_configure_persistent_coordinator(self):
        with open(os.path.join(REPO_ROOT, "render.yaml"), "r", encoding="utf-8") as fh:
            render_txt = fh.read()
        self.assertIn("mountPath: /var/data/kawad_swad", render_txt)
        self.assertIn("TRANSACTION_DB_PATH", render_txt)
        self.assertIn("/var/data/kawad_swad/kawad_swad_tx_coord.db", render_txt)
        self.assertIn("SALES_INSTANCE_COUNT", render_txt)
        self.assertIn("WEB_CONCURRENCY", render_txt)

        with open(os.path.join(REPO_ROOT, ".env.example"), "r", encoding="utf-8") as fh:
            env_txt = fh.read()
        self.assertIn("TRANSACTION_DB_PATH", env_txt)
        self.assertIn("SALES_INSTANCE_COUNT", env_txt)
        self.assertIn("KS_ERP_LOCK_DIR", env_txt)

    def test_package_hygiene_verifier_rejects_forbidden_artifacts_and_passes_clean_zip(self):
        tmp_dir = tempfile.mkdtemp(prefix="ks_r2_pkg_")
        try:
            clean_zip = os.path.join(tmp_dir, "clean.zip")
            with zipfile.ZipFile(clean_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("backend/app/main.py", "print('ok')\n")
                zf.writestr(".env.example", "TRANSACTION_DB_PATH=/var/data/kawad_swad/kawad_swad_tx_coord.db\n")
            ok_clean, rep_clean = audit_zip_archive(clean_zip, require_round2_files=False)
            self.assertTrue(ok_clean, rep_clean)
            self.assertEqual(rep_clean["status"], "PASS")
            self.assertEqual(len(str(rep_clean["sha256"])), 64)

            polluted_zip = os.path.join(tmp_dir, "polluted.zip")
            with zipfile.ZipFile(polluted_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f", "accidental prompt")
                zf.writestr(".env", "SALES_JWT_SECRET=real")
                zf.writestr("backend/tx_coord.db", "sqlite")
            ok_bad, rep_bad = audit_zip_archive(polluted_zip, require_round2_files=False)
            self.assertFalse(ok_bad)
            self.assertEqual(rep_bad["status"], "FAIL")
            joined = " ".join(rep_bad["violations"])
            self.assertIn("aistudio", joined)
            self.assertIn("forbidden_basename:.env", joined)
            self.assertIn("forbidden_extension:.db", joined)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
