# Kawad Swad Production Module (Stage 1)

## Workflow
1. Owner/PA creates factory worker profiles with fixed daily wages.
2. Owner/PA records attendance as Present, Half Day, or Absent. Attendance accrues wages at the worker's saved daily wage; it does not mark wages as paid.
3. Owner/PA saves an approved recipe for each product variant. Recipe quantity means the amount of ingredient required per 1 kg of net papad output.
4. Owner/PA records daily production by variant in kilograms, including rejected/wastage kilograms. The batch remains pending.
5. An authorised Owner/PA approves the batch. Approval requires an approved recipe and enough raw-material stock, records raw-material consumption in `RawMaterialLedger`, and adds unpackaged kilograms to `ProductionStockLedger`.
6. Packaging records the bulk kilograms used and packet counts for 200 g, 500 g, and 1 kg. The app calculates expected weight and flags differences. It checks that the unpackaged bulk balance is sufficient.
7. Packet stock is recorded against the correct SKU row for each pack size. The product catalogue must contain an active SKU for every size used.
8. Dispatch records move finished packets out of factory stock to E-commerce, Retail, Salesman, Wholesale, or Distributor. Dispatch is explicitly marked `DISPATCHED_NOT_SALE`, and does not create a sale or payment.

## Google Sheets tabs
The backend creates these new tabs on first successful write if they do not exist:
- `Workers`
- `WorkerAttendance`
- `Recipes`
- `ProductionBatches`
- `PackagingBatches`
- `ProductionStockLedger`
- `ProductionDispatches`
- `RawMaterialLedger`

The existing `Products` tab is reused. Product variants with multiple pack sizes should have separate SKU rows with the same `product_name` and `pack_weight_g` of 200, 500, or 1000. The product name is used as the bulk-variant key. Make sure names are consistent across pack sizes.

## RawMaterials sheet requirement
Production approval requires an existing `RawMaterials` tab with at least these columns:
- `material_name` (or `raw_material_name` or `name`)
- `current_stock` (or `stock_quantity`, `quantity`, or `opening_stock`)
- Optional: `raw_material_id`, `unit`

Enter opening quantity in the unit used in the recipe. Recipe material names must match the RawMaterials name exactly (case-insensitive). Consumption is appended to `RawMaterialLedger` and deducted from the available amount when subsequent batches are checked. The system does not overwrite the opening stock cell.

## Permissions
Production and factory stock screens/routes are available to Owner and PA roles only in this stage. A separate factory-worker login role and per-user authorisation toggles are not implemented yet; worker profiles are records, not login accounts. Salesmen do not get production access.

## Controls and limitations
- Production batches are pending until approved.
- Inactive products cannot be used for new production, recipes, packaging, or dispatch.
- Stock transfers do not create sales.
- Duplicate attendance for a worker/date is blocked.
- Packaging differences are flagged for review, not silently adjusted.
- Google Sheets disconnect blocks production writes when a spreadsheet ID is configured.
- Google Sheets is not a transactional database. A network failure during a multi-row operation can still leave a partial ledger write. Check the batch reference in `RawMaterialLedger` and `ProductionStockLedger` before manually retrying or correcting any partial failure.
- This stage records wage accrual, not wage payments or payroll compliance.
- No new product/SKU creation screen is added here. Add/activate the needed SKU in the existing Products screen first.
- The full frontend build must be run in CI/Render before deployment. Do not replace live data or use this module against production until a test spreadsheet workflow has been verified.
