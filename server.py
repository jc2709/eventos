"""Servidor local sin dependencias. Ejecutar: python server.py"""
import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from eda.application import Application

ROOT = Path(__file__).resolve().parent


def serve(host='127.0.0.1', port=8000, database=None):
    if database is None:
        (ROOT / 'data').mkdir(exist_ok=True)
        database = ROOT / 'data' / 'aula.sqlite3'
    app = Application(database)
    stopped = threading.Event()

    class Handler(SimpleHTTPRequestHandler):
        def json_response(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == '/api/state':
                return self.json_response(app.snapshot())
            return super().do_GET()

        def do_POST(self):
            try:
                # El laboratorio solo acepta peticiones JSON desde su propia interfaz.
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.json_response({'error': 'Se requiere application/json'}, 415)
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    return self.json_response({'error': 'Origen no permitido'}, 403)
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 4096:
                    raise ValueError('Tamaño de petición inválido')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Se requiere un objeto JSON')
                if self.path == '/api/orders':
                    result = {'order_id': app.create_order(data.get('customer'), data.get('product_id'), data.get('quantity'))}
                elif self.path == '/api/pay':
                    app.pay(data.get('order_id'))
                    result = {'ok': True}
                elif self.path == '/api/step':
                    result = {'delivery': app.broker.step()}
                elif self.path == '/api/settings':
                    app.configure(data)
                    result = {'ok': True}
                elif self.path == '/api/retry':
                    result = {'retried': app.broker.retry_failed()}
                elif self.path == '/api/reset':
                    app.reset()
                    result = {'ok': True}
                else:
                    return self.json_response({'error': 'Ruta inexistente'}, 404)
                return self.json_response(result)
            except (ValueError, TypeError) as exc:
                return self.json_response({'error': str(exc)}, 400)

    def work():
        while not stopped.wait(0.6):
            if app.setting('auto'):
                app.broker.step()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((host, port), partial(Handler, directory=str(ROOT / 'web')))
    print(f'Aula EDA: http://{host}:{port} | Ctrl+C para detener', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        worker.join()
        app.broker.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--database')
    args = parser.parse_args()
    serve(args.host, args.port, args.database)
