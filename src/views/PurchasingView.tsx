import React, { useState, useEffect, useCallback } from 'react';
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
      { material_id: 'RM-MUNG-WHOLE', material_name: 'Mung Whole Dal (Raw Grain)', ordered_quantity: 1000, unit: 'kg', unit_price: 85, gst_rate: 0 },
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
      { material_id: 'RM-MUNG-WHOLE', material_name: 'Mung Whole Dal (Raw Grain)', received_quantity: 1000, unit: 'kg', unit_price: 85, storage_location: 'MAIN_GRAIN_SILO', batch_reference: `LOT-RM-${Date.now().toString().slice(-4)}` },
    ],
  });

  const [newBill, setNewBill] = useState({
    supplier_id: '',
    bill_number: '',
    bill_date: new Date().toISOString().split('T')[0],
    due_date: '',
    taxable_amount: 0,
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
      { material_id: 'RM-MUNG-WHOLE', material_name: 'Mung Whole Dal', returned_quantity: 50, unit: 'kg', unit_price: 85 },
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

      {/* Modal: New Supplier */}
      {showSupplierModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Register New Raw Material Supplier</h3>
              <button onClick={() => setShowSupplierModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateSupplier} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Supplier / Firm Name *</label>
                <input
                  type="text"
                  required
                  value={newSupplier.supplier_name}
                  onChange={(e) => setNewSupplier({ ...newSupplier, supplier_name: e.target.value })}
                  placeholder="e.g. Marwar Agro Traders"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Contact Person</label>
                  <input
                    type="text"
                    value={newSupplier.contact_person}
                    onChange={(e) => setNewSupplier({ ...newSupplier, contact_person: e.target.value })}
                    placeholder="Owner name"
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Mobile Number *</label>
                  <input
                    type="tel"
                    required
                    value={newSupplier.mobile}
                    onChange={(e) => setNewSupplier({ ...newSupplier, mobile: e.target.value })}
                    placeholder="98XXXXXXXX"
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">City</label>
                  <input
                    type="text"
                    value={newSupplier.city}
                    onChange={(e) => setNewSupplier({ ...newSupplier, city: e.target.value })}
                    placeholder="Bikaner"
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Credit Days</label>
                  <input
                    type="number"
                    min="0"
                    value={newSupplier.payment_terms_days}
                    onChange={(e) => setNewSupplier({ ...newSupplier, payment_terms_days: Number(e.target.value) })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">GSTIN</label>
                <input
                  type="text"
                  value={newSupplier.gstin}
                  onChange={(e) => setNewSupplier({ ...newSupplier, gstin: e.target.value })}
                  placeholder="08AAAAA0000A1Z5"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg font-mono focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Address / Mandi Location</label>
                <textarea
                  rows={2}
                  value={newSupplier.address}
                  onChange={(e) => setNewSupplier({ ...newSupplier, address: e.target.value })}
                  placeholder="Krishi Mandi, Bikaner"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowSupplierModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white font-semibold hover:bg-emerald-800"
                >
                  Save Supplier
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: New Purchase Order */}
      {showOrderModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Issue Purchase Order</h3>
              <button onClick={() => setShowOrderModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateOrder} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Select Supplier *</label>
                <select
                  required
                  value={newOrder.supplier_id}
                  onChange={(e) => setNewOrder({ ...newOrder, supplier_id: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                >
                  <option value="">-- Choose Supplier --</option>
                  {suppliers.map((s) => (
                    <option key={s.supplier_id} value={s.supplier_id}>
                      {s.supplier_name} ({s.city})
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">PO Date</label>
                  <input
                    type="date"
                    required
                    value={newOrder.order_date}
                    onChange={(e) => setNewOrder({ ...newOrder, order_date: e.target.value })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Expected Delivery</label>
                  <input
                    type="date"
                    value={newOrder.expected_delivery_date}
                    onChange={(e) => setNewOrder({ ...newOrder, expected_delivery_date: e.target.value })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              {/* Item row */}
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                <div className="font-semibold text-slate-700">Order Item</div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="col-span-2">
                    <label className="block text-2xs text-slate-500 mb-0.5">Raw Material</label>
                    <select
                      value={newOrder.items[0].material_id}
                      onChange={(e) => {
                        const mId = e.target.value;
                        const name = mId === 'RM-MUNG-WHOLE' ? 'Mung Whole Dal' : 'Urad Whole Dal';
                        const updated = [...newOrder.items];
                        updated[0].material_id = mId;
                        updated[0].material_name = name;
                        setNewOrder({ ...newOrder, items: updated });
                      }}
                      className="w-full px-2 py-1 text-xs border border-slate-300 rounded-lg"
                    >
                      <option value="RM-MUNG-WHOLE">Mung Whole Dal (Raw Grain)</option>
                      <option value="RM-URAD-WHOLE">Urad Whole Dal (Raw Grain)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-2xs text-slate-500 mb-0.5">Qty (kg)</label>
                    <input
                      type="number"
                      min="1"
                      value={newOrder.items[0].ordered_quantity}
                      onChange={(e) => {
                        const updated = [...newOrder.items];
                        updated[0].ordered_quantity = Number(e.target.value);
                        setNewOrder({ ...newOrder, items: updated });
                      }}
                      className="w-full px-2 py-1 text-xs border border-slate-300 rounded-lg"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-2xs text-slate-500 mb-0.5">Agreed Rate (₹/kg)</label>
                  <input
                    type="number"
                    min="1"
                    step="0.5"
                    value={newOrder.items[0].unit_price}
                    onChange={(e) => {
                      const updated = [...newOrder.items];
                      updated[0].unit_price = Number(e.target.value);
                      setNewOrder({ ...newOrder, items: updated });
                    }}
                    className="w-full px-2 py-1 text-xs border border-slate-300 rounded-lg"
                  />
                </div>
                <div className="text-right text-xs font-bold text-slate-800">
                  Estimated Total: ₹{(newOrder.items[0].ordered_quantity * newOrder.items[0].unit_price).toLocaleString()}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowOrderModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white font-semibold hover:bg-emerald-800"
                >
                  Issue Purchase Order
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: New GRN */}
      {showReceiptModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Inward Raw Material (Goods Receipt Note)</h3>
              <button onClick={() => setShowReceiptModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateReceipt} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Supplier *</label>
                <select
                  required
                  value={newReceipt.supplier_id}
                  onChange={(e) => setNewReceipt({ ...newReceipt, supplier_id: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                >
                  <option value="">-- Choose Supplier --</option>
                  {suppliers.map((s) => (
                    <option key={s.supplier_id} value={s.supplier_id}>
                      {s.supplier_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Receipt Date</label>
                  <input
                    type="date"
                    required
                    value={newReceipt.receipt_date}
                    onChange={(e) => setNewReceipt({ ...newReceipt, receipt_date: e.target.value })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Vehicle / Truck No</label>
                  <input
                    type="text"
                    value={newReceipt.vehicle_number}
                    onChange={(e) => setNewReceipt({ ...newReceipt, vehicle_number: e.target.value })}
                    placeholder="RJ-07-GA-1234"
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Vendor Challan / Bilty #</label>
                <input
                  type="text"
                  value={newReceipt.vendor_delivery_challan}
                  onChange={(e) => setNewReceipt({ ...newReceipt, vendor_delivery_challan: e.target.value })}
                  placeholder="CH-98712"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Quantity (kg) *</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={newReceipt.items[0].received_quantity}
                    onChange={(e) => {
                      const updated = [...newReceipt.items];
                      updated[0].received_quantity = Number(e.target.value);
                      setNewReceipt({ ...newReceipt, items: updated });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Unit Rate (₹/kg) *</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={newReceipt.items[0].unit_price}
                    onChange={(e) => {
                      const updated = [...newReceipt.items];
                      updated[0].unit_price = Number(e.target.value);
                      setNewReceipt({ ...newReceipt, items: updated });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowReceiptModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white font-semibold hover:bg-emerald-800"
                >
                  Confirm Inward GRN
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Book Supplier Bill */}
      {showBillModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Book Supplier Bill / Invoice</h3>
              <button onClick={() => setShowBillModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateBill} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Supplier *</label>
                <select
                  required
                  value={newBill.supplier_id}
                  onChange={(e) => setNewBill({ ...newBill, supplier_id: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                >
                  <option value="">-- Choose Supplier --</option>
                  {suppliers.map((s) => (
                    <option key={s.supplier_id} value={s.supplier_id}>
                      {s.supplier_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Supplier Invoice # *</label>
                  <input
                    type="text"
                    required
                    value={newBill.bill_number}
                    onChange={(e) => setNewBill({ ...newBill, bill_number: e.target.value })}
                    placeholder="INV-2026-081"
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Invoice Date *</label>
                  <input
                    type="date"
                    required
                    value={newBill.bill_date}
                    onChange={(e) => setNewBill({ ...newBill, bill_date: e.target.value })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Taxable Amount (₹) *</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  required
                  value={newBill.taxable_amount}
                  onChange={(e) => {
                    const amt = Number(e.target.value);
                    setNewBill({ ...newBill, taxable_amount: amt, total_amount: amt + newBill.cgst_amount + newBill.sgst_amount + newBill.freight_amount });
                  }}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">CGST / SGST (₹)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={newBill.cgst_amount}
                    onChange={(e) => {
                      const cgst = Number(e.target.value);
                      setNewBill({ ...newBill, cgst_amount: cgst, sgst_amount: cgst, total_amount: newBill.taxable_amount + (cgst * 2) + newBill.freight_amount });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Freight (₹)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={newBill.freight_amount}
                    onChange={(e) => {
                      const fr = Number(e.target.value);
                      setNewBill({ ...newBill, freight_amount: fr, total_amount: newBill.taxable_amount + (newBill.cgst_amount * 2) + fr });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div className="p-2.5 bg-slate-50 border rounded-lg text-right font-bold text-slate-900 text-xs">
                Total Bill Payable: ₹{newBill.total_amount.toLocaleString()}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowBillModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white font-semibold hover:bg-emerald-800"
                >
                  Book Bill
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Record Supplier Payment */}
      {showPaymentModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Record Supplier Payment</h3>
              <button onClick={() => setShowPaymentModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreatePayment} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Supplier *</label>
                <select
                  required
                  value={newPayment.supplier_id}
                  onChange={(e) => setNewPayment({ ...newPayment, supplier_id: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                >
                  <option value="">-- Choose Supplier --</option>
                  {suppliers.map((s) => (
                    <option key={s.supplier_id} value={s.supplier_id}>
                      {s.supplier_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Payment Mode</label>
                  <select
                    value={newPayment.payment_mode}
                    onChange={(e) => setNewPayment({ ...newPayment, payment_mode: e.target.value as any })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  >
                    <option value="BANK">Bank Transfer (NEFT/RTGS)</option>
                    <option value="UPI">UPI</option>
                    <option value="CASH">Factory Cash</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Amount (₹) *</label>
                  <input
                    type="number"
                    min="1"
                    step="0.01"
                    required
                    value={newPayment.amount}
                    onChange={(e) => setNewPayment({ ...newPayment, amount: Number(e.target.value) })}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">UTR / Bank Reference #</label>
                <input
                  type="text"
                  value={newPayment.reference_no}
                  onChange={(e) => setNewPayment({ ...newPayment, reference_no: e.target.value })}
                  placeholder="UTR-202610-098234"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowPaymentModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white font-semibold hover:bg-emerald-800"
                >
                  Post Payment
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Supplier Return */}
      {showReturnModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-sm font-bold text-slate-900">Issue Return to Supplier (Debit Note)</h3>
              <button onClick={() => setShowReturnModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateReturn} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Supplier *</label>
                <select
                  required
                  value={newReturn.supplier_id}
                  onChange={(e) => setNewReturn({ ...newReturn, supplier_id: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                >
                  <option value="">-- Choose Supplier --</option>
                  {suppliers.map((s) => (
                    <option key={s.supplier_id} value={s.supplier_id}>
                      {s.supplier_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Quantity to Return (kg)</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={newReturn.items[0].returned_quantity}
                    onChange={(e) => {
                      const updated = [...newReturn.items];
                      updated[0].returned_quantity = Number(e.target.value);
                      setNewReturn({ ...newReturn, items: updated });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Rate (₹/kg)</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={newReturn.items[0].unit_price}
                    onChange={(e) => {
                      const updated = [...newReturn.items];
                      updated[0].unit_price = Number(e.target.value);
                      setNewReturn({ ...newReturn, items: updated });
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                  />
                </div>
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Reason for Rejection *</label>
                <input
                  type="text"
                  required
                  value={newReturn.reason}
                  onChange={(e) => setNewReturn({ ...newReturn, reason: e.target.value })}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg focus:outline-hidden focus:border-emerald-600"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowReturnModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-amber-700 text-white font-semibold hover:bg-amber-800"
                >
                  Issue Debit Return
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
