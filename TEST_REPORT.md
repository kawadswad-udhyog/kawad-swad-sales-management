# Test report

Run on this computer on 17 October 2026. No live Google Sheet was contacted. `SALES_GOOGLE_SPREADSHEET_ID` was empty. Tests use in-memory sheet storage.

## Passed

### Backend pytest

Command, from `backend`:

`python -m pytest tests -q --tb=line`

Environment: `SALES_TESTING=1`, a test-only JWT secret, empty spreadsheet id.

Result: **30 passed**, 4 deprecation warnings, about 2.3 seconds.

The warnings are `datetime.utcnow()` in `backend/app/routers/customers.py`. They do not fail the tests.

Passed tests:

- Anonymous and named retail billing, optional buyer fields, invoice text without buyer details
- Rejection of an invalid product, quantity, price, and a payment that does not match the server total
- Idempotent retry of a completed sale does not duplicate it
- Two different idempotency keys create two sales
- Oversized and malformed idempotency keys are rejected
- Concurrent requests with the same key do not create two bills
- Client-supplied bill total is rejected; inactive product is rejected; overselling is rejected
- A retry after a failed payment write repairs the payment and does not add a second stock movement
- UPI payment stores the reference and does not write a cash ledger line
- A salesman cannot bill under another salesman's identity
- Plaintext passwords are rejected; an empty AuthUsers list does not log anyone in
- A PA cannot create an Owner
- There is no public owner-setup route
- Product active/inactive updates, salesman forbidden from product updates, sheet boolean parsing
- Duplicate daily closing is rejected and a physical stock difference is flagged
- Production cannot be approved without an approved recipe; approval consumes raw materials once
- Packaging consumes bulk kilograms; a dispatch is not recorded as a sale

### Frontend build

Command, from the project root, with `NODE_OPTIONS=--use-system-ca` because this PC's Node install could not verify the npm certificate without the Windows certificate store:

`npm install --no-audit --no-fund`

Result: 101 packages added.

`npm run build` (`tsc && vite build`)

Result: **passed**. TypeScript completed with no errors. Vite built `dist/` in about 4.9 seconds. Vite warned that the main JavaScript chunk is larger than 500 kB. That is a size notice, not a failed build.

`npm run lint` is the same `tsc --noEmit` check already included in the build. It was not run as a second command.

## Failed

None in the commands above.

## Skipped

No tests were skipped by pytest.

## Blocked or not run

- Live Google Sheets reads and writes were not run. There is no proof here that the real spreadsheet accepts the new columns.
- No browser click-through of the screens was run. The production build compiled; the pages were not opened in a browser.
- Excel export was not opened in Excel.
- Password reset against a real AuthUsers sheet was not run.
- Two separate deployed servers writing the same sheet at the same time were not tested. The code uses a claim row and an in-process lock. That is not a perfect lock across two servers.
- GST, wage amounts, and recipes were not tested with business numbers because those values are not invented by the app.

## Environment note

The first `npm install` attempts hung because Node reported `UNABLE_TO_VERIFY_LEAF_SIGNATURE` against `registry.npmjs.org`. PowerShell could reach the same address. The successful install and build used the Windows certificate store (`--use-system-ca`). That setting was used only on this PC for the build. It is not written into the project.

## Follow-up safety-hardening run (17 October 2026)

After the critical-sheet freshness change, the backend suite was run again from `backend`:

`SALES_TESTING=1 SALES_JWT_SECRET=test-only-secret-do-not-use-for-deployment-32 python -m pytest tests -q --tb=short`

Result: **54 passed, 5 warnings**. The added quota-handling tests verify that critical sheets such as `AuthUsers` and `Products` do not use stale cache data when a fresh Google Sheets read is required. This run used test mode and did not contact a live spreadsheet. The frontend was not rebuilt as part of this follow-up patch.
