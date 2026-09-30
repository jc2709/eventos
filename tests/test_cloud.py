import copy
import unittest
from eda.cloud import execute_request


class CloudAdapterTests(unittest.TestCase):
    def invoke(self, previous=None, action='state', data=None):
        return execute_request({'session': previous['session'] if previous else None,
                                'action': action, 'data': data or {}})

    def drain(self, previous):
        for _ in range(50):
            previous = self.invoke(previous,'step')
            if previous['result']['delivery'] is None:
                return previous
        self.fail('La cola no termina')

    def test_entire_flow_survives_new_function_for_each_request(self):
        response = self.invoke(action='orders',data={'customer':'Alumno','product_id':'cuaderno','quantity':2})
        order = response['result']['order_id']
        self.assertEqual(response['state']['products'][0]['stock'],8)
        response = self.drain(response)
        self.assertEqual(response['state']['orders'][0]['status'],'reserved')
        response = self.invoke(response,'pay',{'order_id':order})
        response = self.drain(response)
        self.assertEqual(response['state']['orders'][0]['status'],'shipped')
        self.assertEqual(response['state']['products'][0]['stock'],6)
        self.assertEqual(len(response['state']['notifications']),2)
        self.assertEqual(len(response['state']['events']),4)
        self.assertEqual(response['state'],self.invoke(response)['state'])

    def test_students_have_independent_inventory_and_queues(self):
        first = self.invoke(action='orders',data={'customer':'A','product_id':'mochila','quantity':2})
        first = self.drain(first)
        second = self.invoke()
        self.assertEqual(first['state']['products'][2]['stock'],1)
        self.assertEqual(second['state']['products'][2]['stock'],3)
        self.assertEqual(second['state']['events'],[])

    def test_failure_queue_and_recovery_survive_roundtrip(self):
        response = self.invoke(action='settings',data={'fail_notifications':True})
        response = self.invoke(response,'orders',{'customer':'A','product_id':'cuaderno','quantity':2})
        response = self.drain(response)
        self.assertEqual(sum(d['status']=='failed' for d in response['state']['deliveries']),1)
        response = self.invoke(response,'settings',{'fail_notifications':False})
        response = self.invoke(response,'retry')
        response = self.drain(response)
        self.assertEqual(response['state']['products'][0]['stock'],6)
        self.assertEqual(len(response['state']['notifications']),1)

    def test_reset_can_recover_an_invalid_session(self):
        response = execute_request({'session':{'version':999},'action':'reset'})
        self.assertEqual(response['session']['version'],1)
        self.assertEqual(response['state']['orders'],[])

    def test_no_sql_from_the_browser_is_executed(self):
        bad = self.invoke()
        bad['session']['tables']['events; DROP TABLE products'] = []
        with self.assertRaises(ValueError):
            self.invoke(bad)
        safe = self.invoke(action='orders',data={'customer':"'); DROP TABLE products; --",'product_id':'cuaderno','quantity':1})
        self.assertEqual(len(safe['state']['products']),3)

    def test_unknown_columns_and_non_scalar_values_are_rejected(self):
        for value in [[],{},True]:
            bad = copy.deepcopy(self.invoke())
            bad['session']['tables']['products'][0]['stock'] = value
            with self.assertRaises(ValueError):
                self.invoke(bad)
        bad = self.invoke()
        bad['session']['tables']['products'][0]['extra'] = 'invalid'
        with self.assertRaises(ValueError):
            self.invoke(bad)

    def test_incomplete_correlations_survive_reloads(self):
        response = self.invoke(action='orders',data={'customer':'A','product_id':'cuaderno','quantity':1})
        order = response['result']['order_id']
        response = self.drain(response)
        self.assertTrue(response['session']['tables']['shipping_state'][0]['reserved_seen'])
        response = self.invoke(response)
        response = self.invoke(response,'pay',{'order_id':order})
        response = self.drain(response)
        self.assertEqual(sum(e['type']=='EnvioIniciado' for e in response['state']['events']),1)


if __name__ == '__main__':
    unittest.main()
