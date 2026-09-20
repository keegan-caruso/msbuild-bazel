"""Loopback HTTP recovery timing after the paired Linux matrix; no disk cache."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time

root=Path(sys.argv[1]).resolve(); cache=root/'http-cache'; cache.mkdir(exist_ok=True)
class Cache(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args): pass
    def key(self):
        parts=self.path.strip('/').split('/')
        if len(parts)!=2 or parts[0] not in ('ac','cas') or not re.fullmatch('[0-9a-f]{64}',parts[1]): raise ValueError(self.path)
        return cache/(parts[0]+'-'+parts[1])
    def do_GET(self):
        path=self.key()
        if not path.exists(): self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length',str(path.stat().st_size)); self.end_headers()
        with path.open('rb') as stream: shutil.copyfileobj(stream,self.wfile)
    def do_PUT(self):
        self.key().write_bytes(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200); self.send_header('Content-Length','0'); self.end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),Cache)
threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
try:
    for size in (2,32,128):
        folder=root/str(size); workspace=folder/'worker'
        startup=[os.environ['RULES_MSBUILD_BAZEL'],'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/'worker-base'),'--ignore_all_rc_files']
        flags=['--jobs=4','--disk_cache=','--remote_cache=http://127.0.0.1:'+str(server.server_port),'--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4']
        def run(name,args):
            start=time.perf_counter(); p=subprocess.run(startup+args,cwd=workspace,capture_output=True,text=True,timeout=600); seconds=time.perf_counter()-start
            output=p.stdout+p.stderr; (folder/(name+'.log')).write_text(output)
            assert p.returncode==0,output[-4000:]
            return seconds,output
        run('remote-seed-clean',['clean'])
        run('remote-seed',['build','//App','--remote_accept_cached=false']+flags)
        for repetition in range(3):
            run(f'remote-clean-{repetition}',['clean'])
            run(f'remote-shutdown-{repetition}',['shutdown'])
            run(f'remote-analysis-{repetition}',['build','//App','--nobuild']+flags)
            seconds,log=run(f'remote-hit-{repetition}',['build','//App','--profile='+str(folder/f'remote-hit-{repetition}.profile.gz')]+flags)
            hits=sum(map(int,re.findall(r'(\d+) remote cache hit',log)))
            assert hits>=size+1,log[-1500:]
            assert not re.search(r'\d+ worker',log),log[-1500:]
            results.append(dict(projects=size+1,repetition=repetition,seconds=seconds,remoteHits=hits))
            print('remote',size+1,repetition,round(seconds,3),hits,flush=True)
        run('remote-final-shutdown',['shutdown'])
    (root/'remote-results.json').write_text(json.dumps(results,indent=2))
    (root/'remote-summary.json').write_text(json.dumps([dict(projects=n,medianSeconds=statistics.median(r['seconds'] for r in results if r['projects']==n)) for n in (3,33,129)],indent=2))
finally: server.shutdown(); server.server_close()
