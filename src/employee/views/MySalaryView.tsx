import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import { SalaryStructureData, PayrollItemData } from '../types';
import {
  Coins,
  Receipt,
  Download,
  Calendar,
  CreditCard,
  Building,
  CheckCircle2,
  FileText,
  Clock,
} from 'lucide-react';
import { generateSalaryReceiptPdf } from '../../utils/generateSalaryReceiptPdf';

export const MySalaryView: React.FC = () => {
  const { currentUser } = useStore();
  const [data, setData] = useState<{
    salary_structure: SalaryStructureData | null;
    payroll_items: PayrollItemData[];
    receipts: any[];
  }>({
    salary_structure: null,
    payroll_items: [],
    receipts: [],
  });
  const [isLoading, setIsLoading] = useState(true);

  const fetchSalaryData = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch('/api/workforce/my-salary');
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (err) {
      console.error('Failed to load salary details:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSalaryData();
  }, []);

  const structure = data.salary_structure;
  const receipts = data.receipts;
  const payrollItems = data.payroll_items;
  const role = (currentUser?.role || '').toUpperCase();

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
          My Salary & Payment Receipts
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 mt-1">
          Authorized salary structures, monthly payroll items, and verifiable PDF receipts.
        </p>
      </div>

      {/* Salary Structure Card */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-6">
        <div className="flex items-center gap-2 pb-3 mb-4 border-b border-slate-100">
          <Coins size={18} className="text-emerald-700" />
          <h2 className="text-sm font-bold text-slate-900 m-0">
            Registered Salary Structure
          </h2>
        </div>

        {structure ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
              <span className="text-[11px] text-slate-500 font-semibold block">Base Monthly Pay</span>
              <span className="text-lg font-black text-slate-900 mt-1 block">
                ₹{Number(structure.basic_salary || 0).toLocaleString('en-IN')}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
              <span className="text-[11px] text-slate-500 font-semibold block">Allowances (HRA/Travel)</span>
              <span className="text-lg font-black text-slate-900 mt-1 block">
                ₹{Number((structure.hra || 0) + (structure.transport_allowance || 0) + (structure.special_allowance || 0)).toLocaleString('en-IN')}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
              <span className="text-[11px] text-slate-500 font-semibold block">
                {role === 'SALESMAN' ? 'Sales Incentive Slab' : 'Standard Deductions'}
              </span>
              <span className="text-lg font-black text-slate-900 mt-1 block">
                {role === 'SALESMAN'
                  ? structure.sales_commission_rate > 0
                    ? `${structure.sales_commission_rate}% of Sales`
                    : '₹200 / 100 kg'
                  : `₹${Number((structure.pf_deduction || 0) + (structure.tds_deduction || 0)).toLocaleString('en-IN')}`}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
              <span className="text-[11px] text-slate-500 font-semibold block">Disbursement Mode</span>
              <span className="text-base font-bold text-emerald-700 mt-1 block flex items-center gap-1">
                <CreditCard size={15} />
                <span>{structure.payment_mode || 'BANK_TRANSFER'}</span>
              </span>
            </div>
          </div>
        ) : (
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-500 text-center">
            Standard structure is active for your designation. Contact Owner / PA for custom structure details.
          </div>
        )}
      </div>

      {/* Disbursed Salary Receipts */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Receipt size={18} className="text-emerald-700" />
            <h2 className="text-sm font-bold text-slate-900 m-0">Official Salary Receipts (Vouchers)</h2>
          </div>
          <span className="text-xs text-slate-500">{receipts.length} vouchers</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 font-bold border-b border-slate-200">
              <tr>
                <th className="py-3 px-4">Receipt #</th>
                <th className="py-3 px-4">Period</th>
                <th className="py-3 px-4">Disbursed On</th>
                <th className="py-3 px-4">Method / Ref</th>
                <th className="py-3 px-4 text-right">Gross Pay</th>
                <th className="py-3 px-4 text-right">Deductions</th>
                <th className="py-3 px-4 text-right">Net Amount</th>
                <th className="py-3 px-4 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-400">Loading vouchers…</td>
                </tr>
              ) : receipts.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-400">No payment vouchers generated yet.</td>
                </tr>
              ) : (
                receipts.map((rec) => (
                  <tr key={rec.receipt_id} className="hover:bg-slate-50/60">
                    <td className="py-3 px-4 font-bold text-slate-900">
                      {rec.receipt_number || rec.receipt_id}
                    </td>
                    <td className="py-3 px-4">
                      {rec.period_start} to {rec.period_end}
                    </td>
                    <td className="py-3 px-4">{rec.payment_date}</td>
                    <td className="py-3 px-4">
                      <span className="font-semibold text-slate-800">{rec.payment_method}</span>
                      {rec.payment_reference && (
                        <span className="block text-[10px] text-slate-400">Ref: {rec.payment_reference}</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right font-medium">
                      ₹{Number(rec.gross_earnings || rec.net_paid).toFixed(2)}
                    </td>
                    <td className="py-3 px-4 text-right font-medium text-red-600">
                      {Number(rec.total_deductions) > 0 ? `-₹${Number(rec.total_deductions).toFixed(2)}` : '₹0.00'}
                    </td>
                    <td className="py-3 px-4 text-right font-black text-emerald-700">
                      ₹{Number(rec.net_paid).toFixed(2)}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() =>
                          generateSalaryReceiptPdf({
                            receipt_number: rec.receipt_number || rec.receipt_id,
                            recipient_id: rec.recipient_id,
                            recipient_name: rec.recipient_name,
                            recipient_type: rec.recipient_type || 'SALARY',
                            role_or_category: rec.role_or_category || role,
                            period_start: rec.period_start,
                            period_end: rec.period_end,
                            payment_date: rec.payment_date,
                            payment_method: rec.payment_method,
                            payment_reference: rec.payment_reference,
                            gross_earnings: Number(rec.gross_earnings || rec.net_paid),
                            total_deductions: Number(rec.total_deductions || 0),
                            net_paid: Number(rec.net_paid || 0),
                            notes: rec.notes,
                          })
                        }
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs shadow-2xs transition-colors cursor-pointer"
                        title="Download standard PDF receipt"
                      >
                        <Download size={13} />
                        <span>Download PDF</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
