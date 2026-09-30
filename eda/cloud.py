"""Adaptador sin estado para Vercel. Reutiliza el mismo motor EDA de la versión local.

El navegador conserva una sesión JSON de práctica. Cada petición la restaura en
SQLite en memoria, ejecuta una acción y devuelve la nueva sesión. No existe un
archivo SQLite compartido ni se ejecuta SQL recibido del cliente.
"""
import json
import sqlite3
from .application import Application

SESSION_VERSION = 1
MAX_SESSION_BYTES = 1_000_000
COLUMNS = {
    'products': ('id', 'name', 'stock'),
    'orders': ('id', 'customer', 'product_id', 'quantity', 'status'),
    'events': ('seq', 'id', 'type', 'producer', 'correlation_id', 'occurred_at', 'version', 'payload'),
    'deliveries': ('id', 'event_id', 'consumer', 'status', 'attempts', 'error'),
    'traces': ('id', 'event_id', 'consumer', 'result', 'detail'),
    'notifications': ('id', 'event_id', 'order_id', 'message'),
    'shipping_state': ('order_id', 'reserved_seen', 'paid_seen', 'sent'),
    'settings': ('key', 'value'),
}


def export_session(app):
    with app.broker.lock:
        return {'version': SESSION_VERSION, 'tables': {
            table: [dict(row) for row in app.broker.db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in COLUMNS
        }}


def restore_session(app, session):
    if session is None:
        return
    if not isinstance(session, dict) or session.get('version') != SESSION_VERSION:
        raise ValueError('Versión de sesión incompatible. Reinicia el laboratorio.')
    tables = session.get('tables')
    if not isinstance(tables, dict) or set(tables) != set(COLUMNS):
        raise ValueError('La sesión guardada no tiene el formato esperado')
    if len(json.dumps(session, ensure_ascii=False).encode()) > MAX_SESSION_BYTES:
        raise ValueError('El laboratorio alcanzó su límite de historial. Reinícialo para otra práctica.')
    total = 0
    for table, columns in COLUMNS.items():
        rows = tables[table]
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('El laboratorio alcanzó su límite de registros. Reinícialo para otra práctica.')
        total += len(rows)
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError('Registro de sesión inválido')
            for value in row.values():
                if value is not None and type(value) not in (str, int):
                    raise ValueError('Valor de sesión inválido')
                if isinstance(value, str) and len(value) > 2048:
                    raise ValueError('Valor de sesión demasiado largo')
                if type(value) is int and not -(2**31) <= value < 2**31:
                    raise ValueError('Número de sesión inválido')
    if total > 5000:
        raise ValueError('El laboratorio alcanzó su límite de historial. Reinícialo para otra práctica.')
    if {row['key'] for row in tables['settings']} != {'auto', 'fail_notifications'}:
        raise ValueError('Configuración de sesión inválida')
    if len(tables['products']) != 3 or {p['id'] for p in tables['products']} != {'cuaderno', 'lapicero', 'mochila'}:
        raise ValueError('Inventario de sesión inválido')
    if any(type(p['stock']) is not int or not 0 <= p['stock'] <= 100 for p in tables['products']):
        raise ValueError('Stock de sesión inválido')
    if any(s['value'] not in (0, 1) for s in tables['settings']):
        raise ValueError('Configuración de sesión inválida')
    for event in tables['events']:
        try:
            payload = json.loads(event['payload'])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('Carga útil de evento inválida') from exc
        if not isinstance(payload, dict):
            raise ValueError('Carga útil de evento inválida')
    with app.broker.lock, app.broker.db:
        # El orden de eliminación respeta la referencia de deliveries a events.
        for table in reversed(COLUMNS):
            app.broker.db.execute(f'DELETE FROM {table}')
        for table, columns in COLUMNS.items():
            names = ','.join(columns)
            placeholders = ','.join('?' for _ in columns)
            app.broker.db.executemany(f'INSERT INTO {table} ({names}) VALUES ({placeholders})',
                                     [tuple(row[column] for column in columns) for row in tables[table]])


def execute_request(request):
    if not isinstance(request, dict):
        raise ValueError('Se requiere un objeto JSON')
    action, data = request.get('action', 'state'), request.get('data', {})
    if not isinstance(action, str) or not isinstance(data, dict):
        raise ValueError('Acción inválida')
    app = Application(':memory:')
    try:
        # Reset también recupera una sesión incompatible o demasiado grande.
        if action != 'reset':
            restore_session(app, request.get('session'))
        result = {'ok': True}
        if action == 'orders':
            result = {'order_id': app.create_order(data.get('customer'), data.get('product_id'), data.get('quantity'))}
        elif action == 'pay':
            app.pay(data.get('order_id'))
        elif action == 'step':
            result = {'delivery': app.broker.step()}
        elif action == 'settings':
            app.configure(data)
        elif action == 'retry':
            result = {'retried': app.broker.retry_failed()}
        elif action == 'reset':
            app.reset()
        elif action != 'state':
            raise ValueError('Acción inexistente')
        session = export_session(app)
        # Verificar también la salida permite preservar la sesión anterior si se
        # alcanza el límite, sin guardar una sesión que no se pueda restaurar.
        probe = Application(':memory:')
        try:
            restore_session(probe, session)
        finally:
            probe.broker.close()
        return {'result': result, 'state': app.snapshot(), 'session': session}
    except (sqlite3.Error, OverflowError) as exc:
        raise ValueError('No se pudo recuperar la sesión guardada. Reinicia el laboratorio.') from exc
    finally:
        app.broker.close()
