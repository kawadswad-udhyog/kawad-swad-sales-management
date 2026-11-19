# Kawad Swad ERP — Calculation Register (`REG-03`: `CALC-001` to `CALC-032`)

**Governing Policy:** `POL-017`, `POL-018`, `POL-019`, `POL-020`, `POL-026`  
**Authoritative Code Modules:** `backend/app/calculations/{units,recipes,recipe_mapping,production,packaging,costing,inventory}.py`  
**Verification Status:** `IMPLEMENTED — NOT TESTED` (Testing Moratorium Active — Section 25)

---

## 1. Universal Units, Precision & Rounding Standard

- **Mass Canonical Unit:** Kilograms (`kg`), exact identity `1 kg = 1000 g` (1000 grams per kilogram; retail packs strictly `{200, 500, 1000}` g = `0.200`, `0.500`, `1.000` kg).
- **Volume Canonical Unit:** Litres (`L`), exact identity `1 L = 1000 ml`.
- **Count Canonical Unit:** `packet` / `unit` (integer whole packets where applicable).
- **Precision & Rounding (`backend/app/calculations/units.py`):**
  - FastAPI computes intermediate math in `decimal.Decimal` with `ROUND_HALF_UP`:
    - Stock quantities: `3` decimal places (`0.001` kg = `1 g` precision) via `round_stock` (`CALC-003a`).
    - Monetary INR amounts: `2` decimal places (`0.01` INR = `1 paise` precision) via `round_money` (`CALC-003b`).
    - Formulation ratios & yields: `4` decimal places (`0.0001`) via `round_ratio` (`CALC-003c`).
  - Google Apps Script authoritative posting performs monetary arithmetic in **integer paise** (`Math.round(inr * 100)`) to avoid IEEE-754 float drift on journal postings.
- **CA / Owner Policy Gates (`PENDING_CA_APPROVAL`):**
  - No unapproved GST rate, inventory valuation method (`FIFO` vs `WEIGHTED_AVERAGE`), overhead/labour allocation basis, or depreciation rule is hardcoded as authoritative.
  - `CALC-019` (`calculate_batch_actual_cost`) explicitly attaches `overhead_allocation_policy_status`, `overhead_allocation_policy_value`, `inventory_valuation_policy_status`, and `inventory_valuation_policy_value` from `get_ca_policies()`.

---

## 2. Master Calculation Summary Table (`CALC-001` to `CALC-032`)

| Calc ID | Module | Function | Canonical Formula / Behavior | Rounding / Unit | CA Gate / Edge Rule | Status |
|---|---|---|---|---|---|---|
| `CALC-001` | `units.py` | `clean_currency_string` | Strips `₹`, `Rs`, commas, whitespace; normalizes numeric string | String | Returns `"0"` on empty/null | `IMPLEMENTED — NOT TESTED` |
| `CALC-002` | `units.py` | `to_decimal` | Exact `Decimal(clean_currency_string(val))` conversion | Exact `Decimal` | Eliminates binary float noise | `IMPLEMENTED — NOT TESTED` |
| `CALC-003a` | `units.py` | `round_stock` | `to_decimal(val).quantize(0.001, ROUND_HALF_UP)` | `kg` / `L` (3 dp) | 1 g / 1 ml resolution | `IMPLEMENTED — NOT TESTED` |
| `CALC-003b` | `units.py` | `round_money` | `to_decimal(val).quantize(0.01, ROUND_HALF_UP)` | INR (2 dp) | Paise resolution | `IMPLEMENTED — NOT TESTED` |
| `CALC-003c` | `units.py` | `round_ratio` | `to_decimal(val).quantize(0.0001, ROUND_HALF_UP)` | Ratio (4 dp) | Formulation/yield precision | `IMPLEMENTED — NOT TESTED` |
| `CALC-003d` | `units.py` | `parse_currency_amount` | Parses Sheet/API formatted INR into `round_money` float | INR (2 dp) | Handles `None`, `""`, `"₹1,250.50"` | `IMPLEMENTED — NOT TESTED` |
| `CALC-004` | `units.py` | `normalize_to_canonical_unit` | `g -> kg (/1000)`, `ml -> L (/1000)`, `quintal -> kg (*100)`, `ton -> kg (*1000)` | Canonical `kg`/`L`/`packet` | Rejects unknown/incompatible units | `IMPLEMENTED — NOT TESTED` |
| `CALC-005` | `units.py` | `convert_unit` | Converts between compatible units; requires explicit `density_kg_per_l` for mass <-> volume | Target unit (3 dp) | Raises `ValueError` if density omitted | `IMPLEMENTED — NOT TESTED` |
| `CALC-006` | `recipes.py` | `validate_recipe_formulation` | Validates positive base yield, non-empty ingredient rows, canonical units, positive quantities | Validation dict | Protects base formulation integrity | `IMPLEMENTED — NOT TESTED` |
| `CALC-007` | `recipes.py` | `scale_recipe` | `scaled_qty = ingredient_qty * (target_yield_kg / base_yield_kg)` | `kg` (3 dp) / ratio (4 dp) | Rejects `target_yield_kg <= 0` or `base_yield_kg <= 0` | `IMPLEMENTED — NOT TESTED` |
| `CALC-008` | `recipes.py` | `calculate_recipe_cost_estimate` | `sum(scaled_qty * latest_rate)` and `cost_per_kg = total_cost / target_yield_kg` | INR (2 dp) | Flags missing/pending RM rates | `IMPLEMENTED — NOT TESTED` |
| `CALC-009a` | `recipe_mapping.py` | `normalize_product_base_name` | Strips pack weights (`200g`, `500g`, `1000g`, `1kg`) & normalizes whitespace/punctuation | Normalized key | Preserves variant descriptors | `IMPLEMENTED — NOT TESTED` |
| `CALC-009b` | `recipe_mapping.py` | `strip_sku_pack_suffix` | Strips trailing pack suffix (`-200G`, `-500G`, `-1000G`) from SKU code | Normalized code | Used for deterministic base linkage | `IMPLEMENTED — NOT TESTED` |
| `CALC-010` | `recipe_mapping.py` | `resolve_product_recipe` | Deterministic precedence: explicit `recipe_id` -> exact SKU base -> exact normalized base name; picks highest approved version | Single recipe dict | Raises `AmbiguousRecipeMappingError` / `UnapprovedRecipeError` (fail-closed) | `IMPLEMENTED — NOT TESTED` |
| `CALC-011` | `recipe_mapping.py` | `audit_product_recipe_mappings` | Read-only diagnostic across all `Products` against `Recipes` + master recipes | Audit report dict | Identifies unmapped, unapproved, ambiguous SKUs | `IMPLEMENTED — NOT TESTED` |
| `CALC-012` | `production.py` | `calculate_production_requirements` | Scales approved recipe to planned batch kg & compares vs confirmed RM stock | `kg` (3 dp) | Blocks issue against `UNVERIFIED` opening stock (`POL-017`) | `IMPLEMENTED — NOT TESTED` |
| `CALC-013` | `production.py` | `reconcile_production_output` | `expected_net = gross_output_kg - process_loss_kg - wastage_kg`; `variance = actual_saleable_kg - expected_net` | `kg` (3 dp) | Preserves unexplained variance for Owner review | `IMPLEMENTED — NOT TESTED` |
| `CALC-014` | `packaging.py` | `calculate_packed_weight` | `(p200 * 200 + p500 * 500 + p1000 * 1000) / 1000` (exact `Decimal`) | `kg` (3 dp) | Retail packs strictly `{200, 500, 1000}` g (`POL-015`) | `IMPLEMENTED — NOT TESTED` |
| `CALC-015` | `packaging.py` | `calculate_packing_variance` | `variance_kg = bulk_kg_used - packed_weight_kg`; `variance_pct = (variance_kg / bulk_kg_used) * 100` | `kg` (3 dp), `%` (2 dp) | Zero-division safe when `bulk_kg_used == 0` | `IMPLEMENTED — NOT TESTED` |
| `CALC-016` | `packaging.py` | `validate_packing_discrepancy` | Blocks packaging completion when unexplained variance exceeds tolerance without Owner approval | Gate check | Fail-closed; never auto-writes loss | `IMPLEMENTED — NOT TESTED` |
| `CALC-017a` | `packaging.py` | `classify_packaging_discrepancy` | Classifies historical (`55 kg` unrecorded sales), pending review (`2.4 kg`), or approved rows without mutating history | Classification dict | Strictly read-only (`POL-018`) | `IMPLEMENTED — NOT TESTED` |
| `CALC-017b` | `packaging.py` | `summarize_packaging_discrepancies` | Aggregates counts & total kg by discrepancy classification across `PackagingBatches` | Summary dict (`kg`, 3 dp) | Preserves 55 kg historical + 2.4 kg pending separation | `IMPLEMENTED — NOT TESTED` |
| `CALC-018` | `costing.py` | `get_latest_purchase_rate` | Resolves latest valid landed RM rate from `RawMaterialLedger` / `GoodsReceipts` / `RawMaterials` | INR/kg (2 dp) | Flags `PENDING` / missing rate; never invents zero cost | `IMPLEMENTED — NOT TESTED` |
| `CALC-019` | `costing.py` | `calculate_batch_actual_cost` | `total_batch_cost = material_cost + labour_cost + overhead_cost`; `cost_per_kg = total_batch_cost / net_output_kg` | INR (2 dp) | Attaches `PENDING_CA_APPROVAL` status for `overhead_and_labour_allocation_basis` & `inventory_valuation_method` (`POL-020`) | `PENDING_CA_APPROVAL` |
| `CALC-020` | `costing.py` | `calculate_finished_sku_cost` | `sku_cost = (bulk_cost_per_kg * pack_weight_g / 1000) + packing_material_cost + packing_labour_cost` | INR/packet (2 dp) | Respects exact `pack_weight_g / 1000` | `IMPLEMENTED — NOT TESTED` |
| `CALC-021` | `costing.py` | `get_sku_packing_costs` | Sums pouch film, master carton & packing labour per SKU packet | INR/packet (2 dp) | Reads master rates; flags missing inputs | `IMPLEMENTED — NOT TESTED` |
| `CALC-022` | `costing.py` | `get_authoritative_bulk_cost_per_kg` | Resolves authoritative bulk cost/kg from actual batch cost -> resolved legacy cost -> estimated recipe cost | INR/kg (2 dp) | Returns explicit `cost_status` (`ACTUAL`/`ESTIMATED`/`UNRESOLVED`) | `IMPLEMENTED — NOT TESTED` |
| `CALC-023` | `costing.py` | `get_sku_finished_cost` | Combines `CALC-022` bulk cost + `CALC-021` packing cost into authoritative SKU packet cost | INR/packet (2 dp) | Preserves cost-source lineage | `IMPLEMENTED — NOT TESTED` |
| `CALC-024` | `inventory.py` | `calculate_bulk_stock_balance` | `bulk_balance_kg = sum(approved_production_kg) - sum(consumed_in_packaging_kg) + sum(bulk_adjustments_kg)` | `kg` (3 dp) | Approved batches only | `IMPLEMENTED — NOT TESTED` |
| `CALC-025` | `inventory.py` | `calculate_batch_bulk_balances` | Computes independent `produced_kg`, `consumed_kg`, `available_kg` for each approved production batch | `kg` (3 dp) | Ordered deterministically for FIFO allocation | `IMPLEMENTED — NOT TESTED` |
| `CALC-026` | `inventory.py` | `resolve_packaging_batch_allocations` | Allocates packaging `bulk_kg_used` across batches (FIFO or explicit manual map) without over-consuming any batch | Allocation list (`kg`, 3 dp) | Rejects allocation exceeding available batch bulk | `IMPLEMENTED — NOT TESTED` |
| `CALC-027` | `inventory.py` | `calculate_finished_stock_balance` | Factory finished packet balance from `ProductionStockLedger` (`IN - OUT`) | Packets (int/3 dp) | Per-product & consolidated modes | `IMPLEMENTED — NOT TESTED` |
| `CALC-028` | `inventory.py` | `calculate_warehouse_stock_balance` | Central warehouse packet balance (`COMPANY_RECEIPT + RETURNED - ISSUED - DIRECT_SALE + ADJ`) | Packets | Excludes cancelled movements | `IMPLEMENTED — NOT TESTED` |
| `CALC-029` | `inventory.py` | `calculate_salesman_stock_balance` | Field salesman van packet balance (`ISSUED - SOLD - RETURNED + SALESMAN_ADJUSTMENT`) | Packets | Scoped per `salesman_user_id` + `product_id` | `IMPLEMENTED — NOT TESTED` |
| `CALC-030` | `inventory.py` | `calculate_physical_count_variance` | `variance = physical_count - expected_stock` (`SURPLUS` if `> 0`, `SHORTAGE` if `< 0`, `MATCHED` if `== 0`) | Packets / `kg` | Never auto-posts loss without Owner review | `IMPLEMENTED — NOT TESTED` |
| `CALC-031` | `inventory.py` | `calculate_raw_material_balance` | Separates `recorded_balance` vs `confirmed_available`: unverified opening stock (`opening_stock_verified != True`) is excluded from `confirmed_available` until physically verified by Owner | `kg` (3 dp) | Enforces `POL-017` opening-stock safeguard | `IMPLEMENTED — NOT TESTED` |
| `CALC-032` | `inventory.py` | `calculate_consolidated_finished_goods_register` | Aggregates Factory + Warehouse + Salesmen In-Hand = `total_internal_on_hand_packets`, plus `channels_dispatched_packets` & status flags | Register rows + summary | Drives `StockView` & `ProductionView` registers | `IMPLEMENTED — NOT TESTED` |

---

## 3. Accounting & Financial Calculation Notes (CA-Gated)

1. **Double-Entry Voucher Balance (`backend/app/accounting/journal_engine.py::validate_journal_lines`):**
   - Formula: `abs(sum(Decimal(line.debit)) - sum(Decimal(line.credit))) == Decimal("0.00")` with minimum 2 lines and no negative amounts.
   - Fails closed (`HTTP 422`) on unbalanced vouchers.
2. **Automated GST Calculation (`hsn_gst_tax_rates` — `PENDING_CA_APPROVAL`):**
   - Blocked by `assert_ca_policy_approved("hsn_gst_tax_rates")` when automated GST posting is requested on `/api/v2/channels/settlements` until CA approves HSN-to-GST schedule (`EXEMPT_0`, `GST_5`, `GST_12`, `GST_18`, `CUSTOM_BY_HSN`).
3. **Inventory Valuation (`inventory_valuation_method` — `PENDING_CA_APPROVAL`):**
   - Surfaced in `CALC-019` and `GET /api/v2/meta/policies`; awaits CA selection between `FIFO` and `WEIGHTED_AVERAGE`.
4. **Factory Overhead & Labour Capitalization (`overhead_and_labour_allocation_basis` — `PENDING_CA_APPROVAL`):**
   - Surfaced in `CALC-019`; awaits CA selection among `DIRECT_KG`, `BATCH_HOURS`, `STANDARD_ABSORPTION`.
5. **Fixed Asset Depreciation (`depreciation_policy` — `PENDING_CA_APPROVAL`):**
   - Blocked for automated depreciation journals until CA selects `WDV_INCOME_TAX` or `SLM_COMPANIES_ACT`.
