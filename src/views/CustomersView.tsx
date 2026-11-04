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
import {
  FormLayout,
  FormSection,
  FormField,
  TextInput,
  SelectInput,
  TextArea,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

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

      {/* Add Customer Form Modal using FormComponents */}
      {isFormOpen && (
        <div className="mb-6">
          <FormLayout
            title="Register New Customer / Partner"
            subtitle="Only Shop/Business Name is mandatory; contact info and locality are optional"
            icon={<Users size={18} />}
            maxWidth="3xl"
            onSubmit={handleSubmit}
            onCancel={() => setIsFormOpen(false)}
            actions={
              <FormActions
                onCancel={() => setIsFormOpen(false)}
                cancelLabel="Cancel"
                saveLabel="Save Customer"
              />
            }
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <FormField label="Customer Type" required>
                <SelectInput
                  value={customerType}
                  onChange={(e) => setCustomerType(e.target.value as CustomerType)}
                  options={[
                    { value: 'RETAILER', label: 'RETAILER (Kirana / Store)' },
                    { value: 'WHOLESALER', label: 'WHOLESALER (Bulk Trader)' },
                    { value: 'DISTRIBUTOR', label: 'DISTRIBUTOR (Area Agency)' },
                    { value: 'RETAIL', label: 'RETAIL (Direct Consumer)' },
                  ]}
                />
              </FormField>

              <FormField label="Shop / Business Name" required helpText="Official trade name or store banner">
                <TextInput
                  required
                  value={shopName}
                  onChange={(e) => setShopName(e.target.value)}
                  placeholder="e.g. Bharat Kirana Store"
                />
              </FormField>

              <FormField label="Owner / Shopkeeper Name" helpText="Proprietor contact person">
                <TextInput
                  value={shopkeeperName}
                  onChange={(e) => setShopkeeperName(e.target.value)}
                  placeholder="e.g. Bharat Patel"
                />
              </FormField>

              <FormField label="Primary Mobile" helpText="10-digit phone number for WhatsApp receipts">
                <TextInput
                  type="tel"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  placeholder="e.g. 9826012345"
                />
              </FormField>

              <FormField label="Area / Locality" helpText="Market location or delivery zone">
                <TextInput
                  value={localityArea}
                  onChange={(e) => setLocalityArea(e.target.value)}
                  placeholder="e.g. Main Market, Kasrawad"
                />
              </FormField>

              <FormField label="City / Town" helpText="Town or district">
                <TextInput
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="e.g. Khargone, Barwaha"
                />
              </FormField>
            </div>
          </FormLayout>
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
