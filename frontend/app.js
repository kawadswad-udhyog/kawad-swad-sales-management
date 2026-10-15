const API = (window.KAWAD_API_URL || '').replace(/\/$/,'');
let token=localStorage.getItem('ks_token')||'', me=null;
const $=id=>document.getElementById(id);
async function request(path, options={}) {
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(token) headers.Authorization='Bearer '+token;
  const res=await fetch(API+path,{...options,headers});
  if(res.status===401){logout();throw new Error('Session expired. Please sign in again.')}
  const type=res.headers.get('content-type')||'';
  if(!res.ok){let msg='Request failed ('+res.status+')';try{const x=await res.json();msg=x.detail||msg}catch{}throw new Error(msg)}
  if(type.includes('application/pdf')||type.includes('spreadsheetml')) return res.blob();
  return res.json();
}
function showNotice(msg,error=false){$('notice').textContent=msg||'';$('notice').className=error?'error':''}
function logout(){token='';me=null;localStorage.removeItem('ks_token');$('app').classList.add('hidden');$('login').classList.remove('hidden');$('who').textContent='';$('logout').classList.add('hidden')}
$('logout').onclick=logout;
$('loginForm').onsubmit=async e=>{e.preventDefault();$('loginError').textContent='';try{const x=await request('/api/auth/login',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});token=x.access_token;me=x.user;localStorage.setItem('ks_token',token);await boot()}catch(err){$('loginError').textContent=err.message}};
async function boot(){try{me=await request('/api/auth/me');$('login').classList.add('hidden');$('app').classList.remove('hidden');$('who').textContent=me.full_name+' · '+me.role;$('logout').classList.remove('hidden');document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('hidden',me.role==='SALESMAN'&&['dashboard','reports'].includes(b.dataset.view)));await view('dashboard')}catch(e){showNotice(e.message,true)}}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>view(b.dataset.view));
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function table(rows,columns){if(!rows.length)return '<p class="muted">No records found yet.</p>';return '<div class="table-wrap"><table><thead><tr>'+columns.map(c=>'<th>'+esc(c[1])+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+columns.map(c=>'<td>'+esc(r[c[0]])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'}
async function view(name){document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===name));showNotice('');const v=$('view');v.innerHTML='<div class="card">Loading…</div>';try{
 if(name==='dashboard'){if(me.role==='SALESMAN'){v.innerHTML='<div class="card"><h2>Field workspace</h2><p>Use Sales, Customers, Expenses and Shop Visits to record today’s work.</p></div>';return}const d=await request('/api/dashboard');v.innerHTML=`<h1>Dashboard</h1><div class="grid"><div class="metric">Today’s bills<strong>${d.daily.bills}</strong></div><div class="metric">Today’s revenue<strong>₹${Number(d.daily.revenue).toFixed(2)}</strong></div><div class="metric">Month bills<strong>${d.monthly.bills}</strong></div><div class="metric">Month revenue<strong>₹${Number(d.monthly.revenue).toFixed(2)}</strong></div><div class="metric">Pending expenses<strong>${d.pending_expenses}</strong></div><div class="metric">Pending closings<strong>${d.pending_closings}</strong></div></div>`}
 if(name==='products'){
   let rows=await request('/api/products');
   const renderProducts=(filter='')=>{
     const shown=rows.filter(p=>[p.sku,p.product_name,p.category,p.variant].join(' ').toLowerCase().includes(filter.toLowerCase()));
     v.innerHTML=`<h1>Product catalogue</h1>
       <div class="card"><h2 id="productFormTitle">Add product</h2>
       <form id="productForm" class="inline">
       <label>SKU<input name="sku" required maxlength="60" placeholder="KS-MMP-200"></label>
       <label>Product name<input name="product_name" required maxlength="120"></label>
       <label>Category<select name="category"><option>Papad</option><option>Masala</option><option>Katran</option></select></label>
       <label>Variant<input name="variant" value="Plain" required></label>
       <label>Pack weight (g)<input name="pack_weight_g" type="number" min="1" step="1" required></label>
       <label>Selling unit<select name="selling_unit"><option value="packet">packet</option><option value="kg">kg</option></select></label>
       <label class="check-label"><input name="retail_pack_only" type="checkbox" checked> Retail pack only</label>
       <label class="check-label"><input name="active" type="checkbox" checked> Active product</label>
       <label>Notes<input name="notes" maxlength="500"></label>
       <div class="actions"><button id="productSave">Save product</button><button type="button" id="productCancel" class="secondary hidden">Cancel edit</button></div>
       </form><p class="muted">SKU must be unique. To protect sales history, editing a product does not change its SKU.</p></div>
       <div class="card"><div class="toolbar"><h2>Catalogue <span class="count">${shown.length}</span></h2><input id="productSearch" placeholder="Search SKU, product, variant…" value="${esc(filter)}"></div>
       ${shown.length?`<div class="table-wrap"><table><thead><tr><th>SKU</th><th>Product</th><th>Category</th><th>Variant</th><th>Pack g</th><th>Unit</th><th>Status</th><th>Action</th></tr></thead><tbody>${shown.map(p=>`<tr><td>${esc(p.sku)}</td><td>${esc(p.product_name)}</td><td>${esc(p.category)}</td><td>${esc(p.variant)}</td><td>${esc(p.pack_weight_g)}</td><td>${esc(p.selling_unit)}</td><td><span class="badge ${p.active===false||String(p.active).toLowerCase()==='false'?'off':'on'}">${p.active===false||String(p.active).toLowerCase()==='false'?'Inactive':'Active'}</span></td><td><div class="actions"><button class="secondary edit-product" data-id="${esc(p.product_id)}">Edit</button><button class="secondary toggle-product" data-id="${esc(p.product_id)}">${p.active===false||String(p.active).toLowerCase()==='false'?'Activate':'Deactivate'}</button></div></td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">No matching products.</p>'}</div>`;
     $('productSearch').oninput=e=>{const pos=e.target.selectionStart;renderProducts(e.target.value);const input=$('productSearch');input.focus();input.setSelectionRange(pos,pos)};
     $('productForm').onsubmit=async e=>{
       e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));
       d.pack_weight_g=Number(d.pack_weight_g);d.retail_pack_only=f.elements.retail_pack_only.checked;d.active=f.elements.active.checked;
       try{
         if(f.dataset.editId){const id=f.dataset.editId;delete d.sku;await request('/api/products/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify(d)});showNotice('Product updated.')}
         else {await request('/api/products',{method:'POST',body:JSON.stringify(d)});showNotice('Product added to catalogue.')}
         rows=await request('/api/products');renderProducts($('productSearch')?.value||'');
       }catch(err){showNotice(err.message,true)}
     };
     $('productCancel').onclick=()=>renderProducts($('productSearch').value);
     document.querySelectorAll('.edit-product').forEach(b=>b.onclick=()=>{
       const p=rows.find(x=>x.product_id===b.dataset.id);if(!p)return;
       const f=$('productForm');f.dataset.editId=p.product_id;
       for(const k of ['sku','product_name','category','variant','pack_weight_g','selling_unit','notes'])if(f.elements[k])f.elements[k].value=p[k]??'';
       f.elements.sku.disabled=true;f.elements.retail_pack_only.checked=!(p.retail_pack_only===false||String(p.retail_pack_only).toLowerCase()==='false');
       f.elements.active.checked=!(p.active===false||String(p.active).toLowerCase()==='false');
       $('productFormTitle').textContent='Edit product';$('productSave').textContent='Save changes';$('productCancel').classList.remove('hidden');window.scrollTo({top:0,behavior:'smooth'});
     });
     document.querySelectorAll('.toggle-product').forEach(b=>b.onclick=async()=>{
       const p=rows.find(x=>x.product_id===b.dataset.id);if(!p)return;
       const isActive=!(p.active===false||String(p.active).toLowerCase()==='false');
       if(!confirm(`${isActive?'Deactivate':'Activate'} ${p.product_name}?`))return;
       try{await request('/api/products/'+encodeURIComponent(p.product_id),{method:'PATCH',body:JSON.stringify({active:!isActive})});rows=await request('/api/products');showNotice('Product status updated.');renderProducts($('productSearch')?.value||'')}catch(err){showNotice(err.message,true)}
     });
   };
   renderProducts();
 }
 if(name==='customers'){
   let rows=await request('/api/customers');
   const renderCustomers=(filter='')=>{
     const shown=rows.filter(c=>[c.customer_id,c.shop_name,c.customer_type,c.shopkeeper_name,c.mobile,c.locality_area,c.city].join(' ').toLowerCase().includes(filter.toLowerCase()));
     v.innerHTML=`<h1>Customer & retailer management</h1>
       <div class="card"><h2>Add customer / trade partner</h2><form id="customerForm" class="inline">
       <label>Customer type<select name="customer_type"><option>RETAIL</option><option>RETAILER</option><option>WHOLESALER</option><option>DISTRIBUTOR</option></select></label>
       <label>Shop / business name<input name="shop_name" required maxlength="150"></label>
       <label>Contact person<input name="shopkeeper_name" maxlength="100"></label>
       <label>Mobile<input name="mobile" inputmode="tel" maxlength="20"></label>
       <label>Alternate mobile<input name="alternate_mobile" inputmode="tel" maxlength="20"></label>
       <label>Area / locality<input name="locality_area" maxlength="100"></label>
       <label>City / village<input name="city" maxlength="100"></label>
       <label>Address<textarea name="address" rows="2" maxlength="500"></textarea></label>
       <label>Map location / link<input name="map_location" maxlength="300"></label>
       <label>Notes<input name="notes" maxlength="500"></label><button>Add customer</button></form>
       <p class="muted">Use one record per shop or trade partner. Check the list before adding to reduce duplicates.</p></div>
       <div class="card"><div class="toolbar"><h2>Customers <span class="count">${shown.length}</span></h2><input id="customerSearch" placeholder="Search shop, phone, area…" value="${esc(filter)}"></div>
       ${shown.length?`<div class="table-wrap"><table><thead><tr><th>Customer ID</th><th>Shop / business</th><th>Type</th><th>Contact</th><th>Mobile</th><th>Area</th><th>City</th><th>Status</th></tr></thead><tbody>${shown.map(c=>`<tr><td>${esc(c.customer_id)}</td><td>${esc(c.shop_name)}</td><td>${esc(c.customer_type)}</td><td>${esc(c.shopkeeper_name)}</td><td>${esc(c.mobile)}</td><td>${esc(c.locality_area)}</td><td>${esc(c.city)}</td><td><span class="badge ${c.active===false||String(c.active).toLowerCase()==='false'?'off':'on'}">${c.active===false||String(c.active).toLowerCase()==='false'?'Inactive':'Active'}</span></td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">No matching customers.</p>'}</div>`;
     $('customerSearch').oninput=e=>{const pos=e.target.selectionStart;renderCustomers(e.target.value);const input=$('customerSearch');input.focus();input.setSelectionRange(pos,pos)};
     $('customerForm').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));d.active=true;try{await request('/api/customers',{method:'POST',body:JSON.stringify(d)});showNotice('Customer saved.');rows=await request('/api/customers');renderCustomers('')}catch(err){showNotice(err.message,true)}};
   };
   renderCustomers();
 }
 if(name==='sales'){
   const [allCustomers,allProducts,initialSales]=await Promise.all([request('/api/customers'),request('/api/products'),request('/api/sales')]);
   const customers=allCustomers.filter(c=>!(c.active===false||String(c.active).toLowerCase()==='false'));
   const products=allProducts.filter(p=>!(p.active===false||String(p.active).toLowerCase()==='false'));
   let cart=[];
   const money=n=>'₹'+Number(n||0).toFixed(2);
   const productOptions=products.map(p=>`<option value="${esc(p.product_id)}">${esc(p.product_name)} · ${esc(p.sku)}${p.pack_weight_g?' · '+esc(p.pack_weight_g)+'g':''}</option>`).join('');
   v.innerHTML=`<h1>Sales, Billing & Payments</h1>
   <div class="card"><h2>Create bill</h2><form id="saleForm">
   <div class="inline"><label>Customer / trade partner<select name="customer_id" required>${customers.map(c=>`<option value="${esc(c.customer_id)}">${esc(c.shop_name)} · ${esc(c.customer_type)} (${esc(c.customer_id)})</option>`).join('')}</select></label>
   <label>Sale type<select name="sales_type"><option>RETAIL</option><option>RETAILER</option><option>WHOLESALER</option><option>DISTRIBUTOR</option></select></label>
   <label>Payment method<select name="payment_method"><option value="CASH">Cash</option><option value="UPI">UPI</option><option value="BANK_TRANSFER">Bank transfer</option><option value="OTHER">Other approved method</option></select></label>
   <label>Payment reference<input name="payment_reference" maxlength="150" placeholder="UPI / bank reference (if any)"></label></div>
   <div class="table-wrap"><table><thead><tr><th>Product</th><th style="min-width:90px">Quantity</th><th style="min-width:130px">Actual unit price ₹</th><th>Line total</th><th></th></tr></thead><tbody id="cartRows"></tbody></table></div>
   <div class="actions"><button type="button" class="secondary" id="addLine">+ Add product line</button></div>
   <div class="inline"><label>Discount ₹<input name="discount_amount" type="number" min="0" step="0.01" value="0"></label><label>Bill notes<input name="notes" maxlength="500"></label><div class="metric">Bill total<strong id="billTotal">₹0.00</strong></div></div>
   <p class="muted">Only issue the bill after the full amount has been received. Prices are the actual prices charged on this sale. Issued bills are not silently overwritten. Stock deduction is a separate next development stage and is not yet applied automatically.</p>
   <button id="issueBill" type="submit">Issue bill + record full payment</button></form><div id="billResult"></div></div>
   <div class="card"><div class="toolbar"><h2>Recent bills</h2><input id="saleSearch" placeholder="Search bill or customer"></div><div id="salesTable"></div></div>`;
   const rowsEl=$('cartRows');
   function drawCart(){
     rowsEl.innerHTML=cart.map((line,i)=>`<tr><td><select class="cart-product" data-i="${i}" required>${products.map(p=>`<option value="${esc(p.product_id)}" ${p.product_id===line.product_id?'selected':''}>${esc(p.product_name)} · ${esc(p.sku)}${p.pack_weight_g?' · '+esc(p.pack_weight_g)+'g':''}</option>`).join('')}</select></td><td><input class="cart-qty" data-i="${i}" type="number" min="0.001" step="0.001" value="${esc(line.quantity)}" required></td><td><input class="cart-price" data-i="${i}" type="number" min="0" step="0.01" value="${esc(line.actual_unit_price)}" required></td><td>${money(Number(line.quantity||0)*Number(line.actual_unit_price||0))}</td><td><button type="button" class="secondary remove-line" data-i="${i}" ${cart.length===1?'disabled':''}>Remove</button></td></tr>`).join('');
     const subtotal=cart.reduce((sum,l)=>sum+Number(l.quantity||0)*Number(l.actual_unit_price||0),0);const discount=Number($('saleForm').elements.discount_amount.value||0);$('billTotal').textContent=money(Math.max(0,subtotal-discount));
     document.querySelectorAll('.cart-product').forEach(el=>el.onchange=()=>{cart[Number(el.dataset.i)].product_id=el.value;drawCart()});
     document.querySelectorAll('.cart-qty').forEach(el=>el.oninput=()=>{cart[Number(el.dataset.i)].quantity=el.value;updateCartTotals()});
     document.querySelectorAll('.cart-price').forEach(el=>el.oninput=()=>{cart[Number(el.dataset.i)].actual_unit_price=el.value;updateCartTotals()});
     document.querySelectorAll('.remove-line').forEach(el=>el.onclick=()=>{cart.splice(Number(el.dataset.i),1);drawCart()});
   }
   function updateCartTotals(){const subtotal=cart.reduce((sum,l)=>sum+Number(l.quantity||0)*Number(l.actual_unit_price||0),0);const discount=Number($('saleForm').elements.discount_amount.value||0);$('billTotal').textContent=money(Math.max(0,subtotal-discount));rowsEl.querySelectorAll('tr').forEach((tr,i)=>{const cell=tr.children[3];if(cell)cell.textContent=money(Number(cart[i].quantity||0)*Number(cart[i].actual_unit_price||0))})}
   function renderSales(filter=''){const shown=initialSales.slice().reverse().filter(s=>[s.bill_number,s.customer_name_snapshot,s.sales_type,s.payment_status].join(' ').toLowerCase().includes(filter.toLowerCase())).slice(0,100);$('salesTable').innerHTML=shown.length?`<div class="table-wrap"><table><thead><tr><th>Bill</th><th>Date</th><th>Customer</th><th>Type</th><th>Total</th><th>Payment</th><th>Invoice</th></tr></thead><tbody>${shown.map(s=>`<tr><td>${esc(s.bill_number)}</td><td>${esc(s.sale_datetime)}</td><td>${esc(s.customer_name_snapshot)}</td><td>${esc(s.sales_type)}</td><td>${money(s.bill_total)}</td><td>${esc(s.payment_status)}</td><td><button type="button" class="secondary invoice-btn" data-id="${esc(s.sale_id)}" data-bill="${esc(s.bill_number)}">PDF</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">No matching bills.</p>';document.querySelectorAll('.invoice-btn').forEach(b=>b.onclick=()=>downloadInvoice(b.dataset.id,b.dataset.bill));}
   async function downloadInvoice(id,bill){try{const blob=await request('/api/sales/'+encodeURIComponent(id)+'/invoice');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=(bill||'Kawad-Swad-Bill')+'.pdf';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500)}catch(err){showNotice('Invoice could not be generated: '+err.message,true)}}
   $('addLine').onclick=()=>{if(!products.length){showNotice('Add an active product before making a bill.',true);return}cart.push({product_id:products[0].product_id,quantity:1,actual_unit_price:0});drawCart()};
   $('saleForm').elements.discount_amount.oninput=updateCartTotals;
   $('saleForm').onsubmit=async e=>{e.preventDefault();if(!cart.length){showNotice('Add at least one product line.',true);return}const f=e.target;const subtotal=cart.reduce((sum,l)=>sum+Number(l.quantity||0)*Number(l.actual_unit_price||0),0);const discount=Number(f.elements.discount_amount.value||0);if(discount>subtotal){showNotice('Discount cannot exceed subtotal.',true);return}if(!confirm('Confirm bill total '+money(subtotal-discount)+' and confirm the full payment has been received?'))return;const d={customer_id:f.elements.customer_id.value,sales_type:f.elements.sales_type.value,payment_method:f.elements.payment_method.value,payment_reference:f.elements.payment_reference.value,discount_amount:discount,notes:f.elements.notes.value,delivery_status:'DELIVERED',lines:cart.map(l=>({product_id:l.product_id,quantity:Number(l.quantity),actual_unit_price:Number(l.actual_unit_price)}))};try{$('issueBill').disabled=true;const r=await request('/api/sales',{method:'POST',body:JSON.stringify(d)});$('billResult').innerHTML=`<div class="notice-success"><strong>Bill issued: ${esc(r.sale.bill_number)}</strong><p>Total: ${money(r.sale.bill_total)} · Payment: ${esc(d.payment_method)} · ${esc(r.sale.payment_status)}</p><button type="button" id="newBillInvoice">Download invoice PDF</button></div>`; $('newBillInvoice').onclick=()=>downloadInvoice(r.sale.sale_id,r.sale.bill_number);showNotice('Bill issued and full payment recorded.');cart=[{product_id:products[0]?.product_id||'',quantity:1,actual_unit_price:0}].filter(x=>x.product_id);drawCart();f.elements.discount_amount.value='0';f.elements.notes.value='';f.elements.payment_reference.value='';initialSales.unshift(r.sale);renderSales($('saleSearch').value||'')}catch(err){showNotice(err.message,true)}finally{$('issueBill').disabled=false}};
   $('saleSearch').oninput=e=>renderSales(e.target.value);cart=[{product_id:products[0]?.product_id||'',quantity:1,actual_unit_price:0}].filter(x=>x.product_id);drawCart();renderSales();
 }
 if(name==='expenses'){v.innerHTML='<h1>Expenses</h1><div class="card"><form id="expenseForm" class="inline"><label>Category<select name="category"><option>TRAVEL</option><option>DELIVERY</option><option>OTHER</option></select></label><label>Amount ₹<input name="amount" type="number" min=".01" step=".01" required></label><label>Description<input name="description" required></label><label>Receipt link/reference<input name="receipt_link_or_file_ref"></label><button>Submit expense for approval</button></form></div>';const rows=await request('/api/sales/Expenses').catch(()=>[]);$('expenseForm').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));d.amount=Number(d.amount);try{await request('/api/expenses',{method:'POST',body:JSON.stringify(d)});showNotice('Expense submitted');view('expenses')}catch(err){showNotice(err.message,true)}}}
 if(name==='visits'){const customers=await request('/api/customers');v.innerHTML='<h1>Shop visits</h1><div class="card"><form id="visitForm" class="inline"><label>Shop<select name="customer_id">'+customers.map(c=>`<option value="${esc(c.customer_id)}">${esc(c.shop_name)}</option>`).join('')+'</select></label><label>Outcome<input name="visit_outcome" required placeholder="Order / follow-up / closed"></label><label>Next action<input name="next_action"></label><label>Follow-up date<input name="follow_up_date" type="date"></label><label>Order taken<select name="order_taken"><option value="false">No</option><option value="true">Yes</option></select></label><button>Save visit</button></form></div>';$('visitForm').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));d.order_taken=d.order_taken==='true';try{await request('/api/visits',{method:'POST',body:JSON.stringify(d)});showNotice('Visit saved');e.target.reset()}catch(err){showNotice(err.message,true)}}}
 if(name==='reports'){v.innerHTML='<h1>Reports & Exports</h1><div class="card"><p>Export a permitted worksheet to Excel.</p><div class="actions">'+['Sales','SaleItems','Payments','Customers','Products','Expenses','DailyClosing','SalaryIncentives'].map(x=>`<button data-export="${x}">${x}.xlsx</button>`).join('')+'</div></div><div class="card"><label>Monthly report (YYYY-MM)<input id="month" type="month" value="${new Date().toISOString().slice(0,7)}"></label><button id="monthly">View monthly report</button><pre id="report"></pre></div>';document.querySelectorAll('[data-export]').forEach(b=>b.onclick=async()=>{try{const blob=await request('/api/exports/'+b.dataset.export+'.xlsx');const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=b.dataset.export+'.xlsx';a.click();URL.revokeObjectURL(a.href)}catch(err){showNotice(err.message,true)}});$('monthly').onclick=async()=>{try{$('report').textContent=JSON.stringify(await request('/api/reports/monthly?month='+$('month').value),null,2)}catch(err){showNotice(err.message,true)}}}
 }catch(err){v.innerHTML='<div class="card errorbox">'+esc(err.message)+'</div>'}}
if(token)boot();
