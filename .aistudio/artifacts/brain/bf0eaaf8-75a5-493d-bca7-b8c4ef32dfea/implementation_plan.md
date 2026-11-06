# Kawad Swad ERP: Simple Language, User Experience & Workforce Reorganization
## Audit Report & Master Implementation Plan

---

### Executive Summary

Kawad Swad ERP is a manufacturing, inventory, and sales system designed to serve both factory-floor operators and executive decision-makers. The objective of this upgrade is to eliminate operational barriers for employees with limited formal education and no accounting background, while preserving 100% of the underlying backend business logic, double-entry accounting integrity, Google Sheets/MongoDB synchronisation, and API contracts.

This plan details the findings of our comprehensive frontend audit and establishes the concrete, phased implementation architecture.

---

### Phase 1: Comprehensive Language Audit & Centralized Vocabulary Dictionary

#### 1. Audit Findings Across Current Frontend Views
An audit across `/src/views/` (`AccountingView`, `AttendanceView`, `ClosingView`, `CustomersView`, `ExpensesView`, `ProductionView`, `ProductsView`, `PurchasingView`, `QualityView`, `StockView`, `UsersView`, `WorkforceView`, `ReportsView`, `AuditLogView`) revealed technical jargon and inconsistent labeling:
- **Financial & Accounting Jargon**: Terms like *General Ledger*, *Trial Balance*, *Accounts Receivable*, *Accounts Payable*, *Reconciliation*, *Sundry Debtors*, *Contra Voucher*, and *Journal Voucher* are displayed uniformly across all user profiles, confusing shop-floor and field staff.
- **Supply Chain & Manufacturing Terms**: Raw terms like *Procurement*, *Goods Receipt Note (GRN)*, *Variance*, *Milling Input-Output Ratio*, and *Batch Formulation* appear without contextual plain-language descriptions.
- **HR & Workforce Jargon**: Terms like *Muster Roll*, *Workforce*, *Payroll Disbursal Engine*, *Milestone Sign-off*, and *Pro-rata Calculation* increase cognitive load.

#### 2. Centralized Vocabulary Dictionary (`src/utils/terminology.ts`)
A centralized terminology dictionary will translate technical concepts into simple, everyday operational language across the user interface, while retaining technical terms exclusively for authorized Owner and Accountant roles.

| Technical / Internal Term | Plain Business Term (Everyday English) | Hindi / Hinglish Context | Scope of Change |
| :--- | :--- | :--- | :--- |
| **Procurement** | **Buy Materials** | Saaman Khareed | Navigation, Headers, Action Buttons |
| **Goods Receipt Note (GRN)** | **Material Received** | Maal Aaya / Aamad | Slips, Tables, Form Modals |
| **Purchase Order (PO)** | **Material Order** | Khareed Order | Forms, Registers, Status Badges |
| **General Ledger** | **Money Records** | Khata Vahi / Hisab Kitab | Staff Views (Retain GL for Owner/Accountant) |
| **Accounts Receivable (AR)** | **Money to Receive** | Aane Wala Paisa / Bakaya | Dashboard Cards, Summary Metrics |
| **Accounts Payable (AP)** | **Money to Pay** | Dena Hai / Udhaar | Dashboard Cards, Summary Metrics |
| **Payroll / Disbursal** | **Salary & Wages** | Tankhwah / Mazdoori | Navigation, Cards, Actions |
| **Workforce** | **Our Team** | Hamari Team / Staff | Navigation, Section Headers |
| **Reconciliation** | **Match & Check** | Milana Aur Jaanch | Actions, Logs, Audit Modals |
| **Variance** | **Difference** | Farak / Anthar | Stock Audits, Production Yields |
| **Inventory** | **Stock** | Maal Ka Stock | Navigation, Metrics, Tables |
| **Sundry Debtors** | **Customer Balances (Due)** | Grahak Ka Dena | Customer Tables, Statements |
| **Sundry Creditors** | **Supplier Dues** | Vyapari Ka Dena | Supplier Tables, Balances |
| **Cash Handover / Closing** | **Daily Cash Handover** | Din Ka Cash Jama | Salesman & Shop Visit Views |
| **Muster Roll** | **Daily Attendance** | Rozana Haaziri | Labour & Staff Registers |

*Rule*: All internal backend enums (`SALE_TYPES`, `StockTxnType`, `UserRole`, `ApprovalStatus`, `PAYMENT_MODES`) will remain untouched on the wire. Only display labels, placeholders, card titles, and tooltips are transformed through formatting helpers.

---

### Phase 2: Three Primary Employee Categories & Mapping Matrix

Every staff member is classified into one of three operational categories, with the **OWNER** remaining an administrative tier.

#### 1. Category Definitions
1. **FACTORY WORKERS**:
   - Focus: Physical manufacturing, raw material intake, milling, roasting, manual packaging, machine operation, and daily attendance.
   - User Experience: Large touch targets, immediate visual cues, numeric steppers, and zero financial clutter.
2. **OFFICE STAFF**:
   - Focus: Order billing, customer account upkeep, material purchasing, stock auditing, expense voucher entry, team attendance monitoring, and reporting.
   - User Experience: Streamlined data entry tables, auto-complete dropdowns, live totals, and approval routing.
3. **FIELD STAFF**:
   - Focus: Route planning, retailer shop visits, on-spot order taking, retail stock checking, on-spot payment collection, and end-of-day cash handover.
   - User Experience: Mobile-first viewport (390px–430px), single-column tap-friendly forms, one-tap payment recording, and clear daily commission/slab indicators.

#### 2. Designation & Role Mapping Architecture

| Employee Category | Common Designations | Department | Standard System Role (`UserRole`) | Assigned Workspace | Default Landing Page |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FACTORY WORKERS** | Production Worker<br>Packaging Worker<br>Machine Operator<br>Helper<br>Factory Supervisor | Factory Floor / Packaging / Quality | `FACTORY_WORKER`<br>`OPERATOR`<br>`LABOUR_SUPERVISOR` | `factory` or `labour_supervisor` | `dashboard` (Factory Work Priority) |
| **OFFICE STAFF** | Office Assistant<br>Billing Operator<br>Purchase Assistant<br>Stock Manager<br>Production Manager<br>Accountant<br>Personal Assistant (PA) | Admin / Accounts / Operations / Billing | `PA`<br>`ACCOUNTANT`<br>`MANAGER`<br>`ECOMMERCE_MANAGER`<br>`EMPLOYEE` | `pa`<br>`accountant`<br>`manager`<br>`ecommerce` | `dashboard` (Operational Checklist) |
| **FIELD STAFF** | Salesman<br>Delivery Staff<br>Payment Collection Staff<br>Marketing Representative | Field Sales / Logistics / Marketing | `SALESMAN`<br>`SOCIAL_MEDIA_MANAGER`<br>`FREELANCER` | `salesman`<br>`marketing`<br>`freelancer` | `dashboard` (Today's Route & Orders) |
| **OWNER / ADMIN** | Business Owner<br>Managing Director | Executive Management | `OWNER`<br>`OWNER_ADMIN` | `owner` | `dashboard` (Executive Overview) |

---

### Phase 3: Category-Specific Workspaces & Simplified Navigation

Navigation is streamlined so users never see unnecessary or restricted modules.

#### 1. Factory Worker Workspace (`factory`)
- **Home** (`dashboard`): Today's assigned shift, attendance status, and production target.
- **My Attendance** (`attendance`): One-tap check-in/out, hours logged, and month-to-date days worked.
- **My Work / Production** (`production` - *when authorized*): Active batch recipes, input raw materials, and completed output entry.
- **Packaging** (`packaging` - *when authorized*): Packet sealing counter, bulk-to-retail conversion, and batch stickers.
- **Stock** (`stock` - *read-only*): Floor raw material and packing material levels.
- **My Salary** (`workforce`): Clean salary slip view with days worked and earnings summary.
- **My Profile** (`profile`): Emergency contact and worker details.

#### 2. Office Staff Workspace (`office`)
- **Home** (`dashboard`): Daily priorities, pending tasks, and urgent notifications.
- **Orders & Bills** (`sales`): Customer order entry, wholesale invoice generation, and tax-inclusive billing.
- **Customers** (`customers`): Retailer/wholesaler phone directory, shop addresses, and outstanding balances.
- **Production** (`production`): Milling yields, roasting batches, and finished goods transfers.
- **Stock** (`stock`): Warehouse stock levels, batch tracking, and adjustment logs.
- **Buy Materials** (`purchasing`): Material purchase orders, supplier delivery receipts, and quality approval.
- **Daily Expenses** (`expenses`): Operational expense entry, petrol/transport vouchers, and tea/office claims.
- **Our Team** (`workforce` / `users`): Staff directory, attendance muster, and task assignments.
- **Salary & Wages** (`salary` / `workforce`): Monthly attendance calculation, wage registers, and payment slips.
- **Reports** (`reports`): Daily sales summaries, production output, and stock valuation reports.

#### 3. Field Staff Workspace (`salesman`)
- **Home** (`dashboard`): Daily shop targets, active orders count, and incentive meter.
- **My Customers** (`customers`): Route shops, contact numbers, and payment status.
- **New Order** (`sales`): 3-step rapid order taker (Pick Customer → Add Packets → Save & Print).
- **My Stock** (`stock`): Vehicle/van stock register and sample packets available.
- **Shop Visits** (`visits`): Check-in at store, purpose of visit, note, and next visit date.
- **Payments Received** (`accounting` / `closing`): Cash or UPI collected from retail stores.
- **My Expenses** (`expenses`): Fuel, parking, and daily travel allowance claims with receipt photo.
- **Cash Handover** (`closing`): End-of-day cash handover to office with manager sign-off.
- **My Performance** (`workforce`): 100kg slab tracker, month-to-date sales, and commission earned.

#### 4. Owner Workspace (`owner`)
- Unrestricted access to all modules, including advanced double-entry accounting (General Ledger, Trial Balance, Journal Vouchers, Sundry Debtors/Creditors), system settings, audit registers, and workspace preview mode.

---

### Phase 4: Simple Form Design System

Building on the existing `FormComponents.tsx` architecture, forms will adhere to the following principles:

1. **Progressive Disclosure**:
   - Primary required fields visible by default (3–5 fields maximum).
   - Advanced options (GSTIN, tax splits, notes, vehicle numbers) tucked into an optional "Additional Details" collapsible section.
2. **Clear Dropdowns & Autocomplete**:
   - Replace manual text inputs with searchable dropdowns for Customers, Products, Suppliers, and Categories.
3. **Automated Calculations**:
   - Subtotal, GST, discounts, and net payable compute live on input without requiring manual calculation.
   - Visual calculation preview card displays: `Items Total + GST (if any) - Discount = Net Total`.
4. **Pre-filled Defaults**:
   - Transaction dates default to today (`YYYY-MM-DD`).
   - Logged-in user automatically set as creator/salesman.
   - Payment mode defaults to `Cash` for retail and `Bank Transfer (NEFT/UPI)` for wholesale.
5. **Human-Friendly Identification**:
   - Never display raw database UUIDs or internal IDs (e.g. `672...`) to regular users.
   - Show human labels: "Sharma Kirana Store (ORD-2026-0042)" instead of raw IDs.

---

### Phase 5: Centralized Status System

Create `src/utils/statusLabels.ts` with plain-language mappings and distinct visual badges:

```typescript
export interface StatusDisplay {
  label: string;
  hindiLabel?: string;
  badgeClass: string;
  iconName: string;
}

export const STATUS_MAP: Record<string, StatusDisplay> = {
  PENDING: { label: 'Waiting', hindiLabel: 'Ruka Hua', badgeClass: 'bg-amber-50 text-amber-800 border-amber-200', iconName: 'Clock' },
  APPROVED: { label: 'Approved', hindiLabel: 'Manzoor', badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200', iconName: 'CheckCircle2' },
  REJECTED: { label: 'Not Approved', hindiLabel: 'Nakaara', badgeClass: 'bg-red-50 text-red-800 border-red-200', iconName: 'XCircle' },
  PARTIAL: { label: 'Partial', hindiLabel: 'Aadha Hua', badgeClass: 'bg-sky-50 text-sky-800 border-sky-200', iconName: 'PieChart' },
  COMPLETED: { label: 'Done', hindiLabel: 'Poora Hua', badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200', iconName: 'CheckCheck' },
  IN_PROGRESS: { label: 'In Progress', hindiLabel: 'Kaam Chal Raha Hai', badgeClass: 'bg-blue-50 text-blue-800 border-blue-200', iconName: 'Play' },
  CANCELLED: { label: 'Cancelled', hindiLabel: 'Radd Hua', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300', iconName: 'Ban' },
  DRAFT: { label: 'Draft', hindiLabel: 'Kaccha', badgeClass: 'bg-slate-50 text-slate-600 border-slate-200', iconName: 'FileText' },
  OVERDUE: { label: 'Overdue', hindiLabel: 'Samay Beeta', badgeClass: 'bg-rose-50 text-rose-800 border-rose-200', iconName: 'AlertTriangle' },
  PAID: { label: 'Paid', hindiLabel: 'Chukaya', badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-200', iconName: 'Coins' },
  UNPAID: { label: 'Unpaid', hindiLabel: 'Baaqi', badgeClass: 'bg-amber-50 text-amber-800 border-amber-200', iconName: 'AlertCircle' },
};
```

---

### Phase 6: Simple Money Experience for Staff vs. Double-Entry for Owner

#### 1. Everyday Staff Interface
Field staff and office operators interact with simple monetary cards:
- **Money Received**: Total cash and UPI collected today.
- **Money Paid**: Cash disbursed for raw materials, cartage, and daily expenses.
- **Expenses**: Vouchers filed and approved.
- **Money Remaining**: Cash in register / cash in hand awaiting handover.

#### 2. Advanced Owner & Accountant Workspace
The underlying double-entry ledger remains untouched:
- Real-time Journal Vouchers with Debit (`Dr`) and Credit (`Cr`) balancing.
- Trial Balance with Assets, Liabilities, Equity, Revenues, and Expenses.
- Detailed Sundry Debtors and Creditors aging schedules.
- Bank reconciliation and cash-flow statements.

---

### Phase 7: Guided 7-Step Employee Registration Process

To ensure error-free staff onboarding, the registration modal in `WorkforceView` and `UsersView` will be upgraded into a sequential 7-step wizard:

```
[ Step 1: Category & Designation ] ──▶ [ Step 2: Basic Information ] ──▶ [ Step 3: Department & Reporting ]
                                                                                           │
[ Step 6: Review & Confirm ] ◀── [ Step 5: System Access & Login ] ◀── [ Step 4: Salary & Wages ]
            │
            ▼
[ Step 7: Success & Summary ]
```

- **Step 1: Category & Designation**: Select category (Factory Worker, Office Staff, Field Staff) and choose/enter designation.
- **Step 2: Basic Information**: Full Name, Mobile Number, Emergency Contact, and Residential Address.
- **Step 3: Department & Reporting**: Department assignment, Joining Date, and Reporting Manager selection.
- **Step 4: Salary & Wages**: Pay structure (Monthly Fixed Salary, Daily Wage, or Piece-Rate per kg/packet), Base Rate, and Bank Details.
- **Step 5: System Access & Login**: Username, initial secure password, system role mapping, and active status toggle.
- **Step 6: Review & Confirm**: One-page clean summary card verifying all details before submission.
- **Step 7: Success & Summary**: Account created successfully; offers one-click action to print/download welcome slip or view profile.

---

### Phase 8: Centralized Permissions & Security Enforcement

1. **Client-Side View & Action Guards**:
   - Navigation links for unpermitted views are not rendered.
   - If an unauthorized view is entered via URL or `sessionStorage`, the workspace redirects to `defaultView` with a warning message.
   - Action buttons (e.g., Approve Batch, Calculate Payroll, Delete Item) are disabled and hidden for non-permitted roles.
2. **Owner Preview Mode**:
   - Owner can inspect any of the category workspaces (`factory`, `salesman`, `office`, `accountant`) using the Workspace Switcher in the top bar.
   - A distinct amber banner displays: *"Viewing workspace as [Role]. No security permissions are altered."*
   - One-click "Exit Preview" button returns the Owner to the Executive Overview.
3. **Backend As Final Boundary**:
   - All backend endpoint authorization checks (`req.user.role`) remain intact.
   - No mock data fallbacks: all calls route to real API handlers.

---

### Phase 9: Execution Roadmap

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ MASTER IMPLEMENTATION PHASES                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ Phase A: Centralized Terminology & Status Mappings                          │
│          Create `src/utils/terminology.ts` & `src/utils/statusLabels.ts`    │
│                                                                             │
│ Phase B: Workspace & Role Reorganization                                    │
│          Update `src/utils/workspaces.ts` with the 3 categories & nav items │
│                                                                             │
│ Phase C: Navigation & Shell Updates                                         │
│          Apply plain language to `Navigation.tsx`, `App.tsx`, and headers   │
│                                                                             │
│ Phase D: Guided 7-Step Employee Registration Wizard                         │
│          Build `EmployeeRegistrationWizard.tsx` inside `WorkforceView.tsx`  │
│                                                                             │
│ Phase E: Views Modernization (Plain Language & Form Components)             │
│          Apply simplified labels across Orders, Stock, Production, Expenses │
│                                                                             │
│ Phase F: Build, Lint & Automated Verification                               │
│          Run `compile_applet`, `lint_applet`, and Playwright test suite     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Phase 10: Verification & Acceptance Test Matrix

| Verification Target | Test Method | Acceptance Criteria |
| :--- | :--- | :--- |
| **Language Simplicity** | Text scan across all views | Technical terms replaced by plain language for standard staff; double-entry retained for Owner/Accountant. |
| **Role Navigation Coverage** | Role-based login audit | Every role receives a populated navigation with zero empty states or broken views. |
| **7-Step Registration** | End-to-end form completion | Step-by-step validation, back/next navigation, calculation preview, and clean API payload dispatch. |
| **Status Consistency** | Inspection of all badges | Standardized status pill tags with uniform colors and icons across all tables. |
| **Mobile Responsiveness** | Viewport audit (390x844) | Field Staff workspace and mobile navigation render without horizontal scroll or truncated text. |
| **Security & Preview** | Direct view manipulation | Unauthorized views blocked; Owner preview mode works cleanly without privilege escalation. |
| **Compilation & Linting** | `compile_applet` & `lint_applet` | 0 TypeScript errors, 0 ESLint warnings, successful production build. |
