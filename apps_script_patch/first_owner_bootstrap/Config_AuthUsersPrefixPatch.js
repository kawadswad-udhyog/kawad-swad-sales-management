/**
 * Kawad Swad ERP — Isolated Pre-Merge Patch Spec for `Config.js`
 * File: Config_AuthUsersPrefixPatch.js
 *
 * Status:
 *   ISOLATED PATCH SPECIFICATION ONLY — NOT MERGED INTO LIVE APPS SCRIPT.
 *
 * Verified Against Verbatim Export:
 *   File: Config.js (06/43)
 *   SHA-256: 30b7baacde143ff306b936c9a9da0cf3c88a8cbd529a0040744d58639dfa243b
 *   Export lines: 3002–3168 (Code body starts at export line 3006 = Config.js line 1)
 *
 * Why This Patch Is MANDATORY Before Merging `BootstrapOwnerHandler.js`:
 *   1. `IdAllocator.js:7-9` (export lines 4377–4379) enforces a strict prefix allowlist:
 *        if (!targetTabName || !KS_CONFIG.ID_PREFIXES[targetTabName]) {
 *          throw new Error('Invalid or unapproved target table for ID allocation: ' + targetTabName);
 *        }
 *   2. In verbatim `Config.js:29-117` (export lines 3034–3122), `Users: 'USR'` IS present
 *      (`Config.js:44`, export line 3049), but `AuthUsers` IS OMITTED.
 *   3. Because `KS_CONFIG` (`Config.js:7`, export line 3012) and `KS_CONFIG.ID_PREFIXES`
 *      (`Config.js:29`, export line 3034) are wrapped in `Object.freeze(...)`, `AuthUsers`
 *      CANNOT be registered dynamically at runtime by another script file.
 *   4. Canonical prefix `'AUTH'` for `AuthUsers` is independently confirmed by BOTH:
 *      - Bound Apps Script `Code.js:2129` (export line 2877):
 *          `KS_MASTER.ID_RULES: { ..., Users:['user_id','USR'], AuthUsers:['auth_id','AUTH'], ... }`
 *      - FastAPI Backend `backend/app/sheets.py:63`:
 *          `"AuthUsers": "AUTH"`
 *
 * Exact Authorized Surgical Diff to Apply to Bound `Config.js` During Merge:
 *
 * --- Config.js (original verbatim, export lines 3024–3054)
 * +++ Config.js (with AuthUsers canonical prefix registered)
 * @@ -18,10 +18,11 @@
 *      PRODUCTS: 'Products',
 *      RAW_MATERIALS: 'RawMaterials',
 *      CUSTOMERS: 'Customers',
 *      SUPPLIERS: 'Suppliers',
 *      USERS: 'Users',
 * +    AUTH_USERS: 'AuthUsers',
 *      INVENTORY_LOTS: 'InventoryLots',
 *      INVENTORY_MOVEMENTS: 'InventoryMovements'
 *    }),
 *
 * @@ -41,8 +42,9 @@
 *      Customers: 'CUST',
 *      Suppliers: 'SUP',
 *      Users: 'USR',
 * +    AuthUsers: 'AUTH',
 *      Employees: 'EMP',
 *      FactoryLocations: 'FAC',
 *      Warehouses: 'WH',
 *
 * Notes:
 *   - Preserves all existing `KS_CONFIG.TABS`, `KS_CONFIG.ID_PREFIXES`, and `KS_CONFIG.REQUIRED_HEADERS`
 *     entries untouched.
 *   - Produces canonical `AuthUsers` IDs via `IdAllocator.js:65` (`AUTH-YYYYMMDD-00001`), which passes
 *     FastAPI `backend/app/schema_registry.py:357` (`_ID_FORMAT_RE = r"^([A-Z]{2,6})-[A-Z0-9_-]{3,}$"`).
 *   - `BootstrapOwnerHandler.js` asserts `KS_CONFIG.ID_PREFIXES.AuthUsers === 'AUTH'` upfront before
 *     allocating any ID, so an unpatched `Config.js` fails closed cleanly with zero orphaned IDs.
 */
