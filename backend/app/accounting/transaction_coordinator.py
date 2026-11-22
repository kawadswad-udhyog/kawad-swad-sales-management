# backend/app/accounting/transaction_coordinator.py
"""
Kawad Swad ERP - Transactional Financial Authorization & Concurrency Coordinator
Provides host-local cross-process ACID transactional guarantees for:
1. Governed transaction lifecycle tracking, idempotency conflict detection,
   stale-lock detection, step tracking, and recovery state persistence.
2. Approval reservation (atomic Compare-And-Swap across threads & OS processes).
3. Approval consumption (verifies sale ownership and unconsumed status).
4. Approval release (releases reservation on early sale failures).
5. Customer credit reservations (serializes concurrent credit exposure checks).
6. Sale idempotency locks (prevents duplicate simultaneous creation).

Storage Engine Architecture & Scope Honesty:
- Authoritative Business Database: Google Sheets via Apps Script Single Write Owner.
  This coordinator NEVER replaces Google Sheets as the business source of truth.
- Local Coordination Engine: SQLite with Write-Ahead Logging (WAL) and BEGIN IMMEDIATE
  transactions. Provides strong cross-thread and cross-process ACID coordination on
  the active backend host (`WEB_CONCURRENCY=1` on Render).
- Distributed Boundary: Multi-host / multi-container distributed locking and cross-tab
  sheet atomicity remain dependent on the external Apps Script LockService (`DB-008`,
  UNVERIFIED in this repository).
"""

import json
import os
import sqlite3
import threading
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Tuple, Optional, Dict, Any, List, Union

from app.transaction_safety import (
    CoordinatorDurabilityError,
    CoordinatorDurabilityMode,
    InvalidStateTransitionError,
    LEGAL_TRANSITION_MATRIX,
    TERMINAL_STATES,
    TransactionState,
    TransitionAuthority,
    validate_coordinator_durability,
    validate_state_transition,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("TRANSACTION_DB_PATH", "").strip()
DEFAULT_TX_LEASE_SECONDS = int(os.environ.get("SALES_TX_LEASE_SECONDS", "90") or "90")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


class TransactionCoordinator:
    _instance = None
    _init_lock = threading.Lock()

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        env: Optional[str] = None,
        testing: Optional[bool] = None,
        allow_volatile_in_test: Optional[bool] = None,
        instance_count: Optional[int] = None,
        auto_recover_stale_leases: bool = True,
        defer_durability_error: bool = False,
    ):
        self._thread_lock = threading.RLock()
        self._durability_error: Optional[CoordinatorDurabilityError] = None
        self._durability_info: Dict[str, Any] = {}
        self._env_override = env
        self._testing_override = testing
        self._allow_volatile_override = allow_volatile_in_test
        self._instance_count_override = instance_count

        try:
            info = validate_coordinator_durability(
                db_path=db_path,
                env=env,
                testing=testing,
                allow_volatile_in_test=allow_volatile_in_test,
                instance_count=instance_count,
                create_dir_in_nonprod=False,
            )
            self._durability_info = info
            self.db_path = info["db_path"]
        except CoordinatorDurabilityError as exc:
            self._durability_error = exc
            self._durability_info = {
                "mode": exc.mode.value,
                "db_path": exc.db_path,
                "error_code": exc.error_code,
                "error": str(exc),
                "persistent": False,
                "single_host_only": True,
            }
            self.db_path = exc.db_path or ""
            if not defer_durability_error:
                raise
            logger.critical("TransactionCoordinator durability validation failed: %s", exc)
            return

        self._init_sqlite()
        if auto_recover_stale_leases:
            try:
                recovered = self.recover_stale_leases_on_startup()
                if recovered:
                    logger.warning(
                        "TransactionCoordinator startup recovery transitioned %d stale lease(s) to UNKNOWN.",
                        len(recovered),
                    )
            except Exception as exc:
                logger.error("Error during startup stale-lease recovery: %s", exc)

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> "TransactionCoordinator":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path, defer_durability_error=True)
            return cls._instance

    def durability_status(self) -> Dict[str, Any]:
        """Return current coordinator durability classification and availability."""
        return dict(self._durability_info)

    def assert_writable_coordinator(self) -> None:
        """
        Fail-closed check before any governed transaction mutation.
        Verifies both startup durability configuration and live filesystem availability.
        """
        if self._durability_error is not None:
            raise self._durability_error
        if not self.db_path:
            raise CoordinatorDurabilityError(
                "Transaction coordinator database path is empty.",
                error_code="COORDINATOR_PATH_UNCONFIGURED",
                mode=CoordinatorDurabilityMode.MISCONFIGURED,
                db_path="",
            )
        if self.db_path != ":memory:" and not self.db_path.lower().startswith("file::memory:"):
            parent_dir = os.path.dirname(os.path.abspath(self.db_path))
            if not parent_dir or not os.path.isdir(parent_dir):
                raise CoordinatorDurabilityError(
                    f"Transaction coordinator directory '{parent_dir}' is unavailable.",
                    error_code="COORDINATOR_DIRECTORY_UNAVAILABLE",
                    mode=CoordinatorDurabilityMode.UNAVAILABLE,
                    db_path=self.db_path,
                )
            if not os.access(parent_dir, os.R_OK | os.W_OK | os.X_OK):
                raise CoordinatorDurabilityError(
                    f"Transaction coordinator directory '{parent_dir}' is not writable.",
                    error_code="COORDINATOR_DIRECTORY_NOT_WRITABLE",
                    mode=CoordinatorDurabilityMode.UNAVAILABLE,
                    db_path=self.db_path,
                )

    def _get_connection(self) -> sqlite3.Connection:
        self.assert_writable_coordinator()
        try:
            conn = sqlite3.connect(self.db_path, timeout=15.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=15000;")
            conn.execute("PRAGMA synchronous=FULL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            return conn
        except sqlite3.Error as exc:
            raise CoordinatorDurabilityError(
                f"Transaction coordinator SQLite connection failed at '{self.db_path}': {exc}",
                error_code="COORDINATOR_STORAGE_ERROR",
                mode=CoordinatorDurabilityMode.UNAVAILABLE,
                db_path=self.db_path,
            ) from exc

    def _init_sqlite(self):
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_reservations (
                    approval_id TEXT PRIMARY KEY,
                    sale_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    requested_credit REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'RESERVED',
                    reserved_at TEXT NOT NULL,
                    consumed_at TEXT,
                    released_at TEXT
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS credit_reservations (
                    customer_id TEXT NOT NULL,
                    sale_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (customer_id, sale_id)
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_locks (
                    idempotency_key TEXT PRIMARY KEY,
                    sale_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
                    created_at TEXT NOT NULL
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS governed_transactions (
                    nonce TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_tab TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    previous_state TEXT,
                    last_authority TEXT,
                    bridge_status TEXT NOT NULL,
                    failure_category TEXT,
                    error_code TEXT,
                    allocated_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    version INTEGER NOT NULL DEFAULT 1,
                    lease_owner TEXT,
                    steps_json TEXT,
                    result_snapshot_json TEXT,
                    message TEXT,
                    recovery_decision TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_expires_at TEXT
                );
                """)
                # Non-destructive schema migration for existing SQLite coordinator files
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(governed_transactions);")
                existing_cols = {str(r["name"]) for r in cur.fetchall()}
                migrations = [
                    ("previous_state", "ALTER TABLE governed_transactions ADD COLUMN previous_state TEXT;"),
                    ("last_authority", "ALTER TABLE governed_transactions ADD COLUMN last_authority TEXT;"),
                    ("version", "ALTER TABLE governed_transactions ADD COLUMN version INTEGER NOT NULL DEFAULT 1;"),
                    ("lease_owner", "ALTER TABLE governed_transactions ADD COLUMN lease_owner TEXT;"),
                ]
                for col_name, ddl in migrations:
                    if col_name not in existing_cols:
                        conn.execute(ddl)
                conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_gov_tx_state_updated
                ON governed_transactions (lifecycle_state, updated_at);
                """)
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Failed to initialize SQLite transaction schema: %s", e)
                raise
            finally:
                conn.close()

    @staticmethod
    def _row_to_tx_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        d = dict(row)
        try:
            d["steps"] = json.loads(d.get("steps_json") or "[]")
        except Exception:
            d["steps"] = []
        try:
            d["result_snapshot"] = json.loads(d.get("result_snapshot_json") or "null")
        except Exception:
            d["result_snapshot"] = None
        if d.get("version") is None:
            d["version"] = 1
        return d

    def recover_stale_leases_on_startup(self) -> List[Dict[str, Any]]:
        """
        Scan for in-flight transactions (INITIATED / VALIDATING / EXECUTING) whose lease
        expired prior to restart and atomically CAS-transition them to UNKNOWN under
        RECOVERY authority so they cannot remain stuck in EXECUTING.
        """
        now_dt = _utc_now()
        now_s = _utc_iso(now_dt)
        transitioned: List[Dict[str, Any]] = []

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT * FROM governed_transactions
                    WHERE lifecycle_state IN ('INITIATED', 'VALIDATING', 'EXECUTING')
                    """
                )
                candidates = cur.fetchall()
                for row in candidates:
                    ex = self._row_to_tx_dict(row) or {}
                    lease_dt = _parse_iso(ex.get("lease_expires_at"))
                    if lease_dt is not None and now_dt < lease_dt:
                        continue
                    nonce = str(ex.get("nonce") or "").strip()
                    src_state = str(ex.get("lifecycle_state") or "").strip().upper()
                    ver = int(ex.get("version") or 1)
                    validate_state_transition(
                        src_state,
                        TransactionState.UNKNOWN,
                        TransitionAuthority.RECOVERY,
                        nonce=nonce,
                        reason="Stale execution lease expired before coordinator startup.",
                        evidence={"lease_expires_at": ex.get("lease_expires_at"), "detected_at": now_s},
                    )
                    steps = list(ex.get("steps") or [])
                    steps.append({
                        "step": "STALE_LEASE_RECOVERED_ON_STARTUP",
                        "from_state": src_state,
                        "to_state": TransactionState.UNKNOWN.value,
                        "authority": TransitionAuthority.RECOVERY.value,
                        "at": now_s,
                    })
                    cur.execute(
                        """
                        UPDATE governed_transactions
                        SET lifecycle_state = 'UNKNOWN',
                            previous_state = ?,
                            last_authority = 'RECOVERY',
                            bridge_status = 'PENDING_UNKNOWN',
                            failure_category = 'WRITE_OUTCOME_UNKNOWN',
                            error_code = 'STALE_EXECUTION_LEASE',
                            steps_json = ?,
                            updated_at = ?,
                            lease_expires_at = NULL,
                            lease_owner = NULL,
                            version = version + 1
                        WHERE nonce = ? AND lifecycle_state = ? AND version = ?
                        """,
                        (src_state, json.dumps(steps[-40:]), now_s, nonce, src_state, ver),
                    )
                    if cur.rowcount == 1:
                        cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (nonce,))
                        updated = self._row_to_tx_dict(cur.fetchone())
                        if updated:
                            transitioned.append(updated)
                conn.execute("COMMIT;")
                return transitioned
            except Exception as exc:
                conn.execute("ROLLBACK;")
                logger.error("Error in recover_stale_leases_on_startup: %s", exc)
                raise
            finally:
                conn.close()

    def register_external_recovery_intent(
        self,
        *,
        nonce: str,
        action: str,
        target_tab: str,
        actor_user_id: str,
        payload_hash: str,
        correlation_id: str,
        allocated_id: Optional[str] = None,
        reason: str = "Authoritative Google Sheets evidence found after local coordinator loss.",
    ) -> Dict[str, Any]:
        """
        Atomically register an existing external Sheets transaction in UNKNOWN state when the
        local coordinator DB was lost/replaced, enabling evidence-based recovery without
        allowing a blind duplicate write.
        """
        clean_nonce = str(nonce or "").strip()
        clean_action = str(action or "").strip().upper()
        clean_tab = str(target_tab or "").strip()
        clean_actor = str(actor_user_id or "").strip()
        clean_hash = str(payload_hash or "").strip()
        clean_corr = str(correlation_id or "").strip()
        now_s = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                existing = cur.fetchone()
                if existing is not None:
                    res = self._row_to_tx_dict(existing) or {}
                    conn.execute("COMMIT;")
                    return res

                tx_id = f"TXN-{uuid.uuid4().hex[:14].upper()}"
                steps = [{
                    "step": "EXTERNAL_RECOVERY_REGISTERED",
                    "to_state": TransactionState.UNKNOWN.value,
                    "authority": TransitionAuthority.RECOVERY.value,
                    "allocated_id": allocated_id,
                    "reason": reason,
                    "at": now_s,
                    "correlation_id": clean_corr,
                }]
                cur.execute(
                    """
                    INSERT INTO governed_transactions (
                        nonce, transaction_id, correlation_id, action, target_tab,
                        actor_user_id, payload_hash, lifecycle_state, previous_state,
                        last_authority, bridge_status, failure_category, error_code,
                        allocated_id, attempt_count, version, lease_owner, steps_json,
                        message, recovery_decision, created_at, updated_at, lease_expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', NULL, 'RECOVERY', 'PENDING_UNKNOWN',
                            'WRITE_OUTCOME_UNKNOWN', 'COORDINATOR_LOSS_SHEETS_EVIDENCE_FOUND',
                            ?, 1, 1, NULL, ?, ?, 'INSPECTING_SHEETS_AFTER_COORDINATOR_LOSS', ?, ?, NULL)
                    """,
                    (
                        clean_nonce,
                        tx_id,
                        clean_corr,
                        clean_action,
                        clean_tab,
                        clean_actor,
                        clean_hash,
                        allocated_id,
                        json.dumps(steps),
                        reason,
                        now_s,
                        now_s,
                    ),
                )
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                created = self._row_to_tx_dict(cur.fetchone()) or {}
                conn.execute("COMMIT;")
                return created
            except Exception as exc:
                conn.execute("ROLLBACK;")
                logger.error("Error in register_external_recovery_intent(%s): %s", clean_nonce, exc)
                raise
            finally:
                conn.close()

    def begin_governed_transaction(
        self,
        *,
        nonce: str,
        action: str,
        target_tab: str,
        actor_user_id: str,
        payload_hash: str,
        correlation_id: str,
        lease_seconds: int = DEFAULT_TX_LEASE_SECONDS,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Atomically register or inspect a governed transaction intent by `nonce`.

        Outcomes:
        - ("ACQUIRED", tx_dict): Fresh transaction claimed in EXECUTING state with lease_owner.
        - ("RETRY_ACQUIRED", tx_dict): Prior confirmed-not-committed (FAILED/PENDING) attempt
          safely re-acquired via RETRY authority with incremented attempt_count & version.
        - ("ALREADY_COMMITTED", tx_dict): Same nonce + action + payload already COMMITTED/RECONCILED.
        - ("IN_PROGRESS", tx_dict): Active unexpired execution already in flight (concurrent duplicate).
        - ("RECOVERY_CHECK_REQUIRED", tx_dict): Prior state is UNKNOWN / RECOVERY_REQUIRED or
          stale expired EXECUTING lease; caller MUST inspect authoritative Google Sheets
          evidence before deciding whether to return committed, quarantine, or retry.
        - ("ACTION_CONFLICT", tx_dict): Same nonce reused for a different action/target_tab.
        - ("PAYLOAD_CONFLICT", tx_dict): Same nonce + action reused with a different payload_hash.
        """
        clean_nonce = str(nonce or "").strip()
        clean_action = str(action or "").strip().upper()
        clean_tab = str(target_tab or "").strip()
        clean_actor = str(actor_user_id or "").strip()
        clean_hash = str(payload_hash or "").strip()
        clean_corr = str(correlation_id or "").strip()

        now_dt = _utc_now()
        now_s = _utc_iso(now_dt)
        lease_exp_s = _utc_iso(now_dt + timedelta(seconds=max(5, int(lease_seconds))))

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                existing = cur.fetchone()

                if existing is not None:
                    ex_dict = self._row_to_tx_dict(existing) or {}
                    ex_action = str(ex_dict.get("action") or "").strip().upper()
                    ex_tab = str(ex_dict.get("target_tab") or "").strip()
                    ex_hash = str(ex_dict.get("payload_hash") or "").strip()
                    ex_state = str(ex_dict.get("lifecycle_state") or "").strip().upper()
                    ex_ver = int(ex_dict.get("version") or 1)

                    if ex_action != clean_action or ex_tab != clean_tab:
                        conn.execute("COMMIT;")
                        return "ACTION_CONFLICT", ex_dict

                    if ex_hash != clean_hash:
                        # Strictly reject payload mismatch for COMMITTED, RECONCILED, EXECUTING,
                        # UNKNOWN, RECOVERY_REQUIRED, PENDING, or any attempt that received an ID.
                        # Only a definitively confirmed pre-commit FAILED attempt (zero allocated_id)
                        # may be corrected and retried under the same deterministic reference nonce.
                        if ex_state != TransactionState.FAILED.value or bool(ex_dict.get("allocated_id")):
                            conn.execute("COMMIT;")
                            return "PAYLOAD_CONFLICT", ex_dict

                    if ex_state in {TransactionState.COMMITTED.value, TransactionState.RECONCILED.value}:
                        conn.execute("COMMIT;")
                        return "ALREADY_COMMITTED", ex_dict

                    if ex_state in {
                        TransactionState.INITIATED.value,
                        TransactionState.VALIDATING.value,
                        TransactionState.EXECUTING.value,
                    }:
                        lease_dt = _parse_iso(ex_dict.get("lease_expires_at"))
                        if lease_dt is not None and now_dt < lease_dt:
                            conn.execute("COMMIT;")
                            return "IN_PROGRESS", ex_dict
                        # Lease expired (worker crash/restart while executing) -> atomic CAS transition to UNKNOWN
                        validate_state_transition(
                            ex_state,
                            TransactionState.UNKNOWN,
                            TransitionAuthority.RECOVERY,
                            nonce=clean_nonce,
                            reason="Execution lease expired before completion.",
                            evidence={"expired_at": ex_dict.get("lease_expires_at"), "detected_at": now_s},
                        )
                        steps = list(ex_dict.get("steps") or [])
                        steps.append({
                            "step": "STALE_LEASE_DETECTED",
                            "from_state": ex_state,
                            "to_state": TransactionState.UNKNOWN.value,
                            "authority": TransitionAuthority.RECOVERY.value,
                            "at": now_s,
                            "correlation_id": clean_corr,
                        })
                        cur.execute(
                            """
                            UPDATE governed_transactions
                            SET lifecycle_state = 'UNKNOWN',
                                previous_state = ?,
                                last_authority = 'RECOVERY',
                                bridge_status = 'PENDING_UNKNOWN',
                                failure_category = 'WRITE_OUTCOME_UNKNOWN',
                                error_code = 'STALE_EXECUTION_LEASE',
                                steps_json = ?,
                                updated_at = ?,
                                lease_expires_at = NULL,
                                lease_owner = NULL,
                                version = version + 1
                            WHERE nonce = ? AND lifecycle_state = ? AND version = ?
                            """,
                            (ex_state, json.dumps(steps[-40:]), now_s, clean_nonce, ex_state, ex_ver),
                        )
                        if cur.rowcount != 1:
                            conn.execute("ROLLBACK;")
                            raise InvalidStateTransitionError(
                                f"Concurrent state change prevented stale-lease transition for nonce '{clean_nonce}'.",
                                code="CAS_ATOMIC_CONFLICT",
                                nonce=clean_nonce,
                                current_state=ex_state,
                                target_state=TransactionState.UNKNOWN.value,
                                authority=TransitionAuthority.RECOVERY.value,
                            )
                        cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                        updated = self._row_to_tx_dict(cur.fetchone()) or ex_dict
                        conn.execute("COMMIT;")
                        return "RECOVERY_CHECK_REQUIRED", updated

                    if ex_state in {TransactionState.UNKNOWN.value, TransactionState.RECOVERY_REQUIRED.value}:
                        conn.execute("COMMIT;")
                        return "RECOVERY_CHECK_REQUIRED", ex_dict

                    # Confirmed-not-committed (FAILED or PENDING) -> explicit controlled RETRY via legal matrix + CAS
                    validate_state_transition(
                        ex_state,
                        TransactionState.EXECUTING,
                        TransitionAuthority.RETRY,
                        nonce=clean_nonce,
                        reason="Controlled same-nonce retry after confirmed-absent/failed state.",
                    )
                    next_attempt = int(ex_dict.get("attempt_count") or 1) + 1
                    steps = list(ex_dict.get("steps") or [])
                    steps.append({
                        "step": "RETRY_STARTED" if ex_hash == clean_hash else "RETRY_STARTED_AFTER_CONFIRMED_FAILURE",
                        "from_state": ex_state,
                        "to_state": TransactionState.EXECUTING.value,
                        "authority": TransitionAuthority.RETRY.value,
                        "attempt": next_attempt,
                        "at": now_s,
                        "correlation_id": clean_corr,
                    })
                    cur.execute(
                        """
                        UPDATE governed_transactions
                        SET correlation_id = ?,
                            payload_hash = ?,
                            lifecycle_state = 'EXECUTING',
                            previous_state = ?,
                            last_authority = 'RETRY',
                            bridge_status = 'PENDING_UNKNOWN',
                            failure_category = NULL,
                            error_code = NULL,
                            attempt_count = ?,
                            steps_json = ?,
                            updated_at = ?,
                            lease_expires_at = ?,
                            lease_owner = ?,
                            version = version + 1
                        WHERE nonce = ? AND lifecycle_state = ? AND version = ?
                        """,
                        (
                            clean_corr,
                            clean_hash,
                            ex_state,
                            next_attempt,
                            json.dumps(steps[-40:]),
                            now_s,
                            lease_exp_s,
                            clean_corr,
                            clean_nonce,
                            ex_state,
                            ex_ver,
                        ),
                    )
                    if cur.rowcount != 1:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Concurrent state change prevented retry acquisition for nonce '{clean_nonce}'.",
                            code="CAS_ATOMIC_CONFLICT",
                            nonce=clean_nonce,
                            current_state=ex_state,
                            target_state=TransactionState.EXECUTING.value,
                            authority=TransitionAuthority.RETRY.value,
                        )
                    cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                    updated = self._row_to_tx_dict(cur.fetchone()) or ex_dict
                    conn.execute("COMMIT;")
                    return "RETRY_ACQUIRED", updated

                # Brand-new governed transaction intent
                tx_id = f"TXN-{uuid.uuid4().hex[:14].upper()}"
                initial_steps = [
                    {"step": "INITIATED", "at": now_s, "correlation_id": clean_corr},
                    {"step": "VALIDATING", "at": now_s, "correlation_id": clean_corr},
                    {
                        "step": "EXECUTING",
                        "from_state": "VALIDATING",
                        "to_state": "EXECUTING",
                        "authority": TransitionAuthority.ORDINARY.value,
                        "attempt": 1,
                        "at": now_s,
                        "correlation_id": clean_corr,
                    },
                ]
                cur.execute(
                    """
                    INSERT INTO governed_transactions (
                        nonce, transaction_id, correlation_id, action, target_tab,
                        actor_user_id, payload_hash, lifecycle_state, previous_state,
                        last_authority, bridge_status, attempt_count, version, lease_owner,
                        steps_json, created_at, updated_at, lease_expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'EXECUTING', 'VALIDATING', 'ORDINARY',
                            'PENDING_UNKNOWN', 1, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_nonce,
                        tx_id,
                        clean_corr,
                        clean_action,
                        clean_tab,
                        clean_actor,
                        clean_hash,
                        clean_corr,
                        json.dumps(initial_steps),
                        now_s,
                        now_s,
                        lease_exp_s,
                    ),
                )
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                created = self._row_to_tx_dict(cur.fetchone()) or {}
                conn.execute("COMMIT;")
                return "ACQUIRED", created
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in begin_governed_transaction(%s): %s", clean_nonce, e)
                raise
            finally:
                conn.close()

    def transition_governed_transaction(
        self,
        *,
        nonce: str,
        lifecycle_state: Union[TransactionState, str],
        bridge_status: str,
        failure_category: Optional[str] = None,
        error_code: Optional[str] = None,
        allocated_id: Optional[str] = None,
        message: Optional[str] = None,
        recovery_decision: Optional[str] = None,
        result_snapshot: Optional[Dict[str, Any]] = None,
        step_event: Optional[Dict[str, Any]] = None,
        clear_lease: bool = True,
        lease_seconds: Optional[int] = None,
        authority: Union[TransitionAuthority, str] = TransitionAuthority.ORDINARY,
        expected_from_state: Optional[Union[TransactionState, str, Iterable[Union[TransactionState, str]]]] = None,
        expected_version: Optional[int] = None,
        expected_correlation_id: Optional[str] = None,
        expected_attempt: Optional[int] = None,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
        evidence: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically enforce the authoritative transaction state-transition matrix using
        Compare-And-Swap (CAS) inside a SQLite `BEGIN IMMEDIATE` transaction.

        Guarantees:
        - Terminal states (`COMMITTED`, `RECONCILED`) cannot be overwritten by ordinary
          execution, stale workers, or illegal transitions.
        - `RECOVERY_REQUIRED` cannot be bypassed by ordinary retries or execution.
        - Stale workers (mismatched correlation_id, attempt_count, version, or expired lease)
          are rejected atomically without mutating any transaction metadata or step history.
        - Every rejection rolls back cleanly and raises `InvalidStateTransitionError`.
        """
        clean_nonce = str(nonce or "").strip()
        target_state_str = (
            lifecycle_state.value
            if isinstance(lifecycle_state, TransactionState)
            else str(lifecycle_state or "").strip().upper()
        )
        auth_enum = (
            authority
            if isinstance(authority, TransitionAuthority)
            else TransitionAuthority(str(authority or TransitionAuthority.ORDINARY.value).strip().upper())
        )
        now_dt = _utc_now()
        now_s = _utc_iso(now_dt)

        expected_states_set: Optional[set] = None
        if expected_from_state is not None:
            if isinstance(expected_from_state, (TransactionState, str)):
                raw_s = (
                    expected_from_state.value
                    if isinstance(expected_from_state, TransactionState)
                    else str(expected_from_state).strip().upper()
                )
                expected_states_set = {raw_s}
            else:
                expected_states_set = {
                    (s.value if isinstance(s, TransactionState) else str(s).strip().upper())
                    for s in expected_from_state
                }

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                row = cur.fetchone()
                if row is None:
                    conn.execute("COMMIT;")
                    return None

                ex = self._row_to_tx_dict(row) or {}
                current_state = str(ex.get("lifecycle_state") or "").strip().upper()
                current_ver = int(ex.get("version") or 1)
                current_corr = str(ex.get("correlation_id") or "").strip()
                current_attempt = int(ex.get("attempt_count") or 1)
                current_lease_owner = str(ex.get("lease_owner") or "").strip()

                def _validate_strict_identity_int(
                    raw_val: Any,
                    *,
                    field_name: str,
                    missing_code: str,
                    required: bool,
                ) -> Optional[int]:
                    """
                    TX-AUDIT-08: Strict genuine-integer validation for security-sensitive
                    transaction identity parameters (expected_attempt, expected_version).
                    - Accepts ONLY genuine built-in `int` values >= 1 (`type(raw_val) is int`).
                    - Strictly rejects bool (`True`/`False`), numeric strings (`"1"`, `"5"`),
                      floats including integral floats (`1.0`, `5.0`, `nan`, `inf`, `-inf`),
                      Decimal, negative values, zero, and None when mandatory.
                    - NEVER calls `int()` to coerce non-integer types.
                    """
                    if raw_val is None:
                        if required:
                            conn.execute("ROLLBACK;")
                            raise InvalidStateTransitionError(
                                f"Ordinary lease-protected transition {current_state} -> {target_state_str} "
                                f"for nonce '{clean_nonce}' requires explicit positive integer {field_name}.",
                                code=missing_code,
                                nonce=clean_nonce,
                                current_state=current_state,
                                target_state=target_state_str,
                                authority=auth_enum.value,
                            )
                        return None
                    if isinstance(raw_val, bool):
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Invalid boolean {field_name}={raw_val!r} for nonce '{clean_nonce}'; "
                            f"genuine positive integer required.",
                            code=missing_code,
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if type(raw_val) is not int:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Invalid non-integer {field_name}={raw_val!r} "
                            f"(type={type(raw_val).__name__}) for nonce '{clean_nonce}'; "
                            f"genuine positive integer required without implicit coercion.",
                            code="INVALID_WORKER_IDENTITY_TYPE",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if raw_val < 1:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Out-of-range {field_name}={raw_val} for nonce '{clean_nonce}'; "
                            f"must be a positive integer >= 1.",
                            code="INVALID_WORKER_IDENTITY_RANGE",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    return raw_val

                # 0. Strict pre-CAS type & range validation on any supplied expected_version / expected_attempt (TX-AUDIT-08)
                validated_exp_ver: Optional[int] = _validate_strict_identity_int(
                    expected_version,
                    field_name="expected_version",
                    missing_code="MISSING_EXPECTED_VERSION",
                    required=False,
                )
                validated_exp_attempt: Optional[int] = _validate_strict_identity_int(
                    expected_attempt,
                    field_name="expected_attempt",
                    missing_code="MISSING_WORKER_ATTEMPT",
                    required=False,
                )

                # 1. Explicit expected_from_state CAS check
                if expected_states_set is not None and current_state not in expected_states_set:
                    conn.execute("ROLLBACK;")
                    raise InvalidStateTransitionError(
                        f"CAS expected-state mismatch for nonce '{clean_nonce}': "
                        f"expected {sorted(expected_states_set)}, found '{current_state}'.",
                        code="CAS_STATE_MISMATCH",
                        nonce=clean_nonce,
                        current_state=current_state,
                        target_state=target_state_str,
                        authority=auth_enum.value,
                    )

                # 2. Explicit optimistic version CAS check
                if validated_exp_ver is not None and current_ver != validated_exp_ver:
                    conn.execute("ROLLBACK;")
                    raise InvalidStateTransitionError(
                        f"CAS version mismatch for nonce '{clean_nonce}': "
                        f"expected version {validated_exp_ver}, found {current_ver}.",
                        code="CAS_VERSION_MISMATCH",
                        nonce=clean_nonce,
                        current_state=current_state,
                        target_state=target_state_str,
                        authority=auth_enum.value,
                    )

                # 3. Authoritative transition-matrix & terminal-state validation
                effective_reason = reason if reason is not None else message
                effective_evidence = (
                    evidence
                    if evidence is not None
                    else (step_event if step_event is not None else recovery_decision)
                )
                effective_actor = (
                    actor
                    if actor is not None
                    else (step_event.get("actor") if isinstance(step_event, dict) else None)
                )
                rule = validate_state_transition(
                    current_state,
                    target_state_str,
                    auth_enum,
                    nonce=clean_nonce,
                    reason=effective_reason,
                    evidence=effective_evidence,
                    actor=effective_actor,
                )

                # 4. Unconditional worker identity, version, attempt & lease ownership validation (TX-AUDIT-04 & TX-AUDIT-08)
                if expected_correlation_id is not None and not isinstance(expected_correlation_id, str):
                    conn.execute("ROLLBACK;")
                    raise InvalidStateTransitionError(
                        f"Invalid non-string expected_correlation_id={expected_correlation_id!r} "
                        f"for nonce '{clean_nonce}'.",
                        code="INVALID_WORKER_IDENTITY_TYPE",
                        nonce=clean_nonce,
                        current_state=current_state,
                        target_state=target_state_str,
                        authority=auth_enum.value,
                    )
                clean_exp_corr = (
                    expected_correlation_id.strip()
                    if isinstance(expected_correlation_id, str) and expected_correlation_id.strip()
                    else None
                )
                is_ordinary_lease_transition = bool(
                    rule.requires_lease_owner and auth_enum == TransitionAuthority.ORDINARY
                )
                raw_lease_exp = ex.get("lease_expires_at")

                if is_ordinary_lease_transition:
                    # Mandatory caller worker identity arguments — NEVER silently defaulted or substituted
                    if clean_exp_corr is None:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Ordinary lease-protected transition {current_state} -> {target_state_str} "
                            f"for nonce '{clean_nonce}' requires non-empty expected_correlation_id.",
                            code="MISSING_WORKER_CORRELATION_ID",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    exp_attempt_int = _validate_strict_identity_int(
                        expected_attempt,
                        field_name="expected_attempt",
                        missing_code="MISSING_WORKER_ATTEMPT",
                        required=True,
                    )
                    exp_ver_int = _validate_strict_identity_int(
                        expected_version,
                        field_name="expected_version",
                        missing_code="MISSING_EXPECTED_VERSION",
                        required=True,
                    )

                    if not current_corr or current_corr != clean_exp_corr:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Stale worker rejected for nonce '{clean_nonce}': "
                            f"correlation_id '{clean_exp_corr}' does not match active '{current_corr}'.",
                            code="STALE_WORKER_CORRELATION_MISMATCH",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if not current_lease_owner:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Missing active lease_owner for nonce '{clean_nonce}' during ordinary transition.",
                            code="MISSING_ACTIVE_LEASE_OWNER",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if current_lease_owner != clean_exp_corr:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Stale lease owner '{clean_exp_corr}' rejected for nonce '{clean_nonce}' "
                            f"(active lease_owner='{current_lease_owner}').",
                            code="STALE_LEASE_OWNER",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if current_attempt != exp_attempt_int:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Stale worker rejected for nonce '{clean_nonce}': "
                            f"attempt {exp_attempt_int} does not match active attempt {current_attempt}.",
                            code="STALE_WORKER_ATTEMPT_MISMATCH",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if current_ver != exp_ver_int:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"CAS version mismatch for nonce '{clean_nonce}': "
                            f"expected version {exp_ver_int}, found {current_ver}.",
                            code="CAS_VERSION_MISMATCH",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    lease_dt = _parse_iso(raw_lease_exp)
                    if raw_lease_exp is None or not str(raw_lease_exp).strip() or lease_dt is None:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Missing or invalid execution lease expiration for nonce '{clean_nonce}'.",
                            code="MISSING_OR_INVALID_LEASE_EXPIRATION",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if now_dt >= lease_dt:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Expired execution lease for nonce '{clean_nonce}' (expired at {raw_lease_exp}).",
                            code="STALE_LEASE_EXPIRED",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                else:
                    # Non-ordinary authorities (RECOVERY, SECONDARY_QUARANTINE, RECONCILIATION) or
                    # non-lease-protected transitions: still enforce any explicitly passed worker CAS fields.
                    if clean_exp_corr is not None and current_corr != clean_exp_corr:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Stale worker rejected for nonce '{clean_nonce}': "
                            f"correlation_id '{clean_exp_corr}' does not match active '{current_corr}'.",
                            code="STALE_WORKER_CORRELATION_MISMATCH",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )
                    if validated_exp_attempt is not None and current_attempt != validated_exp_attempt:
                        conn.execute("ROLLBACK;")
                        raise InvalidStateTransitionError(
                            f"Stale worker rejected for nonce '{clean_nonce}': "
                            f"attempt {validated_exp_attempt} does not match active attempt {current_attempt}.",
                            code="STALE_WORKER_ATTEMPT_MISMATCH",
                            nonce=clean_nonce,
                            current_state=current_state,
                            target_state=target_state_str,
                            authority=auth_enum.value,
                        )

                # 5. Build auditable transition step preserving previous_state, authority, actor, reason
                steps = list(ex.get("steps") or [])
                step_entry: Dict[str, Any] = {
                    "step": target_state_str,
                    "from_state": current_state,
                    "to_state": target_state_str,
                    "authority": auth_enum.value,
                    "at": now_s,
                }
                if effective_actor:
                    step_entry["actor"] = str(effective_actor).strip()
                if effective_reason:
                    step_entry["reason"] = str(effective_reason).strip()[:240]
                if step_event:
                    step_entry.update(step_event)
                steps.append(step_entry)

                new_alloc = allocated_id if allocated_id is not None else ex.get("allocated_id")
                new_snapshot_json = (
                    json.dumps(result_snapshot, default=str)
                    if result_snapshot is not None
                    else ex.get("result_snapshot_json")
                )
                if clear_lease or rule.destination_is_terminal:
                    new_lease = None
                    new_lease_owner = None
                elif lease_seconds is not None:
                    new_lease = _utc_iso(now_dt + timedelta(seconds=max(5, int(lease_seconds))))
                    new_lease_owner = current_lease_owner or current_corr
                else:
                    new_lease = ex.get("lease_expires_at")
                    new_lease_owner = current_lease_owner or None

                # 6. Single atomic CAS UPDATE guarding nonce + lifecycle_state + version (+ unconditional worker/lease identity)
                where_clauses = ["nonce = ?", "lifecycle_state = ?", "version = ?"]
                where_params: List[Any] = [clean_nonce, current_state, current_ver]
                if is_ordinary_lease_transition:
                    where_clauses.extend([
                        "correlation_id = ?",
                        "lease_owner = ?",
                        "attempt_count = ?",
                        "lease_expires_at = ?",
                    ])
                    where_params.extend([
                        clean_exp_corr,
                        clean_exp_corr,
                        exp_attempt_int,
                        str(raw_lease_exp),
                    ])
                else:
                    if clean_exp_corr is not None:
                        where_clauses.append("correlation_id = ?")
                        where_params.append(clean_exp_corr)
                    if validated_exp_attempt is not None:
                        where_clauses.append("attempt_count = ?")
                        where_params.append(validated_exp_attempt)

                sql = f"""
                    UPDATE governed_transactions
                    SET lifecycle_state = ?,
                        previous_state = ?,
                        last_authority = ?,
                        bridge_status = ?,
                        failure_category = ?,
                        error_code = ?,
                        allocated_id = ?,
                        steps_json = ?,
                        result_snapshot_json = ?,
                        message = ?,
                        recovery_decision = ?,
                        updated_at = ?,
                        lease_expires_at = ?,
                        lease_owner = ?,
                        version = version + 1
                    WHERE {' AND '.join(where_clauses)}
                """
                params = [
                    target_state_str,
                    current_state,
                    auth_enum.value,
                    str(bridge_status).strip().upper(),
                    failure_category,
                    error_code,
                    new_alloc,
                    json.dumps(steps[-40:]),
                    new_snapshot_json,
                    message if message is not None else ex.get("message"),
                    recovery_decision if recovery_decision is not None else ex.get("recovery_decision"),
                    now_s,
                    new_lease,
                    new_lease_owner,
                    *where_params,
                ]
                cur.execute(sql, params)
                if cur.rowcount != 1:
                    conn.execute("ROLLBACK;")
                    raise InvalidStateTransitionError(
                        f"Atomic CAS update failed for nonce '{clean_nonce}' ({current_state} -> {target_state_str}).",
                        code="CAS_ATOMIC_CONFLICT",
                        nonce=clean_nonce,
                        current_state=current_state,
                        target_state=target_state_str,
                        authority=auth_enum.value,
                    )

                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                updated = self._row_to_tx_dict(cur.fetchone())
                conn.execute("COMMIT;")
                return updated
            except InvalidStateTransitionError:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            except CoordinatorDurabilityError:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            except Exception as e:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                logger.error("Error in transition_governed_transaction(%s): %s", clean_nonce, e)
                raise
            finally:
                conn.close()

    def get_governed_transaction(self, nonce: str) -> Optional[Dict[str, Any]]:
        clean_nonce = str(nonce or "").strip()
        if not clean_nonce:
            return None
        with self._thread_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                return self._row_to_tx_dict(cur.fetchone())
            except CoordinatorDurabilityError:
                raise
            except Exception as e:
                logger.error("Error in get_governed_transaction(%s): %s", clean_nonce, e)
                return None
            finally:
                conn.close()

    def list_unresolved_transactions(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._thread_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT * FROM governed_transactions
                    WHERE lifecycle_state IN ('UNKNOWN', 'RECOVERY_REQUIRED', 'PENDING', 'EXECUTING')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                )
                return [self._row_to_tx_dict(r) for r in cur.fetchall() if r is not None]
            except CoordinatorDurabilityError:
                raise
            except Exception as e:
                logger.error("Error in list_unresolved_transactions: %s", e)
                return []
            finally:
                conn.close()

    def mark_transaction_reconciled(
        self,
        *,
        nonce: str,
        actor_user_id: str,
        resolution_notes: str,
        final_allocated_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Mark a PENDING, UNKNOWN, or RECOVERY_REQUIRED transaction RECONCILED under
        RECONCILIATION authority after verified operator inspection.
        Cannot overwrite COMMITTED or already-RECONCILED transactions.
        """
        return self.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=TransactionState.RECONCILED,
            bridge_status="CONFIRMED",
            failure_category=None,
            error_code=None,
            allocated_id=final_allocated_id,
            message=resolution_notes,
            recovery_decision="RECONCILED_BY_OPERATOR",
            authority=TransitionAuthority.RECONCILIATION,
            expected_from_state=(
                TransactionState.UNKNOWN,
                TransactionState.RECOVERY_REQUIRED,
                TransactionState.PENDING,
            ),
            actor=actor_user_id,
            reason=resolution_notes,
            evidence={"reconciled_by": actor_user_id, "final_allocated_id": final_allocated_id},
            step_event={
                "step": "RECONCILED",
                "actor": actor_user_id,
                "notes": resolution_notes[:300],
            },
            clear_lease=True,
        )

    def reserve_approval(
        self,
        approval_id: str,
        sale_id: str,
        customer_id: str,
        requested_credit: float,
    ) -> Tuple[bool, str]:
        """
        Atomically reserves an approval for a specific sale_id.
        Returns (True, 'OK') or (False, reason).
        """
        clean_app = str(approval_id).strip()
        clean_sale = str(sale_id).strip()
        clean_cid = str(customer_id).strip()
        now = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute(
                    "SELECT approval_id, sale_id, status FROM approval_reservations WHERE approval_id = ?",
                    (clean_app,),
                )
                row = cur.fetchone()

                if row:
                    curr_sale = str(row["sale_id"]).strip()
                    curr_status = str(row["status"]).strip().upper()

                    if curr_status == "CONSUMED":
                        conn.execute("ROLLBACK;")
                        return False, f"already consumed by sale '{curr_sale}'"

                    if curr_status == "RESERVED":
                        if curr_sale == clean_sale:
                            conn.execute("COMMIT;")
                            return True, "already reserved by this sale"
                        conn.execute("ROLLBACK;")
                        return False, f"concurrently reserved by sale '{curr_sale}'"

                    if curr_status == "RELEASED":
                        cur.execute(
                            """
                            UPDATE approval_reservations
                            SET sale_id = ?, customer_id = ?, requested_credit = ?,
                                status = 'RESERVED', reserved_at = ?, released_at = NULL
                            WHERE approval_id = ?
                            """,
                            (clean_sale, clean_cid, requested_credit, now, clean_app),
                        )
                        conn.execute("COMMIT;")
                        return True, "reserved successfully"

                # Not existing in table -> insert
                cur.execute(
                    """
                    INSERT INTO approval_reservations
                    (approval_id, sale_id, customer_id, requested_credit, status, reserved_at)
                    VALUES (?, ?, ?, ?, 'RESERVED', ?)
                    """,
                    (clean_app, clean_sale, clean_cid, requested_credit, now),
                )
                conn.execute("COMMIT;")
                return True, "reserved successfully"
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK;")
                return False, "concurrently reserved by another transaction"
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in reserve_approval: %s", e)
                return False, str(e)
            finally:
                conn.close()

    def consume_approval(self, approval_id: str, sale_id: str) -> Tuple[bool, str]:
        """
        Atomically marks an approval as consumed by sale_id.
        Fails if approval is not reserved by this exact sale_id or was already consumed.
        """
        clean_app = str(approval_id).strip()
        clean_sale = str(sale_id).strip()
        now = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute(
                    "SELECT approval_id, sale_id, status FROM approval_reservations WHERE approval_id = ?",
                    (clean_app,),
                )
                row = cur.fetchone()

                if not row:
                    # In case reservation was outside coordinator, insert consumed
                    cur.execute(
                        """
                        INSERT INTO approval_reservations
                        (approval_id, sale_id, customer_id, requested_credit, status, reserved_at, consumed_at)
                        VALUES (?, ?, '', 0, 'CONSUMED', ?, ?)
                        """,
                        (clean_app, clean_sale, now, now),
                    )
                    conn.execute("COMMIT;")
                    return True, "consumed successfully"

                curr_sale = str(row["sale_id"]).strip()
                curr_status = str(row["status"]).strip().upper()

                if curr_status == "CONSUMED":
                    if curr_sale == clean_sale:
                        conn.execute("COMMIT;")
                        return True, "already consumed by this sale"
                    conn.execute("ROLLBACK;")
                    return False, f"already consumed by another sale '{curr_sale}'"

                if curr_sale != clean_sale:
                    conn.execute("ROLLBACK;")
                    return False, f"reservation is owned by sale '{curr_sale}', not '{clean_sale}'"

                cur.execute(
                    """
                    UPDATE approval_reservations
                    SET status = 'CONSUMED', consumed_at = ?
                    WHERE approval_id = ? AND sale_id = ? AND status = 'RESERVED'
                    """,
                    (now, clean_app, clean_sale),
                )
                if cur.rowcount == 0:
                    conn.execute("ROLLBACK;")
                    return False, "failed to update approval reservation to consumed"

                conn.execute("COMMIT;")
                return True, "consumed successfully"
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in consume_approval: %s", e)
                return False, str(e)
            finally:
                conn.close()

    def release_approval(self, approval_id: str, sale_id: str) -> Tuple[bool, str]:
        """
        Atomically releases an approval reservation owned by sale_id.
        Fails if the approval is not reserved by sale_id or was already consumed.
        """
        clean_app = str(approval_id).strip()
        clean_sale = str(sale_id).strip()
        now = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute(
                    "SELECT approval_id, sale_id, status FROM approval_reservations WHERE approval_id = ?",
                    (clean_app,),
                )
                row = cur.fetchone()

                if not row:
                    conn.execute("COMMIT;")
                    return True, "no reservation existed"

                curr_sale = str(row["sale_id"]).strip()
                curr_status = str(row["status"]).strip().upper()

                if curr_status == "CONSUMED":
                    conn.execute("ROLLBACK;")
                    return False, "cannot release already consumed approval"

                if curr_status == "RELEASED":
                    conn.execute("COMMIT;")
                    return True, "already released"

                if curr_sale != clean_sale:
                    conn.execute("ROLLBACK;")
                    return False, f"reservation owned by another sale '{curr_sale}'"

                cur.execute(
                    """
                    UPDATE approval_reservations
                    SET status = 'RELEASED', released_at = ?
                    WHERE approval_id = ? AND sale_id = ? AND status = 'RESERVED'
                    """,
                    (now, clean_app, clean_sale),
                )
                conn.execute("COMMIT;")
                return True, "released successfully"
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in release_approval: %s", e)
                return False, str(e)
            finally:
                conn.close()

    def reserve_customer_credit(
        self,
        customer_id: str,
        sale_id: str,
        requested_credit: float,
        credit_limit: float,
        current_outstanding: float,
    ) -> Tuple[bool, str]:
        """
        Atomically reserves customer credit against active exposure.
        Prevents two concurrent sales from both exceeding the credit limit.
        """
        clean_cid = str(customer_id).strip()
        clean_sale = str(sale_id).strip()
        now = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()

                # Sum active reservations for this customer excluding current sale_id
                cur.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) as total_reserved
                    FROM credit_reservations
                    WHERE customer_id = ? AND status = 'ACTIVE' AND sale_id != ?
                    """,
                    (clean_cid, clean_sale),
                )
                row = cur.fetchone()
                active_reserved = float(row["total_reserved"]) if row else 0.0

                total_exposure = round(current_outstanding + active_reserved + requested_credit, 2)
                if credit_limit > 0 and total_exposure > credit_limit:
                    conn.execute("ROLLBACK;")
                    return (
                        False,
                        f"Exposure ₹{total_exposure:.2f} exceeds credit limit ₹{credit_limit:.2f} "
                        f"(Outstanding: ₹{current_outstanding:.2f}, In-Flight: ₹{active_reserved:.2f}, Requested: ₹{requested_credit:.2f})",
                    )

                cur.execute(
                    """
                    INSERT INTO credit_reservations (customer_id, sale_id, amount, status, created_at)
                    VALUES (?, ?, ?, 'ACTIVE', ?)
                    ON CONFLICT(customer_id, sale_id) DO UPDATE SET
                    amount = excluded.amount, status = 'ACTIVE', created_at = excluded.created_at
                    """,
                    (clean_cid, clean_sale, requested_credit, now),
                )
                conn.execute("COMMIT;")
                return True, "credit reserved successfully"
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in reserve_customer_credit: %s", e)
                return False, str(e)
            finally:
                conn.close()

    def release_customer_credit(self, customer_id: str, sale_id: str):
        clean_cid = str(customer_id).strip()
        clean_sale = str(sale_id).strip()
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "UPDATE credit_reservations SET status = 'RELEASED' WHERE customer_id = ? AND sale_id = ?",
                    (clean_cid, clean_sale),
                )
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in release_customer_credit(%s, %s): %s", clean_cid, clean_sale, e)
            finally:
                conn.close()

    def finalize_customer_credit(self, customer_id: str, sale_id: str):
        clean_cid = str(customer_id).strip()
        clean_sale = str(sale_id).strip()
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "UPDATE credit_reservations SET status = 'FINALIZED' WHERE customer_id = ? AND sale_id = ?",
                    (clean_cid, clean_sale),
                )
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in finalize_customer_credit(%s, %s): %s", clean_cid, clean_sale, e)
            finally:
                conn.close()

    def acquire_idempotency_lock(self, idempotency_key: str, sale_id: str) -> Tuple[bool, Optional[str]]:
        """
        Attempts to acquire an idempotency lock for sale creation.
        Returns (True, sale_id) if acquired.
        Returns (False, existing_sale_id) if key was already claimed.
        """
        clean_key = str(idempotency_key).strip()
        clean_sale = str(sale_id).strip()
        now = _utc_iso()

        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute(
                    "SELECT sale_id, status FROM idempotency_locks WHERE idempotency_key = ?",
                    (clean_key,),
                )
                row = cur.fetchone()
                if row:
                    existing_sale = str(row["sale_id"]).strip()
                    conn.execute("COMMIT;")
                    return False, existing_sale

                cur.execute(
                    """
                    INSERT INTO idempotency_locks (idempotency_key, sale_id, status, created_at)
                    VALUES (?, ?, 'IN_PROGRESS', ?)
                    """,
                    (clean_key, clean_sale, now),
                )
                conn.execute("COMMIT;")
                return True, clean_sale
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK;")
                cur = conn.cursor()
                cur.execute(
                    "SELECT sale_id FROM idempotency_locks WHERE idempotency_key = ?",
                    (clean_key,),
                )
                row = cur.fetchone()
                existing_sale = str(row["sale_id"]).strip() if row else clean_sale
                return False, existing_sale
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in acquire_idempotency_lock: %s", e)
                return False, None
            finally:
                conn.close()

    def complete_idempotency_lock(self, idempotency_key: str, sale_id: str):
        clean_key = str(idempotency_key).strip()
        clean_sale = str(sale_id).strip()
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "UPDATE idempotency_locks SET status = 'COMPLETE' WHERE idempotency_key = ? AND sale_id = ?",
                    (clean_key, clean_sale),
                )
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in complete_idempotency_lock(%s): %s", clean_key, e)
            finally:
                conn.close()

    def release_idempotency_lock(self, idempotency_key: str):
        clean_key = str(idempotency_key).strip()
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "DELETE FROM idempotency_locks WHERE idempotency_key = ?",
                    (clean_key,),
                )
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in release_idempotency_lock(%s): %s", clean_key, e)
            finally:
                conn.close()

    def reset_store(self):
        """Empties all coordinator tables (for test teardown)."""
        with self._thread_lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("DELETE FROM approval_reservations;")
                conn.execute("DELETE FROM credit_reservations;")
                conn.execute("DELETE FROM idempotency_locks;")
                conn.execute("DELETE FROM governed_transactions;")
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in reset_store: %s", e)
            finally:
                conn.close()


# Global singleton instance
tx_coordinator = TransactionCoordinator.get_instance()
