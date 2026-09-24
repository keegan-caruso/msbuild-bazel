"""Full Orchard HTTP action-cache recovery at a relocated checkout.

Loopback transport isolates cache mechanics; this does not model WAN latency.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

source = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
cache = Path('/tmp/orchard-http-cache'); cache.mkdir(exist_ok=True)

class Cache(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def key(self):
        parts = self.path.strip('/').split('/')
        if len(parts) != 2 or parts[0] not in ('ac', 'cas') or not re.fullmatch('[0-9a-f]{64}', parts[1]):
            raise ValueError(self.path)
        return cache/(parts[0]+'-'+parts[1])
    def do_GET(self):
        path = self.key()
        if not path.exists():
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length', str(path.stat().st_size)); self.end_headers()
        with path.open('rb') as stream:
            shutil.copyfileobj(stream, self.wfile)
    def do_PUT(self):
        destination = self.key()
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            remaining = int(self.headers['Content-Length'])
            while remaining:
                chunk = self.rfile.read(min(remaining, 1024*1024))
                if not chunk:
                    raise IOError('Incomplete cache upload')
                stream.write(chunk); remaining -= len(chunk)
        os.replace(stream.name, destination)
        self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers()

server = ThreadingHTTPServer(('127.0.0.1', 0), Cache)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = Path('/tmp/orchard-explicit-base')
flags = ['--jobs=4', '--disk_cache=', '--remote_cache=http://127.0.0.1:'+str(server.server_port), '--remote_download_outputs=all', '--repository_cache=/tmp/repository-cache', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=2', '--noshow_progress', '--color=no', '--curses=no']
results = []
def run(name, args):
    command = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(base), '--ignore_all_rc_files']+args
    start = time.perf_counter()
    with (evidence/(name+'.log')).open('w') as log:
        p = subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    elapsed = time.perf_counter()-start
    assert p.returncode == 0, name
    return elapsed, (evidence/(name+'.log')).read_text()
try:
    run('remote-clean', ['clean'])
    run('remote-shutdown', ['shutdown'])
    elapsed, log = run('remote-seed', ['build', '//:OrchardCore.Cms.Web', '--remote_accept_cached=false']+flags)
    results.append(dict(case='seed', seconds=elapsed))
    run('remote-seed-shutdown', ['shutdown'])
    relocated = Path('/orchard-relocated')
    shutil.rmtree(base)  # No producer execution state survives recovery.
    if '--pause-before-recovery' in sys.argv:
        (evidence/'remote-ready-for-recovery').write_text('Producer output base removed; reclaim unused container blocks now.\n')
        deadline = time.monotonic()+300
        while not (evidence/'remote-continue').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Waiting for external disk reclamation')
            time.sleep(0.25)
    if relocated.exists():
        shutil.rmtree(relocated)
    shutil.copytree(source, relocated, ignore=shutil.ignore_patterns('bin', 'obj', 'bazel-*'), copy_function=os.link)
    source = relocated
    base = Path('/tmp/orchard-recovered-base')
    elapsed, log = run('remote-recovery', ['build', '//:OrchardCore.Cms.Web', '--profile=/evidence/remote-recovery.profile.gz']+flags)
    hits = sum(map(int, re.findall(r'(\d+) remote cache hit', log)))
    assert hits >= 489 and not re.search(r'\d+ worker', log), log[-2000:]
    results.append(dict(case='relocated-recovery-all-outputs', seconds=elapsed, remoteHits=hits))
    run('remote-recovered-shutdown', ['shutdown'])
    (evidence/'remote-results.json').write_text(json.dumps(results, indent=2))
    print(results, flush=True)
finally:
    server.shutdown(); server.server_close()
