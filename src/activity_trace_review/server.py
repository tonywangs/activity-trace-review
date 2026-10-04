"""Single-user loopback server. No outbound HTTP, recorder, telemetry, or URL execution."""
import base64
import binascii
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files as resources
import json
import secrets
from urllib.parse import urlsplit, parse_qs
from .core import (Invalid, LIMITS, require, loads, dumps, load_files, read_directory,
                   new_review, validate_review, build_bundle, bundle_zip, rgb_png)
from .runtime import deadline

MAX_BODY = 34*1024*1024

class Workbench(HTTPServer):
    def __init__(self, port=0, source=None):
        super().__init__(('127.0.0.1', port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.source = source
        self.review = new_review(source) if source else None
        self.origin = f'http://127.0.0.1:{self.server_port}'
    def snapshot(self):
        return snapshot(self.source, self.review)

def snapshot(source, review):
    if source is None:
        return {'source':None, 'limits':LIMITS}
    return {'source':source.digest, 'trace':source.trace, 'review':review,
            'dimensions':{k:list(v.size) for k,v in source.images.items()}, 'limits':LIMITS}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # source strings and tokens never enter request logs
    def setup(self):
        super().setup()
        self.connection.settimeout(15)
    def reply(self, code, data, mime='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)
    def check_host(self):
        require(self.headers.get('Host') == urlsplit(self.server.origin).netloc, 'Invalid Host')
    def authorize(self):
        self.check_host()
        provided = self.headers.get('X-Review-Token','')
        require(provided.isascii() and secrets.compare_digest(provided, self.server.token), 'Unauthorized')
        origin = self.headers.get('Origin')
        require(origin is None or origin == self.server.origin, 'Invalid Origin')
    def do_GET(self):
        try:
            with deadline():
                self.check_host()
                path = urlsplit(self.path).path
                if path in ('/', '/app.js', '/style.css'):
                    name = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
                    mime = {'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
                    return self.reply(200, resources('activity_trace_review').joinpath('web',name).read_bytes(), mime)
                self.authorize()
                if path == '/api/state':
                    return self.reply(200, dumps(self.server.snapshot()))
                if path == '/api/image':
                    name = parse_qs(urlsplit(self.path).query).get('name',[''])[0]
                    require(self.server.source is not None and name in self.server.source.images, 'Unknown screenshot')
                    return self.reply(200, rgb_png(self.server.source.images[name]), 'image/png')
                self.reply(404, dumps({'error':'Not found'}))
        except (Invalid, ValueError, OSError) as e:
            self.reply(400, dumps({'error':str(e)}))
    def do_POST(self):
        try:
            with deadline():
                self.authorize()
                require(self.headers.get('Content-Type') == 'application/json', 'JSON content type required')
                require(self.headers.get('Transfer-Encoding') is None, 'Transfer encoding unsupported')
                n = int(self.headers.get('Content-Length','0'))
                require(0 < n <= MAX_BODY, 'Request byte limit exceeded')
                raw = self.rfile.read(n)
                require(len(raw) == n, 'Incomplete request')
                path = urlsplit(self.path).path
                if path == '/api/import':
                    # Envelope has a separate cap; embedded trace still has the core JSON cap.
                    body = loads(raw, max_bytes=MAX_BODY)
                    require(type(body) is dict and set(body) == {'files'} and type(body['files']) is dict
                            and len(body['files']) <= LIMITS['files'], 'Invalid import envelope')
                    decoded, total = {}, 0
                    for name, data in body['files'].items():
                        require(type(data) is str, 'File must be base64')
                        decoded[name] = base64.b64decode(data, validate=True)
                        total += len(decoded[name])
                        require(total <= LIMITS['input_bytes'], 'Input byte limit exceeded')
                    source = load_files(decoded)
                    review = new_review(source)
                    payload = dumps(snapshot(source, review))
                    # Commit only after every file validates and response serialization succeeds.
                    self.server.source, self.server.review = source, review
                    return self.reply(200, payload)
                require(self.server.source is not None, 'Import a trace first')
                review = loads(raw)
                validate_review(self.server.source, review, ready=path == '/api/export')
                if path == '/api/review':
                    self.server.review = review
                    return self.reply(200, dumps({'ok':True}))
                if path == '/api/export':
                    payload = bundle_zip(build_bundle(self.server.source, review))
                    self.server.review = review
                    return self.reply(200, payload, 'application/zip')
                self.reply(404, dumps({'error':'Not found'}))
        except (Invalid, ValueError, OSError, binascii.Error, RecursionError) as e:
            self.reply(400, dumps({'error':str(e)[:240]}))


def serve(source_path=None, port=8765):
    with deadline():
        source = read_directory(source_path) if source_path else None
    with Workbench(port, source) as server:
        print(f'Workbench: {server.origin}/#{server.token}', flush=True)
        print('Loopback only. Keep this URL private. Ctrl+C stops the server.', flush=True)
        server.serve_forever()
