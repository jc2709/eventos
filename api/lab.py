"""Vercel Function: una invocación procesa una acción del laboratorio."""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from eda.cloud import execute_request, MAX_SESSION_BYTES


class handler(BaseHTTPRequestHandler):
    def respond(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.respond({'ok': True, 'application': 'Aula EDA', 'storage': 'browser-session', 'runtime': 'python'})

    def do_POST(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.respond({'error': 'Se requiere application/json'}, 415)
        origin = self.headers.get('Origin')
        host = self.headers.get('X-Forwarded-Host') or self.headers.get('Host', '')
        if origin and urlsplit(origin).netloc != host:
            return self.respond({'error': 'Origen no permitido'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_SESSION_BYTES + 4096:
                return self.respond({'error': 'Petición demasiado grande. Reinicia el laboratorio.'}, 413)
            request = json.loads(self.rfile.read(size))
            return self.respond(execute_request(request))
        except (ValueError, TypeError, UnicodeError) as exc:
            return self.respond({'error': str(exc)}, 400)
