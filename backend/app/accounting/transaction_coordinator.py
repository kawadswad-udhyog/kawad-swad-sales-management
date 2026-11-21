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
from typing import Tuple, Optional, Dict, Any, List

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("TRANSACTION_DB_PATH", "/tmp/kawad_swad_tx_coord.db")
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

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.environ.get("TRANSACTION_DB_PATH", DEFAULT_DB_PATH)
        self._thread_lock = threading.RLock()
        self._init_sqlite()

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> "TransactionCoordinator":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

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
                    bridge_status TEXT NOT NULL,
                    failure_category TEXT,
                    error_code TEXT,
                    allocated_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    steps_json TEXT,
                    result_snapshot_json TEXT,
                    message TEXT,
                    recovery_decision TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_expires_at TEXT
                );
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
        return d

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
        - ("ACQUIRED", tx_dict): Fresh transaction claimed in EXECUTING state.
        - ("RETRY_ACQUIRED", tx_dict): Prior confirmed-not-committed (FAILED/PENDING) attempt
          safely re-acquired with incremented attempt_count.
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

                    if ex_action != clean_action or ex_tab != clean_tab:
                        conn.execute("COMMIT;")
                        return "ACTION_CONFLICT", ex_dict

                    if ex_hash != clean_hash:
                        # Strictly reject payload mismatch for COMMITTED, RECONCILED, EXECUTING,
                        # UNKNOWN, RECOVERY_REQUIRED, PENDING, or any attempt that received an ID.
                        # Only a definitively confirmed pre-commit FAILED attempt (zero allocated_id)
                        # may be corrected and retried under the same deterministic reference nonce.
                        if ex_state != "FAILED" or bool(ex_dict.get("allocated_id")):
                            conn.execute("COMMIT;")
                            return "PAYLOAD_CONFLICT", ex_dict

                    if ex_state in {"COMMITTED", "RECONCILED"}:
                        conn.execute("COMMIT;")
                        return "ALREADY_COMMITTED", ex_dict

                    if ex_state in {"INITIATED", "VALIDATING", "EXECUTING"}:
                        lease_dt = _parse_iso(ex_dict.get("lease_expires_at"))
                        if lease_dt is not None and now_dt < lease_dt:
                            conn.execute("COMMIT;")
                            return "IN_PROGRESS", ex_dict
                        # Lease expired (worker crash/restart while executing) -> transition to UNKNOWN
                        steps = list(ex_dict.get("steps") or [])
                        steps.append({
                            "step": "STALE_LEASE_DETECTED",
                            "at": now_s,
                            "correlation_id": clean_corr,
                        })
                        cur.execute(
                            """
                            UPDATE governed_transactions
                            SET lifecycle_state = 'UNKNOWN',
                                bridge_status = 'PENDING_UNKNOWN',
                                failure_category = 'WRITE_OUTCOME_UNKNOWN',
                                error_code = 'STALE_EXECUTION_LEASE',
                                steps_json = ?,
                                updated_at = ?,
                                lease_expires_at = NULL
                            WHERE nonce = ?
                            """,
                            (json.dumps(steps), now_s, clean_nonce),
                        )
                        cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                        updated = self._row_to_tx_dict(cur.fetchone()) or ex_dict
                        conn.execute("COMMIT;")
                        return "RECOVERY_CHECK_REQUIRED", updated

                    if ex_state in {"UNKNOWN", "RECOVERY_REQUIRED"}:
                        conn.execute("COMMIT;")
                        return "RECOVERY_CHECK_REQUIRED", ex_dict

                    # Confirmed-not-committed (FAILED or PENDING) -> safe to re-acquire with same nonce
                    next_attempt = int(ex_dict.get("attempt_count") or 1) + 1
                    steps = list(ex_dict.get("steps") or [])
                    steps.append({
                        "step": "RETRY_STARTED" if ex_hash == clean_hash else "RETRY_STARTED_AFTER_CONFIRMED_FAILURE",
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
                            bridge_status = 'PENDING_UNKNOWN',
                            failure_category = NULL,
                            error_code = NULL,
                            attempt_count = ?,
                            steps_json = ?,
                            updated_at = ?,
                            lease_expires_at = ?
                        WHERE nonce = ?
                        """,
                        (clean_corr, clean_hash, next_attempt, json.dumps(steps), now_s, lease_exp_s, clean_nonce),
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
                    {"step": "EXECUTING", "attempt": 1, "at": now_s, "correlation_id": clean_corr},
                ]
                cur.execute(
                    """
                    INSERT INTO governed_transactions (
                        nonce, transaction_id, correlation_id, action, target_tab,
                        actor_user_id, payload_hash, lifecycle_state, bridge_status,
                        attempt_count, steps_json, created_at, updated_at, lease_expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'EXECUTING', 'PENDING_UNKNOWN', 1, ?, ?, ?, ?)
                    """,
                    (
                        clean_nonce,
                        tx_id,
                        clean_corr,
                        clean_action,
                        clean_tab,
                        clean_actor,
                        clean_hash,
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
        lifecycle_state: str,
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
    ) -> Optional[Dict[str, Any]]:
        """Atomically record a transaction lifecycle transition and optional step/snapshot."""
        clean_nonce = str(nonce or "").strip()
        now_dt = _utc_now()
        now_s = _utc_iso(now_dt)

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
                steps = list(ex.get("steps") or [])
                if step_event:
                    steps.append({"at": now_s, **step_event})
                else:
                    steps.append({"step": lifecycle_state, "at": now_s})

                new_alloc = allocated_id if allocated_id is not None else ex.get("allocated_id")
                new_snapshot_json = (
                    json.dumps(result_snapshot, default=str)
                    if result_snapshot is not None
                    else ex.get("result_snapshot_json")
                )
                if clear_lease:
                    new_lease = None
                elif lease_seconds is not None:
                    new_lease = _utc_iso(now_dt + timedelta(seconds=max(5, int(lease_seconds))))
                else:
                    new_lease = ex.get("lease_expires_at")

                cur.execute(
                    """
                    UPDATE governed_transactions
                    SET lifecycle_state = ?,
                        bridge_status = ?,
                        failure_category = ?,
                        error_code = ?,
                        allocated_id = ?,
                        steps_json = ?,
                        result_snapshot_json = ?,
                        message = ?,
                        recovery_decision = ?,
                        updated_at = ?,
                        lease_expires_at = ?
                    WHERE nonce = ?
                    """,
                    (
                        str(lifecycle_state).strip().upper(),
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
                        clean_nonce,
                    ),
                )
                cur.execute("SELECT * FROM governed_transactions WHERE nonce = ?", (clean_nonce,))
                updated = self._row_to_tx_dict(cur.fetchone())
                conn.execute("COMMIT;")
                return updated
            except Exception as e:
                conn.execute("ROLLBACK;")
                logger.error("Error in transition_governed_transaction(%s): %s", clean_nonce, e)
                return None
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
        """Mark an UNKNOWN or RECOVERY_REQUIRED transaction RECONCILED after manual/verified inspection."""
        return self.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state="RECONCILED",
            bridge_status="CONFIRMED",
            failure_category=None,
            error_code=None,
            allocated_id=final_allocated_id,
            message=resolution_notes,
            recovery_decision="RECONCILED_BY_OPERATOR",
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
