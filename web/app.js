'use strict';
const $ = (id) => document.getElementById(id);
const labels = {created:'Creado',reserved:'Reservado',paid:'Pagado',shipped:'Envío iniciado',rejected:'Rechazado',pending:'Pendiente',retry:'Reintento',failed:'Fallido',done:'Completado'};
let state = null, selectedEvent = null, refreshing = false;
const escape = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short = value => value.slice(0,8);
const badge = status => `<span class="badge ${escape(status)}">${labels[status] || escape(status)}</span>`;
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
async function command(route, data = {}) {
  try {
    const res = await fetch('/api/' + route, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const value = await res.json();
    if (!res.ok) throw new Error(value.error || 'No se pudo completar la operación');
    showError('');
    await refresh();
    return value;
  } catch (error) { showError(error.message); return null; }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const res = await fetch('/api/state');
    if (!res.ok) throw new Error('No se pudo consultar el estado');
    state = await res.json(); render();
    if ($('error').textContent.startsWith('No se puede conectar')) showError('');
  } catch { showError('No se puede conectar con el servidor. Comprueba que python server.py siga ejecutándose.'); }
  finally { refreshing = false; }
}
function render() {
  const productSelected = $('product').value;
  const options = state.products.map(p => `<option value="${escape(p.id)}">${escape(p.name)} · ${p.stock} disponibles</option>`).join('');
  if ($('product').innerHTML !== options) {
    $('product').innerHTML = options;
    if (productSelected) $('product').value = productSelected;
  }
  $('stock').innerHTML = state.products.map(p => `<div class="stock-row"><span>${escape(p.name)}</span><strong>${p.stock}</strong></div>`).join('');
  const products = Object.fromEntries(state.products.map(p => [p.id,p.name]));
  $('orders').innerHTML = state.orders.length ? [...state.orders].reverse().map(o => `<tr><td><code>${short(o.id)}</code></td><td>${escape(o.customer)}<small>${escape(products[o.product_id])}</small></td><td>${o.quantity}</td><td>${badge(o.status)}</td><td>${o.status === 'reserved' ? `<button class="quiet" data-pay="${o.id}">Simular pago</button>` : '<span aria-label="Sin acciones disponibles">—</span>'}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">Todavía no hay pedidos. Crea el primero para observar su recorrido.</td></tr>';
  const count = status => state.deliveries.filter(d => status.includes(d.status)).length;
  $('event-count').textContent = state.events.length;
  $('pending-count').textContent = count(['pending','retry']);
  $('done-count').textContent = count(['done']);
  $('failed-count').textContent = count(['failed']);
  $('auto').textContent = state.settings.auto ? 'Pausar automático' : 'Activar automático';
  $('mode').textContent = state.settings.auto ? 'Una entrega cada 0,6 s' : 'Modo paso a paso';
  $('step').disabled = state.settings.auto || !count(['pending','retry']);
  $('retry').disabled = !count(['failed']);
  $('failure').checked = state.settings.fail_notifications;
  const last = state.traces.at(-1);
  document.querySelectorAll('[data-consumer]').forEach(el => {
    el.classList.toggle('active', !!last && el.dataset.consumer === last.consumer && last.result === 'done');
    el.classList.toggle('error', !!last && el.dataset.consumer === last.consumer && last.result !== 'done');
  });
  $('latest').textContent = last ? `${last.consumer} · ${labels[last.result]}: ${last.detail}` : (state.events.length ? 'El evento ya está publicado. Procesa una entrega para que un consumidor reaccione.' : 'Crea tu primer pedido. Su evento quedará pendiente hasta que lo proceses.');
  if (!state.events.some(e => e.id === selectedEvent)) selectedEvent = state.events.at(-1)?.id || null;
  $('events').innerHTML = state.events.length ? [...state.events].reverse().map(e => `<button class="event-button ${e.id === selectedEvent ? 'selected' : ''}" aria-pressed="${e.id === selectedEvent}" data-event="${e.id}">${e.seq.toString().padStart(2,'0')} · ${escape(e.type)}<small>${escape(e.producer)} · Pedido ${short(e.correlation_id)}</small></button>`).join('') : '<div class="empty">Aquí aparecerán los hechos publicados.</div>';
  renderDetail();
  $('notifications').innerHTML = state.notifications.length ? [...state.notifications].reverse().map(n => `<div class="message">${escape(n.message)}<small>Pedido ${short(n.order_id)} · Notificación simulada</small></div>`).join('') : '<p class="empty">Los mensajes aparecerán cuando Notificaciones consuma un evento.</p>';
}
function renderDetail() {
  const event = state.events.find(e => e.id === selectedEvent);
  if (!event) { $('event-detail').textContent = 'Todavía no hay eventos. Crea un pedido para empezar.'; return; }
  const {seq, ...contract} = event;
  const deliveries = state.deliveries.filter(d => d.event_id === event.id);
  $('event-detail').innerHTML = `<h3>Contrato del evento</h3><pre>${escape(JSON.stringify(contract,null,2))}</pre><h3>Entregas a suscriptores</h3>${deliveries.map(d => `<div class="delivery-row"><span>${escape(d.consumer)}<br><small>${d.attempts} intentos${d.error ? ' · ' + escape(d.error) : ''}</small></span>${badge(d.status)}</div>`).join('') || '<p>No hay suscriptores para este tipo de evento.</p>'}`;
}
$('order-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  await command('orders',{customer:$('customer').value,product_id:$('product').value,quantity:Number($('quantity').value)});
  button.disabled = false;
});
$('orders').addEventListener('click', e => { const button = e.target.closest('[data-pay]'); if (button) { button.disabled = true; command('pay',{order_id:button.dataset.pay}); } });
$('events').addEventListener('click', e => { const button = e.target.closest('[data-event]'); if (button) { selectedEvent = button.dataset.event; render(); } });
$('step').addEventListener('click', () => command('step'));
$('auto').addEventListener('click', () => state && command('settings',{auto:!state.settings.auto}));
$('failure').addEventListener('change', e => command('settings',{fail_notifications:e.target.checked}));
$('retry').addEventListener('click', () => command('retry'));
$('reset').addEventListener('click', () => { if (confirm('¿Borrar pedidos, eventos y mensajes de este laboratorio y restaurar el stock?')) { selectedEvent = null; command('reset'); } });
refresh(); setInterval(refresh,800);
