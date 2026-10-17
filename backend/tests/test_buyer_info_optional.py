#!/usr/bin/env python3
"""
Automated test suite verifying that buyer-provided information is optional
across customer creation, sales billing, invoice data, and persistence.
Mandatory internal business data (product, quantity, price, payments, stock) remains strictly enforced.
"""

import sys
import os
import unittest

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

if False and "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def post(self, path="", **kwargs):
                return lambda f: f
            def get(self, path="", **kwargs):
                return lambda f: f
            def put(self, path="", **kwargs):
                return lambda f: f
            def patch(self, path="", **kwargs):
                return lambda f: f
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None, headers=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers
        class status:
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_404_NOT_FOUND = 404
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default

    sys.modules["fastapi"] = MockFastAPIModule("fastapi")
    sys.modules["fastapi.security"] = types.ModuleType("security")
    sys.modules["fastapi.security"].HTTPBearer = lambda **kwargs: None
    sys.modules["fastapi.security"].HTTPAuthorizationCredentials = None
    sys.modules["jwt"] = types.ModuleType("jwt")
    sys.modules["jwt"].encode = lambda payload, secret, algorithm="HS256": "mock-jwt"
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "SALESMAN"}

    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    sys.modules["pydantic"].BaseModel = MockBaseModel
    sys.modules["pydantic"].Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db
from app.models import CustomerCreate, SaleCreate, SaleItemCreate
import app.routers.customers as customers_router
import app.routers.sales as sales_router


class TestBuyerInfoOptional(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reset in-memory database store
        db.memory_store["Customers"] = []
        db.memory_store["Sales"] = []
        db.memory_store["SaleItems"] = []
        db.memory_store["Payments"] = []
        db.memory_store["CashLedger"] = []
        db.memory_store["SalesmanStockLedger"] = [{
            "stock_txn_id": "STK-SEED",
            "salesman_user_id": "USR-000001",
            "product_id": "PRD-000001",
            "txn_type": "SALESMAN_POSITIVE_ADJUSTMENT",
            "quantity": 1000,
        }]
        db.memory_store["AuditLog"] = []
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-000001",
                "sku": "PAPAD-MOONG-500G",
                "product_name": "Moong Special Papad",
                "pack_weight_g": 500,
                "selling_unit": "PACKET",
            }
        ]
        self.mock_user = {
            "user_id": "USR-000001",
            "full_name": "Test Salesman",
            "role": "SALESMAN",
        }

    def tearDown(self):
        self.setUp()

    async def test_01_anonymous_retail_billing_no_customer_record(self):
        """Sale succeeds with completely empty/omitted customer details, creating a clean walk-in bill."""
        req = SaleCreate(
            sales_type="RETAIL",
            customer_id="",
            customer_name_snapshot="",
            customer_mobile="",
            customer_address="",
            customer_gstin="",
            payment_method="CASH",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=2,
                    actual_unit_price=60.0,
                    line_total=120.0,
                )
            ],
            subtotal=120.0,
            bill_total=120.0,
        )

        sale = await sales_router.create_sale(req, current_user=self.mock_user)

        self.assertEqual(sale.customer_id, "CUS-WALKIN")
        self.assertEqual(sale.customer_name_snapshot, "Walk-in Customer")
        self.assertEqual(sale.customer_mobile, "")
        self.assertEqual(sale.customer_gstin, "")
        self.assertEqual(sale.bill_total, 120.0)
        self.assertEqual(len(sale.items), 1)

        # Check Payments and CashLedger
        payments = db.get_records("Payments")
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0]["amount"], 120.0)
        cash = db.get_records("CashLedger")
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0]["amount"], 120.0)

        # Check stock deduction
        stock = [row for row in db.get_records("SalesmanStockLedger") if row.get("txn_type") == "SOLD_DELIVERY"]
        self.assertEqual(len(stock), 1)
        self.assertEqual(int(stock[0]["quantity"]), -2)

    async def test_02_retail_billing_with_customer_name_only(self):
        """Sale succeeds with customer name provided but no contact/address/GSTIN info."""
        req = SaleCreate(
            sales_type="RETAIL",
            customer_id="",
            customer_name_snapshot="Ramesh Bhai (Direct Retail)",
            customer_mobile="",
            customer_address="",
            payment_method="UPI",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=1,
                    actual_unit_price=55.0,
                )
            ],
            subtotal=55.0,
            bill_total=55.0,
        )

        sale = await sales_router.create_sale(req, current_user=self.mock_user)

        self.assertEqual(sale.customer_id, "CUS-WALKIN")
        self.assertEqual(sale.customer_name_snapshot, "Ramesh Bhai (Direct Retail)")
        self.assertEqual(sale.customer_mobile, "")
        # UPI payments record in Payments but NOT in physical CashLedger
        self.assertEqual(len(db.get_records("Payments")), 1)
        self.assertEqual(len(db.get_records("CashLedger")), 0)

    async def test_03_saved_customer_with_name_and_no_mobile(self):
        """Saved customer creation succeeds with only business/shop name; all contact info omitted."""
        req = CustomerCreate(
            shop_name="Mahadev Kirana Store",
            shopkeeper_name="",
            mobile="",
            alternate_mobile="",
            address="",
            locality_area="",
            city="",
            gstin="",
            notes="",
        )

        cust = await customers_router.create_customer(req, current_user=self.mock_user)

        self.assertTrue(cust.customer_id.startswith("CUS-"))
        self.assertEqual(cust.shop_name, "Mahadev Kirana Store")
        self.assertEqual(cust.mobile, "")
        self.assertEqual(cust.address, "")
        self.assertEqual(cust.city, "Bhilwara")
        self.assertEqual(cust.gstin, "")

    async def test_04_saved_customer_with_mobile_no_email_or_address(self):
        """Saved customer creation succeeds with mobile number while address and alternate mobile are omitted."""
        req = CustomerCreate(
            shop_name="Patidar Daily Needs",
            mobile="9826012345",
            address="",
        )

        cust = await customers_router.create_customer(req, current_user=self.mock_user)

        self.assertEqual(cust.shop_name, "Patidar Daily Needs")
        self.assertEqual(cust.mobile, "9826012345")
        self.assertEqual(cust.address, "")

    async def test_05_optional_fields_omitted_from_api_requests(self):
        """Customer and Sale endpoints gracefully handle completely omitted optional attributes."""
        # Customer creation with only shop_name attribute
        cust_req = CustomerCreate(shop_name="Sharma Traders")
        cust = await customers_router.create_customer(cust_req, current_user=self.mock_user)
        self.assertEqual(cust.shop_name, "Sharma Traders")
        self.assertEqual(cust.mobile, "")

        # Sale creation with minimal required payload
        sale_req = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=3, actual_unit_price=50.0)]
        )
        sale = await sales_router.create_sale(sale_req, current_user=self.mock_user)
        self.assertEqual(sale.customer_name_snapshot, "Walk-in Customer")
        self.assertEqual(sale.bill_total, 150.0)

    async def test_06_optional_fields_supplied_as_empty_strings(self):
        """Supplying whitespace or empty strings never stores string literals 'None' or 'undefined'."""
        cust_req = CustomerCreate(
            shop_name="Kisan Seva Kendra",
            shopkeeper_name="   ",
            mobile="",
            address="  ",
            notes="",
        )
        cust = await customers_router.create_customer(cust_req, current_user=self.mock_user)
        self.assertEqual(cust.shopkeeper_name, "")
        self.assertEqual(cust.mobile, "")
        self.assertEqual(cust.address, "")

        # Check raw stored database record
        raw_cust = db.get_records("Customers")[0]
        for key, val in raw_cust.items():
            self.assertNotEqual(val, "None", f"Field {key} stored literal string 'None'")
            self.assertNotEqual(val, "null", f"Field {key} stored literal string 'null'")
            self.assertNotEqual(val, "undefined", f"Field {key} stored literal string 'undefined'")

    async def test_07_invoice_generation_without_buyer_details(self):
        """Listing sales formats empty buyer data cleanly without placeholder strings."""
        req = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=1, actual_unit_price=60.0)]
        )
        await sales_router.create_sale(req, current_user=self.mock_user)

        all_sales = await sales_router.list_sales(current_user=self.mock_user)
        self.assertEqual(len(all_sales), 1)
        invoice = all_sales[0]
        self.assertEqual(invoice.customer_name_snapshot, "Walk-in Customer")
        self.assertEqual(invoice.customer_mobile, "")
        self.assertNotIn("None", invoice.customer_name_snapshot)

    async def test_08_backend_rejection_invalid_product(self):
        """Sale creation rejects missing or empty product_id with HTTP 422."""
        req = SaleCreate(
            items=[SaleItemCreate(product_id="", quantity=1, actual_unit_price=50.0)]
        )
        with self.assertRaises(sales_router.HTTPException) as ctx:
            await sales_router.create_sale(req, current_user=self.mock_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Product selection is mandatory", ctx.exception.detail)

    async def test_09_backend_rejection_invalid_quantity(self):
        """Sale creation rejects quantity <= 0 with HTTP 422."""
        req_zero = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=0, actual_unit_price=50.0)]
        )
        with self.assertRaises(sales_router.HTTPException) as ctx:
            await sales_router.create_sale(req_zero, current_user=self.mock_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Quantity must be greater than zero", ctx.exception.detail)

        req_neg = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=-3, actual_unit_price=50.0)]
        )
        with self.assertRaises(sales_router.HTTPException) as ctx2:
            await sales_router.create_sale(req_neg, current_user=self.mock_user)
        self.assertEqual(ctx2.exception.status_code, 422)

    async def test_10_backend_rejection_invalid_price(self):
        """Sale creation rejects negative prices with HTTP 422."""
        req = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=2, actual_unit_price=-15.0)]
        )
        with self.assertRaises(sales_router.HTTPException) as ctx:
            await sales_router.create_sale(req, current_user=self.mock_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Price cannot be negative", ctx.exception.detail)

    async def test_11_payment_and_discount_validation(self):
        """Financial calculations validate subtotal, discount, tax, and prevent invalid discounts."""
        # Discount exceeding subtotal
        req_over_discount = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=1, actual_unit_price=50.0)],
            subtotal=50.0,
            discount_amount=70.0,
        )
        with self.assertRaises(sales_router.HTTPException) as ctx:
            await sales_router.create_sale(req_over_discount, current_user=self.mock_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Discount cannot exceed subtotal", ctx.exception.detail)

        # Valid discount and tax calculation
        req_valid = SaleCreate(
            items=[SaleItemCreate(product_id="PRD-000001", quantity=2, actual_unit_price=100.0)],
            subtotal=200.0,
            discount_amount=20.0,
            tax_amount=10.0,
        )
        sale = await sales_router.create_sale(req_valid, current_user=self.mock_user)
        self.assertEqual(sale.subtotal, 200.0)
        self.assertEqual(sale.discount_amount, 20.0)
        self.assertEqual(sale.tax_amount, 10.0)
        self.assertEqual(sale.bill_total, 190.0)

    async def test_12_persistence_cleanliness_in_sheets_store(self):
        """Verify that records appended to database store contain only clean values."""
        req = SaleCreate(
            sales_type="RETAIL",
            customer_id=None,
            customer_name_snapshot="",
            customer_mobile=None,
            customer_gstin=None,
            notes=None,
            items=[SaleItemCreate(product_id="PRD-000001", quantity=1, actual_unit_price=50.0)],
        )
        await sales_router.create_sale(req, current_user=self.mock_user)

        raw_sales = db.get_records("Sales")
        self.assertEqual(len(raw_sales), 1)
        record = raw_sales[0]

        for k, v in record.items():
            self.assertIsNotNone(v, f"Field '{k}' was None in database store")
            self.assertNotEqual(v, "None", f"Field '{k}' was literal 'None' in database store")
            self.assertNotEqual(v, "null", f"Field '{k}' was literal 'null' in database store")
            self.assertNotEqual(v, "undefined", f"Field '{k}' was literal 'undefined' in database store")

        self.assertEqual(record["customer_id"], "CUS-WALKIN")
        self.assertEqual(record["customer_name_snapshot"], "Walk-in Customer")
        self.assertEqual(record["customer_mobile"], "")
        self.assertEqual(record["customer_gstin"], "")
        self.assertEqual(record["notes"], "")


if __name__ == "__main__":
    unittest.main()
