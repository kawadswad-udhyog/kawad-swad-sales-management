# KAWAD SWAD ERP - MASTER STAGE 3 RELEASE MANIFEST
**Release Branch**: `stage3-workforce-production-release`  
**Release Commit**: `cf6dac93e4bf5b1398628baa7cc55aa6cf68115c`  
**Timestamp**: 2026-11-03T15:11:07Z  
**Release Title**: Master Stage 3 Workforce Security, Migration Safety, Formula Backups, Guarded Rollback & Enterprise Release  

---

### 1. SUMMARY OF RELEASE
This release packages the complete Master Stage 3 upgrade for Kawad Swad ERP:
- **Workforce Migration Safety**: Formula-preserving snapshot backups (`value_render_option="FORMULA"`), SHA-256 fingerprinting, pre-migration verification, and guarded non-destructive rollback.
- **16 Canonical Workforce Worksheets**: Full support for Employee, Freelancer, and Factory Labour operations.
- **Data & Identity Preservation**: `Users` preserved as canonical employee identity source; `AuthUsers` preserved as login source; `Workers` and `WorkerAttendance` preserved as legacy history.
- **Payroll & Incentive Synchronization**: Incentive calculation math strictly aligned with `salary.py` (PAID, DELIVERED, != CANCELLED); automatic parent `PayrollRuns` header totals synchronization on item adjustment.
- **Workforce Payment Idempotency**: Strict deduplication for `WorkforcePayments` and balanced double-entry accounting journals (`post_workforce_payment_journal`).
- **Complete ERP Regression Integrity**: Production multi-batch costing, SKU-level finished goods valuation, sales COGS recognition, double-entry balanced accounting, and inventory ledgers.

---

### 2. ARTIFACTS & VERSIONS
- **Frontend Build**: Vite 6.0.7 / React 18.3.1 (Static output in `dist/`)
- **Backend API**: FastAPI 0.109.0 / Uvicorn (Root entry in `main.py` and `backend/main.py`)
- **Database Engine**: Google Sheets Adapter (`app.sheets.db`) with 65 managed tabs
- **Test Suite Results**: 276 / 276 Unit & Integration Tests Passed (12.18s)
- **Frontend Typecheck**: TypeScript 5.7.2 (`tsc --noEmit` Passed with 0 errors)
- **Frontend Production Build**: `npm run build` Passed (`✓ built in 15.49s`)

---

### 3. LIVE PRODUCTION SERVICES
- **Backend URL**: `https://kawad-swad-sales-dev.onrender.com`
  - Health Endpoint: `https://kawad-swad-sales-dev.onrender.com/health` (HTTP 200, Connected, Persistent Writes Active)
  - Managed Tabs Endpoint: `https://kawad-swad-sales-dev.onrender.com/health/verify-tabs` (65/65 Tabs Verified)
- **Frontend URL**: `https://kawad-swad-sales-frontend.onrender.com` (HTTP 200)

---

### 4. MIGRATION & ROLLBACK OPERATIONAL INSTRUCTIONS

#### Dry-Run Audit (Default & Non-Destructive):
```bash
python3 backend/scripts/migrate_workforce_stage3.py --dry-run
```

#### Authorized Live Migration:
```bash
python3 backend/scripts/migrate_workforce_stage3.py --execute \
    --authorization-code=STAGE3_WORKFORCE_GATE1_CONFIRMED \
    --confirm-spreadsheet-id="<PRODUCTION_SPREADSHEET_ID>" \
    --backup-dir="backend/backups"
```

#### Guarded Rollback (Allowed only before live business data entry):
```bash
python3 backend/scripts/migrate_workforce_stage3.py --rollback \
    --manifest="backend/backups/workforce_stage3_<MIGRATION_ID>/manifest.json" \
    --authorization-code=STAGE3_WORKFORCE_GATE1_CONFIRMED
```

*Note: The rollback engine refuses worksheet deletion if row 2+ contains active business records (`RollbackRefusalError`).*
