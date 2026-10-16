import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { Product } from '../types';

const CATEGORIES = ['ALL', 'Papad', 'Masala', 'Katran'] as const;

export const ProductsView: React.FC = () => {
  const {
    products,
    addProduct,
    updateProduct,
    toggleProductActive,
    currentUser,
    companyStockSummary,
    salesmanStockSummary,
  } = useStore();

  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';

  const [filter, setFilter] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [notice, setNotice] = useState<{ msg: string; error?: boolean } | null>(null);

  // Pagination to avoid long scrolling lists
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 12;

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
    setIsFormOpen(false);
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
    setIsFormOpen(true);
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
        setNotice({ msg: 'Product added to catalogue successfully.' });
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

  const getProductStock = (productId: string) => {
    if (currentUser?.role === 'SALESMAN') {
      const sm = salesmanStockSummary.find(
        (s) => s.product_id === productId && s.salesman_user_id === currentUser.user_id
      );
      return { quantity: sm ? sm.quantity : 0, label: 'My Stock' };
    }
    const comp = companyStockSummary.find((c) => c.product_id === productId);
    return { quantity: comp ? comp.company_quantity : 0, label: 'Warehouse Stock' };
  };

  const filtered = useMemo(() => {
    return products.filter((p) => {
      const matchesCategory =
        selectedCategory === 'ALL' ||
        p.category.toLowerCase() === selectedCategory.toLowerCase();
      if (!matchesCategory) return false;

      if (!filter.trim()) return true;
      const q = filter.toLowerCase();
      return (
        p.sku.toLowerCase().includes(q) ||
        p.product_name.toLowerCase().includes(q) ||
        p.variant.toLowerCase().includes(q) ||
        p.category.toLowerCase().includes(q) ||
        (p.notes && p.notes.toLowerCase().includes(q))
      );
    });
  }, [products, filter, selectedCategory]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginatedProducts = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, currentPage]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0 }}>Product Catalogue &amp; Stock</h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.9rem' }}>
            Fast SKU and pack search · Inventory visibility · Clean pagination
          </p>
        </div>
        {isManager && (
          <button
            type="button"
            onClick={() => {
              if (isFormOpen && !editingId) {
                setIsFormOpen(false);
              } else {
                resetForm();
                setIsFormOpen(true);
              }
            }}
            style={{
              background: isFormOpen ? '#475569' : '#047857',
              color: '#fff',
              padding: '8px 16px',
              borderRadius: '6px',
              fontSize: '0.88rem',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>{isFormOpen ? '✕ Close Form' : '➕ Add New Product'}</span>
          </button>
        )}
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: '16px' }}>
          {notice.msg}
        </div>
      )}

      {/* Product Form Card (Collapsible) */}
      {isManager && isFormOpen && (
        <div className="card" style={{ marginBottom: '20px', background: '#f8fafc', border: '1px solid #cbd5e1' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ margin: 0, fontSize: '1.2rem' }}>
              {editingId ? 'Edit Product Details' : 'Add New Product to Catalogue'}
            </h2>
            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
              SKU is immutable after creation to protect past sales records
            </span>
          </div>

          <form className="inline" onSubmit={handleSubmit}>
            <label>
              SKU <span style={{ color: '#b91c1c' }}>*</span>
              <input
                required
                maxLength={60}
                placeholder="e.g. KS-MMP-200"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                disabled={!!editingId}
                style={{ padding: '8px', background: editingId ? '#f1f5f9' : '#fff' }}
                title={editingId ? 'SKU cannot be altered to preserve billing history' : ''}
              />
            </label>

            <label>
              Product Name <span style={{ color: '#b91c1c' }}>*</span>
              <input
                required
                maxLength={120}
                placeholder="e.g. Moong Masala Papad 200g"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Category
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ padding: '8px' }}
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
                placeholder="e.g. Plain, Spicy, Jeera, Special"
                style={{ padding: '8px' }}
              />
            </label>

            <label>
              Pack Weight (grams)
              <div style={{ display: 'flex', gap: '4px' }}>
                <input
                  type="number"
                  min={1}
                  step={1}
                  required
                  value={packWeightG}
                  onChange={(e) => setPackWeightG(Number(e.target.value))}
                  style={{ width: '80px', padding: '8px' }}
                />
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPackWeightG(200)}
                  style={{ padding: '4px 6px', fontSize: '0.75rem' }}
                >
                  200g
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPackWeightG(500)}
                  style={{ padding: '4px 6px', fontSize: '0.75rem' }}
                >
                  500g
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPackWeightG(1000)}
                  style={{ padding: '4px 6px', fontSize: '0.75rem' }}
                >
                  1kg
                </button>
              </div>
            </label>

            <label>
              Selling Unit
              <select
                value={sellingUnit}
                onChange={(e) => setSellingUnit(e.target.value as 'packet' | 'kg')}
                style={{ padding: '8px' }}
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
              Active in sales
            </label>

            <label style={{ gridColumn: 'span 2' }}>
              Notes / Packaging Specs
              <input
                maxLength={500}
                placeholder="Packaging notes, barcode details, target market..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{ padding: '8px' }}
              />
            </label>

            <div className="actions" style={{ gridColumn: 'span 2', marginTop: '10px', display: 'flex', gap: '10px' }}>
              <button
                type="submit"
                style={{ background: '#047857', color: '#fff', padding: '10px 20px', fontWeight: 600 }}
              >
                {editingId ? '💾 Save Changes' : '💾 Save Product'}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={resetForm}
                style={{ padding: '10px 16px' }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Catalogue List & Filters */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
          {/* Category Filter Buttons */}
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {CATEGORIES.map((cat) => {
              const isSelected = selectedCategory === cat;
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => {
                    setSelectedCategory(cat);
                    setCurrentPage(1);
                  }}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.84rem',
                    borderRadius: '6px',
                    border: isSelected ? '1px solid #047857' : '1px solid #cbd5e1',
                    background: isSelected ? '#047857' : '#ffffff',
                    color: isSelected ? '#ffffff' : '#475569',
                    fontWeight: isSelected ? 600 : 500,
                    cursor: 'pointer',
                  }}
                >
                  {cat === 'ALL' ? 'All Products' : cat}
                </button>
              );
            })}
          </div>

          <div style={{ minWidth: '260px', flex: '1', maxWidth: '380px' }}>
            <input
              type="text"
              placeholder="🔍 Search product name, SKU, variant..."
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setCurrentPage(1);
              }}
              style={{ width: '100%', padding: '8px 12px', fontSize: '0.9rem' }}
            />
          </div>
        </div>

        {paginatedProducts.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product &amp; Variant</th>
                    <th>Category</th>
                    <th>Pack Size</th>
                    <th>Unit</th>
                    <th>Live Stock</th>
                    <th>Status</th>
                    {isManager && <th style={{ textAlign: 'right' }}>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {paginatedProducts.map((p) => {
                    const stockInfo = getProductStock(p.product_id);
                    return (
                      <tr key={p.product_id}>
                        <td>
                          <code>{p.sku}</code>
                        </td>
                        <td>
                          <strong>{p.product_name}</strong>
                          <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                            Variant: {p.variant}
                          </div>
                        </td>
                        <td>
                          <span style={{ fontSize: '0.78rem', background: '#f1f5f9', padding: '3px 8px', borderRadius: '4px', color: '#475569' }}>
                            {p.category}
                          </span>
                        </td>
                        <td>{p.pack_weight_g}g</td>
                        <td>{p.selling_unit}</td>
                        <td>
                          <strong style={{ color: stockInfo.quantity > 0 ? '#15803d' : '#b91c1c' }}>
                            {stockInfo.quantity}
                          </strong>{' '}
                          <small style={{ color: '#64748b' }}>{p.selling_unit}</small>
                        </td>
                        <td>
                          <span className={`badge ${p.active ? 'on' : 'off'}`}>
                            {p.active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        {isManager && (
                          <td style={{ textAlign: 'right' }}>
                            <div className="actions" style={{ justifyContent: 'flex-end', gap: '6px' }}>
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
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '14px', paddingTop: '10px', borderTop: '1px solid #f1f5f9' }}>
                <span style={{ fontSize: '0.84rem', color: '#64748b' }}>
                  Showing {(currentPage - 1) * PAGE_SIZE + 1} -{' '}
                  {Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length} products
                </span>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    type="button"
                    className="secondary"
                    disabled={currentPage === 1}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    style={{ padding: '5px 12px', fontSize: '0.82rem' }}
                  >
                    ◀ Previous
                  </button>
                  <span style={{ padding: '5px 10px', fontSize: '0.85rem', fontWeight: 600 }}>
                    Page {currentPage} of {totalPages}
                  </span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={currentPage === totalPages}
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    style={{ padding: '5px 12px', fontSize: '0.82rem' }}
                  >
                    Next ▶
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="muted" style={{ padding: '20px 0', textAlign: 'center' }}>
            No matching products found in catalogue.
          </p>
        )}
      </div>
    </div>
  );
};
