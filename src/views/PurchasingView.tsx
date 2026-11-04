import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Truck,
  Plus,
  RefreshCw,
  Search,
  FileText,
  DollarSign,
  PackageCheck,
  AlertCircle,
  Building,
  CheckCircle,
  XCircle,
  Receipt,
  ArrowRightLeft,
  X,
  CreditCard,
  Trash2,
  PackagePlus,
  Calculator,
  Building2,
  FileSpreadsheet,
} from 'lucide-react';
import {
  getSuppliers,
  createSupplier,
  getPurchaseOrders,
  createPurchaseOrder,
  cancelPurchaseOrder,
  getGoodsReceipts,
  createGoodsReceipt,
  getSupplierBills,
  createSupplierBill,
  getSupplierPayments,
  recordSupplierPayment,
  getSupplierReturns,
  createSupplierReturn,
  getPurchasingSummary,
} from '../services/api';
import type {
  Supplier,
  PurchaseOrder,
  GoodsReceipt,
  SupplierBill,
  SupplierPayment,
  SupplierReturn,
} from '../types';
import {
  FormLayout,
  FormSection,
  FormField,
  MoneyInput,
  QuantityInput,
  DateInput,
  CalculationPreview,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

export const RAW_MATERIAL_CATALOG = [
  { id: 'RM-WHOLE-MOONG-DAL', name: 'Whole Moong Dal (Raw Grain)', unit: 'kg', defaultRate: 85, gstRate: 0, category: 'Dal' },
  { id: 'RM-WHOLE-URAD-DAL', name: 'Whole Urad Dal (Raw Grain)', unit: 'kg', defaultRate: 98, gstRate: 0, category: 'Dal' },
  { id: 'RM-WHOLE-CHANA-DAL', name: 'Whole Chana Dal (Raw Grain)', unit: 'kg', defaultRate: 72, gstRate: 0, category: 'Dal' },
  { id: 'RM-SPICE-BLACK-PEPPER', name: 'Black Pepper (Kali Mirch)', unit: 'kg', defaultRate: 640, gstRate: 0.05, category: 'Spice' },
  { id: 'RM-SPICE-JEERA', name: 'Jeera (Cumin Seeds)', unit: 'kg', defaultRate: 320, gstRate: 0.05, category: 'Spice' },
  { id: 'RM-SPICE-RED-CHILLI', name: 'Red Chilli Powder', unit: 'kg', defaultRate: 280, gstRate: 0.05, category: 'Spice' },
  { id: 'RM-SPICE-HING', name: 'Hing (Compounded Asafoetida)', unit: 'kg', defaultRate: 1400, gstRate: 0.05, category: 'Spice' },
  { id: 'RM-ADD-PAPAD-KHAR', name: 'Saji Khar / Papad Khar', unit: 'kg', defaultRate: 65, gstRate: 0.05, category: 'Additive' },
  { id: 'RM-ADD-SALT', name: 'Iodized Salt', unit: 'kg', defaultRate: 18, gstRate: 0, category: 'Additive' },
  { id: 'RM-ADD-EDIBLE-OIL', name: 'Edible Cooking Oil', unit: 'kg', defaultRate: 135, gstRate: 0.05, category: 'Additive' },
  { id: 'RM-PKG-POUCH-200G', name: 'Printed Pouch Film (200g Moong)', unit: 'kg', defaultRate: 260, gstRate: 0.18, category: 'Packaging' },
  { id: 'RM-PKG-POUCH-400G', name: 'Printed Pouch Film (400g Moong)', unit: 'kg', defaultRate: 260, gstRate: 0.18, category: 'Packaging' },
  { id: 'RM-PKG-POUCH-500G', name: 'Printed Pouch Film (500g Chana)', unit: 'kg', defaultRate: 260, gstRate: 0.18, category: 'Packaging' },
  { id: 'RM-PKG-MASTER-CARTON', name: '5-Ply Master Corrugated Boxes', unit: 'packet', defaultRate: 42, gstRate: 0.18, category: 'Packaging' },
];

type PurchasingTab = 'suppliers' | 'orders' | 'receipts' | 'bills' | 'payments' | 'returns';

export const PurchasingView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PurchasingTab>('orders');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Summary Metrics
  const [summary, setSummary] = useState({
    total_suppliers: 0,
    open_pos: 0,
    unpaid_bills: 0,
    total_payables: 0,
  });

  // Tab Data States
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [receipts, setReceipts] = useState<GoodsReceipt[]>([]);
  const [bills, setBills] = useState<SupplierBill[]>([]);
  const [payments, setPayments] = useState<SupplierPayment[]>([]);
  const [returns, setReturns] = useState<SupplierReturn[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  // Modals
  const [showSupplierModal, setShowSupplierModal] = useState(false);
  const [showOrderModal, setShowOrderModal] = useState(false);
  const [showReceiptModal, setShowReceiptModal] = useState(false);
  const [showBillModal, setShowBillModal] = useState(false);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [showReturnModal, setShowReturnModal] = useState(false);

  // Form states
  const [newSupplier, setNewSupplier] = useState({
    supplier_name: '',
    contact_person: '',
    mobile: '',
    email: '',
    gstin: '',
    address: '',
    city: 'Bikaner',
    payment_terms_days: 15,
  });

  const [newOrder, setNewOrder] = useState({
    supplier_id: '',
    order_date: new Date().toISOString().split('T')[0],
    expected_delivery_date: '',
    notes: '',
    items: [
      {
        material_id: 'RM-WHOLE-MOONG-DAL',
        material_name: 'Whole Moong Dal (Raw Grain)',
        ordered_quantity: 1000,
        unit: 'kg',
        unit_price: 85,
        tax_rate: 0,
      },
    ],
  });

  const [newReceipt, setNewReceipt] = useState({
    supplier_id: '',
    po_id: '',
    receipt_date: new Date().toISOString().split('T')[0],
    vendor_delivery_challan: '',
    vehicle_number: '',
    notes: '',
    items: [
      {
        po_item_id: '',
        material_id: 'RM-WHOLE-MOONG-DAL',
        material_name: 'Whole Moong Dal (Raw Grain)',
        delivered_quantity: 1000,
        accepted_quantity: 1000,
        rejected_quantity: 0,
        unit: 'kg',
        unit_price: 85,
        rejection_reason: '',
      },
    ],
  });

  const [newBill, setNewBill] = useState({
    supplier_id: '',
    po_id: '',
    receipt_id: '',
    bill_number: '',
    bill_date: new Date().toISOString().split('T')[0],
    due_date: '',
    taxable_amount: 0,
    gst_rate_preset: 0, // 0, 5, 12, 18
    cgst_amount: 0,
    sgst_amount: 0,
    freight_amount: 0,
    total_amount: 0,
    notes: '',
  });

  const [newPayment, setNewPayment] = useState({
    supplier_id: '',
    bill_id: '',
    payment_date: new Date().toISOString().split('T')[0],
    payment_mode: 'BANK' as 'CASH' | 'BANK' | 'UPI' | 'NEFT',
    amount: 0,
    reference_no: '',
    notes: '',
  });

  const [newReturn, setNewReturn] = useState({
    supplier_id: '',
    return_date: new Date().toISOString().split('T')[0],
    reason: 'Damaged packaging / moisture exceeding limit',
    notes: '',
    items: [
      {
        material_id: 'RM-WHOLE-MOONG-DAL',
        material_name: 'Whole Moong Dal (Raw Grain)',
        returned_quantity: 50,
        unit: 'kg',
        unit_price: 85,
      },
    ],
  });

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sum, suppList] = await Promise.all([
        getPurchasingSummary().catch(() => ({ total_suppliers: 0, open_pos: 0, unpaid_bills: 0, total_payables: 0 })),
        getSuppliers().catch(() => []),
      ]);
      setSummary(sum);
      setSuppliers(suppList);

      if (activeTab === 'orders') {
        const poList = await getPurchaseOrders().catch(() => []);
        setOrders(poList);
      } else if (activeTab === 'receipts') {
        const grnList = await getGoodsReceipts().catch(() => []);
        setReceipts(grnList);
      } else if (activeTab === 'bills') {
        const billList = await getSupplierBills().catch(() => []);
        setBills(billList);
      } else if (activeTab === 'payments') {
        const payList = await getSupplierPayments().catch(() => []);
        setPayments(payList);
      } else if (activeTab === 'returns') {
        const retList = await getSupplierReturns().catch(() => []);
        setReturns(retList);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreateSupplier = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createSupplier(newSupplier);
      setSuccessMsg(`Supplier '${newSupplier.supplier_name}' registered successfully.`);
      setShowSupplierModal(false);
      setNewSupplier({
        supplier_name: '',
        contact_person: '',
        mobile: '',
        email: '',
        gstin: '',
        address: '',
        city: 'Bikaner',
        payment_terms_days: 15,
      });
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createPurchaseOrder(newOrder);
      setSuccessMsg('Purchase Order generated successfully.');
      setShowOrderModal(false);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCancelOrder = async (orderId: string) => {
    const reason = prompt('Reason for cancelling Purchase Order:');
    if (!reason) return;
    try {
      await cancelPurchaseOrder(orderId, reason);
      setSuccessMsg(`Purchase Order ${orderId} cancelled.`);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateReceipt = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createGoodsReceipt(newReceipt);
      setSuccessMsg('Goods Receipt Note (GRN) created. Stock ledger & accounting posted.');
      setShowReceiptModal(false);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateBill = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createSupplierBill(newBill);
      setSuccessMsg(`Supplier Bill ${newBill.bill_number} booked in accounts payable.`);
      setShowBillModal(false);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreatePayment = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await recordSupplierPayment(newPayment);
      setSuccessMsg(`Payment of ₹${newPayment.amount.toLocaleString()} recorded and ledger updated.`);
      setShowPaymentModal(false);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateReturn = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createSupplierReturn(newReturn);
      setSuccessMsg('Supplier Return (Debit Note) issued. Raw material stock deducted.');
      setShowReturnModal(false);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Truck className="text-emerald-700" size={26} />
            Purchasing & Procurement Management
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
            End-to-end procurement: vendor registry, purchase orders, goods receipts (GRN), bills & payments.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadData()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
          {activeTab === 'suppliers' && (
            <button
              onClick={() => setShowSupplierModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> New Supplier
            </button>
          )}
          {activeTab === 'orders' && (
            <button
              onClick={() => setShowOrderModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> Create PO
            </button>
          )}
          {activeTab === 'receipts' && (
            <button
              onClick={() => setShowReceiptModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> Inward GRN
            </button>
          )}
          {activeTab === 'bills' && (
            <button
              onClick={() => setShowBillModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> Book Bill
            </button>
          )}
          {activeTab === 'payments' && (
            <button
              onClick={() => setShowPaymentModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> Record Payment
            </button>
          )}
          {activeTab === 'returns' && (
            <button
              onClick={() => setShowReturnModal(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-amber-700 text-white hover:bg-amber-800 shadow-xs transition-colors"
            >
              <Plus size={14} /> Return to Supplier
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            <X size={14} />
          </button>
        </div>
      )}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle size={16} className="shrink-0" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-600 hover:text-emerald-800">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Active Suppliers</span>
            <Building className="text-slate-400" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-slate-900">{summary.total_suppliers}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Open Orders</span>
            <FileText className="text-blue-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-blue-700">{summary.open_pos}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Unpaid Bills</span>
            <Receipt className="text-amber-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-amber-700">{summary.unpaid_bills}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Accounts Payable</span>
            <DollarSign className="text-red-500" size={18} />
          </div>
          <div className="mt-2 text-xl font-bold text-red-700">
            ₹{Number(summary.total_payables || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="border-b border-slate-200 flex items-center gap-2 overflow-x-auto">
        {[
          { key: 'orders', label: 'Purchase Orders', icon: <FileText size={15} /> },
          { key: 'receipts', label: 'Goods Receipts (GRN)', icon: <PackageCheck size={15} /> },
          { key: 'bills', label: 'Supplier Bills', icon: <Receipt size={15} /> },
          { key: 'payments', label: 'Payments', icon: <CreditCard size={15} /> },
          { key: 'returns', label: 'Supplier Returns', icon: <ArrowRightLeft size={15} /> },
          { key: 'suppliers', label: 'Suppliers Master', icon: <Building size={15} /> },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as PurchasingTab)}
            className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 whitespace-nowrap transition-colors ${
              activeTab === tab.key
                ? 'border-emerald-700 text-emerald-800 bg-emerald-50/50'
                : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Contents */}
      {/* 1. Purchase Orders */}
      {activeTab === 'orders' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between gap-4">
            <h2 className="text-sm font-bold text-slate-900">Purchase Orders Registry</h2>
            <div className="relative max-w-xs w-full">
              <Search className="absolute left-2.5 top-2.5 text-slate-400" size={14} />
              <input
                type="text"
                placeholder="Search PO#, Supplier..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
              />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">PO Number</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Total Amount</th>
                  <th className="px-4 py-3 text-center">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {orders
                  .filter(
                    (o) =>
                      !searchQuery ||
                      o.po_number?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                      o.supplier_name?.toLowerCase().includes(searchQuery.toLowerCase())
                  )
                  .map((o) => (
                    <tr key={o.po_id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-semibold text-slate-900">{o.po_number}</td>
                      <td className="px-4 py-3">{o.order_date}</td>
                      <td className="px-4 py-3">{o.supplier_name}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                            o.status === 'CONFIRMED'
                              ? 'bg-blue-100 text-blue-800'
                              : o.status === 'FULFILLED'
                              ? 'bg-emerald-100 text-emerald-800'
                              : o.status === 'CANCELLED'
                              ? 'bg-red-100 text-red-800'
                              : 'bg-slate-100 text-slate-800'
                          }`}
                        >
                          {o.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-900">
                        ₹{Number(o.total_amount || 0).toLocaleString('en-IN')}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {o.status !== 'CANCELLED' && o.status !== 'FULFILLED' && (
                          <button
                            onClick={() => handleCancelOrder(o.po_id)}
                            className="text-2xs font-semibold text-red-600 hover:text-red-800 hover:underline"
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No purchase orders recorded yet. Click &quot;Create PO&quot; to issue your first order.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 2. Goods Receipts (GRN) */}
      {activeTab === 'receipts' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Goods Receipts (GRN) & Inward Batches</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">GRN #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Challan / Vehicle</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Items Inward</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {receipts.map((r) => (
                  <tr key={r.grn_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{r.grn_number}</td>
                    <td className="px-4 py-3">{r.receipt_date}</td>
                    <td className="px-4 py-3">{r.supplier_name}</td>
                    <td className="px-4 py-3">
                      {r.vendor_delivery_challan || '-'} / {r.vehicle_number || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-block px-2 py-0.5 rounded-full text-2xs font-bold bg-emerald-100 text-emerald-800">
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {r.items?.length || 0} line(s)
                    </td>
                  </tr>
                ))}
                {receipts.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No Goods Receipts found. Click &quot;Inward GRN&quot; to intake raw materials.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 3. Supplier Bills */}
      {activeTab === 'bills' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Supplier Invoices & Bills</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Bill #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3 text-right">Total Amount</th>
                  <th className="px-4 py-3 text-right">Paid</th>
                  <th className="px-4 py-3 text-right">Balance</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {bills.map((b) => (
                  <tr key={b.bill_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{b.bill_number}</td>
                    <td className="px-4 py-3">{b.bill_date}</td>
                    <td className="px-4 py-3">{b.supplier_name}</td>
                    <td className="px-4 py-3 text-right font-medium">₹{Number(b.total_amount || 0).toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-emerald-700">₹{Number(b.paid_amount || 0).toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-bold text-red-700">
                      ₹{(Number(b.total_amount || 0) - Number(b.paid_amount || 0)).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-2xs font-bold ${
                          b.payment_status === 'PAID'
                            ? 'bg-emerald-100 text-emerald-800'
                            : b.payment_status === 'PARTIALLY_PAID'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {b.payment_status}
                      </span>
                    </td>
                  </tr>
                ))}
                {bills.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-slate-400">
                      No supplier bills recorded yet. Click &quot;Book Bill&quot; to enter vendor invoices.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 4. Payments */}
      {activeTab === 'payments' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Supplier Payment Disbursements</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Payment #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3">Ref No</th>
                  <th className="px-4 py-3 text-right">Amount Paid</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {payments.map((p) => (
                  <tr key={p.payment_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{p.payment_number}</td>
                    <td className="px-4 py-3">{p.payment_date}</td>
                    <td className="px-4 py-3">{p.supplier_name}</td>
                    <td className="px-4 py-3 font-medium text-slate-700">{p.payment_mode}</td>
                    <td className="px-4 py-3">{p.reference_no || '-'}</td>
                    <td className="px-4 py-3 text-right font-bold text-emerald-800">
                      ₹{Number(p.amount || 0).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {payments.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No payments recorded yet. Click &quot;Record Payment&quot; to disburse funds.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 5. Returns */}
      {activeTab === 'returns' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Supplier Returns (Debit Notes)</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Return #</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Reason</th>
                  <th className="px-4 py-3 text-right">Total Debit Value</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {returns.map((ret) => (
                  <tr key={ret.return_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{ret.return_number}</td>
                    <td className="px-4 py-3">{ret.return_date}</td>
                    <td className="px-4 py-3">{ret.supplier_name}</td>
                    <td className="px-4 py-3">{ret.reason}</td>
                    <td className="px-4 py-3 text-right font-medium text-slate-900">
                      ₹{Number(ret.total_amount || 0).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-block px-2 py-0.5 rounded-full text-2xs font-bold bg-amber-100 text-amber-800">
                        {ret.status}
                      </span>
                    </td>
                  </tr>
                ))}
                {returns.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-400">
                      No supplier returns recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 6. Suppliers Master */}
      {activeTab === 'suppliers' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Registered Raw Material Vendors</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 text-slate-700 uppercase font-semibold border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Code</th>
                  <th className="px-4 py-3">Vendor / Firm</th>
                  <th className="px-4 py-3">Contact</th>
                  <th className="px-4 py-3">City</th>
                  <th className="px-4 py-3">GSTIN</th>
                  <th className="px-4 py-3 text-center">Credit Terms</th>
                  <th className="px-4 py-3 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {suppliers.map((s) => (
                  <tr key={s.supplier_id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-semibold text-slate-900">{s.supplier_code}</td>
                    <td className="px-4 py-3 font-medium text-slate-900">{s.supplier_name}</td>
                    <td className="px-4 py-3">{s.mobile || s.contact_person || '-'}</td>
                    <td className="px-4 py-3">{s.city || '-'}</td>
                    <td className="px-4 py-3 font-mono text-2xs">{s.gstin || 'UNREGISTERED'}</td>
                    <td className="px-4 py-3 text-center">{s.payment_terms_days} days</td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-block px-2 py-0.5 rounded-full text-2xs font-bold bg-emerald-100 text-emerald-800">
                        ACTIVE
                      </span>
                    </td>
                  </tr>
                ))}
                {suppliers.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-slate-400">
                      No suppliers registered. Click &quot;New Supplier&quot; to add vendors.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 1. Modal: Register New Supplier */}
      {showSupplierModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
          <FormLayout
            title="Register Raw Material Supplier"
            subtitle="Add a certified grain mandi trader, spice merchant, or packaging vendor"
            icon={<Building2 size={20} />}
            onSubmit={handleCreateSupplier}
            onCancel={() => setShowSupplierModal(false)}
            maxWidth="lg"
            actions={
              <FormActions>
                <CancelButton onClick={() => setShowSupplierModal(false)} />
                <SaveButton label="Save Supplier" icon={<Building2 size={15} />} />
              </FormActions>
            }
          >
            <FormSection title="Vendor & Mandi Details">
              <FormField label="Supplier / Firm Name" required>
                <input
                  type="text"
                  required
                  value={newSupplier.supplier_name}
                  onChange={(e) => setNewSupplier({ ...newSupplier, supplier_name: e.target.value })}
                  placeholder="e.g. Marwar Agro Traders / Bikaner Mandi"
                  className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                />
              </FormField>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField label="Contact Person">
                  <input
                    type="text"
                    value={newSupplier.contact_person}
                    onChange={(e) => setNewSupplier({ ...newSupplier, contact_person: e.target.value })}
                    placeholder="Owner / Proprietor name"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                  />
                </FormField>
                <FormField label="Mobile Number" required helpText="10-digit primary mobile">
                  <input
                    type="tel"
                    required
                    maxLength={10}
                    value={newSupplier.mobile}
                    onChange={(e) => setNewSupplier({ ...newSupplier, mobile: e.target.value.replace(/\D/g, '') })}
                    placeholder="98XXXXXXXX"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                  />
                </FormField>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField label="Mandi / City">
                  <input
                    type="text"
                    value={newSupplier.city}
                    onChange={(e) => setNewSupplier({ ...newSupplier, city: e.target.value })}
                    placeholder="Bikaner"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                  />
                </FormField>
                <FormField label="Credit Terms (Days)">
                  <QuantityInput
                    unit="days"
                    min={0}
                    max={120}
                    value={newSupplier.payment_terms_days}
                    onChange={(val) => setNewSupplier({ ...newSupplier, payment_terms_days: val })}
                  />
                </FormField>
              </div>

              <FormField label="GSTIN (15 Digits)" helpText="Format: 08AAAAA0000A1Z5 (Leave blank if unregistered mandi dealer)">
                <input
                  type="text"
                  maxLength={15}
                  value={newSupplier.gstin}
                  onChange={(e) => setNewSupplier({ ...newSupplier, gstin: e.target.value.toUpperCase() })}
                  placeholder="08AAAAA0000A1Z5"
                  className="w-full px-3.5 py-2.5 text-sm font-mono uppercase border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                />
              </FormField>

              <FormField label="Address / Mandi Shop Reference">
                <textarea
                  rows={2}
                  value={newSupplier.address}
                  onChange={(e) => setNewSupplier({ ...newSupplier, address: e.target.value })}
                  placeholder="Shop #14, Grain Market, Krishi Upaj Mandi, Bikaner"
                  className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                />
              </FormField>
            </FormSection>
          </FormLayout>
        </div>
      )}

      {/* 2. Modal: Multi-Item Purchase Order */}
      {showOrderModal && (() => {
        const poSubtotal = newOrder.items.reduce(
          (sum, itm) => sum + (Number(itm.ordered_quantity) || 0) * (Number(itm.unit_price) || 0),
          0
        );
        const poGstTotal = newOrder.items.reduce((sum, itm) => {
          const base = (Number(itm.ordered_quantity) || 0) * (Number(itm.unit_price) || 0);
          return sum + base * (Number(itm.tax_rate) || 0);
        }, 0);
        const poGrandTotal = Math.round((poSubtotal + poGstTotal) * 100) / 100;
        const totalItemsQty = newOrder.items.reduce((sum, itm) => sum + (Number(itm.ordered_quantity) || 0), 0);

        return (
          <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
            <FormLayout
              title="Issue Purchase Order (PO)"
              subtitle="Generate a binding procurement order with agreed mandi rates and GST terms"
              icon={<Truck size={20} />}
              onSubmit={handleCreateOrder}
              onCancel={() => setShowOrderModal(false)}
              maxWidth="3xl"
              actions={
                <FormActions>
                  <CancelButton onClick={() => setShowOrderModal(false)} />
                  <SaveButton label="Issue Purchase Order" icon={<Truck size={15} />} />
                </FormActions>
              }
            >
              <FormSection title="Supplier & Schedule">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="sm:col-span-2">
                    <FormField label="Select Raw Material Supplier" required>
                      <select
                        required
                        value={newOrder.supplier_id}
                        onChange={(e) => setNewOrder({ ...newOrder, supplier_id: e.target.value })}
                        className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 focus:border-transparent outline-none"
                      >
                        <option value="">-- Choose Vendor / Mandi Trader --</option>
                        {suppliers.map((s) => (
                          <option key={s.supplier_id} value={s.supplier_id}>
                            {s.supplier_name} ({s.city}) — Credit: {s.payment_terms_days}d
                          </option>
                        ))}
                      </select>
                    </FormField>
                  </div>
                  <div>
                    <FormField label="Expected Delivery Date">
                      <DateInput
                        value={newOrder.expected_delivery_date}
                        onChange={(val) => setNewOrder({ ...newOrder, expected_delivery_date: val })}
                      />
                    </FormField>
                  </div>
                </div>
              </FormSection>

              <FormSection
                title="Procurement Line Items"
                description="Specify raw materials, quantities, agreed purchase rates, and GST tax treatment"
              >
                <div className="space-y-3">
                  {newOrder.items.map((item, idx) => {
                    const lineSubtotal = (Number(item.ordered_quantity) || 0) * (Number(item.unit_price) || 0);
                    const lineTax = lineSubtotal * (Number(item.tax_rate) || 0);
                    const lineTotal = Math.round((lineSubtotal + lineTax) * 100) / 100;

                    return (
                      <div
                        key={idx}
                        className="p-3.5 sm:p-4 rounded-xl border border-slate-200 bg-slate-50/70 space-y-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-1.5">
                            <span className="w-5 h-5 rounded-full bg-emerald-800 text-white inline-flex items-center justify-center text-2xs font-mono">
                              {idx + 1}
                            </span>
                            Item Line
                          </span>
                          {newOrder.items.length > 1 && (
                            <button
                              type="button"
                              onClick={() => {
                                setNewOrder({
                                  ...newOrder,
                                  items: newOrder.items.filter((_, i) => i !== idx),
                                });
                              }}
                              className="text-xs text-rose-600 hover:text-rose-700 font-semibold inline-flex items-center gap-1 px-2 py-0.5 rounded-md hover:bg-rose-50"
                            >
                              <Trash2 size={13} /> Remove
                            </button>
                          )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
                          <div className="sm:col-span-5">
                            <label className="block text-2xs font-bold uppercase text-slate-600 mb-1">
                              Raw Material *
                            </label>
                            <select
                              value={item.material_id}
                              onChange={(e) => {
                                const selectedCat = RAW_MATERIAL_CATALOG.find((m) => m.id === e.target.value);
                                const updated = [...newOrder.items];
                                updated[idx] = {
                                  ...updated[idx],
                                  material_id: e.target.value,
                                  material_name: selectedCat?.name || e.target.value,
                                  unit: selectedCat?.unit || 'kg',
                                  unit_price: selectedCat?.defaultRate || updated[idx].unit_price,
                                  tax_rate: selectedCat?.gstRate ?? updated[idx].tax_rate,
                                };
                                setNewOrder({ ...newOrder, items: updated });
                              }}
                              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                            >
                              <optgroup label="Whole Grain Dals (Direct Mandi)">
                                {RAW_MATERIAL_CATALOG.filter((m) => m.category === 'Dal').map((m) => (
                                  <option key={m.id} value={m.id}>
                                    🌾 {m.name}
                                  </option>
                                ))}
                              </optgroup>
                              <optgroup label="Spices & Seasonings">
                                {RAW_MATERIAL_CATALOG.filter((m) => m.category === 'Spice').map((m) => (
                                  <option key={m.id} value={m.id}>
                                    🌶️ {m.name}
                                  </option>
                                ))}
                              </optgroup>
                              <optgroup label="Food Additives & Processing">
                                {RAW_MATERIAL_CATALOG.filter((m) => m.category === 'Additive').map((m) => (
                                  <option key={m.id} value={m.id}>
                                    🧪 {m.name}
                                  </option>
                                ))}
                              </optgroup>
                              <optgroup label="Packaging Materials & Cartons">
                                {RAW_MATERIAL_CATALOG.filter((m) => m.category === 'Packaging').map((m) => (
                                  <option key={m.id} value={m.id}>
                                    📦 {m.name}
                                  </option>
                                ))}
                              </optgroup>
                            </select>
                          </div>

                          <div className="sm:col-span-3">
                            <label className="block text-2xs font-bold uppercase text-slate-600 mb-1">
                              Quantity ({item.unit}) *
                            </label>
                            <input
                              type="number"
                              min="0.1"
                              step="any"
                              required
                              value={item.ordered_quantity}
                              onChange={(e) => {
                                const updated = [...newOrder.items];
                                updated[idx].ordered_quantity = Number(e.target.value);
                                setNewOrder({ ...newOrder, items: updated });
                              }}
                              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-emerald-600 outline-none font-semibold text-slate-800"
                            />
                          </div>

                          <div className="sm:col-span-2">
                            <label className="block text-2xs font-bold uppercase text-slate-600 mb-1">
                              Rate (₹/{item.unit}) *
                            </label>
                            <input
                              type="number"
                              min="0.01"
                              step="0.01"
                              required
                              value={item.unit_price}
                              onChange={(e) => {
                                const updated = [...newOrder.items];
                                updated[idx].unit_price = Number(e.target.value);
                                setNewOrder({ ...newOrder, items: updated });
                              }}
                              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-emerald-600 outline-none font-semibold text-slate-800"
                            />
                          </div>

                          <div className="sm:col-span-2">
                            <label className="block text-2xs font-bold uppercase text-slate-600 mb-1">
                              GST Rate
                            </label>
                            <select
                              value={item.tax_rate}
                              onChange={(e) => {
                                const updated = [...newOrder.items];
                                updated[idx].tax_rate = Number(e.target.value);
                                setNewOrder({ ...newOrder, items: updated });
                              }}
                              className="w-full px-2 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-emerald-600 outline-none font-semibold text-slate-700"
                            >
                              <option value={0}>0% (Exempt Grain)</option>
                              <option value={0.05}>5% (Spices / Oil)</option>
                              <option value={0.12}>12%</option>
                              <option value={0.18}>18% (Packaging)</option>
                            </select>
                          </div>
                        </div>

                        <div className="flex items-center justify-between pt-1 border-t border-slate-200/80 text-xs">
                          <span className="text-slate-500">
                            Base: ₹{lineSubtotal.toLocaleString(undefined, { minimumFractionDigits: 2 })} + GST: ₹{lineTax.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </span>
                          <span className="font-bold text-slate-900">
                            Line Total: ₹{lineTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                      </div>
                    );
                  })}

                  <button
                    type="button"
                    onClick={() => {
                      setNewOrder({
                        ...newOrder,
                        items: [
                          ...newOrder.items,
                          {
                            material_id: 'RM-WHOLE-URAD-DAL',
                            material_name: 'Whole Urad Dal (Raw Grain)',
                            ordered_quantity: 500,
                            unit: 'kg',
                            unit_price: 98,
                            tax_rate: 0,
                          },
                        ],
                      });
                    }}
                    className="w-full py-2.5 border-2 border-dashed border-emerald-400/80 rounded-xl text-emerald-800 font-semibold text-xs hover:bg-emerald-50 transition-colors flex items-center justify-center gap-1.5"
                  >
                    <Plus size={14} /> Add Another Raw Material Line
                  </button>
                </div>
              </FormSection>

              <CalculationPreview
                title="Purchase Order Financial Summary"
                items={[
                  { label: 'Total Ordered Quantity', value: `${totalItemsQty.toLocaleString()} units / kg` },
                  { label: 'Taxable Subtotal', value: `₹${poSubtotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                  { label: 'GST Tax Amount', value: `₹${poGstTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                  {
                    label: 'Grand Order Commitment',
                    value: `₹${poGrandTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                    isHighlight: true,
                  },
                ]}
              />

              <FormSection title="Purchase Order Notes" defaultOpen={false}>
                <FormField label="Terms & Delivery Instructions">
                  <textarea
                    rows={2}
                    value={newOrder.notes}
                    onChange={(e) => setNewOrder({ ...newOrder, notes: e.target.value })}
                    placeholder="e.g. Moisture must be <= 11%, delivery via transport bilty to factory shed"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                  />
                </FormField>
              </FormSection>
            </FormLayout>
          </div>
        );
      })()}

      {/* 3. Modal: Inward Goods Receipt Note (GRN) */}
      {showReceiptModal && (() => {
        const totalDelivered = newReceipt.items.reduce((s, itm) => s + (Number(itm.delivered_quantity) || 0), 0);
        const totalAccepted = newReceipt.items.reduce((s, itm) => s + (Number(itm.accepted_quantity) || 0), 0);
        const totalRejected = newReceipt.items.reduce((s, itm) => s + (Number(itm.rejected_quantity) || 0), 0);
        const totalAcceptedValue = newReceipt.items.reduce(
          (s, itm) => s + (Number(itm.accepted_quantity) || 0) * (Number(itm.unit_price) || 0),
          0
        );

        return (
          <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
            <FormLayout
              title="Inward Goods Receipt Note (GRN)"
              subtitle="Inspect incoming grain & materials, record accepted stock, and update raw material inventory"
              icon={<PackageCheck size={20} />}
              onSubmit={handleCreateReceipt}
              onCancel={() => setShowReceiptModal(false)}
              maxWidth="3xl"
              actions={
                <FormActions>
                  <CancelButton onClick={() => setShowReceiptModal(false)} />
                  <SaveButton label="Confirm Inward GRN" icon={<PackageCheck size={15} />} />
                </FormActions>
              }
            >
              <FormSection title="Receiving Reference & PO Link">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField label="Link to Purchase Order (Optional)">
                    <select
                      value={newReceipt.po_id}
                      onChange={(e) => {
                        const poId = e.target.value;
                        const matchPo = orders.find((o) => o.po_id === poId);
                        if (matchPo) {
                          setNewReceipt({
                            ...newReceipt,
                            po_id: poId,
                            supplier_id: matchPo.supplier_id,
                            items: (matchPo.items || []).map((pi) => ({
                              po_item_id: pi.po_item_id || '',
                              material_id: (pi as any).material_id || pi.raw_material_id || 'RM-WHOLE-MOONG-DAL',
                              material_name: pi.material_name,
                              delivered_quantity: pi.ordered_quantity,
                              accepted_quantity: pi.ordered_quantity,
                              rejected_quantity: 0,
                              unit: pi.unit,
                              unit_price: pi.unit_price,
                              rejection_reason: '',
                            })),
                          });
                        } else {
                          setNewReceipt({ ...newReceipt, po_id: '' });
                        }
                      }}
                      className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                    >
                      <option value="">-- Direct Mandi Purchase (No PO) --</option>
                      {orders
                        .filter((o) => o.status !== 'CANCELLED')
                        .map((o) => (
                          <option key={o.po_id} value={o.po_id}>
                            {o.po_number} — {o.supplier_name} (₹{Number(o.total_amount || 0).toLocaleString()})
                          </option>
                        ))}
                    </select>
                  </FormField>

                  <FormField label="Supplier / Firm Name *" required>
                    <select
                      required
                      value={newReceipt.supplier_id}
                      onChange={(e) => setNewReceipt({ ...newReceipt, supplier_id: e.target.value })}
                      className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                    >
                      <option value="">-- Choose Vendor --</option>
                      {suppliers.map((s) => (
                        <option key={s.supplier_id} value={s.supplier_id}>
                          {s.supplier_name} ({s.city})
                        </option>
                      ))}
                    </select>
                  </FormField>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <FormField label="Inward Date *" required>
                    <DateInput
                      value={newReceipt.receipt_date}
                      onChange={(val) => setNewReceipt({ ...newReceipt, receipt_date: val })}
                    />
                  </FormField>
                  <FormField label="Vendor Challan / Bilty #" required helpText="Transport consignment reference">
                    <input
                      type="text"
                      required
                      value={newReceipt.vendor_delivery_challan}
                      onChange={(e) => setNewReceipt({ ...newReceipt, vendor_delivery_challan: e.target.value })}
                      placeholder="e.g. BL-98412 / Mandi Memo"
                      className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                    />
                  </FormField>
                  <FormField label="Truck / Vehicle Number">
                    <input
                      type="text"
                      value={newReceipt.vehicle_number}
                      onChange={(e) => setNewReceipt({ ...newReceipt, vehicle_number: e.target.value.toUpperCase() })}
                      placeholder="RJ-07-GA-1234"
                      className="w-full px-3.5 py-2.5 text-sm uppercase font-mono border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                    />
                  </FormField>
                </div>
              </FormSection>

              <FormSection
                title="Physical Inspection & Quantity Reconciliation"
                description="Weighbridge / physical scale counts: accepted stock goes directly to Factory Raw Material Ledger"
              >
                <div className="space-y-4">
                  {newReceipt.items.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-sm text-slate-900">
                          {item.material_name}
                        </span>
                        <span className="text-xs px-2.5 py-1 rounded-md bg-emerald-100 text-emerald-800 font-bold">
                          ₹{Number(item.unit_price).toFixed(2)} / {item.unit}
                        </span>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <FormField label={`Delivered Quantity (${item.unit}) *`}>
                          <input
                            type="number"
                            min="0.1"
                            step="any"
                            required
                            value={item.delivered_quantity}
                            onChange={(e) => {
                              const deliv = Number(e.target.value);
                              const updated = [...newReceipt.items];
                              updated[idx].delivered_quantity = deliv;
                              updated[idx].accepted_quantity = Math.max(0, deliv - updated[idx].rejected_quantity);
                              setNewReceipt({ ...newReceipt, items: updated });
                            }}
                            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white font-semibold"
                          />
                        </FormField>

                        <FormField label={`Accepted Quantity (${item.unit}) *`}>
                          <input
                            type="number"
                            min="0"
                            step="any"
                            required
                            value={item.accepted_quantity}
                            onChange={(e) => {
                              const acc = Number(e.target.value);
                              const updated = [...newReceipt.items];
                              updated[idx].accepted_quantity = acc;
                              updated[idx].rejected_quantity = Math.max(0, updated[idx].delivered_quantity - acc);
                              setNewReceipt({ ...newReceipt, items: updated });
                            }}
                            className="w-full px-3 py-2 text-sm border border-emerald-500 rounded-lg bg-white font-bold text-emerald-800"
                          />
                        </FormField>

                        <FormField label={`Rejected Quantity (${item.unit})`}>
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={item.rejected_quantity}
                            onChange={(e) => {
                              const rej = Number(e.target.value);
                              const updated = [...newReceipt.items];
                              updated[idx].rejected_quantity = rej;
                              updated[idx].accepted_quantity = Math.max(0, updated[idx].delivered_quantity - rej);
                              setNewReceipt({ ...newReceipt, items: updated });
                            }}
                            className="w-full px-3 py-2 text-sm border border-rose-400 rounded-lg bg-white font-bold text-rose-800"
                          />
                        </FormField>
                      </div>

                      {item.rejected_quantity > 0 && (
                        <FormField label="Rejection Justification *" required>
                          <input
                            type="text"
                            required
                            value={item.rejection_reason}
                            onChange={(e) => {
                              const updated = [...newReceipt.items];
                              updated[idx].rejection_reason = e.target.value;
                              setNewReceipt({ ...newReceipt, items: updated });
                            }}
                            placeholder="e.g. Moisture > 14%, foreign particles, or damaged bags"
                            className="w-full px-3 py-1.5 text-xs border border-rose-300 rounded-lg bg-rose-50/50"
                          />
                        </FormField>
                      )}
                    </div>
                  ))}
                </div>
              </FormSection>

              <CalculationPreview
                title="Inward Inventory Accounting Impact"
                items={[
                  { label: 'Total Inward Delivered', value: `${totalDelivered.toLocaleString()} kg` },
                  { label: 'Accepted to Stock Ledger', value: `${totalAccepted.toLocaleString()} kg` },
                  { label: 'Rejected at Gate', value: `${totalRejected.toLocaleString()} kg` },
                  {
                    label: 'Accepted Stock Valuation',
                    value: `₹${totalAcceptedValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                    isHighlight: true,
                  },
                ]}
              />
            </FormLayout>
          </div>
        );
      })()}

      {/* 4. Modal: Book Supplier Bill / Invoice */}
      {showBillModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
          <FormLayout
            title="Book Supplier Invoice / Bill"
            subtitle="Record vendor bill in accounts payable with automated GST calculation and freight capitalization"
            icon={<Receipt size={20} />}
            onSubmit={handleCreateBill}
            onCancel={() => setShowBillModal(false)}
            maxWidth="xl"
            actions={
              <FormActions>
                <CancelButton onClick={() => setShowBillModal(false)} />
                <SaveButton label="Book Supplier Bill" icon={<Receipt size={15} />} />
              </FormActions>
            }
          >
            <FormSection title="Supplier & Invoice Details">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField label="Supplier *" required>
                  <select
                    required
                    value={newBill.supplier_id}
                    onChange={(e) => setNewBill({ ...newBill, supplier_id: e.target.value })}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                  >
                    <option value="">-- Choose Supplier --</option>
                    {suppliers.map((s) => (
                      <option key={s.supplier_id} value={s.supplier_id}>
                        {s.supplier_name}
                      </option>
                    ))}
                  </select>
                </FormField>

                <FormField label="Supplier Invoice # *" required>
                  <input
                    type="text"
                    required
                    value={newBill.bill_number}
                    onChange={(e) => setNewBill({ ...newBill, bill_number: e.target.value })}
                    placeholder="e.g. INV-2026-081"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                  />
                </FormField>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField label="Invoice Date *" required>
                  <DateInput
                    value={newBill.bill_date}
                    onChange={(val) => setNewBill({ ...newBill, bill_date: val })}
                  />
                </FormField>
                <FormField label="Payment Due Date">
                  <DateInput
                    value={newBill.due_date}
                    onChange={(val) => setNewBill({ ...newBill, due_date: val })}
                  />
                </FormField>
              </div>
            </FormSection>

            <FormSection title="Amounts & GST Breakdown">
              <FormField label="Taxable Subtotal (₹) *" required>
                <MoneyInput
                  value={newBill.taxable_amount}
                  onChange={(amt) => {
                    const gstRate = newBill.gst_rate_preset / 100;
                    const halfGst = (amt * gstRate) / 2;
                    const tot = Math.round((amt + (halfGst * 2) + newBill.freight_amount) * 100) / 100;
                    setNewBill({
                      ...newBill,
                      taxable_amount: amt,
                      cgst_amount: halfGst,
                      sgst_amount: halfGst,
                      total_amount: tot,
                    });
                  }}
                />
              </FormField>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                    GST Rate Preset
                  </label>
                  <select
                    value={newBill.gst_rate_preset}
                    onChange={(e) => {
                      const rate = Number(e.target.value);
                      const halfGst = (newBill.taxable_amount * (rate / 100)) / 2;
                      const tot = Math.round((newBill.taxable_amount + (halfGst * 2) + newBill.freight_amount) * 100) / 100;
                      setNewBill({
                        ...newBill,
                        gst_rate_preset: rate,
                        cgst_amount: halfGst,
                        sgst_amount: halfGst,
                        total_amount: tot,
                      });
                    }}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                  >
                    <option value={0}>0% (Exempt Grains)</option>
                    <option value={5}>5% (Spices / 2.5% each)</option>
                    <option value={12}>12% (6% each)</option>
                    <option value={18}>18% (Packaging / 9% each)</option>
                  </select>
                </div>

                <FormField label="CGST (₹)">
                  <MoneyInput
                    value={newBill.cgst_amount}
                    onChange={(cgst) => {
                      const tot = Math.round((newBill.taxable_amount + cgst + newBill.sgst_amount + newBill.freight_amount) * 100) / 100;
                      setNewBill({ ...newBill, cgst_amount: cgst, total_amount: tot });
                    }}
                  />
                </FormField>

                <FormField label="SGST (₹)">
                  <MoneyInput
                    value={newBill.sgst_amount}
                    onChange={(sgst) => {
                      const tot = Math.round((newBill.taxable_amount + newBill.cgst_amount + sgst + newBill.freight_amount) * 100) / 100;
                      setNewBill({ ...newBill, sgst_amount: sgst, total_amount: tot });
                    }}
                  />
                </FormField>
              </div>

              <FormField label="Freight & Unloading Expenses (₹)">
                <MoneyInput
                  value={newBill.freight_amount}
                  onChange={(fr) => {
                    const tot = Math.round((newBill.taxable_amount + newBill.cgst_amount + newBill.sgst_amount + fr) * 100) / 100;
                    setNewBill({ ...newBill, freight_amount: fr, total_amount: tot });
                  }}
                />
              </FormField>
            </FormSection>

            <CalculationPreview
              title="Payable Invoice Summary"
              items={[
                { label: 'Taxable Goods Subtotal', value: `₹${newBill.taxable_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                { label: 'Input Tax Credit (CGST + SGST)', value: `₹${(newBill.cgst_amount + newBill.sgst_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                { label: 'Freight Charges', value: `₹${newBill.freight_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                {
                  label: 'Total Accounts Payable',
                  value: `₹${newBill.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                  isHighlight: true,
                },
              ]}
            />
          </FormLayout>
        </div>
      )}

      {/* 5. Modal: Record Supplier Payment */}
      {showPaymentModal && (() => {
        const vendorBills = bills.filter((b) => b.supplier_id === newPayment.supplier_id && b.status !== 'PAID');
        const selectedBill = bills.find((b) => b.bill_id === newPayment.bill_id);
        const billAmount = Number(selectedBill?.total_amount || 0);
        const remainingAfter = Math.max(0, billAmount - (Number(newPayment.amount) || 0));

        return (
          <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
            <FormLayout
              title="Record Supplier Payment"
              subtitle="Disburse funds via Bank Transfer, UPI, or Factory Cash and reconcile accounts payable"
              icon={<CreditCard size={20} />}
              onSubmit={handleCreatePayment}
              onCancel={() => setShowPaymentModal(false)}
              maxWidth="lg"
              actions={
                <FormActions>
                  <CancelButton onClick={() => setShowPaymentModal(false)} />
                  <SaveButton label="Disburse & Post Payment" icon={<CreditCard size={15} />} />
                </FormActions>
              }
            >
              <FormSection title="Payee & Bill Reference">
                <FormField label="Select Raw Material Supplier *" required>
                  <select
                    required
                    value={newPayment.supplier_id}
                    onChange={(e) => setNewPayment({ ...newPayment, supplier_id: e.target.value, bill_id: '' })}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                  >
                    <option value="">-- Choose Vendor --</option>
                    {suppliers.map((s) => (
                      <option key={s.supplier_id} value={s.supplier_id}>
                        {s.supplier_name} ({s.city})
                      </option>
                    ))}
                  </select>
                </FormField>

                {newPayment.supplier_id && vendorBills.length > 0 && (
                  <FormField label="Link to Unpaid Bill">
                    <select
                      value={newPayment.bill_id}
                      onChange={(e) => {
                        const bId = e.target.value;
                        const match = vendorBills.find((b) => b.bill_id === bId);
                        setNewPayment({
                          ...newPayment,
                          bill_id: bId,
                          amount: match ? Number(match.total_amount) : newPayment.amount,
                        });
                      }}
                      className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                    >
                      <option value="">-- On Account Payment (General) --</option>
                      {vendorBills.map((b) => (
                        <option key={b.bill_id} value={b.bill_id}>
                          Bill #{b.bill_number} ({b.bill_date}) — Total: ₹{Number(b.total_amount).toLocaleString()}
                        </option>
                      ))}
                    </select>
                  </FormField>
                )}
              </FormSection>

              <FormSection title="Payment Details">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField label="Disbursement Date *" required>
                    <DateInput
                      value={newPayment.payment_date}
                      onChange={(val) => setNewPayment({ ...newPayment, payment_date: val })}
                    />
                  </FormField>
                  <FormField label="Payment Channel *" required>
                    <select
                      value={newPayment.payment_mode}
                      onChange={(e) => setNewPayment({ ...newPayment, payment_mode: e.target.value as any })}
                      className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none font-semibold"
                    >
                      <option value="BANK">🏦 Bank NEFT / RTGS</option>
                      <option value="UPI">📱 UPI Direct</option>
                      <option value="CASH">💵 Factory Petty Cash</option>
                      <option value="NEFT">📄 Cheque Clearing</option>
                    </select>
                  </FormField>
                </div>

                <FormField label="Disbursement Amount (₹) *" required>
                  <div className="space-y-1.5">
                    <MoneyInput
                      value={newPayment.amount}
                      onChange={(val) => setNewPayment({ ...newPayment, amount: val })}
                    />
                    {selectedBill && (
                      <button
                        type="button"
                        onClick={() => setNewPayment({ ...newPayment, amount: billAmount })}
                        className="text-xs text-emerald-700 hover:text-emerald-800 font-semibold underline"
                      >
                        Click to fill full bill balance (₹{billAmount.toLocaleString()})
                      </button>
                    )}
                  </div>
                </FormField>

                <FormField label="Bank Reference / UTR Number *" required helpText="Unique transaction identifier from bank/UPI">
                  <input
                    type="text"
                    required
                    value={newPayment.reference_no}
                    onChange={(e) => setNewPayment({ ...newPayment, reference_no: e.target.value })}
                    placeholder="e.g. UTR-202611-891234 / UPI Ref"
                    className="w-full px-3.5 py-2.5 text-sm font-mono border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                  />
                </FormField>
              </FormSection>

              {selectedBill && (
                <CalculationPreview
                  title="Payment Settlement Reconciliation"
                  items={[
                    { label: 'Original Bill Payable', value: `₹${billAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                    { label: 'This Payment Amount', value: `₹${Number(newPayment.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                    {
                      label: 'Remaining Unpaid Balance',
                      value: `₹${remainingAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                      isHighlight: remainingAfter === 0,
                    },
                  ]}
                />
              )}
            </FormLayout>
          </div>
        );
      })()}

      {/* 6. Modal: Supplier Return (Debit Note) */}
      {showReturnModal && (() => {
        const retQty = Number(newReturn.items[0]?.returned_quantity || 0);
        const retRate = Number(newReturn.items[0]?.unit_price || 0);
        const debitTotal = Math.round(retQty * retRate * 100) / 100;

        return (
          <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
            <FormLayout
              title="Issue Supplier Return (Debit Note)"
              subtitle="Return defective raw materials to vendor, generate a debit note, and deduct stock"
              icon={<ArrowRightLeft size={20} />}
              onSubmit={handleCreateReturn}
              onCancel={() => setShowReturnModal(false)}
              maxWidth="lg"
              actions={
                <FormActions>
                  <CancelButton onClick={() => setShowReturnModal(false)} />
                  <SaveButton label="Issue Debit Note & Return" icon={<ArrowRightLeft size={15} />} variant="danger" />
                </FormActions>
              }
            >
              <FormSection title="Vendor & Material Selection">
                <FormField label="Supplier *" required>
                  <select
                    required
                    value={newReturn.supplier_id}
                    onChange={(e) => setNewReturn({ ...newReturn, supplier_id: e.target.value })}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                  >
                    <option value="">-- Choose Vendor --</option>
                    {suppliers.map((s) => (
                      <option key={s.supplier_id} value={s.supplier_id}>
                        {s.supplier_name} ({s.city})
                      </option>
                    ))}
                  </select>
                </FormField>

                <FormField label="Raw Material to Return *" required>
                  <select
                    value={newReturn.items[0].material_id}
                    onChange={(e) => {
                      const selectedCat = RAW_MATERIAL_CATALOG.find((m) => m.id === e.target.value);
                      const updated = [...newReturn.items];
                      updated[0] = {
                        ...updated[0],
                        material_id: e.target.value,
                        material_name: selectedCat?.name || e.target.value,
                        unit_price: selectedCat?.defaultRate || updated[0].unit_price,
                      };
                      setNewReturn({ ...newReturn, items: updated });
                    }}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none"
                  >
                    {RAW_MATERIAL_CATALOG.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </FormField>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField label="Quantity to Return (kg) *" required>
                    <QuantityInput
                      unit="kg"
                      value={newReturn.items[0].returned_quantity}
                      onChange={(val) => {
                        const updated = [...newReturn.items];
                        updated[0].returned_quantity = val;
                        setNewReturn({ ...newReturn, items: updated });
                      }}
                    />
                  </FormField>

                  <FormField label="Credit Agreed Rate (₹/kg) *" required>
                    <MoneyInput
                      value={newReturn.items[0].unit_price}
                      onChange={(val) => {
                        const updated = [...newReturn.items];
                        updated[0].unit_price = val;
                        setNewReturn({ ...newReturn, items: updated });
                      }}
                    />
                  </FormField>
                </div>
              </FormSection>

              <FormSection title="Rejection Reason & Documentation">
                <FormField label="Primary Cause of Return *" required>
                  <select
                    value={newReturn.reason}
                    onChange={(e) => setNewReturn({ ...newReturn, reason: e.target.value })}
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl bg-white focus:ring-2 focus:ring-emerald-600 outline-none font-medium"
                  >
                    <option value="Damaged packaging / moisture exceeding limit">Damaged packaging / moisture exceeding limit</option>
                    <option value="High foreign matter / stone / dirt contamination">High foreign matter / stone / dirt contamination</option>
                    <option value="Insect infestation / pest damage">Insect infestation / pest damage</option>
                    <option value="Wrong grain grade or variety delivered">Wrong grain grade or variety delivered</option>
                    <option value="Purchase rate / invoice discrepancy">Purchase rate / invoice discrepancy</option>
                  </select>
                </FormField>

                <FormField label="Inspector Observations">
                  <textarea
                    rows={2}
                    value={newReturn.notes}
                    onChange={(e) => setNewReturn({ ...newReturn, notes: e.target.value })}
                    placeholder="Provide specific QC lab report or visual inspection findings"
                    className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-600 outline-none"
                  />
                </FormField>
              </FormSection>

              <CalculationPreview
                title="Debit Note Financial Impact"
                items={[
                  { label: 'Returned Grain Mass', value: `${retQty.toLocaleString()} kg` },
                  { label: 'Agreed Mandi Rate', value: `₹${retRate.toFixed(2)}/kg` },
                  {
                    label: 'Total Debit Note Issued',
                    value: `₹${debitTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                    isHighlight: true,
                  },
                ]}
              />
            </FormLayout>
          </div>
        );
      })()}
    </div>
  );
};
