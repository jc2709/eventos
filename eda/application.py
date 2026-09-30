"""Productores y consultas de la aplicación. Todos los cambios son transaccionales."""
import json
import uuid
from .broker import Broker
from .consumers import register_consumers


class Application:
    def __init__(self, path):
        self.broker = Broker(path)
        self.broker.db.executescript('''
        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT,stock INTEGER CHECK(stock>=0));
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,customer TEXT,product_id TEXT,
          quantity INTEGER CHECK(quantity>0),status TEXT);
        CREATE TABLE IF NOT EXISTS shipping_state(order_id TEXT PRIMARY KEY,
          reserved_seen INTEGER DEFAULT 0, paid_seen INTEGER DEFAULT 0, sent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,event_id TEXT UNIQUE,
          order_id TEXT,message TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value INTEGER);
        INSERT OR IGNORE INTO products VALUES('cuaderno','Cuaderno universitario',8);
        INSERT OR IGNORE INTO products VALUES('lapicero','Lapicero azul',12);
        INSERT OR IGNORE INTO products VALUES('mochila','Mochila',3);
        INSERT OR IGNORE INTO settings VALUES('auto',0);
        INSERT OR IGNORE INTO settings VALUES('fail_notifications',0);
        ''')
        register_consumers(self)

    def setting(self, key):
        with self.broker.lock:
            return bool(self.broker.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()['value'])

    def configure(self, data):
        with self.broker.lock, self.broker.db:
            for key, value in data.items():
                if key not in {'auto', 'fail_notifications'} or not isinstance(value, bool):
                    raise ValueError('Configuración inválida')
                self.broker.db.execute('UPDATE settings SET value=? WHERE key=?', (int(value), key))

    def create_order(self, customer, product_id, quantity):
        if not isinstance(customer, str) or not 1 <= len(customer.strip()) <= 60:
            raise ValueError('Escribe un nombre de 1 a 60 caracteres')
        if type(quantity) is not int or not 1 <= quantity <= 100:
            raise ValueError('La cantidad debe ser un entero de 1 a 100')
        if not isinstance(product_id, str):
            raise ValueError('Producto inválido')
        with self.broker.lock, self.broker.db:
            if not self.broker.db.execute('SELECT id FROM products WHERE id=?', (product_id,)).fetchone():
                raise ValueError('Producto inexistente')
            order_id = str(uuid.uuid4())
            self.broker.db.execute('INSERT INTO orders VALUES(?,?,?,?,?)',
                                   (order_id, customer.strip(), product_id, quantity, 'created'))
            self.broker.publish('PedidoCreado', 'Pedidos', order_id,
                                {'customer': customer.strip(), 'product_id': product_id, 'quantity': quantity})
            return order_id

    def pay(self, order_id):
        if not isinstance(order_id, str):
            raise ValueError('Identificador de pedido inválido')
        with self.broker.lock, self.broker.db:
            order = self.broker.db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if not order or order['status'] != 'reserved':
                raise ValueError('Solo se puede pagar un pedido con inventario reservado')
            self.broker.db.execute('UPDATE orders SET status="paid" WHERE id=?', (order_id,))
            self.broker.publish('PagoCompletado', 'Pagos', order_id, {'quantity': order['quantity'], 'product_id': order['product_id']})

    def snapshot(self):
        with self.broker.lock:
            db = self.broker.db
            result = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                      for table in ['products', 'orders', 'events', 'deliveries', 'traces', 'notifications']}
            for event in result['events']:
                event['payload'] = json.loads(event['payload'])
            result['settings'] = {row['key']: bool(row['value']) for row in db.execute('SELECT * FROM settings')}
            return result

    def reset(self):
        with self.broker.lock, self.broker.db:
            for table in ['deliveries', 'traces', 'notifications', 'shipping_state', 'events', 'orders']:
                self.broker.db.execute(f'DELETE FROM {table}')
            for product, stock in [('cuaderno', 8), ('lapicero', 12), ('mochila', 3)]:
                self.broker.db.execute('UPDATE products SET stock=? WHERE id=?', (stock, product))
            self.broker.db.execute('UPDATE settings SET value=0')
