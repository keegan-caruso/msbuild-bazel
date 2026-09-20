"""Pinned real cache service for acceptance; never an in-memory replacement."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

PIN=json.loads(Path(__file__).with_name('bazel-remote.json').read_text())

class CacheService:
    def __init__(self,binary,root,max_size=2,cache_directory=None):
        self.binary=Path(binary);self.root=Path(root);self.max_size=max_size
        self.cache_directory=Path(cache_directory) if cache_directory is not None else self.root/'cache'
        if hashlib.sha256(self.binary.read_bytes()).hexdigest()!=PIN['sha256']:
            raise ValueError('bazel-remote does not match checked-in pin')
    def __enter__(self):
        self.root.mkdir(parents=True,exist_ok=False)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{self.port}'
        self.log=(self.root/'server.log').open('wb')
        self.process=subprocess.Popen([str(self.binary),'--dir',str(self.cache_directory),'--max_size',str(self.max_size),
            '--http_address',f'127.0.0.1:{self.port}','--grpc_address','none','--enable_endpoint_metrics',
            '--access_log_level','all'],stdout=self.log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if self.process.poll() is not None:raise RuntimeError('cache server exited')
                try:
                    self.status=self.read('/status');return self
                except OSError:time.sleep(.05)
            raise RuntimeError('cache server readiness timed out')
        except BaseException:self.__exit__(None,None,None);raise
    def read(self,path):
        with urllib.request.urlopen(self.url+path,timeout=10) as response:return response.read()
    def capture(self,name):
        for path in ('/status','/metrics'):
            (self.root/(name+'-'+path[1:]+'.txt')).write_bytes(self.read(path))
    def __exit__(self,*_):
        self.process.terminate()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()
