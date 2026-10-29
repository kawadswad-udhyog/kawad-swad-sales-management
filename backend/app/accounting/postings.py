"""
Kawad Swad ERP - Double-Entry Accounting Posting Handlers
Maps operational ERP business events to balanced double-entry journal vouchers.
"""

from decimal import Decimal
from typing import Dict, Any, Optional
from app.calculations.units import to_decimal, round_money
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
    qty = to_decimal(receipt_data.get("quantity", 0) or receipt_data.get("quantity_received", 0) or 0)
    rate = to_decimal(receipt_data.get("purchase_rate", 0) or receipt_data.get("rate_per_unit", 0) or 0)
    freight = to_decimal(receipt_data.get("freight_amount", 0) or 0)
    gst = to_decimal(receipt_data.get("gst_amount", 0) or 0)
    gst_treatment = str(receipt_data.get("gst_treatment", "RECOVERABLE_ITC")).upper()

    mat_name = str(receipt_data.get("material_name", "")).strip()
    is_dal = "dal" in mat_name.lower() or "moong" in mat_name.lower() or "urad" in mat_name.lower() or "chana" in mat_name.lower()
    inv_code = "1210" if is_dal else "1215"

    base_amt = qty * rate
    lines = []

    if gst_treatment == "RECOVERABLE_ITC" and gst > Decimal("0"):
        # Split GST equally into CGST and SGST
        cgst = gst / Decimal("2")
        sgst = gst / Decimal("2")
        inv_amt = base_amt + freight
        total_payable = base_amt + freight + gst

        lines.append({"account_code": inv_code, "debit_amount": round_money(inv_amt), "notes": f"Material {mat_name} + Freight"})
        lines.append({"account_code": "1310", "debit_amount": round_money(cgst), "notes": "Input CGST 2.5%"})
        lines.append({"account_code": "1320", "debit_amount": round_money(sgst), "notes": "Input SGST 2.5%"})
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
    flour_cost: Decimal,
    spice_cost: Decimal,
    labor_cost: Decimal,
    actor: str,
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

    total_cost = flour_cost + spice_cost + labor_cost
    lines = [
        {
            "account_code": "1230",
            "debit_amount": round_money(total_cost),
            "notes": f"Bulk papad produced: {qty_kg} kg {p_name}",
        },
        {
            "account_code": "1220",
            "credit_amount": round_money(flour_cost),
            "notes": "Flour consumed in batch recipe",
        },
    ]

    if spice_cost > Decimal("0"):
        lines.append({
            "account_code": "1215",
            "credit_amount": round_money(spice_cost),
            "notes": "Spices and condiments consumed",
        })

    if labor_cost > Decimal("0"):
        lines.append({
            "account_code": "2120",
            "credit_amount": round_money(labor_cost),
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
    bulk_cost: Decimal,
    packing_material_cost: Decimal,
    packing_labor_cost: Decimal,
    actor: str,
) -> Dict[str, Any]:
    """
    Packaging Conversion:
    Debit: Finished Goods Inventory - Packaged SKUs (1240)
    Credit: Work-in-Progress / Bulk Papad (1230)
    Credit: Packaging Materials Inventory (1250)
    Credit: Wages Payable (2120)
    """
    pack_id = str(pack_data.get("packaging_id", "")).strip()
    tot_packets = int(float(pack_data.get("total_packets", 0) or 0))
    p_name = str(pack_data.get("product_name_snapshot", "Papad"))

    total_finished_cost = bulk_cost + packing_material_cost + packing_labor_cost
    lines = [
        {
            "account_code": "1240",
            "debit_amount": round_money(total_finished_cost),
            "notes": f"Finished packet addition: {tot_packets} packets of {p_name}",
        },
        {
            "account_code": "1230",
            "credit_amount": round_money(bulk_cost),
            "notes": f"Bulk papad consumed: {pack_data.get('bulk_kg_used')} kg",
        },
    ]

    if packing_material_cost > Decimal("0"):
        lines.append({
            "account_code": "1250",
            "credit_amount": round_money(packing_material_cost),
            "notes": "Printed film pouches & cartons consumed",
        })

    if packing_labor_cost > Decimal("0"):
        lines.append({
            "account_code": "2120",
            "credit_amount": round_money(packing_labor_cost),
            "notes": "Direct packaging and sealing labor",
        })

    return post_journal_voucher(
        voucher_type="MANUFACTURING",
        reference_type="PACKAGING_BATCH",
        reference_id=pack_id,
        narration=f"Packaging conversion: {pack_data.get('bulk_kg_used')} kg Bulk -> {tot_packets} Packets {p_name}",
        lines=lines,
        posted_by=actor,
        journal_date=str(pack_data.get("packaging_date", "")).strip() or None,
    )


def post_sale_journal(
    sale_data: Dict[str, Any],
    estimated_cogs: Decimal,
    actor: str,
) -> Dict[str, Any]:
    """
    Sales Billing & COGS Recognition:
    Leg 1: Revenue Recognition
      Debit: Field Salesman Van Cash / Cash in Transit (1115) [if CASH] OR Accounts Receivable (1130)
      Credit: Papad Sales Revenue (4100)
    Leg 2: Inventory Reduction & Cost of Goods Sold
      Debit: Cost of Goods Sold - Papad (5100)
      Credit: Finished Goods Inventory - Packaged SKUs (1240)
    """
    sale_id = str(sale_data.get("sale_id", "")).strip()
    bill_no = str(sale_data.get("bill_number", "")).strip()
    bill_total = to_decimal(sale_data.get("bill_total", 0) or 0)
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
        {
            "account_code": "4100",
            "credit_amount": round_money(bill_total),
            "notes": f"Revenue from bill {bill_no} to {sale_data.get('customer_name_snapshot', 'Customer')}",
        },
    ]

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

