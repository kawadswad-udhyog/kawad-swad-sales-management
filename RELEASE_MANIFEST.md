# KAWAD SWAD ERP - PRODUCTION RELEASE MANIFEST
**Release Branch**: `erp-production-upgrade`  
**Release Commit**: `48a548d`  
**Timestamp**: 2026-11-03T15:42:00Z  
**Release Title**: Complete Production ERP Upgrade: Multi-Batch Costing, Workforce Operations Safety, Full Grid Rollback Restoration & Multi-Module Dashboard Matrix  

---

### 1. SUMMARY OF RELEASE
This release unifies all operational modules of Kawad Swad Udhyog into a cohesive, production-grade ERP system:
- **Zero-Swallowed Exceptions & Post-Write Read-Back Verification**: All schema updates (`backend/app/workforce_migration.py`) verify the exact written headers against canonical schemas. Failures halt execution immediately, record the failed operation in `manifest.json`, and set status to `MIGRATION_FAILED`.
- **Pre-Migration Header Anomaly Detection**: Proactively detects blank headers, duplicate column names, and case-insensitive/whitespace ambiguity before executing writes or backups.
- **Full Grid & Formula Restoration Rollback**: The rollback engine uses `clear()` and re-populates row `A1` with full grid contents (preserving formulas like `=E2*F2`), validates worksheet ID (`worksheet_id`), and validates SHA-256 fingerprints before confirming restoration. Deletion of created sheets is refused (`RollbackRefusalError`) if active business records exist in row 2+.
- **Secure Authorization Architecture**: Authorization code is dynamically sourced from `SALES_MIGRATION_AUTH_CODE` without logging secrets. Live execution strictly enforces confirmation of the target spreadsheet ID (`--confirm-spreadsheet-id`).
- **16 Canonical Workforce Worksheets**: Full support for Employee, Freelancer, and Factory Labour operations without altering canonical identity (`Users`, `AuthUsers`) or legacy audit sheets (`Workers`, `WorkerAttendance`).
- **Integrated Factory Dashboard Matrix**: Quick operations matrix linking Workforce, Procurement, Accounting, Approvals, Production, and Stock. Floor attendance metrics aggregate active attendance across both new `LabourMaster`/`LabourAttendance` and legacy `Workers`/`WorkerAttendance`.
- **Complete ERP Regression Integrity**: Production multi-batch actual costing, SKU-level finished goods valuation, sales COGS recognition, double-entry balanced accounting, and inventory ledgers.

---

### 2. ARTIFACTS & VERSIONS
- **Frontend Build**: Vite 6.4.5 / React 18.3.1 / Tailwind CSS (Static output in `dist/`)
- **Backend API**: FastAPI 0.109.0 / Uvicorn (Root entry in `main.py` and `backend/main.py`)
- **Database Engine**: Google Sheets Adapter (`app.sheets.db`) with 65 managed tabs
- **Test Suite Results**: 280 / 280 Unit & Integration Tests Passed (11.01s)
- **Frontend Typecheck**: TypeScript 5.7.2 (`tsc --noEmit` Passed with 0 errors)
- **Frontend Production Build**: `npm run build` Passed (`✓ built in 13.62s`)

---

### 3. LIVE PRODUCTION SERVICES & STATUS RECONCILIATION
- **Backend URL**: `https://kawad-swad-sales-dev.onrender.com`
  - Health Endpoint: `https://kawad-swad-sales-dev.onrender.com/health` (HTTP 200, Connected, Persistent Writes Active)
  - Managed Tabs Endpoint: `https://kawad-swad-sales-dev.onrender.com/health/verify-tabs` (65/65 Tabs Verified)
- **Frontend URL**: `https://kawad-swad-sales-frontend.onrender.com` (HTTP 200)
- **Commit History Reconciliation**:
  - `cf6dac9`: Initial workforce migration safety engine and backup snapshot utility.
  - `52fc97d`: Documentation and intermediate release manifest.
  - `3f8fd8a`: Dashboard integration with multi-module operational matrix and combined attendance.
  - `48a548d`: Final hardened migration engine eliminating swallowed exceptions, enforcing post-write read-back verification, pre-migration header anomaly detection, and full-grid formula-preserving rollback.

---

### 4. MIGRATION & ROLLBACK OPERATIONAL INSTRUCTIONS

#### Dry-Run Audit (Default & Non-Destructive):
```bash
python3 backend/scripts/migrate_workforce_stage3.py --dry-run
```

#### Authorized Live Migration:
```bash
# Requires explicit environment authorization variable set by owner:
export SALES_MIGRATION_AUTH_CODE="<SECURE_OWNER_AUTH_CODE>"

python3 backend/scripts/migrate_workforce_stage3.py --execute \
    --authorization-code="$SALES_MIGRATION_AUTH_CODE" \
    --confirm-spreadsheet-id="<PRODUCTION_SPREADSHEET_ID>" \
    --backup-dir="backend/backups"
```

#### Guarded Rollback (Allowed only before live business data entry):
```bash
export SALES_MIGRATION_AUTH_CODE="<SECURE_OWNER_AUTH_CODE>"

python3 backend/scripts/migrate_workforce_stage3.py --rollback \
    --manifest="backend/backups/workforce_<MIGRATION_ID>/manifest.json" \
    --authorization-code="$SALES_MIGRATION_AUTH_CODE"
```

*Note: The rollback engine refuses worksheet deletion if row 2+ contains active business records (`RollbackRefusalError`).*
