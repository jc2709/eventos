"""Cada consumidor conoce contratos de eventos, sin llamar a otros consumidores."""


def register_consumers(app):
    db, broker = app.broker.db, app.broker

    def inventory(event):
        data = event['payload']
        stock = db.execute('SELECT stock FROM products WHERE id=?', (data['product_id'],)).fetchone()['stock']
        if stock < data['quantity']:
            db.execute('UPDATE orders SET status="rejected" WHERE id=?', (event['correlation_id'],))
            broker.publish('PedidoRechazado', 'Inventario', event['correlation_id'], {'reason': 'Stock insuficiente'})
            return 'Pedido rechazado: no alcanza el stock. No se podrá pagar ni enviar.'
        db.execute('UPDATE products SET stock=stock-? WHERE id=?', (data['quantity'], data['product_id']))
        db.execute('UPDATE orders SET status="reserved" WHERE id=?', (event['correlation_id'],))
        broker.publish('InventarioReservado', 'Inventario', event['correlation_id'], data)
        return f"Se reservaron {data['quantity']} unidades. Inventario publica InventarioReservado."

    def shipping(event):
        column = 'reserved_seen' if event['type'] == 'InventarioReservado' else 'paid_seen'
        db.execute('INSERT OR IGNORE INTO shipping_state(order_id) VALUES(?)', (event['correlation_id'],))
        db.execute(f'UPDATE shipping_state SET {column}=1 WHERE order_id=?', (event['correlation_id'],))
        state = db.execute('SELECT * FROM shipping_state WHERE order_id=?', (event['correlation_id'],)).fetchone()
        if state['reserved_seen'] and state['paid_seen'] and not state['sent']:
            db.execute('UPDATE shipping_state SET sent=1 WHERE order_id=?', (event['correlation_id'],))
            db.execute('UPDATE orders SET status="shipped" WHERE id=?', (event['correlation_id'],))
            broker.publish('EnvioIniciado', 'Envíos', event['correlation_id'], {'message': 'Pedido preparado para envío'})
            return 'Se observaron reserva y pago del mismo pedido. Se publica EnvioIniciado.'
        return 'Envíos guarda el hecho y espera la otra condición del mismo pedido.'

    def notifications(event):
        if app.setting('fail_notifications'):
            raise RuntimeError('Fallo simulado de Notificaciones. Los otros consumidores siguen funcionando.')
        message = {'PedidoCreado': 'Pedido recibido', 'PedidoRechazado': 'Pedido rechazado por falta de stock',
                   'EnvioIniciado': 'Tu pedido está preparado para envío'}[event['type']]
        db.execute('INSERT OR IGNORE INTO notifications(event_id,order_id,message) VALUES(?,?,?)',
                   (event['id'], event['correlation_id'], message))
        return f'Notificación simulada: {message}. No se envían correos reales.'

    broker.subscribe('Inventario', ['PedidoCreado'], inventory)
    broker.subscribe('Envíos', ['InventarioReservado', 'PagoCompletado'], shipping)
    broker.subscribe('Notificaciones', ['PedidoCreado', 'PedidoRechazado', 'EnvioIniciado'], notifications)
