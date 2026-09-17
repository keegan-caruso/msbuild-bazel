"""Loopback-only experimental HTTP cache; deliberately not a production service."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import time


class CacheServer:
    def __init__(self, delay_ms=0):
        self.data = {}; self.events = []; self.lock = threading.Lock()
        self.delay_ms = delay_ms; self.offline = False; self.offline_prefixes = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args): pass
            def do_GET(self): self.handle_cache(False)
            def do_PUT(self): self.handle_cache(True)
            def handle_cache(self, write):
                start = time.perf_counter()
                path = self.path
                if not re.fullmatch(r'/(?:bazel/(?:ac|cas)|native/(?:index|cas))/[0-9a-f]{64}', path):
                    self.send_error(400); return
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 64 * 1024 * 1024:
                    self.send_error(413); return
                body = self.rfile.read(size) if write else b''
                time.sleep(owner.delay_ms / 1000)
                with owner.lock:
                    status = 503 if owner.offline or any(path.startswith(prefix) for prefix in owner.offline_prefixes) else 200
                    if status == 200:
                        if write:
                            if '/cas/' in path and hashlib.sha256(body).hexdigest() != path.rsplit('/',1)[1]: status = 400
                            else: owner.data[path] = body
                        elif path in owner.data: body = owner.data[path]
                        else: status = 404
                    response = b'' if write or status != 200 else body
                    owner.events.append(dict(method=self.command,path=path,status=status,bytes=len(body) if write else len(response),seconds=time.perf_counter()-start))
                self.send_response(status); self.send_header('Content-Length',str(len(response))); self.end_headers()
                if response: self.wfile.write(response)
        class Server(ThreadingHTTPServer):
            request_queue_size = 256
        self.server = Server(('127.0.0.1',0),Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
    @property
    def url(self): return f'http://127.0.0.1:{self.server.server_port}'
    def __enter__(self): self.thread.start(); return self
    def __exit__(self,*args): self.server.shutdown(); self.server.server_close(); self.thread.join()
    def totals(self, start=0):
        with self.lock: events = self.events[start:].copy()
        return dict(requests=len(events),downloadBytes=sum(e['bytes'] for e in events if e['method']=='GET'),uploadBytes=sum(e['bytes'] for e in events if e['method']=='PUT'),hits=sum(e['method']=='GET' and e['status']==200 for e in events),misses=sum(e['status']==404 for e in events),errors=sum(e['status']>=500 for e in events),requestSeconds=sum(e['seconds'] for e in events))
