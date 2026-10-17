# Manual deployment guide

Do this only after you have a backup of the current site and a copy of the development spreadsheet. Do not point this build at a production ERP spreadsheet.

## 1. Upload the project to GitHub yourself

1. Unzip `kawad-swad-sales-management-complete.zip`.
2. You should see one folder, `kawad-swad-sales-management-main`, containing `backend`, `src`, `package.json`, and this guide.
3. On GitHub, open your existing repository. Use “Upload files” or replace the old source with these folders. Do not upload `node_modules`, `.env`, or any service-account JSON file. Those are not in the ZIP.
4. Commit the upload on the branch your host already builds, usually `main`.

## 2. Backend host settings

Keep the current style of deploy:

- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Set these environment variables on the backend service. Do not paste them into the Git repository.

| Variable | What to put |
| --- | --- |
| `SALES_GOOGLE_SPREADSHEET_ID` | The development spreadsheet ID only |
| `SALES_GOOGLE_SERVICE_ACCOUNT_FILE` | Path to the secret file on the host, usually `/etc/secrets/sales-service-account.json` |
| `SALES_JWT_SECRET` | A new random string, at least 32 characters. If the host already generated one, keep that same value so existing logins stay valid. |
| `SALES_CORS_ORIGINS` | The exact frontend address, for example `https://your-frontend.onrender.com`, plus `http://localhost:3000` if you test locally. Do not use `*`. |
| `SALES_ENV` | `production` on the hosted service |
| `SALES_TOKEN_HOURS` | `8` unless you want a shorter login |

The backend will refuse to start if the JWT secret is missing or is the old built-in default, and it will refuse wildcard CORS when `SALES_ENV=production`.

Open `https://your-backend/health`. It should say `"status": "ok"`. `google_sheets_connected` should be true only after the spreadsheet ID and service account are set.

## 3. Frontend host settings

- Root directory: the repository root (blank)
- Build command: `npm install && npm run build`
- Publish directory: `dist`
- `VITE_API_URL`: the public backend address, with no slash at the end

The app no longer hides a development backend address in the code. The build must receive `VITE_API_URL`.

## 4. Spreadsheet tabs to confirm

Existing sales tabs stay as they are. The first successful write may add columns; it will not clear rows.

Confirm these production tabs exist before using Production:

- RawMaterials, Workers, WorkerAttendance, Recipes, ProductionBatches, PackagingBatches, ProductionStockLedger, ProductionDispatches, RawMaterialLedger

Raw material names in a recipe must match the RawMaterials name exactly. Each packet size you package (200 g, 500 g, 1000 g) needs its own active product row with that pack weight and the same product name.

## 5. Safe check on the development site

1. Sign in as the owner. If an old password was stored as plain text, sign-in will refuse it. On a computer that has the service-account file, run `python scripts/reset_password.py` from the `backend` folder, then sign in and change the password.
2. Create one test product, issue a few packets to a test salesman, and make one small cash bill. Check the sheet for one sale, one item, one payment, one cash row, and one stock row.
3. Download the PDF once. The bill number must not change and stock must not move again.
4. Submit one test expense and approve it. The status should change only after the page finishes saving.
5. In Production, save one recipe, record one small batch, approve it, and confirm the raw-material ledger lost only that recipe quantity once. Retrying approval must not deduct twice.
6. Delete the test rows yourself if you do not want them kept. The app will not bulk-delete them.

## 6. Roll back

1. In GitHub, open the commit from before this upload.
2. Redeploy that older commit on both the backend and the frontend.
3. Keep the same `SALES_JWT_SECRET` if you want current logins to continue. Changing it signs everyone out, which is safe but inconvenient.
4. Extra columns added to the sheet can stay. The older app ignores columns it does not know.

Do not deploy this build against the production ERP spreadsheet.
