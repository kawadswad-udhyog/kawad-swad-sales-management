# Kawad Swad ERP — Mission 51B-1 Repair Round 2 README

## What Was Fixed in Round 2

1. **`TX-AUDIT-01` — Authoritative Transaction State Machine & Atomic CAS:**
   - Implemented single authoritative `LEGAL_TRANSITION_MATRIX` (24 explicit rules) in `backend/app/transaction_safety.py`.
   - Protected terminal states (`COMMITTED`, `RECONCILED`) and `RECOVERY_REQUIRED` against illegal overwrites (`COMMITTED -> FAILED` is now atomically rejected with `TERMINAL_STATE_PROTECTED` and zero DB mutation).
   - Enforced SQLite `BEGIN IMMEDIATE` Compare-And-Swap (`WHERE nonce = ? AND lifecycle_state = ? AND version = ?`) plus worker `correlation_id` / `attempt_count` / lease ownership checks in `backend/app/accounting/transaction_coordinator.py` and `backend/app/apps_script_bridge.py`.
   - Separated transition authorities (`ORDINARY`, `RETRY`, `RECOVERY`, `SECONDARY_QUARANTINE`, `RECONCILIATION`).

2. **`TX-AUDIT-02` — Persistent Coordinator Durability & Restart Safety:**
   - Eliminated silent fallback to volatile `/tmp/kawad_swad_tx_coord.db` in production.
   - Configured persistent Render disk (`/var/data/kawad_swad`) and single-instance safeguards (`WEB_CONCURRENCY=1`, `SALES_INSTANCE_COUNT=1`) in `render.yaml` and `.env.example`.
   - Added fail-closed production startup validation (`backend/app/config.py`) and runtime mutation gating (HTTP 503 if coordinator storage is missing/unwritable).
   - Added startup stale-lease recovery (`recover_stale_leases_on_startup`) and post-coordinator-loss Google Sheets `IdAllocations` lookup (`_find_existing_sheets_allocation_for_nonce`) so retries after local DB loss never blindly duplicate gateway POSTs.

3. **`TX-AUDIT-03` — Package Hygiene & Reproducible Release Verification:**
   - Removed unused accidental prompt artifact `public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f` and empty parent directories.
   - Added `scripts/verify_package_hygiene.py` to verify ZIP structural integrity (`testzip()=None`), zero forbidden artifacts/secrets/DBs, required Round 2 files, and final SHA-256 digest.

---

## Independent Verification Commands

```bash
# 1. Mission 51B-1 Round 2 state-integrity, durability, restart & hygiene suite (25 tests)
python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v

# 2. Mission 51B-1 Round 1 transaction safety suite (21 tests)
python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v

# 3. Complete backend regression suite (626 discovered tests)
python3 -m unittest discover -s backend/tests -t backend

# 4. Frontend typecheck, transaction safety & contract checks
npx tsc --noEmit
npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts
npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts

# 5. Frontend production build & lint
npm run build
npm run lint

# 6. Verify finalized release archive integrity, hygiene & SHA-256
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round2_Audit_Package.zip
```

## Detailed Engineering Report

See `docs/MISSION_51B1_ROUND2_REPAIR_REPORT.md` for Deliverables A–H (pre-fix defect evidence, full 24-rule state-transition matrix, durability architecture, change manifest, failure-injection verification results, and honest external dependencies).
