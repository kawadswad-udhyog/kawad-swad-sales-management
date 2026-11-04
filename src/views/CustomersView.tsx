import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { CustomerType } from '../types';
import { ViewType } from '../components/Navigation';
import { PageHeader } from '../components/common/PageHeader';
import { SearchFilter } from '../components/common/SearchFilter';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import {
  Users,
  Plus,
  Phone,
  MapPin,
  ShoppingCart,
  Building,
  X,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';

interface CustomersViewProps {
  onNavigate?: (view: ViewType) => void;
}

const CUSTOMER_TYPE_OPTIONS: Array<{ value: CustomerType | 'ALL'; label: string }> = [
  { value: 'ALL', label: 'All Partners' },
  { value: 'RETAILER', label: 'Retailers' },
  { value: 'WHOLESALER', label: 'Wholesalers' },
  { value: 'DISTRIBUTOR', label: 'Distributors' },
  { value: 'RETAIL', label: 'Retail' },
];

export const CustomersView: React.FC<CustomersViewProps> = ({ onNavigate }) => {
  const { customers, addCustomer, setActiveCustomerIdForBilling } = useStore();
  const [filter, setFilter] = useState('');
  const [selectedType, setSelectedType] = useState<CustomerType | 'ALL'>('ALL');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);

  // Form state
  const [customerType, setCustomerType] = useState<CustomerType>('RETAILER');
  const [shopName, setShopName] = useState('');
  const [shopkeeperName, setShopkeeperName] = useState('');
  const [mobile, setMobile] = useState('');
  const [alternateMobile, setAlternateMobile] = useState('');
  const [localityArea, setLocalityArea] = useState('');
  const [city, setCity] = useState('');
  const [address, setAddress] = useState('');
  const [mapLocation, setMapLocation] = useState('');
  const [notes, setNotes] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    if (!shopName.trim()) {
      setNotice({ msg: 'Shop / business name is required.', error: true });
      return;
    }

    try {
      addCustomer({
        customer_type: customerType,
        shop_name: shopName.trim(),
        shopkeeper_name: shopkeeperName.trim(),
        mobile: mobile.trim(),
        alternate_mobile: alternateMobile.trim(),
        locality_area: localityArea.trim(),
        city: city.trim(),
        address: address.trim(),
        map_location: mapLocation.trim(),
        active: true,
        notes: notes.trim(),
      });

      setNotice({ msg: `Customer "${shopName}" registered successfully.` });
      setShopName('');
      setShopkeeperName('');
      setMobile('');
      setAlternateMobile('');
      setLocalityArea('');
      setCity('');
      setAddress('');
      setMapLocation('');
      setNotes('');
      setIsFormOpen(false);
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to add customer';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleStartBilling = (customerId: string) => {
    setActiveCustomerIdForBilling(customerId);
    if (onNavigate) {
      onNavigate('sales');
    }
  };

  const filtered = useMemo(() => {
    return customers.filter((c) => {
      const matchesType = selectedType === 'ALL' || c.customer_type === selectedType;
      if (!matchesType) return false;

      if (!filter.trim()) return true;
      const q = filter.toLowerCase();
      return (
        c.customer_id.toLowerCase().includes(q) ||
        c.shop_name.toLowerCase().includes(q) ||
        (c.shopkeeper_name && c.shopkeeper_name.toLowerCase().includes(q)) ||
        (c.mobile && c.mobile.includes(q)) ||
        (c.locality_area && c.locality_area.toLowerCase().includes(q)) ||
        (c.city && c.city.toLowerCase().includes(q))
      );
    });
  }, [customers, filter, selectedType]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customers & Trade Directory"
        subtitle="Search retail outlets, wholesale accounts, contact details, and start 1-tap sales orders"
        icon={<Users size={22} />}
        actions={
          <button
            type="button"
            onClick={() => setIsFormOpen(!isFormOpen)}
            className="px-4 py-2 bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors cursor-pointer flex items-center gap-1.5"
          >
            {isFormOpen ? <X size={15} /> : <Plus size={15} />}
            <span>{isFormOpen ? 'Cancel' : 'Add Customer'}</span>
          </button>
        }
      />

      {notice && (
        <div
          className={`p-3.5 rounded-xl text-xs flex items-center justify-between border ${
            notice.error
              ? 'bg-red-50 border-red-200 text-red-900'
              : 'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}
        >
          <div className="flex items-center gap-2">
            {notice.error ? <AlertCircle size={16} className="text-red-600" /> : <CheckCircle2 size={16} className="text-emerald-600" />}
            <span className="font-medium">{notice.msg}</span>
          </div>
          <button onClick={() => setNotice(null)} className="p-1 text-slate-400 hover:text-slate-600">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Add Customer Form Modal / Card */}
      {isFormOpen && (
        <div className="bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 shadow-xs">
          <div className="flex items-center justify-between pb-3 mb-4 border-b border-slate-100">
            <div>
              <h2 className="text-base font-bold text-slate-900 m-0">Register New Customer / Partner</h2>
              <p className="text-xs text-slate-500 m-0">Only Shop/Business Name is mandatory; contact info is optional</p>
            </div>
            <button onClick={() => setIsFormOpen(false)} className="text-slate-400 hover:text-slate-600 p-1">
              <X size={18} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Customer Type <span className="text-emerald-700">*</span>
                </label>
                <select
                  value={customerType}
                  onChange={(e) => setCustomerType(e.target.value as CustomerType)}
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-medium"
                >
                  <option value="RETAILER">RETAILER (Kirana / Store)</option>
                  <option value="WHOLESALER">WHOLESALER (Bulk Trader)</option>
                  <option value="DISTRIBUTOR">DISTRIBUTOR (Area Agency)</option>
                  <option value="RETAIL">RETAIL (Direct Consumer)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Shop / Business Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={shopName}
                  onChange={(e) => setShopName(e.target.value)}
                  placeholder="e.g. Bharat Kirana Store"
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-medium"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Owner / Shopkeeper Name
                </label>
                <input
                  type="text"
                  value={shopkeeperName}
                  onChange={(e) => setShopkeeperName(e.target.value)}
                  placeholder="e.g. Bharat Patel"
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Primary Mobile
                </label>
                <input
                  type="tel"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  placeholder="10-digit mobile"
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Area / Locality
                </label>
                <input
                  type="text"
                  value={localityArea}
                  onChange={(e) => setLocalityArea(e.target.value)}
                  placeholder="e.g. Main Market, Kasrawad"
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  City / Town
                </label>
                <input
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="e.g. Khargone, Barwaha"
                  className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => setIsFormOpen(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-5 py-2 text-xs font-bold text-white bg-emerald-800 hover:bg-emerald-900 rounded-lg transition-colors cursor-pointer shadow-xs"
              >
                Save Customer
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Search & Segmented Filter */}
      <SearchFilter
        searchTerm={filter}
        onSearchChange={setFilter}
        searchPlaceholder="Search by shop name, owner, city, or phone…"
        filterValue={selectedType}
        onFilterChange={setSelectedType}
        filterOptions={CUSTOMER_TYPE_OPTIONS.map((opt) => ({
          ...opt,
          count: opt.value === 'ALL'
            ? customers.length
            : customers.filter((c) => c.customer_type === opt.value).length,
        }))}
      />

      {/* Customer Directory Table & Cards */}
      {filtered.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-2xl p-6">
          <EmptyState
            title="No Customers Found"
            description={filter ? 'No customers match your search criteria.' : 'No customers registered yet.'}
            icon={<Users size={28} />}
            actionLabel={filter ? 'Clear Search' : 'Add First Customer'}
            onAction={filter ? () => setFilter('') : () => setIsFormOpen(true)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
          {filtered.map((c) => (
            <div
              key={c.customer_id}
              className="bg-white border border-slate-200 hover:border-slate-300 rounded-xl p-4 shadow-2xs transition-all flex flex-col justify-between gap-3"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h3 className="text-sm font-bold text-slate-900 tracking-tight leading-snug m-0">
                    {c.shop_name}
                  </h3>
                  <StatusBadge status={c.customer_type} size="sm" />
                </div>

                <div className="space-y-1 text-xs text-slate-600">
                  {c.shopkeeper_name && (
                    <div className="text-slate-500 font-medium">
                      Contact: <span className="text-slate-800">{c.shopkeeper_name}</span>
                    </div>
                  )}

                  {c.mobile && (
                    <div className="flex items-center gap-1.5 text-slate-600 font-mono">
                      <Phone size={12} className="text-slate-400" />
                      <a href={`tel:${c.mobile}`} className="hover:text-emerald-700 hover:underline">
                        {c.mobile}
                      </a>
                    </div>
                  )}

                  {(c.locality_area || c.city) && (
                    <div className="flex items-center gap-1.5 text-slate-500 text-[11px]">
                      <MapPin size={12} className="text-slate-400 shrink-0" />
                      <span className="truncate">{[c.locality_area, c.city].filter(Boolean).join(', ')}</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                <span className="text-[11px] font-mono text-slate-400">
                  {c.customer_id}
                </span>

                <button
                  type="button"
                  onClick={() => handleStartBilling(c.customer_id)}
                  className="px-3 py-1.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-200/80 rounded-lg text-xs font-bold transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <ShoppingCart size={13} />
                  <span>New Order</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
