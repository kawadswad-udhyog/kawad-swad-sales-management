"""
Kawad Swad ERP - Double-Entry Accounting Posting Handlers
Maps operational ERP business events to balanced double-entry journal vouchers.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from app.calculations.units import to_decimal, round_money, MONEY_PRECISION
from app.accounting.journal_engine import post_journal_voucher


def post_receipt_journal(
    receipt_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Supplier Purchase Receipt:
    Debit: Raw Material Inventory (1210 / 1215)
    Debit: Input CGST / SGST (1310 / 1320) if recoverable
    Credit: Accounts Payable (2100)
    """
    txn_id = str(receipt_data.get("raw_material_txn_id") or receipt_data.get("transaction_id") or "").strip()
    qty = to_decimal(
        receipt_data.get("quantity")
        or receipt_data.get("quantity_kg")
        or receipt_data.get("quantity_received")
        or 0
    )
    rate = to_decimal(
        receipt_data.get("purchase_rate")
        or receipt_data.get("unit_price_inr")
        or receipt_data.get("rate_per_unit")
        or 0
    )
    freight = to_decimal(receipt_data.get("freight_amount", 0) or 0)
    gst = to_decimal(receipt_data.get("gst_amount") or receipt_data.get("tax_amount") or 0)
    gst_treatment = str(receipt_data.get("gst_treatment", "RECOVERABLE_ITC")).upper()

    mat_name = str(receipt_data.get("material_name") or receipt_data.get("material_name_snapshot") or "").strip()
    is_dal = "dal" in mat_name.lower() or "moong" in mat_name.lower() or "urad" in mat_name.lower() or "chana" in mat_name.lower()
    inv_code = "1210" if is_dal else "1215"

    base_amt = qty * rate
    lines = []

    if gst_treatment == "RECOVERABLE_ITC" and gst > Decimal("0"):
        # Split GST with penny-accurate rounding so debits equal credits
        cgst = (gst / Decimal("2")).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        sgst = gst - cgst
        inv_amt = base_amt + freight
        total_payable = inv_amt + cgst + sgst

        lines.append({"account_code": inv_code, "debit_amount": round_money(inv_amt), "notes": f"Material {mat_name} + Freight"})
        lines.append({"account_code": "1310", "debit_amount": round_money(cgst), "notes": "Input CGST"})
        lines.append({"account_code": "1320", "debit_amount": round_money(sgst), "notes": "Input SGST"})
        lines.append({"account_code": "2100", "credit_amount": round_money(total_payable), "notes": f"Payable to {receipt_data.get('supplier_name', 'Supplier')}"})
    else:
        # Capitalize GST into inventory cost or zero-rated
        inv_amt = base_amt + freight + gst
        lines.append({"account_code": inv_code, "debit_amount": round_money(inv_amt), "notes": f"Landed inventory cost for {mat_name}"})
        lines.append({"account_code": "2100", "credit_amount": round_money(inv_amt), "notes": f"Payable to {receipt_data.get('supplier_name', 'Supplier')}"})

    return post_journal_voucher(
        voucher_type="PURCHASE",
        reference_type="RAW_MATERIAL_RECEIPT",
        reference_id=txn_id,
        narration=f"Purchase receipt of {qty} kg {mat_name} from {receipt_data.get('supplier_name', 'Supplier')} (Bill: {receipt_data.get('invoice_number', 'N/A')})",
        lines=lines,
        posted_by=actor,
        journal_date=str(receipt_data.get("receipt_date", "")).strip() or None,
    )


def post_milling_journal(
    milling_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Dal Milling Conversion:
    Debit: Milled Flour Inventory (1220) [Total Flour Cost]
    Credit: Raw Material Inventory - Whole Dal (1210) [Source Dal Cost]
    Credit: Accrued Operating Expenses Payable (2130) [Milling Expenses]
    """
    batch_id = str(milling_data.get("milling_batch_id", "")).strip()
    in_qty = to_decimal(milling_data.get("input_quantity_kg", 0) or 0)
    out_qty = to_decimal(milling_data.get("flour_output_kg", 0) or 0)
    source_rate = to_decimal(milling_data.get("source_unit_rate", 0) or 0)
    milling_exp = to_decimal(milling_data.get("milling_expenses", 0) or 0)

    dal_cost = in_qty * source_rate
    total_flour_cost = dal_cost + milling_exp

    lines = [
        {
            "account_code": "1220",
            "debit_amount": round_money(total_flour_cost),
            "notes": f"Milled flour addition: {out_qty} kg @ ₹{float(total_flour_cost / out_qty):.2f}/kg",
        },
        {
            "account_code": "1210",
            "credit_amount": round_money(dal_cost),
            "notes": f"Whole dal consumption: {in_qty} kg @ ₹{source_rate}/kg",
        },
    ]

    if milling_exp > Decimal("0"):
        lines.append({
            "account_code": "2130",
            "credit_amount": round_money(milling_exp),
            "notes": "Grinding & machine electricity expenses absorbed into flour",
        })

    return post_journal_voucher(
        voucher_type="MANUFACTURING",
        reference_type="DAL_MILLING",
        reference_id=batch_id,
        narration=f"Milling conversion: {in_qty} kg Whole Dal -> {out_qty} kg Milled Flour (Loss: {float(in_qty - out_qty):.2f} kg)",
        lines=lines,
        posted_by=actor,
        journal_date=str(milling_data.get("milling_date", "")).strip() or None,
    )


def post_production_batch_journal(
    batch_data: Dict[str, Any],
    flour_cost: Optional[Decimal] = None,
    spice_cost: Optional[Decimal] = None,
    labor_cost: Optional[Decimal] = None,
    actor: str = "SYSTEM",
) -> Dict[str, Any]:
    """
    Papad Dough & Bulk Production:
    Debit: Work-in-Progress / Bulk Papad (1230)
    Credit: Milled Flour Inventory (1220)
    Credit: Spices & Ingredients (1215)
    Credit: Wages Payable (2120)
    """
    prod_id = str(batch_data.get("production_id") or batch_data.get("batch_id") or "").strip()
    qty_kg = to_decimal(batch_data.get("net_quantity_kg") or batch_data.get("quantity_kg", 0) or 0)
    p_name = str(batch_data.get("product_name_snapshot", "Papad"))

    # Dynamically extract or resolve costs if not explicitly passed
    if flour_cost is None or spice_cost is None:
        f_cost_val = batch_data.get("flour_cost")
        s_cost_val = batch_data.get("ingredient_cost")
        if f_cost_val is not None and s_cost_val is not None:
            flour_cost = to_decimal(f_cost_val)
            spice_cost = to_decimal(s_cost_val)
        else:
            # Query RawMaterialLedger deductions for this batch
            from app.sheets import db
            from app.calculations.costing import get_latest_purchase_rate
            from app.calculations.recipes import calculate_recipe_cost_estimate
            raw_deductions = [
                x for x in db.get_records("RawMaterialLedger", fresh=True)
                if str(x.get("production_id", "")).strip() == prod_id
                and str(x.get("movement_type", "")).strip().upper() == "PRODUCTION_CONSUMPTION"
            ]
            rm_master = db.get_records("RawMaterials", fresh=True) or db.get_records("RawMaterialsMaster", fresh=True)
            pur_ledger = db.get_records("RawMaterialLedger", fresh=True)
            f_calc = Decimal("0")
            s_calc = Decimal("0")
            for d in raw_deductions:
                m_name = str(d.get("material_name", "")).lower()
                m_id = str(d.get("raw_material_id", ""))
                q = to_decimal(d.get("quantity", 0) or 0)
                r_val = d.get("rate_per_unit")
                if r_val is not None and str(r_val).strip() not in {"", "0", "none", "null", "pending"}:
                    r = to_decimal(r_val)
                else:
                    rate_lookup = get_latest_purchase_rate(m_name or m_id, rm_master, pur_ledger)
                    r = to_decimal(rate_lookup.get("rate_per_canonical_unit") or 0)
                c = q * r
                if "flour" in m_name or "atta" in m_name:
                    f_calc += c
                else:
                    s_calc += c

            # If deduction rates are completely absent, evaluate approved recipe formula cost
            if f_calc == Decimal("0") and s_calc == Decimal("0"):
                recipes = db.get_records("Recipes", fresh=True)
                m_rec = next((r for r in recipes if str(r.get("product_name_snapshot", "")).strip().lower() == p_name.lower() and str(r.get("approved", "")).lower() in {"true", "1"}), None)
                if m_rec:
                    import json
                    items_raw = m_rec.get("items") or m_rec.get("items_json")
                    if isinstance(items_raw, str):
                        try:
                            items_raw = json.loads(items_raw)
                        except Exception:
                            items_raw = []
                    yield_kg = float(m_rec.get("expected_yield_kg", 1.2) or 1.2)
                    rec_cost = calculate_recipe_cost_estimate(items_raw, yield_kg)
                    if rec_cost.get("cost_per_kg"):
                        tot_c = to_decimal(rec_cost["cost_per_kg"]) * qty_kg
                        f_calc = tot_c * Decimal("0.85")
                        s_calc = tot_c * Decimal("0.15")

            flour_cost = f_calc
            spice_cost = s_calc

    if labor_cost is None:
        labor_cost = to_decimal(batch_data.get("labor_cost") or batch_data.get("labour_cost") or 0)

    r_flour = round_money(flour_cost)
    r_spice = round_money(spice_cost)
    r_labor = round_money(labor_cost)
    r_total = r_flour + r_spice + r_labor

    if r_total <= Decimal("0"):
        raise ValueError(f"Cannot post production batch journal for {prod_id}: Total production cost is ₹0.00. Rates must be confirmed.")

    lines = [
        {
            "account_code": "1230",
            "debit_amount": r_total,
            "notes": f"Bulk papad produced: {qty_kg} kg {p_name}",
        },
        {
            "account_code": "1220",
            "credit_amount": r_flour,
            "notes": "Flour consumed in batch recipe",
        },
    ]

    if r_spice > Decimal("0"):
        lines.append({
            "account_code": "1215",
            "credit_amount": r_spice,
            "notes": "Spices and condiments consumed",
        })

    if r_labor > Decimal("0"):
        lines.append({
            "account_code": "2120",
            "credit_amount": r_labor,
            "notes": "Accrued rolling & pressing labor",
        })

    return post_journal_voucher(
        voucher_type="MANUFACTURING",
        reference_type="PRODUCTION_BATCH",
        reference_id=prod_id,
        narration=f"Papad production: {qty_kg} kg {p_name} bulk batch",
        lines=lines,
        posted_by=actor,
        journal_date=str(batch_data.get("production_date", "")).strip() or None,
    )


def post_packaging_batch_journal(
    pack_data: Dict[str, Any],
    bulk_cost: Optional[Decimal] = None,
    packing_material_cost: Optional[Decimal] = None,
    packing_labor_cost: Optional[Decimal] = None,
    actor: str = "SYSTEM",
    require_actual_cost: bool = False,
) -> Dict[str, Any]:
    """
    Packaging Conversion:
    Debit: Finished Goods Inventory - Packaged SKUs (1240)
    Credit: Work-in-Progress / Bulk Papad (1230)
    Credit: Packaging Materials Inventory (1250)
    Credit: Wages Payable (2120)

    Enforces strict segregation between ACTUAL and ESTIMATED valuations:
    - If require_actual_cost is True and any batch cost is ESTIMATED, raises ValueError.
    - If ESTIMATED costs are used operationally, the voucher is tagged as PROVISIONAL
      and recorded in IncompleteTransactions for audit and Owner review.
    """
    pack_id = str(pack_data.get("packaging_id", "") or pack_data.get("packaging_batch_id", "")).strip()
    tot_packets = int(float(pack_data.get("total_packets", 0) or pack_data.get("packet_count", 0) or 0))
    p_name = str(pack_data.get("product_name_snapshot", "Papad"))
    bulk_kg = to_decimal(pack_data.get("bulk_kg_used", 0) or 0)

    # Normalize incoming cost arguments to Decimal
    if bulk_cost is not None:
        try:
            bulk_cost = to_decimal(bulk_cost)
        except Exception:
            bulk_cost = None
    if packing_material_cost is not None:
        try:
            packing_material_cost = to_decimal(packing_material_cost)
        except Exception:
            packing_material_cost = None
    if packing_labor_cost is not None:
        try:
            packing_labor_cost = to_decimal(packing_labor_cost)
        except Exception:
            packing_labor_cost = None

    # Detect estimated cost status
    is_estimated = (
        str(pack_data.get("cost_status", "")).strip().upper() == "ESTIMATED"
        or bool(pack_data.get("has_estimated_cost"))
    )
    if not is_estimated and pack_data.get("batch_allocations_json"):
        try:
            import json
            allocs = json.loads(str(pack_data["batch_allocations_json"]))
            if isinstance(allocs, list):
                if any(str(a.get("cost_status", "")).strip().upper() == "ESTIMATED" for a in allocs):
                    is_estimated = True
        except Exception:
            pass

    if require_actual_cost and is_estimated:
        raise ValueError(f"Estimated cost rejected for actual-cost accounting. Authoritative actual cost required for packaging {pack_id}.")

    # Dynamically resolve bulk cost if omitted
    if bulk_cost is None:
        rec_bulk_cost = pack_data.get("bulk_cost") or pack_data.get("total_bulk_cost")
        if rec_bulk_cost is not None and str(rec_bulk_cost).strip() not in {"", "0", "null", "none"}:
            try:
                bulk_cost = to_decimal(rec_bulk_cost)
            except Exception:
                pass

        if bulk_cost is None and pack_data.get("batch_allocations_json"):
            try:
                import json
                allocs = json.loads(str(pack_data["batch_allocations_json"]))
                if isinstance(allocs, list) and allocs:
                    sum_c = sum(to_decimal(a.get("total_cost", 0) or 0) for a in allocs)
                    if sum_c > Decimal("0"):
                        bulk_cost = sum_c
            except Exception:
                pass

        if bulk_cost is None:
            from app.sheets import db
            # Check ledger movements for recorded total_cost on BULK_PACKAGED rows
            ledger = db.get_records("ProductionStockLedger", fresh=True)
            pack_mvts = [
                m for m in ledger
                if str(m.get("reference_id", "")).strip() == pack_id
                and str(m.get("movement_type", "")).strip().upper() == "BULK_PACKAGED"
            ]
            if pack_mvts:
                sum_ledger_cost = sum(to_decimal(m.get("total_cost", 0) or 0) for m in pack_mvts)
                if sum_ledger_cost > Decimal("0"):
                    bulk_cost = sum_ledger_cost

        if bulk_cost is None:
            from app.sheets import db
            from app.calculations.costing import get_authoritative_bulk_cost_per_kg
            batches = db.get_records("ProductionBatches", fresh=True)
            recipes = db.get_records("Recipes", fresh=True)
            stock_ledger = db.get_records("ProductionStockLedger", fresh=True)
            rm_master = db.get_records("RawMaterials", fresh=True) or db.get_records("RawMaterialsMaster", fresh=True)
            bulk_cost_per_kg = get_authoritative_bulk_cost_per_kg(p_name, batches, recipes, stock_ledger, rm_master)
            bulk_cost = bulk_kg * to_decimal(bulk_cost_per_kg)
            is_estimated = True
            if require_actual_cost:
                raise ValueError(f"Estimated cost rejected for actual-cost accounting. Authoritative actual cost required for packaging {pack_id}.")

    if packing_material_cost is None:
        packing_material_cost = to_decimal(pack_data.get("packaging_material_cost") or pack_data.get("packing_material_cost") or 0)
    if packing_labor_cost is None:
        packing_labor_cost = to_decimal(pack_data.get("packaging_labor_cost") or pack_data.get("packing_labor_cost") or 0)

    r_bulk = round_money(to_decimal(bulk_cost))
    r_mat = round_money(to_decimal(packing_material_cost))
    r_lab = round_money(to_decimal(packing_labor_cost))
    r_finished = r_bulk + r_mat + r_lab

    if r_finished <= Decimal("0"):
        raise ValueError(f"Cannot post packaging batch journal for {pack_id}: Total finished valuation is ₹0.00.")

    bulk_note = f"Bulk papad consumed: {bulk_kg} kg [ESTIMATED_VALUATION]" if is_estimated else f"Bulk papad consumed: {bulk_kg} kg"
    finished_note = f"Finished packet addition (PROVISIONAL): {tot_packets} packets of {p_name}" if is_estimated else f"Finished packet addition: {tot_packets} packets of {p_name}"
    voucher_type = "PROVISIONAL_MANUFACTURING" if is_estimated else "MANUFACTURING"
    narration_prefix = "[PROVISIONAL_ESTIMATED_VALUATION] " if is_estimated else ""

    lines = [
        {
            "account_code": "1240",
            "debit_amount": r_finished,
            "notes": finished_note,
        },
        {
            "account_code": "1230",
            "credit_amount": r_bulk,
            "notes": bulk_note,
        },
    ]

    if r_mat > Decimal("0"):
        lines.append({
            "account_code": "1250",
            "credit_amount": r_mat,
            "notes": "Printed film pouches & cartons consumed",
        })

    if r_lab > Decimal("0"):
        lines.append({
            "account_code": "2120",
            "credit_amount": r_lab,
            "notes": "Direct packaging and sealing labor",
        })

    res = post_journal_voucher(
        voucher_type=voucher_type,
        reference_type="PACKAGING_BATCH",
        reference_id=pack_id,
        narration=f"{narration_prefix}Packaging conversion: {bulk_kg} kg Bulk -> {tot_packets} Packets {p_name}",
        lines=lines,
        posted_by=actor,
        journal_date=str(pack_data.get("packaging_date", "")).strip() or None,
    )

    if is_estimated:
        try:
            from app.sheets import db
            from app.time_utils import now
            from app.id_generator import make_id
            db.append_record("IncompleteTransactions", {
                "transaction_id": make_id("IncompleteTransactions"),
                "transaction_type": "ESTIMATED_COST_REVIEW_REQUIRED",
                "idempotency_key": f"acct-est-pack-{pack_id}",
                "status": "PENDING_REVIEW",
                "payload_json": json.dumps({"packaging_id": pack_id, "bulk_cost": float(r_bulk), "valuation_status": "ESTIMATED"}),
                "error_details": "Voucher posted with provisional estimated rates. Requires Owner actual cost confirmation.",
                "created_at": now(),
                "updated_at": now(),
                "resolved_by": "",
                "resolved_at": "",
            })
        except Exception:
            pass

    return res


def post_sale_journal(
    sale_data: Dict[str, Any],
    estimated_cogs: Decimal = Decimal("0"),
    actor: str = "OPERATOR",
) -> Dict[str, Any]:
    """
    Sales Billing & COGS Recognition:
    Leg 1: Revenue Recognition
      Debit: Field Salesman Van Cash / Cash in Transit (1115) [if CASH] OR Bank (1120) OR Accounts Receivable (1130)
      Credit: Papad Sales Revenue (4100) [Net of GST]
      Credit: Output CGST Payable (2210) & Output SGST Payable (2220) [if tax applied]
    Leg 2: Inventory Reduction & Cost of Goods Sold
      Debit: Cost of Goods Sold - Papad (5100)
      Credit: Finished Goods Inventory - Packaged SKUs (1240)
    """
    sale_id = str(sale_data.get("sale_id", "")).strip()
    bill_no = str(sale_data.get("bill_number", "")).strip()
    bill_total = to_decimal(sale_data.get("bill_total", 0) or 0)
    tax_amt = to_decimal(sale_data.get("tax_amount", 0) or 0)
    pay_method = str(sale_data.get("payment_method", "CASH")).upper()

    # Cash collected on van delivery routes is held as Van Cash (1115) until daily closing
    debtor_or_cash_code = "1115" if pay_method == "CASH" else "1120" if pay_method in {"UPI", "BANK_TRANSFER"} else "1130"

    lines = [
        # Revenue Entry
        {
            "account_code": debtor_or_cash_code,
            "debit_amount": round_money(bill_total),
            "notes": f"Sale settlement via {pay_method} for bill {bill_no}",
        },
    ]

    cgst_input = sale_data.get("cgst_amount")
    sgst_input = sale_data.get("sgst_amount")
    if cgst_input is not None and sgst_input is not None:
        cgst = to_decimal(cgst_input).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        sgst = to_decimal(sgst_input).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        tax_amt = cgst + sgst
    elif tax_amt > Decimal("0"):
        cgst = (tax_amt / Decimal("2")).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        sgst = tax_amt - cgst
    else:
        cgst = Decimal("0")
        sgst = Decimal("0")

    if tax_amt > Decimal("0"):
        net_revenue = bill_total - (cgst + sgst)
        lines.append({
            "account_code": "4100",
            "credit_amount": round_money(net_revenue),
            "notes": f"Net papad revenue from bill {bill_no}",
        })
        if cgst > Decimal("0"):
            lines.append({
                "account_code": "2210",
                "credit_amount": round_money(cgst),
                "notes": f"Output CGST collected on bill {bill_no}",
            })
        if sgst > Decimal("0"):
            lines.append({
                "account_code": "2220",
                "credit_amount": round_money(sgst),
                "notes": f"Output SGST collected on bill {bill_no}",
            })
    else:
        lines.append({
            "account_code": "4100",
            "credit_amount": round_money(bill_total),
            "notes": f"Revenue from bill {bill_no} to {sale_data.get('customer_name_snapshot', 'Customer')}",
        })

    # COGS Entry (if unit cost available)
    if estimated_cogs > Decimal("0"):
        lines.append({
            "account_code": "5100",
            "debit_amount": round_money(estimated_cogs),
            "notes": f"Cost of goods sold for bill {bill_no}",
        })
        lines.append({
            "account_code": "1240",
            "credit_amount": round_money(estimated_cogs),
            "notes": "Finished goods packet inventory deduction",
        })

    return post_journal_voucher(
        voucher_type="SALES",
        reference_type="SALE_INVOICE",
        reference_id=sale_id,
        narration=f"Sales invoice {bill_no} to {sale_data.get('customer_name_snapshot', 'Customer')} (Total: ₹{bill_total:.2f})",
        lines=lines,
        posted_by=actor,
        journal_date=str(sale_data.get("sale_datetime", "")).strip()[:10] or None,
    )



def post_daily_closing_cash_remittance_journal(
    closing_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Daily Closing Cash Settlement:
    Transfers cash from Van Float (1115) to Central Factory Safe (1110):
    Debit: Cash-in-Hand / Factory Safe (1110)
    Credit: Field Salesman Van Float (1115)
    """
    close_id = str(closing_data.get("closing_id", "")).strip()
    returned_cash = to_decimal(closing_data.get("physical_cash_returned", 0) or 0)
    s_user = str(closing_data.get("salesman_user_id", "")).strip()

    if returned_cash <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero cash returned"}

    lines = [
        {
            "account_code": "1110",
            "debit_amount": round_money(returned_cash),
            "notes": f"Physical cash remitted to factory safe from {s_user}",
        },
        {
            "account_code": "1115",
            "credit_amount": round_money(returned_cash),
            "notes": f"Van float clearance for daily closing {close_id}",
        },
    ]

    return post_journal_voucher(
        voucher_type="RECEIPT",
        reference_type="DAILY_CLOSING_CASH",
        reference_id=close_id,
        narration=f"Daily cash remittance from salesman {s_user} (Returned: ₹{returned_cash:.2f})",
        lines=lines,
        posted_by=actor,
        journal_date=str(closing_data.get("closing_date", "")).strip() or None,
    )


def post_expense_journal(
    expense_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Operating Expense Approval:
    Debit: 5210 (Salesman Travel & Petrol) or 5230 (General & Administrative)
    Credit: 1115 (Van Float) if paid out of salesman route cash,
            or 1110 (Factory Safe) if factory cash,
            or 2130 (Accrued Operating Expenses Payable) if credit/accrued.
    """
    exp_id = str(expense_data.get("expense_id", "")).strip()
    amount = to_decimal(expense_data.get("amount", 0) or 0)
    cat = str(expense_data.get("category", "")).lower()
    desc = str(expense_data.get("description", "")).strip()
    is_cash_reducing = str(expense_data.get("cash_reducing_expense", "false")).lower() in {"true", "1"}
    s_user = str(expense_data.get("salesman_user_id", "")).strip()

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero expense amount"}

    # Determine expense account
    if "petrol" in cat or "travel" in cat or "fuel" in cat or "vehicle" in cat:
        exp_code = "5210"
    elif "salary" in cat or "incentive" in cat or "wage" in cat:
        exp_code = "5220"
    else:
        exp_code = "5230"

    # Determine credit settlement account
    if is_cash_reducing and s_user:
        credit_code = "1115"  # Salesman route cash reduced
        credit_note = f"Disbursed from {s_user} van float"
    elif is_cash_reducing:
        credit_code = "1110"  # Factory cash safe reduced
        credit_note = "Disbursed from factory cash safe"
    else:
        credit_code = "2130"  # Accrued liability pending payout
        credit_note = "Accrued operating expense payable"

    lines = [
        {
            "account_code": exp_code,
            "debit_amount": round_money(amount),
            "notes": f"Expense: {desc or expense_data.get('category', 'Expense')}",
        },
        {
            "account_code": credit_code,
            "credit_amount": round_money(amount),
            "notes": credit_note,
        },
    ]

    return post_journal_voucher(
        voucher_type="PAYMENT",
        reference_type="EXPENSE",
        reference_id=exp_id,
        narration=f"Approved expense {exp_id} ({expense_data.get('category')}): ₹{amount:.2f}",
        lines=lines,
        posted_by=actor,
        journal_date=str(expense_data.get("expense_datetime", ""))[:10] or None,
    )


def post_payment_collection_journal(
    payment_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Debtor Collection Entry:
    Debit: 1115 (Van Float) if CASH, or 1120 (Bank) if UPI/BANK
    Credit: 1130 (Accounts Receivable / Sundry Debtors)
    """
    pay_id = str(payment_data.get("payment_id", "")).strip()
    amount = to_decimal(payment_data.get("amount", 0) or 0)
    method = str(payment_data.get("payment_method", "CASH")).upper()
    sale_id = str(payment_data.get("sale_id", "")).strip()

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero payment amount"}

    debit_code = "1115" if method == "CASH" else "1120"
    lines = [
        {
            "account_code": debit_code,
            "debit_amount": round_money(amount),
            "notes": f"Collection via {method} for sale {sale_id}",
        },
        {
            "account_code": "1130",
            "credit_amount": round_money(amount),
            "notes": f"Debtor receivable clearance for sale {sale_id}",
        },
    ]

    return post_journal_voucher(
        voucher_type="RECEIPT",
        reference_type="PAYMENT_COLLECTION",
        reference_id=pay_id,
        narration=f"Customer debt collection via {method}: ₹{amount:.2f} (Payment {pay_id})",
        lines=lines,
        posted_by=actor,
        journal_date=str(payment_data.get("payment_datetime", ""))[:10] or None,
    )


def post_supplier_payment_journal(
    payment_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Supplier Payment Settlement:
    Debit: Accounts Payable / Sundry Creditors (2100)
    Credit: Bank Account (1120) or Cash-in-Hand (1110)
    """
    pay_id = str(payment_data.get("payment_id", "")).strip()
    amount = to_decimal(payment_data.get("amount", 0) or 0)
    method = str(payment_data.get("payment_method", "BANK_TRANSFER")).upper()
    supp_name = str(payment_data.get("supplier_name", "Supplier"))
    bill_id = str(payment_data.get("bill_id", "")).strip()

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero payment amount"}

    credit_code = "1110" if method == "CASH" else "1120"
    lines = [
        {
            "account_code": "2100",
            "debit_amount": round_money(amount),
            "notes": f"Settlement of payable to {supp_name} for bill {bill_id}",
        },
        {
            "account_code": credit_code,
            "credit_amount": round_money(amount),
            "notes": f"Disbursement via {method} (Ref: {payment_data.get('reference_number', 'N/A')})",
        },
    ]

    return post_journal_voucher(
        voucher_type="PAYMENT",
        reference_type="SUPPLIER_PAYMENT",
        reference_id=pay_id,
        narration=f"Supplier payment to {supp_name} via {method}: ₹{amount:.2f}",
        lines=lines,
        posted_by=actor,
        journal_date=str(payment_data.get("payment_date", ""))[:10] or None,
    )


def post_supplier_return_journal(
    return_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Supplier Return (Debit Note):
    Debit: Accounts Payable / Sundry Creditors (2100)
    Credit: Raw Material Inventory (1210 or 1215)
    Credit: Input CGST / SGST (1310 / 1320) if tax included
    """
    ret_id = str(return_data.get("return_id", "")).strip()
    amount = to_decimal(return_data.get("return_amount", 0) or 0)
    supp_name = str(return_data.get("supplier_name", "Supplier"))
    mat_name = str(return_data.get("material_name", "Material"))
    tax_amt = to_decimal(return_data.get("tax_amount", 0) or 0)

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero return amount"}

    is_dal = "dal" in mat_name.lower() or "moong" in mat_name.lower() or "urad" in mat_name.lower() or "chana" in mat_name.lower()
    inv_code = "1210" if is_dal else "1215"

    lines = [
        {
            "account_code": "2100",
            "debit_amount": round_money(amount),
            "notes": f"Debit note against {supp_name} for returned {mat_name}",
        },
    ]

    if tax_amt > Decimal("0"):
        cgst = (tax_amt / Decimal("2")).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        sgst = tax_amt - cgst
        cost_amt = amount - (cgst + sgst)
        lines.append({
            "account_code": inv_code,
            "credit_amount": round_money(cost_amt),
            "notes": f"Inventory return credit for {mat_name}",
        })
        lines.append({
            "account_code": "1310",
            "credit_amount": round_money(cgst),
            "notes": "Reversal of Input CGST",
        })
        lines.append({
            "account_code": "1320",
            "credit_amount": round_money(sgst),
            "notes": "Reversal of Input SGST",
        })
    else:
        lines.append({
            "account_code": inv_code,
            "credit_amount": round_money(amount),
            "notes": f"Inventory return credit for {mat_name}",
        })

    return post_journal_voucher(
        voucher_type="PURCHASE",
        reference_type="SUPPLIER_RETURN",
        reference_id=ret_id,
        narration=f"Supplier debit note for return of {mat_name} to {supp_name}: ₹{amount:.2f}",
        lines=lines,
        posted_by=actor,
        journal_date=str(return_data.get("return_date", ""))[:10] or None,
    )


def post_customer_return_journal(
    return_data: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Customer Sales Return (Credit Note):
    Debit: Papad Sales Revenue (4100) [Net of tax]
    Debit: Output CGST (2210) & Output SGST (2220) [if tax applied]
    Credit: Accounts Receivable (1130) or Cash/Bank
    """
    ret_id = str(return_data.get("return_id", "")).strip()
    amount = to_decimal(return_data.get("refund_amount", 0) or return_data.get("amount", 0) or 0)
    tax_amt = to_decimal(return_data.get("tax_amount", 0) or 0)
    cust_name = str(return_data.get("customer_name", "Customer"))
    is_cash_refund = str(return_data.get("is_cash_refund", "false")).lower() in {"true", "1"}

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero return amount"}

    lines = []
    if tax_amt > Decimal("0"):
        cgst = (tax_amt / Decimal("2")).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
        sgst = tax_amt - cgst
        net_rev = amount - (cgst + sgst)
        lines.append({
            "account_code": "4100",
            "debit_amount": round_money(net_rev),
            "notes": f"Sales return debit for {cust_name}",
        })
        lines.append({
            "account_code": "2210",
            "debit_amount": round_money(cgst),
            "notes": "Output CGST reversal on return",
        })
        lines.append({
            "account_code": "2220",
            "debit_amount": round_money(sgst),
            "notes": "Output SGST reversal on return",
        })
    else:
        lines.append({
            "account_code": "4100",
            "debit_amount": round_money(amount),
            "notes": f"Sales return debit for {cust_name}",
        })

    credit_code = "1115" if is_cash_refund else "1130"
    lines.append({
        "account_code": credit_code,
        "credit_amount": round_money(amount),
        "notes": f"Credit note / refund for {cust_name}",
    })

    return post_journal_voucher(
        voucher_type="SALES_REVERSAL",
        reference_type="CUSTOMER_RETURN",
        reference_id=ret_id,
        narration=f"Sales credit note for return from {cust_name}: ₹{amount:.2f}",
        lines=lines,
        posted_by=actor,
        journal_date=str(return_data.get("return_date", ""))[:10] or None,
    )


def post_workforce_payment_journal(
    payment_data: Dict[str, Any],
    actor: str = "SYSTEM",
) -> Dict[str, Any]:
    """
    Workforce Disbursement Entry:
    1. Factory Labour Wage (LABOUR_WAGE):
       Debit: 2120 (Accrued Factory Labor & Wages Payable) - Clears accrued manufacturing liability, avoids double counting.
       Credit: 1110 (Central Factory Safe) if CASH, or 1120 (Bank Current Account) if BANK_TRANSFER / UPI.
    2. Salesman Salaries & Incentives (SALARY for SALESMAN):
       Debit: 5220 (Salesman Salary & Performance Incentives).
       Credit: 1110 (Cash) or 1120 (Bank).
    3. Administrative Staff Salaries (SALARY for PA, ACCOUNTANT, SOCIAL_MEDIA_MGR, etc.):
       Debit: 5230 (General & Administrative Expenses).
       Credit: 1110 (Cash) or 1120 (Bank).
    4. Freelancer Milestone Payments (FREELANCER_MILESTONE):
       Debit: 5230 (General & Administrative Expenses - Professional Fees).
       Credit: 1120 (Bank) or 1110 (Cash).
    """
    pay_id = str(payment_data.get("payment_id", "")).strip()
    amount = to_decimal(payment_data.get("amount", 0) or 0)
    pay_type = str(payment_data.get("payment_type", "")).strip().upper()
    role = str(payment_data.get("role_or_category", "")).strip().upper()
    method = str(payment_data.get("payment_method", "BANK_TRANSFER")).strip().upper()
    recip_name = str(payment_data.get("recipient_name", "Recipient")).strip()
    recip_id = str(payment_data.get("recipient_id", "")).strip()

    if amount <= Decimal("0"):
        return {"status": "SKIPPED", "message": "Zero workforce payment amount"}

    # Credit settlement account
    credit_code = "1110" if method == "CASH" else "1120"
    credit_account_name = "Cash-in-Hand (Central Factory Safe)" if credit_code == "1110" else "Bank Current Account (SBI / HDFC)"

    # Debit account resolution
    if pay_type == "LABOUR_WAGE":
        debit_code = "2120"
        debit_note = f"Clear accrued factory labor liability for {recip_name} ({recip_id})"
    elif pay_type == "SALARY":
        if role in {"SALESMAN", "FIELD_SALESMAN"}:
            debit_code = "5220"
            debit_note = f"Salesman base salary and performance incentives for {recip_name}"
        else:
            debit_code = "5230"
            debit_note = f"Office & administrative staff salary for {recip_name} ({role})"
    elif pay_type == "FREELANCER_MILESTONE":
        debit_code = "5230"
        debit_note = f"Consultant & freelancer milestone payment for {recip_name}"
    else:
        debit_code = "5230"
        debit_note = f"Workforce disbursement for {recip_name}"

    lines = [
        {
            "account_code": debit_code,
            "debit_amount": round_money(amount),
            "notes": debit_note,
        },
        {
            "account_code": credit_code,
            "credit_amount": round_money(amount),
            "notes": f"Disbursement via {method} from {credit_account_name}",
        },
    ]

    return post_journal_voucher(
        voucher_type="PAYMENT",
        reference_type="WORKFORCE_PAYMENT",
        reference_id=pay_id,
        narration=f"Workforce payment ({pay_type}) to {recip_name}: ₹{float(amount):.2f} via {method}",
        lines=lines,
        posted_by=actor,
        journal_date=str(payment_data.get("payment_date", ""))[:10] or None,
    )


