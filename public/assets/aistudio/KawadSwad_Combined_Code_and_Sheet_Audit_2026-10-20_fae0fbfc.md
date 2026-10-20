# Kawad Swad ERP: Combined Code + Spreadsheet Audit
**Audit date:** 20 October 2026  
**Code source:** `kawad-swad-sales-management-main (24).zip`  
**Spreadsheet source:** `Kawad_Swad_Sales_Management_Google_Sheets.xlsx`  
**Scope:** employee identity reconciliation, sheet/code schema alignment, production and packaging integrity, ledger references, and audit trail.

## Executive summary

**Overall: HIGH RISK. Do not use this workbook as a clean starting point for live production data without reviewing the findings below.** The workbook's `START_HERE` sheet describes it as a development template and says not to connect it to the live ERP sheet until tested. Although it contains populated records and audit events, this audit treats it as the uploaded workbook snapshot, not proof of the live Google Sheets state.

The backend test suite was run against the latest ZIP: **86 passed, 13 warnings**. Tests passing does not validate the actual workbook rows. No source files or spreadsheet records were changed; no live Google Sheets connection was made and no deployment was performed.

## Critical findings

### C1. Duplicate employee identity `USR-000002` in both Users and AuthUsers
**Evidence in workbook:** `Users` contains two rows with `user_id=USR-000002` (Mahi Sharma, role PA; Manish Gosami, role SALESMAN). `AuthUsers` also contains two rows with `user_id=USR-000002` (username `mahi.-.sharma--`, role PA; username `manish`, role SALESMAN). Both auth rows also share `auth_id=AUT-000002`.

**Code impact:** `backend/app/user_service.py:get_all_users_with_auth()` builds `auth_by_uid` as a dictionary keyed by `user_id`; the second auth row overwrites the first. Both profile rows then resolve to the same last auth record. In this workbook, Mahi's profile can be displayed with Manish's username/role. `update_record()` also updates the first matching ID row, so actions keyed only by `USR-000002` are ambiguous.

**Severity:** Critical. This can misattribute identity and permissions and makes employee edits/deactivation unsafe.

**Required action:** Freeze changes to either `USR-000002` account until the Owner confirms which profile and auth row belongs to each person. Assign a unique, stable user ID to the legitimate second employee, ensure the corresponding auth row references that ID, assign unique `auth_id` values, then verify audit references and sessions. Do not automatically change historical sales/production actor IDs without reviewing which person performed each action.

### C2. Packaging batch `PKG-000001` is internally inconsistent and has posted stock
**Workbook values:** `bulk_kg_used=75`, 100 × 200 g packets, `expected_kg=20`, `difference_kg=55`, `difference_status=REVIEW_REQUIRED`, but `status=RECORDED`. The production stock ledger contains a 75 kg `BULK_PACKAGED` movement and a 100-packet `PACKETS_PACKAGED` movement against the same reference.

**Code comparison:** Current `backend/app/routers/production.py:create_packaging()` is designed to save a `PENDING_REVIEW` record and block completion when an unexplained variance exceeds tolerance without approval. The workbook's `RECORDED` state conflicts with that intended control.

**Impact:** 55 kg is unaccounted for in the packaging record. The ledger has already deducted 75 kg bulk while crediting only 20 kg of packed product. Do not silently approve or change the 55 kg difference.

**Required action:** Physically verify remaining bulk and finished packets, check whether `bulk_kg_used` was entered incorrectly, and confirm whether the 100 packets were actually produced. Then use a documented Owner-approved correction/reconciliation. Preserve the original record and add an audit trail; do not delete the ledger movements merely to make totals match.

### C3. Pending production batch `PRB-000002` has a bulk inventory credit
**Workbook values:** `ProductionBatches` marks `PRB-000002` as `PENDING`, with 18 kg net output and no `approved_by`/`approved_at`. `ProductionStockLedger` nevertheless contains `PST-000003`, `BULK_PRODUCED`, quantity 18 kg, reference `PRB-000002`. Raw-material consumption rows also exist for this batch.

**Impact:** Pending production is included in the stock ledger. That can inflate available bulk stock and appears to have enabled the 75 kg packaging deduction. Material issuance before approval may be an intentional workflow, but inventory credit for unapproved output is inconsistent with the current approval flow.

**Required action:** Confirm whether the 18 kg batch was physically produced and approved. Reconcile the batch status and ledger reference with evidence. If it was not approved/produced, correct through a controlled reversing movement rather than deleting ledger history. Add a regression test that pending batches never receive `BULK_PRODUCED` credits.

### C4. Owner profile is incomplete in Users
The Owner row has `full_name=Your Full Name` and a blank `Users.username`, while the matching `AuthUsers` row uses `ankit_owner`.

**Impact:** The profile and authentication identity are inconsistent, and UI displays may fall back to the username or ID depending on the endpoint.

**Required action:** Owner should confirm the intended display name and username. Update profile data through the supported administrative workflow and keep the authentication username as the login identity. Do not expose password hashes in any report.

## High-priority code findings

### H1. User update can report success after AuthUsers synchronization fails
`backend/app/user_service.py:execute_update_user()` catches a failure updating `AuthUsers`, logs a warning, and proceeds to audit/return. This can leave profile and login roles inconsistent while the API reports success.

**Fix:** Treat the operation as incomplete; persist an operation/reconciliation state, invalidate sessions before role changes take effect, verify both records, and only return success after verification or clearly return a recoverable partial-failure response.

### H2. Status changes can report success after AuthUsers write failure
`execute_set_user_status()` updates `Users`, then catches an `AuthUsers` failure and still returns `{ok: true}`. That violates immediate deactivation and consistent account status.

**Fix:** Fail visibly and record a repairable operation. A deactivation must fail closed for authentication immediately, including existing tokens, even if the second sheet write is unavailable.

### H3. User listing collapses duplicate auth rows
`get_all_users_with_auth()` silently overwrites duplicate `user_id` records in a dictionary and defaults missing auth rows to active. It does not surface duplicates or orphaned records.

**Fix:** Reconciliation must independently scan both tabs, report duplicate keys before joining, and mark missing auth records as `MISSING_AUTH_RECORD` rather than active.

### H4. PA password-reset requests persist plaintext passwords
`backend/app/routers/users.py:reset_password()` sends `{"new_password": req.new_password}` into `ApprovalRequests.payload_json` for PA requests. The approval endpoint later reads that value to execute the reset.

**Impact:** The workbook approval tab can contain usable passwords in plaintext. This conflicts with the agreed policy that PA must not set a temporary password.

**Fix:** Stop creating new plaintext password approval payloads. Use a reset request without a password, then after Owner approval generate a one-time secure setup/reset flow. Inspect existing approval records for plaintext secrets, remove them safely from the approval payload after establishing the reset workflow, and rotate any affected credentials. Do not include secrets in audit logs.

### H5. Approval execution is not safely idempotent across partial success
`backend/app/routers/approvals.py` executes the operation before writing the request status `EXECUTED`. If the operation succeeds but the status write fails, retry can repeat the operation. For `CREATE_USER`, this can create duplicate accounts; for update/status actions it can repeat side effects.

**Fix:** Add an idempotency key/operation ID to the executed action, verify prior completion before retry, and separate decision status from execution status. A retry must reconcile first, not blindly execute again.

### H6. Authentication cache and revocation require stronger consistency
`backend/app/sheets.py` allows stale cached records to be served on some quota-error paths for non-fresh reads. The auth code must never use stale status/role data to grant privileged access. The uploaded workbook's `AuthUsers` header lacks `sessions_revoked_at`, which the current code expects; `update_record()` can append missing headers dynamically, but this creates schema drift and should be corrected in the template.

**Fix:** Ensure authorization-critical reads fail closed when freshness cannot be established, implement/test cross-instance session revocation, and align required worksheet headers explicitly.

## Spreadsheet/code schema alignment

The workbook differs from the latest code's `REQUIRED_TABS` schema. Examples:
- `AuthUsers` is missing `sessions_revoked_at`.
- `ApprovalRequests` does not have `requested_by_name` although the approval code writes it. The adapter can add missing headers dynamically, but the template is behind the code.
- `ProductionBatches` lacks several newer fields used by the code, including `gross_output_kg`, `process_loss_kg`, `loss_reason`, `saleable_output_kg`, `unexplained_variance_kg`, and `materials_issued`.
- `PackagingBatches` lacks newer fields used by the code, including `packing_loss_kg`, `loss_reason`, discrepancy approval/explanation metadata, and approval timestamps.
- Several other tabs have legacy extra columns, including `Expenses`, `ShopVisits`, `SalaryIncentives`, `RawMaterials`, and `RawMaterialLedger`.

Because `append_record()` and `update_record()` can add columns dynamically, this is not automatically proof that writes are being discarded. It is a schema-drift risk: the workbook template does not document the exact current contract, and exports/reconciliation tools may interpret columns differently. Create a versioned schema migration/check that verifies required headers and reports extras before any live write.

## Recipe/product identity mapping

All 15 recipe rows use product IDs such as `PRD-MOONG-MASTER`, while the Products tab uses SKU-level IDs such as `PRD-0001`, `PRD-0002`, etc. The current production logic can match approved recipes by `product_name_snapshot`, so this may be an intentional bulk-product versus packaged-SKU design. However, the workbook has no explicit master-product mapping table, and a strict foreign-key audit reports all recipe product IDs as unmatched.

**Required action:** Document the intended mapping and add a stable `bulk_product_id` or master-product mapping table. Do not rewrite recipe IDs automatically until the intended design is confirmed.

## Other workbook observations

- The `Products` tab has 46 rows, including a mini product with ID `PRD-000046`, while the main sequence uses IDs like `PRD-0001` through `PRD-0048` with gaps. This is not automatically a duplicate, but mixed ID formats should be standardized for future allocations.
- The `ProductionBatches` yield fields are internally plausible for `PRB-000001` and `PRB-000003`; the unresolved status/ledger issue is `PRB-000002`.
- Raw-material balances are calculated by code as the master stock baseline minus ledger consumption plus receipts. The workbook calls the baseline `current_stock`, although the calculation treats it like opening stock. Rename/document this field or migrate it carefully; do not subtract ledger consumption twice.
- Sales, sale items, payments, salesman stock, cash, expenses, daily closing, salary incentives, and approval request tabs are empty in this workbook snapshot. Therefore, transaction-to-payment or salary reconciliation cannot be meaningfully completed from this file yet.
- `START_HERE` explicitly labels this workbook a development template. Confirm whether it is a template/sample or an export of the actual live spreadsheet before applying any repair plan.

## Recommended remediation sequence

1. **Stop writes to ambiguous employee ID `USR-000002`** until the two people are separated safely.
2. **Owner review of `PKG-000001` and `PRB-000002`** against physical stock and actual production evidence.
3. **Remove plaintext-password approval design** and establish a secure post-approval reset/invitation workflow.
4. Fix user update/deactivation to never silently succeed after a partial write.
5. Build a read-only reconciliation auditor for `Users` and `AuthUsers`, including duplicate keys, missing counterparts, username collisions, role/status differences, and credential-field presence (never report credential values).
6. Align the workbook headers with the current versioned schema.
7. Add tests for duplicate user IDs, duplicate auth IDs, partial sheet writes, stale caches, pending production inventory credits, packaging discrepancy blocking, and idempotent approval retries.
8. Run reconciliation again, review all unresolved findings with the Owner, then apply logged repairs.

## Test result and limitations

- Latest ZIP backend test suite: **86 passed, 13 warnings**.
- This does not mean the workbook data passes reconciliation. The workbook contains concrete inconsistencies listed above.
- Live Google Sheets was not accessed. No rows were modified.
- No production deployment was tested.
- Password hashes and other credential values were deliberately excluded from this report.
