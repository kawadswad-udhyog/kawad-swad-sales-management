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
 * Frozen Configuration Structure Verification:
 *   Verbatim `Config.js` declares:
 *     - `const KS_CONFIG = Object.freeze({ ... })` (`Config.js:7`, export line 3012)
 *     - `TABS: Object.freeze({ ... })` (`Config.js:14-26`, export lines 3019–3031)
 *     - `ID_PREFIXES: Object.freeze({ ... })` (`Config.js:29-117`, export lines 3034–3122)
 *     - `REQUIRED_HEADERS: Object.freeze({ ... })` (`Config.js:120-147`, export lines 3125–3152)
 *   Because both `KS_CONFIG` and its nested `TABS` / `ID_PREFIXES` / `REQUIRED_HEADERS`
 *   maps are frozen via `Object.freeze(...)`, `AuthUsers` CANNOT be added at runtime by any
 *   external script file. The 2-line surgical edit below inserts `AUTH_USERS: 'AuthUsers'`
 *   inside the `TABS: Object.freeze({ ... })` object literal and `AuthUsers: 'AUTH'` inside
 *   the `ID_PREFIXES: Object.freeze({ ... })` object literal — preserving 100% of the
 *   existing frozen structure, immutability guarantees, and every existing key untouched.
 *
 * Why This Patch Is MANDATORY Before Merging `BootstrapOwnerHandler.js`:
 *   1. `IdAllocator.js:8-10` (export lines 4377–4379) enforces a strict prefix allowlist:
 *        if (!targetTabName || !KS_CONFIG.ID_PREFIXES[targetTabName]) {
 *          throw new Error('Invalid or unapproved target table for ID allocation: ' + targetTabName);
 *        }
 *   2. Verbatim `Config.js:44` (export line 3049) registers `Users: 'USR'` but omits `AuthUsers`.
 *   3. Canonical prefix `'AUTH'` for `AuthUsers` is independently confirmed by BOTH:
 *      - Bound Apps Script `Code.js:2129` (export line 2877):
 *          `KS_MASTER.ID_RULES: { ..., Users:['user_id','USR'], AuthUsers:['auth_id','AUTH'], ... }`
 *      - FastAPI Backend `backend/app/sheets.py:63`:
 *          `"AuthUsers": "AUTH"`
 *
 * Exact Authorized Surgical Diff to Apply to Bound `Config.js` During Merge:
 *
 * --- Config.js (original verbatim, export lines 3019–3054)
 * +++ Config.js (with AuthUsers canonical prefix inside existing Object.freeze literals)
 * @@ -14,13 +14,14 @@
 *    TABS: Object.freeze({
 *      ID_ALLOCATIONS: 'IdAllocations',
 *      AUDIT_LOG: 'AuditLog',
 *      EXCEPTION_REGISTER: 'ExceptionRegister',
 *      SYSTEM_CONFIG: 'SystemConfig',
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
 *   - `Object.isFrozen(KS_CONFIG)`, `Object.isFrozen(KS_CONFIG.TABS)`,
 *     `Object.isFrozen(KS_CONFIG.ID_PREFIXES)`, and `Object.isFrozen(KS_CONFIG.REQUIRED_HEADERS)`
 *     all remain `true` after applying this diff.
 *   - Produces canonical `AuthUsers` IDs via `IdAllocator.js:65` (`AUTH-YYYYMMDD-00001`), which
 *     matches FastAPI `backend/app/schema_registry.py:357`.
 *   - `BootstrapOwnerHandler.js` asserts `KS_CONFIG.ID_PREFIXES.AuthUsers === 'AUTH'` upfront
 *     before any ID allocation or sheet write.
 */
