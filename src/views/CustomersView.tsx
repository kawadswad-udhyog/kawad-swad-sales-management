import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { CustomerType } from '../types';

export const CustomersView: React.FC = () => {
  const { customers, addCustomer } = useStore();
  const [filter, setFilter] = useState('');
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

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
      // Reset form
      setShopName('');
      setShopkeeperName('');
      setMobile('');
      setAlternateMobile('');
      setLocalityArea('');
      setCity('');
      setAddress('');
      setMapLocation('');
      setNotes('');
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to add customer';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const filtered = customers.filter((c) =>
    [
      c.customer_id,
      c.shop_name,
      c.customer_type,
      c.shopkeeper_name,
      c.mobile,
      c.locality_area,
      c.city,
    ]
      .join(' ')
      .toLowerCase()
      .includes(filter.toLowerCase())
  );

  return (
    <div>
      <h1>Customer & Retailer Management</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      <div className="card">
        <h2>Add customer / trade partner</h2>
        <form className="inline" onSubmit={handleSubmit}>
          <label>
            Customer type
            <select
              value={customerType}
              onChange={(e) => setCustomerType(e.target.value as CustomerType)}
            >
              <option value="RETAIL">RETAIL</option>
              <option value="RETAILER">RETAILER</option>
              <option value="WHOLESALER">WHOLESALER</option>
              <option value="DISTRIBUTOR">DISTRIBUTOR</option>
            </select>
          </label>

          <label>
            Shop / business name
            <input
              required
              maxLength={150}
              placeholder="e.g. Patidar Daily Needs"
              value={shopName}
              onChange={(e) => setShopName(e.target.value)}
            />
          </label>

          <label>
            Contact person
            <input
              maxLength={100}
              placeholder="Shopkeeper / owner name"
              value={shopkeeperName}
              onChange={(e) => setShopkeeperName(e.target.value)}
            />
          </label>

          <label>
            Mobile
            <input
              type="tel"
              maxLength={20}
              placeholder="10-digit number"
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
            />
          </label>

          <label>
            Alternate mobile
            <input
              type="tel"
              maxLength={20}
              value={alternateMobile}
              onChange={(e) => setAlternateMobile(e.target.value)}
            />
          </label>

          <label>
            Area / locality
            <input
              maxLength={100}
              placeholder="e.g. Sarafa Chowk"
              value={localityArea}
              onChange={(e) => setLocalityArea(e.target.value)}
            />
          </label>

          <label>
            City / village
            <input
              maxLength={100}
              placeholder="Khargone, Khandwa, Barwani..."
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />
          </label>

          <label>
            Map location / link
            <input
              maxLength={300}
              placeholder="Google Maps link or landmarks"
              value={mapLocation}
              onChange={(e) => setMapLocation(e.target.value)}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Address
            <input
              maxLength={500}
              placeholder="Complete shop address..."
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>

          <label style={{ gridColumn: 'span 2' }}>
            Notes
            <input
              maxLength={500}
              placeholder="Delivery notes, preferred timing, payment habits..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          <div style={{ gridColumn: 'span 2', marginTop: '6px' }}>
            <button type="submit">Add customer</button>
          </div>
        </form>
        <p className="muted">
          Use one record per shop or trade partner. Check the directory before adding to reduce duplicates.
        </p>
      </div>

      <div className="card">
        <div className="toolbar">
          <h2>
            Customers <span className="count">{filtered.length}</span>
          </h2>
          <input
            placeholder="Search shop, phone, area, city..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {filtered.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer ID</th>
                  <th>Shop / business</th>
                  <th>Type</th>
                  <th>Contact</th>
                  <th>Mobile</th>
                  <th>Area</th>
                  <th>City</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.customer_id}>
                    <td>
                      <code>{c.customer_id}</code>
                    </td>
                    <td>
                      <strong>{c.shop_name}</strong>
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.78rem',
                          background: '#f0f4f2',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontWeight: 600,
                        }}
                      >
                        {c.customer_type}
                      </span>
                    </td>
                    <td>{c.shopkeeper_name || '—'}</td>
                    <td>{c.mobile || '—'}</td>
                    <td>{c.locality_area || '—'}</td>
                    <td>{c.city || '—'}</td>
                    <td>
                      <span className={`badge ${c.active ? 'on' : 'off'}`}>
                        {c.active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No matching customers found in directory.</p>
        )}
      </div>
    </div>
  );
};
