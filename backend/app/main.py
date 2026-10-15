import os, io, secrets, string, hmac
from datetime import datetime, date, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.store import Store, now, as_float, is_active, AUTH_HEADERS
from app.security import (
    hash_password,
    verify_password,
    create_token,
    current_user,
    require_roles,
)
from app.services.sales_management_sheets import SALES_HEADERS


app = FastAPI(
    title="Kawad Swad Sales Management",
    version="1.0.0",
    description=(
        "Development sales management API. "
        "Protect this service and use a dedicated development spreadsheet."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        os.getenv("SALES_CORS_ORIGINS", "").split(",")
        if os.getenv("SALES_CORS_ORIGINS")
        else []
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def store():
    try:
        return Store()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Sales data store is unavailable: {e}",
        ) from e


# ============================================================
# REQUEST MODELS
# ============================================================

class OwnerSetupBody(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    user_id: str
    full_name: str
    username: str
    password: str = Field(min_length=12)
    role: str
    mobile: str = ""
    email: str = ""


class ProductIn(BaseModel):
    sku: str
    product_name: str
    category: str = "Papad"
    variant: str = "Plain"
    pack_weight_g: int = Field(gt=0)
    selling_unit: str = "packet"
    retail_pack_only: bool = True
    active: bool = True
    notes: str = ""


class CustomerIn(BaseModel):
    customer_type: str
    shop_name: str
    shopkeeper_name: str = ""
    mobile: str = ""
    alternate_mobile: str = ""
    address: str = ""
    locality_area: str = ""
    city: str = ""
    map_location: str = ""
    active: bool = True
    notes: str = ""


class SaleLine(BaseModel):
    product_id: str
    quantity: float = Field(gt=0)
    actual_unit_price: float = Field(ge=0)


class SaleIn(BaseModel):
    sales_type: str
    customer_id: str
    lines: list[SaleLine] = Field(min_length=1)
    payment_method: str
    payment_reference: str = ""
    delivery_status: str = "DELIVERED"
    discount_amount: float = Field(default=0, ge=0)
    notes: str = ""


class ExpenseIn(BaseModel):
    category: str
    amount: float = Field(gt=0)
    description: str
    receipt_link_or_file_ref: str = ""


class ApprovalIn(BaseModel):
    decision: str
    reason: str = ""


class StockIn(BaseModel):
    salesman_user_id: str
    product_id: str
    quantity: float = Field(gt=0)
    txn_type: str
    unit: str = "packet"
    pack_weight_g: int = 0
    notes: str = ""


class VisitIn(BaseModel):
    customer_id: str
    visit_outcome: str
    order_taken: bool = False
    follow_up_date: str = ""
    next_action: str = ""
    notes: str = ""


class ClosingIn(BaseModel):
    opening_cash: float = Field(ge=0)
    physical_cash_returned: float = Field(ge=0)
    notes: str = ""


# ============================================================
# INITIAL OWNER SETUP
#
# TEMPORARY DEVELOPMENT ENDPOINT.
# Remove this entire endpoint after creating and verifying
# the first Owner account.
# ============================================================

@app.post("/api/setup/owner", status_code=201)
def setup_initial_owner(
    body: OwnerSetupBody,
    x_owner_setup_secret: str = Header(
        default="",
        alias="X-Owner-Setup-Secret",
    ),
    s: Store = Depends(store),
):
    expected_secret = os.getenv("SALES_OWNER_SETUP_SECRET", "")

    # Fail closed if the setup secret is missing or too short.
    if (
        len(expected_secret) < 32
        or not hmac.compare_digest(
            x_owner_setup_secret,
            expected_secret,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Setup authorization failed.",
        )

    # Verify existing accounts before writing anything.
    try:
        auth_rows = s.auth_rows()
        user_rows = s.rows("Users")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to verify existing accounts. "
                "Check the development spreadsheet configuration."
            ),
        )

    # Never create another Owner through this endpoint.
    if any(
        str(row.get("role", "")).strip().upper() == "OWNER"
        for row in auth_rows
    ):
        raise HTTPException(
            status_code=409,
            detail="An Owner account already exists. Setup is closed.",
        )

    username = body.username.strip()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username cannot be empty.",
        )

    if any(
        str(row.get("username", "")).strip().lower() == username.lower()
        for row in auth_rows
    ):
        raise HTTPException(
            status_code=409,
            detail="Username already exists.",
        )

    user_id = "USR-OWNER-001"

    if any(
        str(row.get("user_id", "")) == user_id
        for row in user_rows
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Initial Owner user ID already exists. "
                "Manual review is required."
            ),
        )

    timestamp = now()

    try:
        # Create the Owner profile.
        s.append(
            "Users",
            {
                "user_id": user_id,
                "full_name": body.full_name.strip(),
                "role": "OWNER",
                "mobile": "",
                "email": "",
                "active": "TRUE",
                "created_at": timestamp,
                "notes": "Initial Owner account",
            },
        )

        # Store only the hashed password.
        s.append_auth(
            {
                "auth_id": "AUTH-OWNER-001",
                "user_id": user_id,
                "username": username,
                "password_hash": hash_password(body.password),
                "role": "OWNER",
                "active": "TRUE",
                "created_at": timestamp,
                "must_change_password": "TRUE",
            }
        )

    except Exception:
        # Google Sheets cannot roll back multiple writes atomically.
        # Inspect both worksheets before attempting a retry.
        raise HTTPException(
            status_code=503,
            detail=(
                "Owner setup did not complete successfully. "
                "Inspect Users and AuthUsers before retrying."
            ),
        )

    return {
        "message": "Initial Owner account created.",
        "user_id": user_id,
        "username": username,
        "role": "OWNER",
    }


# ============================================================
# HOME AND HEALTH
# ============================================================

@app.get("/")
def home():
    return {
        "service": "kawad-swad-sales-dev",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# AUTHENTICATION
# ============================================================

@app.post("/api/auth/login")
def login(body: LoginBody, s: Store = Depends(store)):
    try:
        rows = s.auth_rows()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    user = next(
        (
            row
            for row in rows
            if str(row.get("username", "")).strip().lower()
            == body.username.strip().lower()
            and is_active(row.get("active"))
        ),
        None,
    )

    if not user or not verify_password(
        body.password,
        str(user.get("password_hash", "")),
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    profile = next(
        (
            row
            for row in s.rows("Users")
            if str(row.get("user_id")) == str(user.get("user_id"))
        ),
        {},
    )

    if not profile or not is_active(profile.get("active")):
        raise HTTPException(
            status_code=403,
            detail="User profile is missing or inactive.",
        )

    safe = {
        "user_id": str(user["user_id"]),
        "full_name": str(profile.get("full_name") or user.get("username")),
        "role": str(user["role"]),
    }

    return {
        "access_token": create_token(safe),
        "token_type": "bearer",
        "user": safe,
    }


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {
        "user_id": user["sub"],
        "full_name": user["name"],
        "role": user["role"],
    }


# ============================================================
# USER MANAGEMENT
# ============================================================

@app.post("/api/users", status_code=201)
def create_user(
    body: UserCreate,
    actor=Depends(require_roles("OWNER")),
    s: Store = Depends(store),
):
    if body.role not in ("OWNER", "PA", "SALESMAN"):
        raise HTTPException(
            status_code=400,
            detail="Role must be OWNER, PA, or SALESMAN.",
        )

    if any(
        str(row.get("username", "")).strip().lower()
        == body.username.strip().lower()
        for row in s.auth_rows()
    ):
        raise HTTPException(
            status_code=409,
            detail="Username already exists.",
        )

    if any(
        str(row.get("user_id")) == body.user_id
        for row in s.rows("Users")
    ):
        raise HTTPException(
            status_code=409,
            detail="User ID already exists.",
        )

    created = now()

    s.append(
        "Users",
        {
            "user_id": body.user_id,
            "full_name": body.full_name,
            "role": body.role,
            "mobile": body.mobile,
            "email": body.email,
            "active": "TRUE",
            "created_at": created,
            "notes": "",
        },
    )

    s.append_auth(
        {
            "auth_id": s.next_id("Users"),
            "user_id": body.user_id,
            "username": body.username,
            "password_hash": hash_password(body.password),
            "role": body.role,
            "active": "TRUE",
            "created_at": created,
            "must_change_password": "TRUE",
        }
    )

    s.append_audit(actor, "CREATE", "User", body.user_id)

    return {
        "user_id": body.user_id,
        "username": body.username,
        "role": body.role,
    }


# ============================================================
# RECORD FILTERING
# ============================================================

def records(name, user, s):
    data = s.rows(name)

    if user.get("role") == "SALESMAN":
        if name == "Sales":
            data = [
                row
                for row in data
                if str(row.get("salesman_user_id")) == user["sub"]
                or str(row.get("entered_by_user_id")) == user["sub"]
            ]

        elif name in (
            "Expenses",
            "ShopVisits",
            "DailyClosing",
            "SalesmanStockLedger",
            "CashLedger",
        ):
            key = (
                "submitted_by_user_id"
                if name == "Expenses"
                else "salesman_user_id"
            )
            data = [
                row
                for row in data
                if str(row.get(key)) == user["sub"]
            ]

    return data


# ============================================================
# GOOGLE SHEETS SCHEMA STATUS
# ============================================================

@app.get("/api/sales/schema")
def schema_status(
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    result = {}

    for tab, headers in SALES_HEADERS.items():
        try:
            ws = s.ws(tab)
            actual = ws.row_values(1)

            result[tab] = {
                "status": (
                    "ok"
                    if tuple(actual[:len(headers)]) == headers
                    else "header_mismatch"
                ),
                "header_count": len(actual),
            }

        except Exception as e:
            result[tab] = {
                "status": "error",
                "error": str(e),
            }

    try:
        s.auth_rows()
        result["AuthUsers"] = {
            "status": "ok",
            "header_count": len(AUTH_HEADERS),
        }
    except Exception as e:
        result["AuthUsers"] = {
            "status": "error",
            "error": str(e),
        }

    return {"sheets": result}


# ============================================================
# PRODUCTS
# ============================================================

@app.get("/api/users")
def get_users(
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    return s.rows("Users")


@app.get("/api/products")
def get_products(
    q: str = "",
    limit: int = Query(200, ge=1, le=500),
    user=Depends(current_user),
    s: Store = Depends(store),
):
    rows = records("Products", user, s)

    if q:
        rows = [
            row
            for row in rows
            if q.lower() in " ".join(str(v) for v in row.values()).lower()
        ]

    return rows[:limit]


@app.post("/api/products", status_code=201)
def add_product(
    body: ProductIn,
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    if any(
        str(product.get("sku", "")).lower() == body.sku.lower()
        for product in s.rows("Products")
    ):
        raise HTTPException(
            status_code=409,
            detail="SKU already exists.",
        )

    row = {
        "product_id": s.next_id("Products"),
        **body.model_dump(),
    }

    row["retail_pack_only"] = (
        "TRUE" if body.retail_pack_only else "FALSE"
    )
    row["active"] = "TRUE" if body.active else "FALSE"

    s.append("Products", row)
    s.append_audit(user, "CREATE", "Product", row["product_id"])

    return row


@app.patch("/api/products/{product_id}")
def update_product(
    product_id: str,
    body: dict,
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    allowed = {
        "product_name",
        "category",
        "variant",
        "pack_weight_g",
        "selling_unit",
        "retail_pack_only",
        "active",
        "notes",
    }

    if set(body) - allowed:
        raise HTTPException(
            status_code=400,
            detail="Unsupported product fields.",
        )

    ws = s.ws("Products")
    headers = SALES_HEADERS["Products"]
    rows = ws.get_all_records()

    for idx, row in enumerate(rows, start=2):
        if str(row.get("product_id")) == product_id:
            for key, value in body.items():
                row[key] = value

            ws.update(
                f"A{idx}:J{idx}",
                [[row.get(header, "") for header in headers]],
            )

            s.append_audit(user, "UPDATE", "Product", product_id)
            return row

    raise HTTPException(
        status_code=404,
        detail="Product not found.",
    )


# ============================================================
# CUSTOMERS
# ============================================================

@app.get("/api/customers")
def get_customers(
    q: str = "",
    limit: int = Query(200, ge=1, le=500),
    user=Depends(current_user),
    s: Store = Depends(store),
):
    rows = records("Customers", user, s)

    if q:
        rows = [
            row
            for row in rows
            if q.lower() in " ".join(str(v) for v in row.values()).lower()
        ]

    return rows[:limit]


@app.post("/api/customers", status_code=201)
def add_customer(
    body: CustomerIn,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    row = {
        "customer_id": s.next_id("Customers"),
        **body.model_dump(),
    }

    row["active"] = "TRUE" if body.active else "FALSE"
    row["created_at"] = now()

    s.append("Customers", row)
    s.append_audit(user, "CREATE", "Customer", row["customer_id"])

    return row


# ============================================================
# SALES AND PAYMENTS
# ============================================================

@app.post("/api/sales", status_code=201)
def create_sale(
    body: SaleIn,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    if body.sales_type not in (
        "RETAIL",
        "RETAILER",
        "WHOLESALER",
        "DISTRIBUTOR",
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid sales type.",
        )

    customer = next(
        (
            row
            for row in s.rows("Customers")
            if str(row.get("customer_id")) == body.customer_id
            and is_active(row.get("active"))
        ),
        None,
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Active customer not found.",
        )

    products = {
        str(product.get("product_id")): product
        for product in s.rows("Products")
        if is_active(product.get("active"))
    }

    subtotal = 0
    lines = []

    for line in body.lines:
        product = products.get(line.product_id)

        if not product:
            raise HTTPException(
                status_code=400,
                detail=f"Product {line.product_id} not found or inactive.",
            )

        if (
            str(product.get("retail_pack_only")).lower()
            in ("true", "1", "yes")
            and str(product.get("selling_unit", "packet")).lower()
            not in ("packet", "pack")
        ):
            raise HTTPException(
                status_code=400,
                detail="Retail packs must be sold by packet.",
            )

        line_total = round(
            line.quantity * line.actual_unit_price,
            2,
        )
        subtotal += line_total

        weight = float(product.get("pack_weight_g") or 0)

        qualifying_kg = (
            line.quantity * weight / 1000
            if weight
            else line.quantity
        )

        lines.append(
            (line, product, line_total, qualifying_kg)
        )

    total = round(subtotal - body.discount_amount, 2)

    if total < 0:
        raise HTTPException(
            status_code=400,
            detail="Discount cannot exceed subtotal.",
        )

    if body.payment_method not in (
        "CASH",
        "UPI",
        "BANK_TRANSFER",
        "OTHER",
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported payment method.",
        )

    # This API records the full payment with the sale.
    sale_id = s.next_id("Sales")
    bill = (
        f"KS-{datetime.now().strftime('%Y%m%d')}-"
        f"{secrets.token_hex(3).upper()}"
    )
    stamp = now()
    payment_id = s.next_id("Payments")

    sale = {
        "sale_id": sale_id,
        "bill_number": bill,
        "sale_datetime": stamp,
        "sales_type": body.sales_type,
        "customer_id": body.customer_id,
        "customer_name_snapshot": customer.get("shop_name", ""),
        "entered_by_user_id": user["sub"],
        "salesman_user_id": (
            user["sub"] if user["role"] == "SALESMAN" else ""
        ),
        "delivery_status": body.delivery_status,
        "payment_status": "PAID",
        "subtotal": round(subtotal, 2),
        "discount_amount": body.discount_amount,
        "tax_amount": 0,
        "bill_total": total,
        "bill_status": "ISSUED",
        "created_at": stamp,
        "notes": body.notes,
    }

    s.append("Sales", sale)

    for line, product, line_total, qualifying_kg in lines:
        s.append(
            "SaleItems",
            {
                "sale_item_id": s.next_id("SaleItems"),
                "sale_id": sale_id,
                "product_id": line.product_id,
                "product_name_snapshot": product.get("product_name", ""),
                "sku_snapshot": product.get("sku", ""),
                "pack_weight_g": product.get("pack_weight_g", 0),
                "unit": product.get("selling_unit", "packet"),
                "quantity": line.quantity,
                "actual_unit_price": line.actual_unit_price,
                "discount_amount": 0,
                "line_total": line_total,
                "qualifying_kg": round(qualifying_kg, 3),
                "created_at": stamp,
                "notes": "",
            },
        )

    s.append(
        "Payments",
        {
            "payment_id": payment_id,
            "sale_id": sale_id,
            "payment_datetime": stamp,
            "payment_method": body.payment_method,
            "amount": total,
            "reference_number": body.payment_reference,
            "received_by_user_id": user["sub"],
            "payment_status": "RECEIVED",
            "notes": "",
        },
    )

    s.append_audit(user, "CREATE", "Sale", sale_id)

    return {
        "sale": sale,
        "payment_id": payment_id,
        "message": "Bill issued; full payment recorded.",
    }


@app.get("/api/sales")
def list_sales(
    limit: int = Query(200, ge=1, le=500),
    user=Depends(current_user),
    s: Store = Depends(store),
):
    return records("Sales", user, s)[:limit]


# ============================================================
# PDF INVOICE
# ============================================================

@app.get("/api/sales/{sale_id}/invoice")
def invoice(
    sale_id: str,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    sales = records("Sales", user, s)

    sale = next(
        (
            row
            for row in sales
            if str(row.get("sale_id")) == sale_id
            or str(row.get("bill_number")) == sale_id
        ),
        None,
    )

    if not sale:
        raise HTTPException(
            status_code=404,
            detail="Bill not found.",
        )

    items = [
        item
        for item in s.rows("SaleItems")
        if str(item.get("sale_id")) == str(sale["sale_id"])
    ]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(45, 800, "Kawad Swad Udhyog")

    c.setFont("Helvetica", 10)
    c.drawString(45, 780, "Nimar, Madhya Pradesh")
    c.drawString(45, 755, f"Bill: {sale.get('bill_number')}")
    c.drawString(45, 740, f"Date: {sale.get('sale_datetime')}")
    c.drawString(45, 725, f"Customer: {sale.get('customer_name_snapshot')}")

    y = 690

    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, y, "Product")
    c.drawString(300, y, "Qty")
    c.drawString(355, y, "Price")
    c.drawString(440, y, "Total")

    c.setFont("Helvetica", 9)
    y -= 18

    for item in items:
        if y < 80:
            c.showPage()
            y = 800
            c.setFont("Helvetica", 9)

        c.drawString(
            45,
            y,
            str(item.get("product_name_snapshot", ""))[:42],
        )
        c.drawRightString(
            330, y, str(item.get("quantity", ""))
        )
        c.drawRightString(
            410, y, str(item.get("actual_unit_price", ""))
        )
        c.drawRightString(
            510, y, str(item.get("line_total", ""))
        )

        y -= 16

    y -= 15

    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(
        510,
        y,
        f"Total: INR {sale.get('bill_total')}",
    )

    c.setFont("Helvetica", 8)
    c.drawString(
        45,
        40,
        "Payment recorded in full. Keep this bill for your records.",
    )

    c.save()
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{sale.get("bill_number", "invoice")}.pdf"'
            )
        },
    )


# ============================================================
# SALESMAN STOCK TRANSACTIONS
# ============================================================

@app.get("/api/stock/summary")
def stock_summary(
    user=Depends(current_user),
    s: Store = Depends(store),
):
    """Derived stock balances from the append-only stock ledger.

    COMPANY_RECEIPT and COMPANY_ADJUSTMENT increase company stock.
    ISSUED transfers company stock to a salesman; RETURNED transfers it back.
    SOLD reduces salesman stock. SALESMAN_ADJUSTMENT is a reviewed correction.
    """
    products = {str(p.get("product_id")): p for p in s.rows("Products")}
    users = {str(u.get("user_id")): u for u in s.rows("Users")}
    ledger = s.rows("SalesmanStockLedger")
    company = {}
    salesman = {}
    for row in ledger:
        pid = str(row.get("product_id", ""))
        qty = as_float(row.get("quantity"))
        typ = str(row.get("txn_type", "")).upper()
        sid = str(row.get("salesman_user_id", ""))
        if typ == "COMPANY_RECEIPT":
            company[pid] = company.get(pid, 0) + qty
        elif typ == "COMPANY_ADJUSTMENT":
            company[pid] = company.get(pid, 0) + qty
        elif typ == "ISSUED":
            company[pid] = company.get(pid, 0) - qty
            key = (sid, pid)
            salesman[key] = salesman.get(key, 0) + qty
        elif typ == "RETURNED":
            company[pid] = company.get(pid, 0) + qty
            key = (sid, pid)
            salesman[key] = salesman.get(key, 0) - qty
        elif typ == "SOLD":
            key = (sid, pid)
            salesman[key] = salesman.get(key, 0) - qty
        elif typ == "SALESMAN_ADJUSTMENT":
            key = (sid, pid)
            salesman[key] = salesman.get(key, 0) + qty
    company_rows = []
    for pid, product in products.items():
        company_rows.append({
            "product_id": pid, "sku": product.get("sku", ""),
            "product_name": product.get("product_name", ""),
            "pack_weight_g": product.get("pack_weight_g", ""),
            "company_quantity": round(company.get(pid, 0), 3),
        })
    salesman_rows = []
    for (sid, pid), qty in salesman.items():
        product = products.get(pid, {})
        salesman_rows.append({
            "salesman_user_id": sid,
            "salesman_name": users.get(sid, {}).get("full_name", sid),
            "product_id": pid, "sku": product.get("sku", ""),
            "product_name": product.get("product_name", ""),
            "quantity": round(qty, 3),
        })
    return {"company_stock": company_rows, "salesman_stock": salesman_rows}


@app.get("/api/stock/transactions")
def get_stock_transactions(
    limit: int = Query(300, ge=1, le=1000),
    user=Depends(current_user),
    s: Store = Depends(store),
):
    rows = s.rows("SalesmanStockLedger")
    rows.reverse()
    if user.get("role") == "SALESMAN":
        rows = [r for r in rows if str(r.get("salesman_user_id")) == str(user.get("sub"))]
    return rows[:limit]


@app.post("/api/stock/transactions", status_code=201)
def stock_txn(
    body: StockIn,
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    allowed = (
        "COMPANY_RECEIPT", "COMPANY_ADJUSTMENT", "ISSUED",
        "RETURNED", "SOLD", "SALESMAN_ADJUSTMENT",
    )
    txn_type = body.txn_type.strip().upper()
    if txn_type not in allowed:
        raise HTTPException(status_code=400, detail="Invalid stock transaction type.")
    products = {str(p.get("product_id")): p for p in s.rows("Products")}
    product = products.get(body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    users = {str(u.get("user_id")): u for u in s.rows("Users")}
    if txn_type in ("ISSUED", "RETURNED", "SOLD", "SALESMAN_ADJUSTMENT"):
        target = users.get(body.salesman_user_id)
        if not target or not is_active(target.get("active")):
            raise HTTPException(status_code=404, detail="Active salesman not found.")
        if str(target.get("role", "")).upper() != "SALESMAN":
            raise HTTPException(status_code=400, detail="Stock recipient must have SALESMAN role.")
    # Calculate current balances before recording a transfer.
    ledger = s.rows("SalesmanStockLedger")
    company_qty = 0.0
    salesman_qty = 0.0
    for r in ledger:
        if str(r.get("product_id")) != body.product_id:
            continue
        typ = str(r.get("txn_type", "")).upper()
        qty = as_float(r.get("quantity"))
        if typ in ("COMPANY_RECEIPT", "COMPANY_ADJUSTMENT"):
            company_qty += qty
        elif typ == "ISSUED":
            company_qty -= qty
            if str(r.get("salesman_user_id")) == body.salesman_user_id: salesman_qty += qty
        elif typ == "RETURNED":
            company_qty += qty
            if str(r.get("salesman_user_id")) == body.salesman_user_id: salesman_qty -= qty
        elif typ == "SOLD" and str(r.get("salesman_user_id")) == body.salesman_user_id:
            salesman_qty -= qty
        elif typ == "SALESMAN_ADJUSTMENT" and str(r.get("salesman_user_id")) == body.salesman_user_id:
            salesman_qty += qty
    if txn_type == "ISSUED" and body.quantity > company_qty:
        raise HTTPException(status_code=409, detail=f"Insufficient company stock. Available: {company_qty:g}.")
    if txn_type in ("RETURNED", "SOLD") and body.quantity > salesman_qty:
        raise HTTPException(status_code=409, detail=f"Insufficient salesman stock. Available: {salesman_qty:g}.")
    if txn_type == "COMPANY_ADJUSTMENT" and company_qty + body.quantity < 0:
        raise HTTPException(status_code=409, detail="Company adjustment cannot make stock negative.")
    if txn_type == "SALESMAN_ADJUSTMENT" and salesman_qty + body.quantity < 0:
        raise HTTPException(status_code=409, detail="Salesman adjustment cannot make stock negative.")
    row = {
        "stock_txn_id": s.next_id("SalesmanStockLedger"),
        "txn_datetime": now(),
        "salesman_user_id": body.salesman_user_id if txn_type not in ("COMPANY_RECEIPT", "COMPANY_ADJUSTMENT") else "",
        "product_id": body.product_id,
        "sku_snapshot": product.get("sku", ""),
        "txn_type": txn_type,
        "quantity": body.quantity,
        "unit": body.unit or product.get("selling_unit", "packet"),
        "pack_weight_g": body.pack_weight_g or product.get("pack_weight_g", 0),
        "related_sale_id": "",
        "issued_by_user_id": user["sub"] if txn_type == "ISSUED" else "",
        "received_by_user_id": user["sub"] if txn_type in ("COMPANY_RECEIPT", "RETURNED") else "",
        "confirmed_by_user_id": "",
        "reference_id": "",
        "notes": body.notes,
    }
    s.append("SalesmanStockLedger", row)
    s.append_audit(user, "CREATE", "StockTransaction", row["stock_txn_id"], f"Stock transaction: {txn_type}")
    return row


# ============================================================
# SHOP VISITS
# ============================================================

@app.post("/api/visits", status_code=201)
def add_visit(
    body: VisitIn,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    customer = next(
        (
            row
            for row in s.rows("Customers")
            if str(row.get("customer_id")) == body.customer_id
        ),
        None,
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    row = {
        "visit_id": s.next_id("ShopVisits"),
        "visit_datetime": now(),
        "salesman_user_id": user["sub"],
        "customer_id": body.customer_id,
        "shop_name_snapshot": customer.get("shop_name", ""),
        "visit_outcome": body.visit_outcome,
        "order_taken": "TRUE" if body.order_taken else "FALSE",
        "follow_up_date": body.follow_up_date,
        "next_action": body.next_action,
        "created_at": now(),
        "notes": body.notes,
    }

    s.append("ShopVisits", row)

    return row


# ============================================================
# EXPENSES AND APPROVAL
# ============================================================

@app.post("/api/expenses", status_code=201)
def add_expense(
    body: ExpenseIn,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    row = {
        "expense_id": s.next_id("Expenses"),
        "expense_datetime": now(),
        "submitted_by_user_id": user["sub"],
        "salesman_user_id": (
            user["sub"] if user["role"] == "SALESMAN" else ""
        ),
        "category": body.category,
        "amount": body.amount,
        "description": body.description,
        "receipt_link_or_file_ref": body.receipt_link_or_file_ref,
        "approval_status": "PENDING",
        "approved_by_user_id": "",
        "approval_datetime": "",
        "cash_reducing_expense": "FALSE",
        "related_closing_id": "",
        "notes": "",
    }

    s.append("Expenses", row)
    s.append_audit(user, "CREATE", "Expense", row["expense_id"])

    return row


@app.post("/api/expenses/{expense_id}/approval")
def approve_expense(
    expense_id: str,
    body: ApprovalIn,
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    if body.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail="Decision must be APPROVED or REJECTED.",
        )

    ws = s.ws("Expenses")
    headers = SALES_HEADERS["Expenses"]

    for idx, row in enumerate(ws.get_all_records(), start=2):
        if str(row.get("expense_id")) == expense_id:
            row["approval_status"] = body.decision
            row["approved_by_user_id"] = user["sub"]
            row["approval_datetime"] = now()

            row["cash_reducing_expense"] = (
                "TRUE"
                if body.decision == "APPROVED"
                and str(row.get("category", "")).upper() != "DIGITAL"
                else "FALSE"
            )

            ws.update(
                f"A{idx}:N{idx}",
                [[row.get(header, "") for header in headers]],
            )

            s.append_audit(
                user,
                "APPROVE" if body.decision == "APPROVED" else "REJECT",
                "Expense",
                expense_id,
                body.reason,
            )

            return row

    raise HTTPException(
        status_code=404,
        detail="Expense not found.",
    )


# ============================================================
# DAILY CASH CLOSING
# ============================================================

@app.post("/api/closing", status_code=201)
def daily_closing(
    body: ClosingIn,
    user=Depends(current_user),
    s: Store = Depends(store),
):
    sales = [
        row
        for row in records("Sales", user, s)
        if str(row.get("sale_datetime", ""))[:10]
        == date.today().isoformat()
        and str(row.get("payment_status")) == "PAID"
    ]

    payments = {
        str(payment.get("sale_id")): payment
        for payment in s.rows("Payments")
    }

    cash_collected = sum(
        as_float(payment.get("amount"))
        for payment in payments.values()
        if str(payment.get("payment_method")) == "CASH"
        and any(
            str(sale.get("sale_id")) == str(payment.get("sale_id"))
            for sale in sales
        )
    )

    expenses = sum(
        as_float(expense.get("amount"))
        for expense in s.rows("Expenses")
        if str(expense.get("submitted_by_user_id")) == user["sub"]
        and str(expense.get("approval_status")) == "APPROVED"
        and str(expense.get("cash_reducing_expense")).lower() == "true"
    )

    expected = round(
        body.opening_cash + cash_collected - expenses,
        2,
    )

    difference = round(
        body.physical_cash_returned - expected,
        2,
    )

    row = {
        "closing_id": s.next_id("DailyClosing"),
        "closing_date": date.today().isoformat(),
        "salesman_user_id": user["sub"],
        "opening_cash": body.opening_cash,
        "cash_collected": cash_collected,
        "approved_cash_expenses": expenses,
        "expected_cash_return": expected,
        "physical_cash_returned": body.physical_cash_returned,
        "cash_difference": difference,
        "opening_stock_reference": "",
        "stock_discrepancy_flag": "FALSE",
        "closing_status": "SUBMITTED",
        "submitted_at": now(),
        "reviewed_by_user_id": "",
        "reviewed_at": "",
        "notes": body.notes,
    }

    s.append("DailyClosing", row)

    return row


# ============================================================
# OWNER DASHBOARD
# ============================================================

@app.get("/api/dashboard")
def dashboard(
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    sales = s.rows("Sales")
    today = date.today().isoformat()

    daily = [
        row
        for row in sales
        if str(row.get("sale_datetime", ""))[:10] == today
        and str(row.get("bill_status")) == "ISSUED"
    ]

    monthly = [
        row
        for row in sales
        if str(row.get("sale_datetime", ""))[:7] == today[:7]
        and str(row.get("bill_status")) == "ISSUED"
    ]

    return {
        "date": today,
        "daily": {
            "bills": len(daily),
            "revenue": sum(
                as_float(row.get("bill_total"))
                for row in daily
            ),
        },
        "monthly": {
            "bills": len(monthly),
            "revenue": sum(
                as_float(row.get("bill_total"))
                for row in monthly
            ),
        },
        "pending_expenses": sum(
            1
            for row in s.rows("Expenses")
            if str(row.get("approval_status")) == "PENDING"
        ),
        "pending_closings": sum(
            1
            for row in s.rows("DailyClosing")
            if str(row.get("closing_status")) == "SUBMITTED"
        ),
    }


# ============================================================
# EXCEL EXPORTS
# ============================================================

@app.get("/api/exports/{sheet_name}.xlsx")
def export_xlsx(
    sheet_name: str,
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    if sheet_name not in SALES_HEADERS:
        raise HTTPException(
            status_code=404,
            detail="Unknown sheet.",
        )

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    headers = SALES_HEADERS[sheet_name]
    ws.append(list(headers))

    for row in s.rows(sheet_name):
        ws.append([row.get(header, "") for header in headers])

    for column in ws.columns:
        ws.column_dimensions[
            column[0].column_letter
        ].width = min(
            max(
                max(len(str(cell.value or "")) for cell in column) + 2,
                12,
            ),
            40,
        )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{sheet_name}.xlsx"'
            )
        },
    )


# ============================================================
# MONTHLY REPORT
# ============================================================

@app.get("/api/reports/monthly")
def monthly_report(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    user=Depends(require_roles("OWNER", "PA")),
    s: Store = Depends(store),
):
    sales = [
        row
        for row in s.rows("Sales")
        if str(row.get("sale_datetime", ""))[:7] == month
        and str(row.get("bill_status")) == "ISSUED"
    ]

    by_type = {}

    for row in sales:
        sales_type = str(row.get("sales_type", "UNKNOWN"))

        by_type.setdefault(
            sales_type,
            {
                "bills": 0,
                "revenue": 0,
            },
        )

        by_type[sales_type]["bills"] += 1
        by_type[sales_type]["revenue"] += as_float(
            row.get("bill_total")
        )

    return {
        "month": month,
        "bill_count": len(sales),
        "revenue": round(
            sum(as_float(row.get("bill_total")) for row in sales),
            2,
        ),
        "by_sales_type": by_type,
    }
