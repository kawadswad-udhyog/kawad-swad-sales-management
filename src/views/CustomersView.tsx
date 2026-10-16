import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { CustomerType } from '../types';
import { ViewType } from '../components/Navigation';

interface CustomersViewProps {
  onNavigate?: (view: ViewType) => void;
}

const CUSTOMER_TYPES: Array<{ type: CustomerType | 'ALL'; label: string }> = [
  { type: 'ALL', label: 'All Partners' },
  { type: 'RETAILER', label: 'Retailers' },
  { type: 'WHOLESALER', label: 'Wholesalers' },
  { type: 'DISTRIBUTOR', label: 'Distributors' },
  { type: 'RETAIL', label: 'Retail' },
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
      // Reset form & close
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
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0 }}>Customer &amp; Retailer Directory</h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.9rem' }}>
            Fast partner search, 1-tap quick billing, and streamlined customer registration
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsFormOpen(!isFormOpen)}
          style={{
            background: isFormOpen ? '#475569' : '#0f766e',
            color: '#fff',
            padding: '8px 16px',
            borderRadius: '6px',
            fontSize: '0.88rem',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <span>{isFormOpen ? '✕ Close Form' : '➕ Add Saved Customer'}</span>
        </button>
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: '16px' }}>
          {notice.msg}
        </div>
      )}

      {/* Add customer form card (collapsible for fast lookup) */}
      {isFormOpen && (
        <div className="card" style={{ marginBottom: '20px', background: '#f8fafc', border: '1px solid #cbd5e1' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ margin: 0, fontSize: '1.15rem' }}>Register Saved Customer / Trade Partner</h2>
            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
              Only Shop/Business Name is mandatory; contact info is optional
            </span>
          </div>

          <form className="inline" onSubmit={handleSubmit}>
            <label>
              Customer type
              <select
                value={customerType}
                onChange={(e) => setCustomerType(e.target.value as CustomerType)}
                style={{ padding: '8px' }}
              >
                <option value="RETAILER">RETAILER (Kirana)</option>
                <option value="WHOLESALER">WHOLESALER (Bulk)</option>
                <option value="DISTRIBUTOR">DISTRIBUTOR (Area)</option>
                <option value="RETAIL">RETAIL (Consumer)</option>
              </select>
            </label>

            <label>
              Shop / Business Name <span style={{ color: '#b91c1c' }}>*</span>
              <input
                required
                maxLength={150}
                placeholder="e.g. Patidar Daily Needs"
                value={shopName}
                onChange={(e) => setShopName(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Contact Person (Optional)
              <input
                maxLength={100}
                placeholder="Shopkeeper / owner name"
                value={shopkeeperName}
                onChange={(e) => setShopkeeperName(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Mobile (Optional)
              <input
                type="tel"
                maxLength={20}
                placeholder="10-digit number"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Alternate Mobile (Optional)
              <input
                type="tel"
                maxLength={20}
                value={alternateMobile}
                placeholder="Secondary phone"
                onChange={(e) => setAlternateMobile(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Area / Locality (Optional)
              <input
                maxLength={100}
                placeholder="e.g. Sarafa Chowk, Main Market"
                value={localityArea}
                onChange={(e) => setLocalityArea(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              City / Village (Optional)
              <input
                maxLength={100}
                placeholder="Khargone, Khandwa, Barwani..."
                value={city}
                onChange={(e) => setCity(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Map Location / Landmark (Optional)
              <input
                maxLength={300}
                placeholder="Landmark or maps link"
                value={mapLocation}
                onChange={(e) => setMapLocation(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label style={{ gridColumn: 'span 2' }}>
              Address (Optional)
              <input
                maxLength={500}
                placeholder="Complete street address..."
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label style={{ gridColumn: 'span 2' }}>
              Notes / Delivery Habits (Optional)
              <input
                maxLength={500}
                placeholder="Preferred delivery timing, credit status, special requests..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <div style={{ gridColumn: 'span 2', marginTop: '10px', display: 'flex', gap: '10px' }}>
              <button
                type="submit"
                style={{ background: '#047857', color: '#fff', padding: '10px 20px', fontWeight: 600 }}
              >
                💾 Save Customer Record
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setIsFormOpen(false)}
                style={{ padding: '10px 16px' }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
          {/* Category Filter Buttons */}
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {CUSTOMER_TYPES.map(({ type, label }) => {
              const isSelected = selectedType === type;
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => setSelectedType(type)}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.84rem',
                    borderRadius: '6px',
                    border: isSelected ? '1px solid #0f766e' : '1px solid #cbd5e1',
                    background: isSelected ? '#0f766e' : '#ffffff',
                    color: isSelected ? '#ffffff' : '#475569',
                    fontWeight: isSelected ? 600 : 500,
                    cursor: 'pointer',
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div style={{ minWidth: '260px', flex: '1', maxWidth: '380px' }}>
            <input
              type="text"
              placeholder="🔍 Search shop, phone, contact, locality..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', fontSize: '0.9rem' }}
            />
          </div>
        </div>

        {filtered.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Shop / Business</th>
                  <th>Type</th>
                  <th>Contact Person</th>
                  <th>Mobile</th>
                  <th>Area / City</th>
                  <th style={{ textAlign: 'center' }}>Fast Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.customer_id}>
                    <td>
                      <div>
                        <strong style={{ fontSize: '0.95rem', color: '#1e293b' }}>{c.shop_name}</strong>
                        <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                          ID: <code>{c.customer_id}</code>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.78rem',
                          background: '#f1f5f9',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontWeight: 600,
                          color: '#334155',
                        }}
                      >
                        {c.customer_type}
                      </span>
                    </td>
                    <td>{c.shopkeeper_name || '—'}</td>
                    <td>
                      {c.mobile ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span>{c.mobile}</span>
                          <a
                            href={`https://wa.me/91${c.mobile.replace(/\D/g, '').slice(-10)}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ textDecoration: 'none', fontSize: '0.85rem' }}
                            title="Chat on WhatsApp"
                          >
                            💬
                          </a>
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {[c.locality_area, c.city].filter(Boolean).join(', ') || '—'}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <button
                        type="button"
                        onClick={() => handleStartBilling(c.customer_id)}
                        style={{
                          padding: '5px 12px',
                          fontSize: '0.82rem',
                          background: '#047857',
                          color: '#fff',
                          borderRadius: '4px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          fontWeight: 600,
                        }}
                        title="Start billing for this customer immediately"
                      >
                        <span>⚡</span>
                        <span>Bill Customer</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
            No matching customers found. Use the quick walk-in sale or click "+ Add Saved Customer".
          </div>
        )}
      </div>
    </div>
  );
};
