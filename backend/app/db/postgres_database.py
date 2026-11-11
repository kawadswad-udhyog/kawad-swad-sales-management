"""
Kawad Swad ERP - Transactional PostgreSQL & ACID Row-Level Locking Database Engine.

Provides authoritative transactional guarantees, row-level locking (SELECT ... FOR UPDATE),
atomic credit approval reservations/consumption, customer credit limit tracking,
distributed sale idempotency locks, and van loading pass dispatch.

Supports real PostgreSQL via `DATABASE_URL` and ACID SQLite fallback for development and test runners.
"""

import os
import sys
import json
import math
import time
import sqlite3
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, date, timezone

logger = logging.getLogger("kawad_swad.db")

# Optional psycopg/psycopg2 import for PostgreSQL
_HAS_PSYCOPG = False
try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    from psycopg2.extras import RealDictCursor
    _HAS_PSYCOPG = True
except ImportError:
    try:
        import psycopg
        _HAS_PSYCOPG = True
    except ImportError:
        _HAS_PSYCOPG = False


def _get_db_path() -> str:
    """Returns path to the SQLite transactional database file."""
    shared_dir = os.getenv("SALES_SHARED_TEST_DIR")
    if shared_dir and os.path.exists(shared_dir):
        return os.path.join(shared_dir, "kawad_swad_erp_tx.db")
    custom_path = os.getenv("SALES_DATABASE_PATH")
    if custom_path:
        return custom_path
    return "/tmp/kawad_swad_erp_tx.db"


class PostgresDatabase:
    """
    Unified transactional database supporting PostgreSQL and ACID-compliant SQLite.
    Provides row-level locking semantics (SELECT ... FOR UPDATE) for financial
    authorizations, credit limits, idempotency locks, and stock dispatch.
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
        self.is_postgres = bool(
            self.database_url.startswith("postgresql://") or self.database_url.startswith("postgres://")
        )
        self._pg_pool = None
        self._initialized_paths = set()
        self._init_engine()

    def _init_engine(self):
        if self.is_postgres and _HAS_PSYCOPG:
            try:
                # Use psycopg2 ThreadedConnectionPool if available
                if "psycopg2" in sys.modules:
                    self._pg_pool = pg_pool.ThreadedConnectionPool(
                        minconn=1,
                        maxconn=20,
                        dsn=self.database_url
                    )
                    logger.info("Initialized PostgreSQL connection pool successfully.")
            except Exception as e:
                logger.error("Failed to initialize PostgreSQL pool (%s). Falling back to ACID SQLite.", e)
                self.is_postgres = False

        self.init_schema()

    def get_connection(self):
        """Acquires a database connection configured for immediate ACID transactions."""
        if self.is_postgres and self._pg_pool:
            conn = self._pg_pool.getconn()
            conn.autocommit = False
            return conn
        else:
            db_path = _get_db_path()
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and high busy timeout for concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            if db_path not in self._initialized_paths:
                self._ensure_sqlite_schema(conn)
                self._initialized_paths.add(db_path)
            return conn

    def _ensure_sqlite_schema(self, conn):
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    approval_id TEXT PRIMARY KEY,
                    request_type TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    requested_amount REAL NOT NULL,
                    approved_amount REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    decided_by_user_id TEXT,
                    decided_at TEXT,
                    expires_at TEXT NOT NULL,
                    is_revoked INTEGER NOT NULL DEFAULT 0,
                    revoked_at TEXT,
                    is_reserved INTEGER NOT NULL DEFAULT 0,
                    reserved_by_sale_id TEXT,
                    reserved_at TEXT,
                    is_consumed INTEGER NOT NULL DEFAULT 0,
                    consumed_by_sale_id TEXT,
                    consumed_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_customer ON approval_requests(customer_id, status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_res ON approval_requests(is_reserved, is_consumed);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS customer_credit_accounts (
                    customer_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    credit_limit REAL NOT NULL DEFAULT 0.0,
                    max_overdue_days INTEGER NOT NULL DEFAULT 0,
                    current_outstanding REAL NOT NULL DEFAULT 0.0,
                    reserved_outstanding REAL NOT NULL DEFAULT 0.0,
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    last_updated_at TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sale_idempotency_locks (
                    idempotency_key TEXT PRIMARY KEY,
                    sale_id TEXT,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'IN_FLIGHT',
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS van_loading_passes (
                    pass_id TEXT PRIMARY KEY,
                    pass_date TEXT NOT NULL,
                    van_id TEXT NOT NULL,
                    salesman_user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    dispatched_by_user_id TEXT,
                    dispatched_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS van_loading_pass_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pass_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    quantity_loaded REAL NOT NULL,
                    unit_of_measure TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_outbox_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    synced_at TEXT
                );
            """)
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass


    def release_connection(self, conn):
        """Releases or closes a connection."""
        if self.is_postgres and self._pg_pool:
            try:
                self._pg_pool.putconn(conn)
            except Exception:
                pass
        else:
            try:
                conn.close()
            except Exception:
                pass

    def init_schema(self):
        """Idempotently initializes database tables and constraints."""
        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS approval_requests (
                            approval_id VARCHAR(64) PRIMARY KEY,
                            request_type VARCHAR(64) NOT NULL,
                            customer_id VARCHAR(64) NOT NULL,
                            requested_amount NUMERIC(12, 2) NOT NULL,
                            approved_amount NUMERIC(12, 2) NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                            decided_by_user_id VARCHAR(64),
                            decided_at TIMESTAMP WITH TIME ZONE,
                            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
                            revoked_at TIMESTAMP WITH TIME ZONE,
                            is_reserved BOOLEAN NOT NULL DEFAULT FALSE,
                            reserved_by_sale_id VARCHAR(64),
                            reserved_at TIMESTAMP WITH TIME ZONE,
                            is_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                            consumed_by_sale_id VARCHAR(64),
                            consumed_at TIMESTAMP WITH TIME ZONE,
                            version INTEGER NOT NULL DEFAULT 1
                        );
                        CREATE INDEX IF NOT EXISTS idx_approvals_customer ON approval_requests(customer_id, status);
                        CREATE INDEX IF NOT EXISTS idx_approvals_res ON approval_requests(is_reserved, is_consumed);

                        CREATE TABLE IF NOT EXISTS customer_credit_accounts (
                            customer_id VARCHAR(64) PRIMARY KEY,
                            customer_name VARCHAR(255) NOT NULL,
                            credit_limit NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                            max_overdue_days INTEGER NOT NULL DEFAULT 0,
                            current_outstanding NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                            reserved_outstanding NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                            is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                            last_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        );

                        CREATE TABLE IF NOT EXISTS sale_idempotency_locks (
                            idempotency_key VARCHAR(128) PRIMARY KEY,
                            sale_id VARCHAR(64),
                            payload_hash VARCHAR(64) NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'IN_FLIGHT',
                            response_json JSONB,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                            expires_at TIMESTAMP WITH TIME ZONE NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS van_loading_passes (
                            pass_id VARCHAR(64) PRIMARY KEY,
                            pass_date DATE NOT NULL,
                            van_id VARCHAR(64) NOT NULL,
                            salesman_user_id VARCHAR(64) NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
                            dispatched_by_user_id VARCHAR(64),
                            dispatched_at TIMESTAMP WITH TIME ZONE,
                            version INTEGER NOT NULL DEFAULT 1
                        );

                        CREATE TABLE IF NOT EXISTS van_loading_pass_items (
                            item_id SERIAL PRIMARY KEY,
                            pass_id VARCHAR(64) REFERENCES van_loading_passes(pass_id) ON DELETE CASCADE,
                            product_id VARCHAR(64) NOT NULL,
                            batch_id VARCHAR(64) NOT NULL,
                            quantity_loaded NUMERIC(12, 2) NOT NULL,
                            unit_of_measure VARCHAR(32) NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS sync_outbox_events (
                            event_id BIGSERIAL PRIMARY KEY,
                            aggregate_type VARCHAR(64) NOT NULL,
                            aggregate_id VARCHAR(64) NOT NULL,
                            action VARCHAR(32) NOT NULL,
                            payload JSONB NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                            retry_count INTEGER NOT NULL DEFAULT 0,
                            last_error TEXT,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                            synced_at TIMESTAMP WITH TIME ZONE
                        );
                    """)
                    conn.commit()
            else:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS approval_requests (
                        approval_id TEXT PRIMARY KEY,
                        request_type TEXT NOT NULL,
                        customer_id TEXT NOT NULL,
                        requested_amount REAL NOT NULL,
                        approved_amount REAL NOT NULL,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        decided_by_user_id TEXT,
                        decided_at TEXT,
                        expires_at TEXT NOT NULL,
                        is_revoked INTEGER NOT NULL DEFAULT 0,
                        revoked_at TEXT,
                        is_reserved INTEGER NOT NULL DEFAULT 0,
                        reserved_by_sale_id TEXT,
                        reserved_at TEXT,
                        is_consumed INTEGER NOT NULL DEFAULT 0,
                        consumed_by_sale_id TEXT,
                        consumed_at TEXT,
                        version INTEGER NOT NULL DEFAULT 1
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_customer ON approval_requests(customer_id, status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_res ON approval_requests(is_reserved, is_consumed);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS customer_credit_accounts (
                        customer_id TEXT PRIMARY KEY,
                        customer_name TEXT NOT NULL,
                        credit_limit REAL NOT NULL DEFAULT 0.0,
                        max_overdue_days INTEGER NOT NULL DEFAULT 0,
                        current_outstanding REAL NOT NULL DEFAULT 0.0,
                        reserved_outstanding REAL NOT NULL DEFAULT 0.0,
                        is_blocked INTEGER NOT NULL DEFAULT 0,
                        last_updated_at TEXT
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sale_idempotency_locks (
                        idempotency_key TEXT PRIMARY KEY,
                        sale_id TEXT,
                        payload_hash TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'IN_FLIGHT',
                        response_json TEXT,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS van_loading_passes (
                        pass_id TEXT PRIMARY KEY,
                        pass_date TEXT NOT NULL,
                        van_id TEXT NOT NULL,
                        salesman_user_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'DRAFT',
                        dispatched_by_user_id TEXT,
                        dispatched_at TEXT,
                        version INTEGER NOT NULL DEFAULT 1
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS van_loading_pass_items (
                        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pass_id TEXT NOT NULL,
                        product_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        quantity_loaded REAL NOT NULL,
                        unit_of_measure TEXT NOT NULL
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sync_outbox_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        aggregate_type TEXT NOT NULL,
                        aggregate_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        synced_at TEXT
                    );
                """)
                conn.execute("COMMIT;")
        except Exception as e:
            logger.error("Failed to initialize database schema: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            self.release_connection(conn)

    def reset_database(self):
        """Clears all records in tables. Used between test runs."""
        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor() as cur:
                    cur.execute("""
                        TRUNCATE approval_requests, customer_credit_accounts,
                                 sale_idempotency_locks, van_loading_passes,
                                 van_loading_pass_items, sync_outbox_events CASCADE;
                    """)
                    conn.commit()
            else:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("DELETE FROM approval_requests;")
                conn.execute("DELETE FROM customer_credit_accounts;")
                conn.execute("DELETE FROM sale_idempotency_locks;")
                conn.execute("DELETE FROM van_loading_passes;")
                conn.execute("DELETE FROM van_loading_pass_items;")
                conn.execute("DELETE FROM sync_outbox_events;")
                conn.execute("COMMIT;")
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Error resetting database tables: %s", exc)
        finally:
            self.release_connection(conn)

    def sync_approval_record(self, appr: Dict[str, Any]) -> None:
        """
        Synchronizes or creates an approval record from Google Sheets into PostgreSQL.
        Ensures foreign approvals are available for row-level locking.
        """
        req_id = str(appr.get("request_id") or appr.get("approval_id") or "").strip()
        if not req_id:
            return

        payload = {}
        if appr.get("payload_json"):
            try:
                payload = json.loads(str(appr["payload_json"])) if isinstance(appr["payload_json"], str) else appr["payload_json"]
            except Exception:
                payload = {}

        cust_id = str(appr.get("customer_id") or payload.get("customer_id") or payload.get("target_customer_id") or "").strip()
        req_type = str(appr.get("request_type") or "CREDIT_EXCEPTION").strip().upper()

        raw_app_amt = appr.get("approved_amount") or appr.get("amount") or payload.get("approved_amount") or payload.get("amount") or 0.0
        try:
            app_amt = float(raw_app_amt)
        except (ValueError, TypeError):
            app_amt = 0.0

        raw_req_amt = appr.get("requested_amount") or payload.get("requested_amount") or app_amt
        try:
            req_amt = float(raw_req_amt)
        except (ValueError, TypeError):
            req_amt = app_amt

        status = str(appr.get("status") or "PENDING").strip().upper()
        decided_by = str(appr.get("decided_by") or appr.get("approved_by") or "").strip()
        decided_at = str(appr.get("decided_at") or "")

        raw_exp = appr.get("expires_at") or appr.get("valid_until") or appr.get("expiry_date") or payload.get("expires_at") or "2099-12-31"
        expires_at = str(raw_exp)[:10]

        is_revoked = int(bool(str(appr.get("revoked", "")).lower() in {"true", "1", "yes"} or status == "REVOKED"))
        revoked_at = str(appr.get("revoked_at") or "")

        reserved_sale = str(appr.get("reserved_by_sale_id") or payload.get("reserved_by_sale_id") or "").strip()
        is_reserved = int(bool(reserved_sale))
        reserved_at = str(appr.get("reserved_at") or "")

        consumed_sale = str(appr.get("consumed_by_sale_id") or payload.get("consumed_by_sale_id") or "").strip()
        is_consumed = int(bool(appr.get("is_consumed") or payload.get("is_consumed") or consumed_sale))
        consumed_at = str(appr.get("consumed_at") or "")

        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO approval_requests (
                            approval_id, request_type, customer_id, requested_amount, approved_amount,
                            status, decided_by_user_id, decided_at, expires_at, is_revoked, revoked_at,
                            is_reserved, reserved_by_sale_id, reserved_at, is_consumed, consumed_by_sale_id, consumed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (approval_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            approved_amount = EXCLUDED.approved_amount,
                            expires_at = EXCLUDED.expires_at,
                            is_revoked = EXCLUDED.is_revoked,
                            is_reserved = CASE WHEN approval_requests.is_reserved = TRUE THEN TRUE ELSE EXCLUDED.is_reserved END,
                            reserved_by_sale_id = COALESCE(approval_requests.reserved_by_sale_id, EXCLUDED.reserved_by_sale_id),
                            is_consumed = CASE WHEN approval_requests.is_consumed = TRUE THEN TRUE ELSE EXCLUDED.is_consumed END,
                            consumed_by_sale_id = COALESCE(approval_requests.consumed_by_sale_id, EXCLUDED.consumed_by_sale_id);
                    """, (
                        req_id, req_type, cust_id, req_amt, app_amt, status,
                        decided_by or None, decided_at or None, expires_at,
                        bool(is_revoked), revoked_at or None,
                        bool(is_reserved), reserved_sale or None, reserved_at or None,
                        bool(is_consumed), consumed_sale or None, consumed_at or None
                    ))
                    conn.commit()
            else:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("""
                    INSERT INTO approval_requests (
                        approval_id, request_type, customer_id, requested_amount, approved_amount,
                        status, decided_by_user_id, decided_at, expires_at, is_revoked, revoked_at,
                        is_reserved, reserved_by_sale_id, reserved_at, is_consumed, consumed_by_sale_id, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(approval_id) DO UPDATE SET
                        status = excluded.status,
                        approved_amount = excluded.approved_amount,
                        expires_at = excluded.expires_at,
                        is_revoked = excluded.is_revoked,
                        is_reserved = CASE WHEN approval_requests.is_reserved = 1 THEN 1 ELSE excluded.is_reserved END,
                        reserved_by_sale_id = COALESCE(approval_requests.reserved_by_sale_id, excluded.reserved_by_sale_id),
                        is_consumed = CASE WHEN approval_requests.is_consumed = 1 THEN 1 ELSE excluded.is_consumed END,
                        consumed_by_sale_id = COALESCE(approval_requests.consumed_by_sale_id, excluded.consumed_by_sale_id);
                """, (
                    req_id, req_type, cust_id, req_amt, app_amt, status,
                    decided_by, decided_at, expires_at,
                    is_revoked, revoked_at,
                    is_reserved, reserved_sale, reserved_at,
                    is_consumed, consumed_sale, consumed_at
                ))
                conn.execute("COMMIT;")
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Error syncing approval record %s: %s", req_id, exc)
        finally:
            self.release_connection(conn)

    # -------------------------------------------------------------------------
    # TRANSACTIONAL ROW-LEVEL LOCKING METHODS
    # -------------------------------------------------------------------------

    def reserve_approval_tx(
        self,
        approval_id: str,
        sale_id: str,
        customer_id: str,
        requested_credit: float
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Atomically locks and reserves an approval request using SELECT ... FOR UPDATE.
        Enforces validation, checks amount, expiry, and prevents concurrent double-reservation.
        """
        clean_id = str(approval_id).strip()
        clean_sale_id = str(sale_id).strip()
        clean_cust_id = str(customer_id).strip()

        if math.isnan(requested_credit) or math.isinf(requested_credit) or requested_credit <= 0:
            return False, f"Invalid requested credit amount: {requested_credit}", None

        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("BEGIN;")
                    cur.execute("""
                        SELECT * FROM approval_requests
                        WHERE approval_id = %s
                        FOR UPDATE;
                    """, (clean_id,))
                    row = cur.fetchone()
                    if not row:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' not found in database.", None

                    # Strict checks
                    if str(row["status"]).upper() != "APPROVED":
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' has status '{row['status']}' (must be APPROVED).", None
                    if row["is_revoked"]:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' has been revoked.", None

                    exp_str = str(row["expires_at"])[:10]
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                        if date.today() > exp_date:
                            cur.execute("ROLLBACK;")
                            return False, f"Approval request '{clean_id}' expired on {exp_str}.", None
                    except Exception:
                        pass

                    if str(row["customer_id"]).strip() != clean_cust_id:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' is for customer '{row['customer_id']}', does not match '{clean_cust_id}'.", None

                    app_amt = float(row["approved_amount"])
                    if requested_credit > app_amt + 0.05:
                        cur.execute("ROLLBACK;")
                        return False, f"Requested credit ₹{requested_credit:.2f} exceeds approved limit of ₹{app_amt:.2f}.", None

                    # Check already consumed
                    if row["is_consumed"]:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' has already been consumed by sale '{row['consumed_by_sale_id']}'.", None

                    # Check already reserved
                    holder = str(row["reserved_by_sale_id"] or "").strip()
                    if row["is_reserved"] and holder and holder != clean_sale_id:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' was concurrently reserved by sale '{holder}'.", None

                    # Reserve atomically
                    now = datetime.now(timezone.utc).isoformat()
                    cur.execute("""
                        UPDATE approval_requests SET
                            is_reserved = TRUE,
                            reserved_by_sale_id = %s,
                            reserved_at = %s,
                            version = version + 1
                        WHERE approval_id = %s;
                    """, (clean_sale_id, now, clean_id))
                    conn.commit()
                    return True, None, dict(row)
            else:
                # SQLite: BEGIN IMMEDIATE establishes write lock before reading
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("""
                    SELECT * FROM approval_requests WHERE approval_id = ?;
                """, (clean_id,))
                row = cur.fetchone()
                if not row:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' not found in database.", None

                row_dict = dict(row)
                if str(row_dict["status"]).upper() != "APPROVED":
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' has status '{row_dict['status']}' (must be APPROVED).", None
                if bool(row_dict["is_revoked"]):
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' has been revoked.", None

                exp_str = str(row_dict["expires_at"])[:10]
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    if date.today() > exp_date:
                        conn.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' expired on {exp_str}.", None
                except Exception:
                    pass

                if str(row_dict["customer_id"]).strip() != clean_cust_id:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' is for customer '{row_dict['customer_id']}', does not match '{clean_cust_id}'.", None

                app_amt = float(row_dict["approved_amount"])
                if requested_credit > app_amt + 0.05:
                    conn.execute("ROLLBACK;")
                    return False, f"Requested credit ₹{requested_credit:.2f} exceeds approved limit of ₹{app_amt:.2f}.", None

                if bool(row_dict["is_consumed"]):
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' has already been consumed by sale '{row_dict['consumed_by_sale_id']}'.", None

                holder = str(row_dict["reserved_by_sale_id"] or "").strip()
                if bool(row_dict["is_reserved"]) and holder and holder != clean_sale_id:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' was concurrently reserved by sale '{holder}'.", None

                now = datetime.now(timezone.utc).isoformat()
                cur.execute("""
                    UPDATE approval_requests SET
                        is_reserved = 1,
                        reserved_by_sale_id = ?,
                        reserved_at = ?,
                        version = version + 1
                    WHERE approval_id = ?;
                """, (clean_sale_id, now, clean_id))
                conn.execute("COMMIT;")
                return True, None, row_dict
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("reserve_approval_tx failed for %s: %s", clean_id, exc)
            return False, f"Database transaction error reserving approval: {exc}", None
        finally:
            self.release_connection(conn)

    def consume_approval_tx(self, approval_id: str, sale_id: str) -> Tuple[bool, Optional[str]]:
        """
        Atomically marks an approval request as consumed within a row lock.
        Validates reservation ownership, non-revocation, and prevents double-consumption.
        """
        clean_id = str(approval_id).strip()
        clean_sale_id = str(sale_id).strip()

        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("BEGIN;")
                    cur.execute("""
                        SELECT * FROM approval_requests
                        WHERE approval_id = %s
                        FOR UPDATE;
                    """, (clean_id,))
                    row = cur.fetchone()
                    if not row:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' not found."

                    if row["is_consumed"]:
                        if str(row["consumed_by_sale_id"]).strip() == clean_sale_id:
                            cur.execute("COMMIT;")
                            return True, None  # Idempotent
                        cur.execute("ROLLBACK;")
                        return False, f"Approval was already consumed by sale '{row['consumed_by_sale_id']}'."

                    holder = str(row["reserved_by_sale_id"] or "").strip()
                    if holder != clean_sale_id:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval is reserved by '{holder}', cannot be consumed by sale '{clean_sale_id}'."

                    if row["is_revoked"]:
                        cur.execute("ROLLBACK;")
                        return False, "Approval was revoked while reserved."

                    now = datetime.now(timezone.utc).isoformat()
                    cur.execute("""
                        UPDATE approval_requests SET
                            is_consumed = TRUE,
                            consumed_by_sale_id = %s,
                            consumed_at = %s,
                            version = version + 1
                        WHERE approval_id = %s;
                    """, (clean_sale_id, now, clean_id))
                    conn.commit()
                    return True, None
            else:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM approval_requests WHERE approval_id = ?;", (clean_id,))
                row = cur.fetchone()
                if not row:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' not found."

                row_dict = dict(row)
                if bool(row_dict["is_consumed"]):
                    if str(row_dict["consumed_by_sale_id"] or "").strip() == clean_sale_id:
                        conn.execute("COMMIT;")
                        return True, None
                    conn.execute("ROLLBACK;")
                    return False, f"Approval was already consumed by sale '{row_dict['consumed_by_sale_id']}'."

                holder = str(row_dict["reserved_by_sale_id"] or "").strip()
                if holder != clean_sale_id:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval is reserved by '{holder}', cannot be consumed by sale '{clean_sale_id}'."

                if bool(row_dict["is_revoked"]):
                    conn.execute("ROLLBACK;")
                    return False, "Approval was revoked while reserved."

                now = datetime.now(timezone.utc).isoformat()
                cur.execute("""
                    UPDATE approval_requests SET
                        is_consumed = 1,
                        consumed_by_sale_id = ?,
                        consumed_at = ?,
                        version = version + 1
                    WHERE approval_id = ?;
                """, (clean_sale_id, now, clean_id))
                conn.execute("COMMIT;")
                return True, None
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("consume_approval_tx failed for %s: %s", clean_id, exc)
            return False, f"Database transaction error consuming approval: {exc}"
        finally:
            self.release_connection(conn)

    def release_approval_tx(self, approval_id: str, sale_id: str) -> Tuple[bool, Optional[str]]:
        """
        Atomically releases an approval reservation if sale creation aborted.
        Never releases an already consumed approval.
        """
        clean_id = str(approval_id).strip()
        clean_sale_id = str(sale_id).strip()

        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("BEGIN;")
                    cur.execute("""
                        SELECT * FROM approval_requests
                        WHERE approval_id = %s
                        FOR UPDATE;
                    """, (clean_id,))
                    row = cur.fetchone()
                    if not row:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval request '{clean_id}' not found."

                    if row["is_consumed"]:
                        cur.execute("ROLLBACK;")
                        return False, f"Cannot release consumed approval (consumed by {row['consumed_by_sale_id']})."

                    holder = str(row["reserved_by_sale_id"] or "").strip()
                    if holder != clean_sale_id:
                        cur.execute("ROLLBACK;")
                        return False, f"Approval is reserved by '{holder}', release requested by '{clean_sale_id}'."

                    cur.execute("""
                        UPDATE approval_requests SET
                            is_reserved = FALSE,
                            reserved_by_sale_id = NULL,
                            reserved_at = NULL,
                            version = version + 1
                        WHERE approval_id = %s;
                    """, (clean_id,))
                    conn.commit()
                    return True, None
            else:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM approval_requests WHERE approval_id = ?;", (clean_id,))
                row = cur.fetchone()
                if not row:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval request '{clean_id}' not found."

                row_dict = dict(row)
                if bool(row_dict["is_consumed"]):
                    conn.execute("ROLLBACK;")
                    return False, f"Cannot release consumed approval (consumed by {row_dict['consumed_by_sale_id']})."

                holder = str(row_dict["reserved_by_sale_id"] or "").strip()
                if holder != clean_sale_id:
                    conn.execute("ROLLBACK;")
                    return False, f"Approval is reserved by '{holder}', release requested by '{clean_sale_id}'."

                cur.execute("""
                    UPDATE approval_requests SET
                        is_reserved = 0,
                        reserved_by_sale_id = NULL,
                        reserved_at = NULL,
                        version = version + 1
                    WHERE approval_id = ?;
                """, (clean_id,))
                conn.execute("COMMIT;")
                return True, None
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("release_approval_tx failed for %s: %s", clean_id, exc)
            return False, f"Database transaction error releasing approval: {exc}"
        finally:
            self.release_connection(conn)

    # -------------------------------------------------------------------------
    # IDEMPOTENCY LOCKS
    # -------------------------------------------------------------------------

    def acquire_idempotency_lock_tx(
        self,
        idempotency_key: str,
        payload_hash: str,
        sale_id: str,
        ttl_seconds: int = 3600
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Attempts to acquire an idempotency lock atomically.
        Returns ("ACQUIRED", None) if new lock acquired.
        Returns ("REPLAY", response_data) if already completed with identical payload.
        Returns ("CONFLICT", None) if key reused with different payload.
        Returns ("IN_FLIGHT", None) if another worker is currently processing this key.
        """
        clean_key = str(idempotency_key).strip()
        conn = self.get_connection()
        try:
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            exp = datetime.fromtimestamp(time.time() + ttl_seconds, tz=timezone.utc).isoformat()

            if self.is_postgres:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("BEGIN;")
                    cur.execute("""
                        SELECT * FROM sale_idempotency_locks
                        WHERE idempotency_key = %s
                        FOR UPDATE;
                    """, (clean_key,))
                    row = cur.fetchone()
                    if not row:
                        cur.execute("""
                            INSERT INTO sale_idempotency_locks (
                                idempotency_key, sale_id, payload_hash, status, created_at, expires_at
                            ) VALUES (%s, %s, %s, 'IN_FLIGHT', %s, %s);
                        """, (clean_key, sale_id, payload_hash, now, exp))
                        conn.commit()
                        return "ACQUIRED", None

                    # Row exists
                    if str(row["payload_hash"]) != payload_hash:
                        cur.execute("ROLLBACK;")
                        return "CONFLICT", None

                    if str(row["status"]).upper() == "COMMITTED":
                        resp = row["response_json"]
                        cur.execute("COMMIT;")
                        return "REPLAY", resp

                    # Still in flight
                    cur.execute("ROLLBACK;")
                    return "IN_FLIGHT", None
            else:
                conn.execute("BEGIN IMMEDIATE;")
                cur = conn.cursor()
                cur.execute("SELECT * FROM sale_idempotency_locks WHERE idempotency_key = ?;", (clean_key,))
                row = cur.fetchone()
                if not row:
                    cur.execute("""
                        INSERT INTO sale_idempotency_locks (
                            idempotency_key, sale_id, payload_hash, status, created_at, expires_at
                        ) VALUES (?, ?, ?, 'IN_FLIGHT', ?, ?);
                    """, (clean_key, sale_id, payload_hash, now, exp))
                    conn.execute("COMMIT;")
                    return "ACQUIRED", None

                row_dict = dict(row)
                if str(row_dict["payload_hash"]) != payload_hash:
                    conn.execute("ROLLBACK;")
                    return "CONFLICT", None

                if str(row_dict["status"]).upper() == "COMMITTED":
                    resp = json.loads(row_dict["response_json"]) if row_dict["response_json"] else None
                    conn.execute("COMMIT;")
                    return "REPLAY", resp

                conn.execute("ROLLBACK;")
                return "IN_FLIGHT", None
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("acquire_idempotency_lock_tx error: %s", exc)
            return "ERROR", None
        finally:
            self.release_connection(conn)

    def complete_idempotency_lock_tx(
        self,
        idempotency_key: str,
        sale_id: str,
        response_data: Dict[str, Any]
    ) -> bool:
        """Marks an in-flight idempotency lock as COMMITTED with response data."""
        clean_key = str(idempotency_key).strip()
        resp_json = json.dumps(response_data)
        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE sale_idempotency_locks SET
                            status = 'COMMITTED',
                            sale_id = %s,
                            response_json = %s
                        WHERE idempotency_key = %s;
                    """, (sale_id, resp_json, clean_key))
                    conn.commit()
                    return True
            else:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("""
                    UPDATE sale_idempotency_locks SET
                        status = 'COMMITTED',
                        sale_id = ?,
                        response_json = ?
                    WHERE idempotency_key = ?;
                """, (sale_id, resp_json, clean_key))
                conn.execute("COMMIT;")
                return True
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("complete_idempotency_lock_tx error: %s", exc)
            return False
        finally:
            self.release_connection(conn)

    def release_idempotency_lock_tx(self, idempotency_key: str) -> bool:
        """Deletes an in-flight idempotency lock on failure so requests can retry."""
        clean_key = str(idempotency_key).strip()
        conn = self.get_connection()
        try:
            if self.is_postgres:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sale_idempotency_locks WHERE idempotency_key = %s;", (clean_key,))
                    conn.commit()
                    return True
            else:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("DELETE FROM sale_idempotency_locks WHERE idempotency_key = ?;", (clean_key,))
                conn.execute("COMMIT;")
                return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            self.release_connection(conn)


# Global singleton instance
_PG_DB_INSTANCE: Optional[PostgresDatabase] = None

def get_postgres_db() -> PostgresDatabase:
    """Returns the process-wide PostgresDatabase instance."""
    global _PG_DB_INSTANCE
    if _PG_DB_INSTANCE is None:
        _PG_DB_INSTANCE = PostgresDatabase()
    return _PG_DB_INSTANCE
