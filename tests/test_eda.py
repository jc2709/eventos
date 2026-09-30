import tempfile
import unittest
from pathlib import Path
from eda.application import Application


class EventArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.app = Application(self.path)

    def tearDown(self):
        self.app.broker.close()
        self.temp.cleanup()

    def drain(self):
        for _ in range(200):
            if self.app.broker.step() is None:
                return
        self.fail('La cola no termina')

    def test_publishing_does_not_run_consumers(self):
        self.app.create_order('Juan','cuaderno',2)
        state = self.app.snapshot()
        self.assertEqual(state['products'][0]['stock'],8)
        self.assertEqual(len(state['events']),1)
        self.assertEqual({d['consumer'] for d in state['deliveries']},{'Inventario','Notificaciones'})
        self.assertTrue(all(d['status']=='pending' for d in state['deliveries']))

    def test_successful_order_waits_for_payment(self):
        order = self.app.create_order('Juan','cuaderno',2)
        self.drain()
        self.assertEqual(self.app.snapshot()['orders'][0]['status'],'reserved')
        self.assertFalse(any(e['type']=='EnvioIniciado' for e in self.app.snapshot()['events']))
        self.app.pay(order)
        self.drain()
        state = self.app.snapshot()
        self.assertEqual(state['orders'][0]['status'],'shipped')
        self.assertEqual(state['products'][0]['stock'],6)
        self.assertEqual([e['type'] for e in state['events']],['PedidoCreado','InventarioReservado','PagoCompletado','EnvioIniciado'])
        self.assertEqual(len(state['notifications']),2)

    def test_stock_rejection_cannot_be_paid(self):
        order = self.app.create_order('Juan','mochila',4)
        self.drain()
        state = self.app.snapshot()
        self.assertEqual(state['orders'][0]['status'],'rejected')
        self.assertEqual(state['products'][2]['stock'],3)
        with self.assertRaises(ValueError):
            self.app.pay(order)
        self.assertFalse(any(e['type']=='EnvioIniciado' for e in state['events']))

    def test_repeated_pay_command_does_not_duplicate_event(self):
        order = self.app.create_order('Juan','cuaderno',1)
        self.drain()
        self.app.pay(order)
        with self.assertRaises(ValueError):
            self.app.pay(order)
        self.assertEqual(sum(e['type']=='PagoCompletado' for e in self.app.snapshot()['events']),1)

    def test_shipping_correlates_by_order(self):
        first = self.app.create_order('A','cuaderno',1)
        second = self.app.create_order('B','cuaderno',1)
        self.drain()
        self.app.pay(first)
        self.drain()
        orders = {o['id']:o['status'] for o in self.app.snapshot()['orders']}
        self.assertEqual(orders[first],'shipped')
        self.assertEqual(orders[second],'reserved')

    def test_shipping_accepts_both_event_orders(self):
        order = self.app.create_order('Juan','cuaderno',1)
        self.app.broker.step()  # Solo Inventario; la reserva ya existe.
        self.app.pay(order)
        # Entregar el pago primero para comprobar que no depende del orden.
        with self.app.broker.db:
            self.app.broker.db.execute("UPDATE deliveries SET attempts=1 WHERE consumer='Envíos' AND event_id IN (SELECT id FROM events WHERE type='InventarioReservado')")
        self.drain()
        self.assertEqual(self.app.snapshot()['orders'][0]['status'],'shipped')
        self.assertEqual(sum(e['type']=='EnvioIniciado' for e in self.app.snapshot()['events']),1)

    def test_failure_is_isolated_and_recovery_does_not_repeat_inventory(self):
        self.app.configure({'fail_notifications':True})
        order = self.app.create_order('Juan','cuaderno',2)
        self.drain()
        state = self.app.snapshot()
        self.assertEqual(state['orders'][0]['status'],'reserved')
        failed = [d for d in state['deliveries'] if d['status']=='failed']
        self.assertEqual(len(failed),1)
        self.assertEqual(failed[0]['attempts'],3)
        self.app.configure({'fail_notifications':False})
        self.assertEqual(self.app.broker.retry_failed(),1)
        self.drain()
        self.assertEqual(self.app.snapshot()['products'][0]['stock'],6)
        self.assertEqual(len(self.app.snapshot()['notifications']),1)
        self.assertEqual(self.app.broker.retry_failed(),0)
        self.assertEqual(order,self.app.snapshot()['orders'][0]['id'])

    def test_consumer_effect_and_ack_are_atomic(self):
        self.app.create_order('Juan','cuaderno',2)
        types, inventory = self.app.broker.handlers['Inventario']
        def crash(event):
            inventory(event)
            raise RuntimeError('Error después de modificar inventario')
        self.app.broker.handlers['Inventario'] = (types,crash)
        self.app.broker.step()
        state = self.app.snapshot()
        self.assertEqual(state['products'][0]['stock'],8)
        self.assertEqual(len(state['events']),1)
        self.assertEqual(state['orders'][0]['status'],'created')
        self.app.broker.handlers['Inventario'] = (types,inventory)
        self.drain()
        self.assertEqual(self.app.snapshot()['products'][0]['stock'],6)
        self.assertEqual(len(self.app.snapshot()['events']),2)

    def test_pending_events_survive_restart(self):
        self.app.create_order('Juan','lapicero',3)
        before = self.app.snapshot()
        self.app.broker.close()
        self.app = Application(self.path)
        self.assertEqual(before,self.app.snapshot())
        self.drain()
        self.assertEqual(self.app.snapshot()['products'][1]['stock'],9)

    def test_competing_orders_cannot_overdraw_stock(self):
        self.app.create_order('A','mochila',2)
        self.app.create_order('B','mochila',2)
        self.drain()
        self.assertEqual(self.app.snapshot()['products'][2]['stock'],1)
        self.assertEqual([o['status'] for o in self.app.snapshot()['orders']],['reserved','rejected'])

    def test_invalid_inputs_publish_no_events(self):
        for args in [('', 'cuaderno',1),('A','cuaderno',0),('A','cuaderno',1.5),('A','no-existe',1),('A','cuaderno',True)]:
            with self.assertRaises(ValueError):
                self.app.create_order(*args)
        self.assertEqual(self.app.snapshot()['events'],[])

    def test_reset_restores_experiment(self):
        self.app.create_order('A','mochila',3)
        self.drain()
        self.app.configure({'auto':True,'fail_notifications':True})
        self.app.reset()
        state = self.app.snapshot()
        self.assertEqual(state['events'],[])
        self.assertEqual(state['deliveries'],[])
        self.assertEqual(state['products'][2]['stock'],3)
        self.assertFalse(any(state['settings'].values()))


if __name__ == '__main__':
    unittest.main()
