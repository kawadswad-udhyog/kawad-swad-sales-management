import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import { Product } from '../types';

export const ProductsView: React.FC = () => {
  const { products, addProduct, updateProduct, toggleProductActive, currentUser } = useStore();
  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';

  const [filter, setFilter] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // Form state
  const [sku, setSku] = useState('');
  const [productName, setProductName] = useState('');
  const [category, setCategory] = useState<'Papad' | 'Masala' | 'Katran' | string>('Papad');
  const [variant, setVariant] = useState('Plain');
  const [packWeightG, setPackWeightG] = useState(200);
  const [sellingUnit, setSellingUnit] = useState<'packet' | 'kg'>('packet');
  const [retailPackOnly, setRetailPackOnly] = useState(true);
  const [active, setActive] = useState(true);
  const [notes, setNotes] = useState('');

  const resetForm = () => {
    setEditingId(null);
    setSku('');
    setProductName('');
    setCategory('Papad');
    setVariant('Plain');
    setPackWeightG(200);
    setSellingUnit('packet');
    setRetailPackOnly(true);
    setActive(true);
    setNotes('');
  };

  const handleEditClick = (p: Product) => {
    setEditingId(p.product_id);
    setSku(p.sku);
    setProductName(p.product_name);
    setCategory(p.category);
    setVariant(p.variant);
    setPackWeightG(p.pack_weight_g);
    setSellingUnit(p.selling_unit);
    setRetailPackOnly(p.retail_pack_only);
    setActive(p.active);
    setNotes(p.notes || '');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    try {
      if (editingId) {
        // Update product (SKU is immutable)
        updateProduct(editingId, {
          product_name: productName.trim(),
          category,
          variant: variant.trim(),
          pack_weight_g: Number(packWeightG),
          selling_unit: sellingUnit,
          retail_pack_only: retailPackOnly,
          active,
          notes: notes.trim(),
        });
        setNotice({ msg: 'Product updated successfully.' });
        resetForm();
      } else {
        // Check SKU uniqueness
        if (products.some((p) => p.sku.toLowerCase() === sku.trim().toLowerCase())) {
          setNotice({ msg: 'A product with this SKU already exists.', error: true });
          return;
        }

        addProduct({
          sku: sku.trim().toUpperCase(),
          product_name: productName.trim(),
          category,
          variant: variant.trim(),
          pack_weight_g: Number(packWeightG),
          selling_unit: sellingUnit,
          retail_pack_only: retailPackOnly,
          active,
          notes: notes.trim(),
        });
        setNotice({ msg: 'Product added to catalogue.' });
        resetForm();
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to save product';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleToggleActive = (p: Product) => {
    const action = p.active ? 'Deactivate' : 'Activate';
    if (window.confirm(`${action} ${p.product_name}?`)) {
      toggleProductActive(p.product_id);
      setNotice({ msg: `Product status updated.` });
    }
  };

  const filtered = products.filter((p) =>
    [p.sku, p.product_name, p.category, p.variant, p.notes]
      .join(' ')
      .toLowerCase()
      .includes(filter.toLowerCase())
  );

  return (
    <div>
      <h1>Product Catalogue</h1>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'}>
          {notice.msg}
        </div>
      )}

      {isManager && (
        <div className="card">
          <h2>{editingId ? 'Edit Product' : 'Add Product'}</h2>
          <form className="inline" onSubmit={handleSubmit}>
            <label>
              SKU
              <input
                required
                maxLength={60}
                placeholder="KS-MMP-200"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                disabled={!!editingId}
                title={editingId ? 'SKU cannot be altered to preserve billing history' : ''}
              />
            </label>

            <label>
              Product name
              <input
                required
                maxLength={120}
                placeholder="Moong Masala Papad 200g"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
              />
            </label>

            <label>
              Category
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="Papad">Papad</option>
                <option value="Masala">Masala</option>
                <option value="Katran">Katran</option>
              </select>
            </label>

            <label>
              Variant
              <input
                required
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="Plain, Spicy, etc."
              />
            </label>

            <label>
              Pack weight (g)
              <input
                type="number"
                min={1}
                step={1}
                required
                value={packWeightG}
                onChange={(e) => setPackWeightG(Number(e.target.value))}
              />
            </label>

            <label>
              Selling unit
              <select
                value={sellingUnit}
                onChange={(e) => setSellingUnit(e.target.value as 'packet' | 'kg')}
              >
                <option value="packet">packet</option>
                <option value="kg">kg</option>
              </select>
            </label>

            <label className="check-label" style={{ paddingTop: '10px' }}>
              <input
                type="checkbox"
                checked={retailPackOnly}
                onChange={(e) => setRetailPackOnly(e.target.checked)}
              />
              Retail pack only
            </label>

            <label className="check-label" style={{ paddingTop: '10px' }}>
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
              />
              Active product
            </label>

            <label style={{ gridColumn: 'span 2' }}>
              Notes
              <input
                maxLength={500}
                placeholder="Packaging details, target market..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>

            <div className="actions" style={{ gridColumn: 'span 2', marginTop: '8px' }}>
              <button type="submit">
                {editingId ? 'Save Changes' : 'Save Product'}
              </button>
              {editingId && (
                <button type="button" className="secondary" onClick={resetForm}>
                  Cancel Edit
                </button>
              )}
            </div>
          </form>
          <p className="muted">
            SKU must be unique. To protect sales history, editing a product does not change its SKU.
          </p>
        </div>
      )}

      <div className="card">
        <div className="toolbar">
          <h2>
            Catalogue <span className="count">{filtered.length}</span>
          </h2>
          <input
            placeholder="Search SKU, product, variant..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {filtered.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Product</th>
                  <th>Category</th>
                  <th>Variant</th>
                  <th>Pack g</th>
                  <th>Unit</th>
                  <th>Status</th>
                  {isManager && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {filtered.map((p) => (
                  <tr key={p.product_id}>
                    <td>
                      <strong>{p.sku}</strong>
                    </td>
                    <td>{p.product_name}</td>
                    <td>{p.category}</td>
                    <td>{p.variant}</td>
                    <td>{p.pack_weight_g}</td>
                    <td>{p.selling_unit}</td>
                    <td>
                      <span className={`badge ${p.active ? 'on' : 'off'}`}>
                        {p.active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    {isManager && (
                      <td>
                        <div className="actions">
                          <button
                            className="secondary"
                            onClick={() => handleEditClick(p)}
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                          >
                            Edit
                          </button>
                          <button
                            className="secondary"
                            onClick={() => handleToggleActive(p)}
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                          >
                            {p.active ? 'Deactivate' : 'Activate'}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No matching products found in the catalogue.</p>
        )}
      </div>
    </div>
  );
};
