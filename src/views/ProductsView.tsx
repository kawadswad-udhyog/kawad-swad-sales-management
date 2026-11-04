import React, { useState, useMemo } from 'react';
import { useStore } from '../context/StoreContext';
import { Product } from '../types';
import { Package } from 'lucide-react';
import {
  FormLayout,
  FormSection,
  FormField,
  TextInput,
  SelectInput,
  QuantityInput,
  TextArea,
  FormActions,
  SaveButton,
  CancelButton,
} from '../components/common/FormComponents';

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
    refreshData,
    isRefreshing,
  } = useStore();

  const isManager = currentUser?.role === 'OWNER' || currentUser?.role === 'PA';

  const [filter, setFilter] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotice(null);

    try {
      if (editingId) {
        // Update product (SKU is immutable)
        await updateProduct(editingId, {
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
        setNotice({ msg: `✅ Product "${productName.trim()}" updated successfully.` });
        resetForm();
      } else {
        // Check SKU uniqueness
        if (products.some((p) => p.sku.toLowerCase() === sku.trim().toLowerCase())) {
          setNotice({ msg: 'A product with this SKU already exists.', error: true });
          return;
        }

        await addProduct({
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
        setNotice({ msg: `✅ Product "${productName.trim()}" added to catalogue successfully.` });
        resetForm();
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to save product';
      setNotice({ msg: errorMsg, error: true });
    }
  };

  const handleToggleActive = async (p: Product) => {
    setUpdatingId(p.product_id);
    setNotice(null);
    try {
      const nextState = !p.active;
      await toggleProductActive(p.product_id);
      setNotice({
        msg: `✅ "${p.product_name}" is now ${nextState ? 'ACTIVE (visible in Sales & Billing)' : 'INACTIVE (hidden from Sales)'}.`,
        error: false,
      });
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to toggle product status';
      setNotice({ msg: errorMsg, error: true });
    } finally {
      setUpdatingId(null);
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
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            type="button"
            className="secondary"
            onClick={refreshData}
            disabled={isRefreshing}
            style={{ padding: '8px 14px', fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: '6px' }}
            title="Reload products from backend database"
          >
            <span>{isRefreshing ? '⏳' : '↻'}</span>
            <span>{isRefreshing ? 'Refreshing…' : 'Refresh'}</span>
          </button>
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
      </div>

      {notice && (
        <div className={notice.error ? 'notice-error' : 'notice-success'} style={{ marginBottom: '16px' }}>
          {notice.msg}
        </div>
      )}

      {/* Product Form using FormComponents */}
      {isManager && isFormOpen && (
        <div className="mb-6">
          <FormLayout
            title={editingId ? 'Edit Product Details' : 'Add New Product to Catalogue'}
            subtitle={editingId ? 'SKU is locked to preserve billing history' : 'Define SKU, formulation category, and retail packaging specs'}
            icon={<Package size={18} />}
            maxWidth="3xl"
            onSubmit={handleSubmit}
            onCancel={resetForm}
            actions={
              <FormActions
                onCancel={resetForm}
                cancelLabel="Cancel"
                saveLabel={editingId ? 'Save Changes' : 'Save Product'}
              />
            }
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <FormField
                label="SKU Code"
                required
                helpText={editingId ? 'SKU is immutable after creation' : 'Unique identifier (e.g. KS-MMP-200)'}
              >
                <TextInput
                  required
                  maxLength={60}
                  placeholder="e.g. KS-MMP-200"
                  value={sku}
                  onChange={(e) => setSku(e.target.value)}
                  disabled={!!editingId}
                />
              </FormField>

              <FormField label="Product Name" required helpText="Catalogue name displayed on invoices">
                <TextInput
                  required
                  maxLength={120}
                  placeholder="e.g. Moong Masala Papad 200g"
                  value={productName}
                  onChange={(e) => setProductName(e.target.value)}
                />
              </FormField>

              <FormField label="Category">
                <SelectInput
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  options={[
                    { value: 'Papad', label: 'Papad' },
                    { value: 'Masala', label: 'Masala' },
                    { value: 'Katran', label: 'Katran' },
                  ]}
                />
              </FormField>

              <FormField label="Variant" required helpText="Taste or spice formulation">
                <TextInput
                  required
                  value={variant}
                  onChange={(e) => setVariant(e.target.value)}
                  placeholder="e.g. Plain, Spicy, Jeera, Special"
                />
              </FormField>

              <FormField label="Pack Net Weight (grams)" required helpText="Select preset or enter exact grams">
                <div className="space-y-1.5">
                  <QuantityInput
                    unit="g"
                    min={1}
                    step={1}
                    value={packWeightG}
                    onChange={(val) => setPackWeightG(val)}
                  />
                  <div className="flex gap-1.5">
                    {[200, 500, 1000].map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => setPackWeightG(preset)}
                        className={`px-2 py-0.5 text-[11px] font-semibold rounded-md transition-colors cursor-pointer ${
                          packWeightG === preset
                            ? 'bg-[#0F2C23] text-white'
                            : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                        }`}
                      >
                        {preset >= 1000 ? `${preset / 1000}kg` : `${preset}g`}
                      </button>
                    ))}
                  </div>
                </div>
              </FormField>

              <FormField label="Selling Unit">
                <SelectInput
                  value={sellingUnit}
                  onChange={(e) => setSellingUnit(e.target.value as 'packet' | 'kg')}
                  options={[
                    { value: 'packet', label: 'packet' },
                    { value: 'kg', label: 'kg' },
                  ]}
                />
              </FormField>

              <div className="sm:col-span-2 lg:col-span-3 flex items-center gap-6 pt-1">
                <label className="flex items-center gap-2 cursor-pointer select-none text-xs font-semibold text-slate-700">
                  <input
                    type="checkbox"
                    checked={retailPackOnly}
                    onChange={(e) => setRetailPackOnly(e.target.checked)}
                    className="w-4 h-4 rounded text-[#0F2C23] focus:ring-[#0F2C23]"
                  />
                  <span>Retail pack only</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer select-none text-xs font-semibold text-slate-700">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(e) => setActive(e.target.checked)}
                    className="w-4 h-4 rounded text-[#0F2C23] focus:ring-[#0F2C23]"
                  />
                  <span>Active for Sales & Billing</span>
                </label>
              </div>

              <div className="sm:col-span-2 lg:col-span-3">
                <FormField label="Notes / Packaging Specs" helpText="Barcode details, carton dimensions, or market restrictions">
                  <TextInput
                    maxLength={500}
                    placeholder="Packaging notes, barcode details, target market..."
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />
                </FormField>
              </div>
            </div>
          </FormLayout>
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
                                type="button"
                                onClick={() => handleToggleActive(p)}
                                disabled={updatingId === p.product_id}
                                style={{
                                  padding: '4px 10px',
                                  fontSize: '0.8rem',
                                  borderRadius: '4px',
                                  fontWeight: 600,
                                  cursor: updatingId === p.product_id ? 'not-allowed' : 'pointer',
                                  background: p.active ? '#fef2f2' : '#ecfdf5',
                                  color: p.active ? '#991b1b' : '#065f46',
                                  border: p.active ? '1px solid #fecaca' : '1px solid #a7f3d0',
                                }}
                              >
                                {updatingId === p.product_id ? 'Saving…' : p.active ? '✕ Deactivate' : '✓ Activate'}
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
