# Kawad Swad ERP: Final Usability Upgrade Architecture & Master Plan

---

## 1. Final Implementation Architecture

The architecture maintains a strict separation between the **Display & Interaction Layer** and the **Underlying Business & Data Integrity Layer**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   KAWAD SWAD ERP FRONTEND SHELL                        │
├────────────────────────────────────────────────────────────────────────┤
│  Top Bar & Workspace Switcher (Owner Preview / Exit Preview Banner)    │
├───────────────────┬────────────────────────────────────────────────────┤
│  Navigation Menu  │  Active Workspace Viewport                          │
│  (Category-Aware, │  • Category-Specific Dashboards                    │
│   Plain Language, │  • Simple Forms (Auto-Totals, Human IDs)           │
│   Zero-Clutter)   │  • Unified Status Badges & Quick Action Hubs       │
├───────────────────┴────────────────────────────────────────────────────┤
│                 PRESENTATION TRANSLATION SERVICES                      │
│  • Terminology Dictionary (`src/utils/terminology.ts`)                 │
│  • Status Mapping Engine (`src/utils/statusLabels.ts`)                 │
│  • Category & Role Resolver (`src/utils/workspaces.ts`)                │
├────────────────────────────────────────────────────────────────────────┤
│                 BUSINESS LOGIC & SECURITY GUARDS                       │
│  • Client-Side Permission Matrix (`src/utils/permissions.ts`)          │
│  • Double-Entry Bridge (Simplified Cash vs. Journal Ledgers)           │
│  • Navigation Guards (Redirects unpermitted views to default view)     │
├────────────────────────────────────────────────────────────────────────┤
│                 AUTHENTICATION & BACKEND API LAYER                     │
│  • Session Persistence (Bearer JWT / SessionStorage)                  │
│  • Authoritative Backend Authorization Boundary (`/api/*`)             │
│  • Google Sheets 49-Tab Persistence & MongoDB Engine                   │
└────────────────────────────────────────────────────────────────────────┘
```

### Architectural Tenets:
1. **Zero Wire Contamination**: Wire payloads (`/api/sales`, `/api/purchasing`, `/api/workforce/*`) retain 100% of their schema, enums, and calculation keys.
2. **Display-Time Translation**: Technical terms are translated exclusively at the UI boundary.
3. **Double-Entry Preservation**: Simple monetary inputs from staff are transformed into valid accounting vouchers before posting to the backend ledger.

---

## 2. Complete Employee Category & Designation Mapping

Every employee is classified into one of **Three Operational Categories**, with the **OWNER** serving as the administrative authority.

| Category | Designation | Department | Primary System Role (`UserRole`) | Assigned Workspace | Default Landing View |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FACTORY WORKERS** | **Production Worker** | Factory / Processing | `FACTORY_WORKER` | `factory` | `dashboard` (Today's Batches) |
| | **Packaging Worker** | Packaging | `FACTORY_WORKER` | `factory` | `dashboard` (Packing Targets) |
| | **Machine Operator** | Milling / Roasting | `OPERATOR` | `factory` | `dashboard` (Machine Jobs) |
| | **Helper / General Labour** | Factory Floor | `WORKER` | `factory` | `dashboard` (Daily Attendance) |
| | **Factory Supervisor** | Production Operations | `LABOUR_SUPERVISOR` | `labour_supervisor` | `dashboard` (Floor Muster & Output) |
| **OFFICE STAFF** | **Office Assistant** | Administration | `EMPLOYEE` | `employee` | `dashboard` (Daily Tasks) |
| | **Billing Operator** | Sales & Billing | `PA` | `pa` | `sales` (Orders & Bills) |
| | **Purchase Assistant** | Raw Material Supply | `PA` | `pa` | `purchasing` (Buy Materials) |
| | **Stock Manager** | Warehouse & Inventory | `MANAGER` | `manager` | `stock` (Stock Register) |
| | **Production Manager** | Plant Operations | `MANAGER` | `manager` | `production` (Production Plan) |
| | **Accountant** | Accounts & Finance | `ACCOUNTANT` | `accountant` | `accounting` (Money Records) |
| | **Personal Assistant (PA)**| Executive Operations | `PA` | `pa` | `dashboard` (Daily Priorities) |
| | **E-Commerce Manager** | Online Fulfillment | `ECOMMERCE_MANAGER`| `ecommerce` | `sales` (Online Orders) |
| **FIELD STAFF** | **Field Salesman** | Field Sales | `SALESMAN` | `salesman` | `dashboard` (Today's Route & Orders) |
| | **Delivery Staff** | Distribution | `SALESMAN` | `salesman` | `dashboard` (Delivery Queue) |
| | **Payment Collector** | Field Collections | `SALESMAN` | `salesman` | `closing` (Money Received) |
| | **Marketing Representative**| Promotions & Retail | `SOCIAL_MEDIA_MANAGER`| `marketing` | `visits` (Store Visits) |
| | **Freelance Specialist** | Media / Packaging Design | `FREELANCER` | `freelancer` | `workforce` (My Projects) |
| **ADMINISTRATIVE** | **Business Owner / MD** | Executive Management | `OWNER` / `OWNER_ADMIN` | `owner` | `dashboard` (Business Overview) |

---

## 3. Navigation Menus for Each Category

### 3.1 Factory Workers Navigation
Designed for quick, error-free shop-floor interaction:
- **Home** (`dashboard`): Today's shift status, daily production target, and quick check-in.
- **My Attendance** (`attendance`): Punch in/out, view month's days worked, and overtime hours.
- **My Work / Production** (`production` - *if authorized*): View active recipes, log raw materials consumed, record finished goods output.
- **Packaging** (`packaging` - *if authorized*): Bulk-to-retail conversion counter, pouch sealing tally, batch sticker printing.
- **Stock** (`stock` - *read-only*): Check available spices, packaging pouches, and bulk flour.
- **My Salary** (`workforce`): Clean salary slip view showing basic rate, days present, and earned wages.
- **My Profile** (`profile`): Personal information, emergency phone, and bank account on file.

### 3.2 Office Staff Navigation
Optimized for high-volume data entry, records tracking, and approvals:
- **Home** (`dashboard`): Daily priorities, pending approvals, and operational metrics.
- **Orders & Bills** (`sales`): Customer order entry, wholesale invoice generation, and tax-inclusive billing.
- **Customers** (`customers`): Retailer & distributor directory, balances due, and contact info.
- **Production** (`production`): Milling yields, roasting batches, and finished goods transfers.
- **Stock** (`stock`): Warehouse stock levels, batch tracking, and adjustment logs.
- **Buy Materials** (`purchasing`): Material purchase orders, delivery receipts, and quality inspection.
- **Daily Expenses** (`expenses`): Operational expense entry, petrol/transport vouchers, and tea/office claims.
- **Our Team** (`workforce`): Staff directory, attendance muster, and task assignments.
- **Salary & Wages** (`salary` / `workforce`): Monthly attendance calculation, wage registers, and payment slips.
- **Reports** (`reports`): Daily sales summaries, production output, and stock valuation reports.

### 3.3 Field Staff Navigation
Optimized for mobile viewports (390px–430px) with large touch targets:
- **Home** (`dashboard`): Daily shop targets, active orders count, and 100kg incentive meter.
- **My Customers** (`customers`): Route shops, store addresses, and payment status.
- **New Order** (`sales`): 3-step rapid order taker (Pick Customer → Add Packets → Save & Print).
- **My Stock** (`stock`): Vehicle/van stock register and sample packets available.
- **Shop Visits** (`visits`): Check-in at store, purpose of visit, note, and next visit date.
- **Payments Received** (`closing`): Cash or UPI collected from retail stores.
- **My Expenses** (`expenses`): Fuel, parking, and daily travel allowance claims with receipt photo.
- **Daily Cash Handover** (`closing`): End-of-day cash handover to office with manager sign-off.
- **My Performance** (`workforce`): 100kg slab tracker, month-to-date sales, and commission earned.

---

## 4. Permissions Matrix by Designation

| View / Function | Factory Worker | Machine Operator | Factory Supervisor | Billing Operator | Stock Manager | Accountant | PA | Field Salesman | Owner |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Home Dashboard** | View (Floor) | View (Floor) | View (Floor) | View (Ops) | View (Ops) | View (Finance)| View (Ops) | View (Field) | Full (Exec) |
| **Attendance (Self)** | Clock In/Out | Clock In/Out | Clock In/Out | Clock In/Out | Clock In/Out | Clock In/Out | Clock In/Out| Clock In/Out | View All |
| **Attendance (Team)** | None | None | Record/Verify | View | View | View | Record/Verify| None | Full Control |
| **Production Batches** | Log Output | Full Entry | Supervise | View | View | View | View/Edit | None | Full Control |
| **Packaging Work** | Log Output | Log Output | Supervise | None | View | None | View | None | Full Control |
| **Stock Levels** | View Floor | View Floor | View Floor | View All | Manage/Adjust | View All | View All | View Van | Full Control |
| **Order Entry** | None | None | None | Create/Edit | View | View | Create/Edit | Create (Assigned)| Full Control |
| **Customer Balances**| None | None | None | View/Edit | None | Full Access | View/Edit | View (Assigned)| Full Control |
| **Buy Materials (PO)**| None | None | Request | Create | Create | View/Verify | Create/Edit | None | Full Control |
| **Material Received** | None | Unload/Check | Inspect | Record | Record | Verify | Record | None | Full Control |
| **Expense Filing** | None | None | Floor Expenses| Office Claims | None | Manage All | Review/File | Field Claims | Full Control |
| **Daily Cash Handover**| None | None | None | Receive | None | Reconcile | Receive | Submit Handover| Full Control |
| **Money Records (GL)** | None | None | None | None | None | Full Access | None | None | Full Control |
| **Salary Calculation** | View Own | View Own | View Own | None | None | Prepare | Prepare | View Own | Full Control |
| **Reports** | None | None | Floor Report | Sales Report | Stock Report | Financials | Operations | My Report | All Reports |
| **Team Management** | None | None | View Team | None | None | None | Request Add | None | Full Admin |

---

## 5. Complete Existing-versus-New Vocabulary Dictionary

| Category | Internal / Legacy ERP Term | Plain Everyday Business Term | Hindi / Hinglish Assistance | Context in UI |
| :--- | :--- | :--- | :--- | :--- |
| **Supply Chain** | Procurement | **Buy Materials** | Saaman Khareed | Navigation, Main Actions |
| | Goods Receipt Note (GRN) | **Material Received** | Maal Aaya / Aamad Slip | Inward Records, Delivery Slips |
| | Purchase Order (PO) | **Material Order** | Khareed Order | Order Entry, Status Badges |
| | Supplier / Vendor | **Material Supplier** | Maal Dene Wala Vyapari | Dropdowns, Supplier Tables |
| | Minimum Order Qty (MOQ) | **Minimum Order Limit** | Kam Se Kam Order | Purchasing Guidelines |
| **Accounting** | General Ledger (GL) | **Money Records** | Khata Vahi / Hisab Kitab | Staff Views (GL for Accountant) |
| | Accounts Receivable (AR) | **Money to Receive** | Aane Wala Paisa / Bakaya | Dashboard Summary Cards |
| | Accounts Payable (AP) | **Money to Pay** | Dena Hai / Udhaar | Dashboard Summary Cards |
| | Sundry Debtors | **Customer Balances** | Grahak Ka Dena | Customer Ledger, Balance Lists |
| | Sundry Creditors | **Supplier Dues** | Vyapari Ka Dena | Supplier Outstanding Tables |
| | Contra Voucher | **Bank & Cash Transfer** | Bank Aur Cash Ka Len-Den | Transaction Modals |
| | Journal Voucher (JV) | **Adjustment Entry** | Hisab Sudhar Entry | Accounting Voucher Forms |
| | Trial Balance | **Accounts Balance Check** | Khata Santulan Jaanch | Financial Reporting Hub |
| | Reconciliation | **Match & Check** | Milana Aur Jaanch | Cash and Bank Verification |
| **Inventory** | Inventory | **Stock** | Maal Ka Stock | Navigation, Cards, Tables |
| | Variance | **Difference** | Farak / Anthar | Stock Audits, Production Yields |
| | Batch Formulation / Recipe | **Mixture Recipe** | Banane Ka Formula | Production Batch Form |
| | Stock Ledger | **Stock History** | Maal Aane Jane Ka Record | Item History Drawer |
| **Workforce** | Workforce | **Our Team** | Hamari Team / Staff | Navigation, Section Headers |
| | Muster Roll | **Daily Attendance** | Rozana Haaziri | Attendance Tables & Registers |
| | Payroll Disbursal Engine | **Salary & Wages** | Tankhwah / Mazdoori | Salary Tab, Payment Vouchers |
| | Pro-rata Calculation | **Per-Day Calculation** | Dino Ke Hisab Se | Salary Review Modal |
| | Designation | **Job Role / Post** | Kaam Ka Pad | Staff Onboarding, Profiles |
| **Sales & Cash** | Cash Reconciliation / Closing | **Daily Cash Handover** | Din Ka Cash Jama | Salesman & Counter Handover |
| | Tax Invoice | **Bill / Invoice** | Pukka Bill | Order Billing, Customer Modal |
| | Delivery Challan | **Delivery Slip** | Maal Bhejne Ki Parchi | Dispatch Modals |

---

## 6. Connecting Simple Interfaces to Backend Accounting & Operations

The upgrade introduces an **intelligent client-side adapter layer** so simplified inputs map cleanly to backend contracts:

1. **Daily Cash Handover to Accounting Voucher**:
   - Field salesman enters simple inputs: `Cash Handed Over: ₹4,500`, `Received By: Office Cashier`.
   - The frontend automatically transforms this into the exact `/api/accounting/vouchers` schema:
     ```json
     {
       "voucher_type": "RECEIPT",
       "debit_account": "CASH_IN_HAND",
       "credit_account": "SALESMAN_CLEARING_ACCOUNT",
       "amount": 4500,
       "narration": "Daily counter cash handover by user_id",
       "reference_id": "HANDOVER-2026-03-29"
     }
     ```
2. **Simplified Order Entry to Multi-Tier Invoice**:
   - Staff selects a customer and item quantities.
   - The frontend computes wholesale rate, applies product tax rate (GST 5% or 12%), and submits the standard `/api/sales` payload with lines, discounts, and round-off intact.
3. **Raw Material Intake (GRN) to Inventory & Creditor Ledger**:
   - Staff clicks "Material Received", selects Supplier, enters Bags/Kg received.
   - The backend creates the PO fulfillment record, triggers the stock increment transaction, and generates the Accounts Payable voucher simultaneously.

---

## 7. Component Reuse & Modification Plan

### Reusable Components (Zero Re-architecting):
- `src/components/common/FormComponents.tsx`: `FormLayout`, `FormSection`, `FormField`, `MoneyInput`, `QuantityInput`, `DateInput`, `CalculationPreview`, `SaveButton`, `CancelButton`.
- `src/components/common/StatusBadge.tsx`: Enhanced to consume the new `statusLabels.ts` dictionary.
- `src/components/common/PageHeader.tsx`: Preserved for standard titles and breadcrumbs.
- `src/components/common/StatCard.tsx`: Reused across all category dashboards.
- `src/components/common/ConfirmDialog.tsx`: Used for approvals and cancellations.
- `src/components/LoginModal.tsx`: Recently verified modern login experience.

### Files Requiring Targeted Modification:
1. **New Modules to Create**:
   - `src/utils/terminology.ts`: Central vocabulary dictionary and text helper functions.
   - `src/utils/statusLabels.ts`: Central status mapping (English + Hindi tags + Lucide icons).
   - `src/utils/permissions.ts`: Role and designation view-level guards.
   - `src/components/workforce/EmployeeRegistrationWizard.tsx`: Guided 7-step staff onboarding wizard.
2. **Existing Files to Update (Surgically)**:
   - `src/utils/workspaces.ts`: Map the 3 categories (Factory, Office, Field) + Owner; define category-specific navigation arrays.
   - `src/components/Navigation.tsx`: Render plain-language menu items based on active category workspace.
   - `src/components/Header.tsx`: Display active category badge and clean Owner preview banner.
   - `src/views/WorkforceView.tsx`: Integrate the 7-step onboarding wizard and apply plain language to registers.
   - `src/views/UsersView.tsx`: Streamline user creation and permission profiles.
   - `src/views/SalesView.tsx`, `PurchasingView.tsx`, `AccountingView.tsx`, `StockView.tsx`: Update headings, action labels, and table headers using `terminology.ts`.

---

## 8. Potential Compatibility Risks with Existing Employee Records

| Risk Area | Potential Failure Mode | Prevention Strategy |
| :--- | :--- | :--- |
| **Existing `User.role` Values** | Breaking authentication or permissions if backend enums are renamed. | **Never change enum strings** on the wire (`SALESMAN`, `PA`, `OWNER`, `FACTORY_WORKER`). Map them dynamically in `workspaces.ts`. |
| **Legacy Users Missing Category** | Existing records in database without `employee_category` field. | Provide automatic fallback: if `employee_category` is undefined, infer category from `role` (e.g. `SALESMAN` &rarr; `FIELD_STAFF`, `FACTORY_WORKER` &rarr; `FACTORY_WORKER`, others &rarr; `OFFICE_STAFF`). |
| **Unset Designations** | Older accounts with blank `designation`. | Fallback gracefully to displaying humanized role name (e.g. `SALESMAN` &rarr; `Field Salesman`) instead of empty string. |
| **Salary Structure Variation** | Some workers on daily wage, others on monthly salary or piecework. | Ensure the 7-step wizard supports `MONTHLY_SALARY`, `DAILY_WAGE`, and `PIECE_RATE` without requiring all fields for every type. |
| **Direct URL Bookmarking** | User navigating directly to an unpermitted view. | Implement automatic client-side redirection to `defaultView` with an informative toast rather than a broken page. |

---

## 9. Phased Implementation & Testing Sequence

```
Phase A: Foundations (Zero UI Impact)
  ├── 1. Create `src/utils/terminology.ts` (Vocabulary dictionary)
  ├── 2. Create `src/utils/statusLabels.ts` (Status mappings & icons)
  └── 3. Create `src/utils/permissions.ts` (Designation & category guards)

Phase B: Workspace & Navigation Reorganization
  ├── 1. Refactor `src/utils/workspaces.ts` with 3 Categories + Owner
  ├── 2. Update `src/components/Navigation.tsx` (Plain labels & category navs)
  └── 3. Update `src/components/Header.tsx` (Owner preview switcher & banner)

Phase C: Guided 7-Step Employee Registration Wizard
  ├── 1. Build `EmployeeRegistrationWizard.tsx` using `FormComponents.tsx`
  ├── 2. Wire into `src/views/WorkforceView.tsx` & `src/views/UsersView.tsx`
  └── 3. Verify step validation, back/next navigation, and payload generation

Phase D: View Terminology & Form Modernization
  ├── 1. Sales & Purchasing views (Orders & Bills, Buy Materials, GRN)
  ├── 2. Stock & Production views (Stock Register, Difference, Mixture Recipe)
  └── 3. Accounting & Expenses views (Money Records, Daily Cash Handover)

Phase E: Comprehensive Verification & Acceptance
  ├── 1. Role-based navigation audit (Factory, Office, Field, Owner)
  ├── 2. Form submission and calculation verification
  ├── 3. Mobile responsiveness check (390px, 768px, 1440px)
  └── 4. Build & Lint validation (`compile_applet` + `lint_applet`)
```
