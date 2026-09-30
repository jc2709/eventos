'use strict';

// El servidor local usa SQLite en disco. Vercel ejecuta el mismo motor Python
// por petición y el navegador conserva la sesión independiente del alumno.
window.aulaRuntime = (() => {
  const STORAGE_KEY = 'aula-eda-session-v1';
  let mode = 'local', session = null, busy = false, storageAvailable = true;
  const ready = fetch('/runtime.json').then(async response => {
    if (!response.ok) throw new Error('No se pudo cargar la configuración');
    mode = (await response.json()).mode;
    if (mode !== 'cloud') return;
    try { session = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); }
    catch { session = null; storageAvailable = false; }
    document.getElementById('storage-note').hidden = false;
    document.getElementById('persistence-description').textContent = 'Recarga la página: el navegador conserva tu sesión. El progreso pertenece a este navegador y no se comparte con otros alumnos. El automático avanza mientras la pestaña está abierta. La versión local guarda los datos en SQLite.';
    document.getElementById('broker-storage').textContent = 'Motor Python · tu sesión en el navegador';
    document.getElementById('simplifications-description').textContent = 'Los módulos se ejecutan en Python con un broker educativo SQLite en memoria. Tu navegador conserva los registros entre peticiones. El automático procesa una entrega por petición mientras la pestaña está visible. No incluye Kafka, RabbitMQ, pagos reales, correo ni CEP completo.';
  });
  async function cloudRequest(action, data = {}) {
    busy = true;
    try {
      const response = await fetch('/api/lab', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action, data, session})
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || 'No se pudo completar la operación');
      session = value.session;
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(session)); }
      catch { storageAvailable = false; document.getElementById('storage-note').textContent = 'El navegador no permite guardar tu progreso. La práctica se conservará mientras esta pestaña siga abierta.'; }
      return value;
    } finally { busy = false; }
  }
  async function exchange(action, data) {
    await ready;
    if (mode === 'cloud') {
      // Web Locks mantiene ordenadas las acciones de varias pestañas del mismo
      // navegador. Se vuelve a leer la sesión dentro de la sección exclusiva.
      const run = async () => {
        try { const saved = storageAvailable && localStorage.getItem(STORAGE_KEY); if (saved) session = JSON.parse(saved); }
        catch { /* Mantener sesión en memoria si el almacenamiento está bloqueado. */ }
        return cloudRequest(action, data);
      };
      if (navigator.locks) return navigator.locks.request('aula-eda-session', run);
      return run();
    }
    const response = await fetch('/api/' + action, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data || {})});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'No se pudo completar la operación');
    return {result:value};
  }
  return {
    ready,
    isCloud: () => mode === 'cloud',
    isBusy: () => busy,
    command: exchange,
    async initial() {
      await ready;
      if (mode === 'cloud') return (await exchange('state')).state;
      const response = await fetch('/api/state');
      if (!response.ok) throw new Error('No se pudo consultar el estado');
      return response.json();
    },
    async tick(currentState) {
      await ready;
      if (mode !== 'cloud') return null;
      if (!currentState || busy || !currentState.settings.auto || document.hidden) return currentState;
      const pending = currentState.deliveries.some(d => ['pending','retry'].includes(d.status));
      if (!pending) return currentState;
      return (await exchange('step')).state;
    },
    async synchronize() {
      await ready;
      if (mode !== 'cloud') return null;
      return (await exchange('state')).state;
    }
  };
})();
