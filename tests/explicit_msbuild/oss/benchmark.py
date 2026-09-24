"""Paired OSS build timings and independent loopback HTTP-cache recovery.

Run after setup.py and prepare.py in the qualified Linux worker container.
Acquisition and BUILD fixture generation are outside timing; cold means fresh
project outputs and build processes, with warm package and OS filesystem caches.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import threading
import time
import uuid

RULES=Path(__file__).resolve().parents[3]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL=os.environ['RULES_MSBUILD_BAZEL']


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);parser.add_argument('--repeats',type=int,default=3);args=parser.parse_args()
 assert args.repeats>0,'At least one repetition is required'
 folder=args.folder.resolve();config=json.loads((folder/'config.json').read_text());inventory=json.loads((folder/'inventory.json').read_text());source=folder/'bazel';raw=folder/'source';evidence=folder/'evidence';evidence.mkdir(exist_ok=False)
 edit=json.loads((RULES/'tests/explicit_msbuild/oss/projects.json').read_text())[folder.name]['edit']
 base=folder/'measurement-base';startup=[BAZEL,'--output_base='+str(base),'--output_user_root='+str(folder/'user'),'--ignore_all_rc_files']
 flags=['--jobs=4','--disk_cache=','--remote_cache=','--remote_download_outputs=all','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4','--noshow_progress','--color=no','--curses=no']
 rawcmd=[str(SDK/'dotnet'),'build','Benchmark.slnx','-c','Release','-m:4','-p:RestorePackagesPath=/tmp/nuget','--nologo']+['-p:'+k+'='+v for k,v in config['properties'].items()]
 rows=[];api={};orig=(raw/edit['path']).read_text();assert orig.count(edit['before'])==1
 def command(name,command,cwd):
  start=time.perf_counter()
  with (evidence/(name+'.log')).open('w') as log:p=subprocess.run(list(map(str,command)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=600)
  seconds=time.perf_counter()-start
  assert p.returncode==0,(name,(evidence/(name+'.log')).read_text()[-4500:])
  return seconds
 def record(row):
  rows.append(row);(evidence/'results.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
 def bazel_outputs():
  outputs=base/'execroot/_main/bazel-out';refs={p.name:digest(p) for p in outputs.glob('*/bin/*.reference/*.dll')}
  runtime=next(outputs.glob('*/bin/'+edit['assembly']+'.runtime/'+edit['assembly']+'.dll'))
  assert len(refs)==len(inventory),(refs,len(inventory))
  return refs,digest(runtime)
 def raw_outputs():
  refs={};runtime=None
  for row in inventory:
   project=raw/Path(row['project']).parent;name=row['properties']['AssemblyName']+'.dll'
   refs[name]=digest(project/'obj/Release'/row['framework']/'ref'/name)
   if row['properties']['AssemblyName']==edit['assembly']:runtime=digest(project/'bin/Release'/row['framework']/name)
  assert runtime is not None
  return refs,runtime
 def actions(name):
  text=(evidence/(name+'.execution.json')).read_text();decoder=json.JSONDecoder();result=[]
  while text.strip():
   row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
   if row.get('mnemonic')=='MSBuildAssembly':result.append(row)
  return result
 try:
  for repetition in range(args.repeats):
   for engine in (('raw','bazel') if repetition%2==0 else ('bazel','raw')):
    cwd=raw if engine=='raw' else source;prefix=f'{repetition}-{engine}'
    (cwd/edit['path']).write_text(orig)
    command(prefix+'-dotnet-shutdown',[SDK/'dotnet','build-server','shutdown'],raw)
    if engine=='bazel':
     command(prefix+'-clean',startup+['clean'],source);command(prefix+'-shutdown',startup+['shutdown'],source)
    else:
     for row in inventory:
      for name in ('bin','obj'):shutil.rmtree(raw/Path(row['project']).parent/name,ignore_errors=True)
    before=None
    for case in ('cold','noop','body-edit'):
     name=prefix+'-'+case
     if case=='body-edit':
      replacement='"void benchmark '+str(repetition)+'"' if edit['before']=='"void"' else edit['before']+' Benchmark '+str(repetition)+'.'
      (cwd/edit['path']).write_text(orig.replace(edit['before'],replacement))
     cmd=rawcmd if engine=='raw' else startup+['build','//:benchmark','--profile='+str(evidence/(name+'.profile.gz')),'--execution_log_json_file='+str(evidence/(name+'.execution.json'))]+flags
     seconds=command(name,cmd,cwd)
     row=dict(repetition=repetition,engine=engine,case=case,seconds=seconds)
     outputs=raw_outputs() if engine=='raw' else bazel_outputs()
     if case=='cold':
      before=outputs;api[engine]=outputs[0]
     if case=='body-edit':
      assert outputs[0]==before[0],('reference changed',engine)
      assert outputs[1]!=before[1],('edited runtime unchanged',engine)
      row['referenceUnchanged']=True
     if engine=='bazel':
      executed=actions(name);row['assemblyActions']=len(executed);row['uncachedAssemblyActions']=sum(not r.get('cacheHit',False) for r in executed)
      if case=='cold':assert row['uncachedAssemblyActions']==len(inventory),row
     record(row)
    if engine=='bazel':command(prefix+'-final-shutdown',startup+['shutdown'],source)
    command(prefix+'-final-dotnet-shutdown',[SDK/'dotnet','build-server','shutdown'],raw)
    (cwd/edit['path']).write_text(orig)
  (evidence/'reference-comparison.json').write_text(json.dumps(dict(raw=api['raw'],bazel=api['bazel'],identical=api['raw']==api['bazel']),indent=2)+'\n')
  # Seed a separate HTTP action cache, remove the producer checkout and all its
  # local Bazel state, then recover into an independent output base and path.
  cache=evidence/'http-cache';cache.mkdir()
  class Cache(BaseHTTPRequestHandler):
   protocol_version='HTTP/1.1'
   def log_message(self,*args):pass
   def key(self):
    parts=self.path.strip('/').split('/')
    if len(parts)!=2 or parts[0] not in ('ac','cas') or not re.fullmatch('[0-9a-f]{64}',parts[1]):raise ValueError(self.path)
    return cache/(parts[0]+'-'+parts[1])
   def do_GET(self):
    path=self.key()
    if not path.exists():self.send_error(404);return
    self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
    with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
   def do_PUT(self):
    path=self.key();tmp=cache/str(uuid.uuid4());tmp.write_bytes(self.rfile.read(int(self.headers['Content-Length'])));tmp.replace(path)
    self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
  server=ThreadingHTTPServer(('127.0.0.1',0),Cache);threading.Thread(target=server.serve_forever,daemon=True).start()
  remote=[x for x in flags if not x.startswith('--remote_cache=')]+['--remote_cache=http://127.0.0.1:'+str(server.server_port)]
  try:
   command('seed-clean',startup+['clean'],source)
   command('seed',startup+['build','//:benchmark','--remote_accept_cached=false']+remote,source)
   references,unused=bazel_outputs()
   producer_outputs=base/'execroot/_main/bazel-out';runtime_hashes={p.relative_to(next(parent for parent in p.parents if parent.name=='bin')).as_posix():digest(p) for p in producer_outputs.glob('*/bin/*.runtime/**/*') if p.is_file()}
   relocated=folder/'relocated';shutil.copytree(source,relocated,ignore=shutil.ignore_patterns('bazel-*'))
   command('seed-shutdown',startup+['shutdown'],source);shutil.rmtree(base);shutil.rmtree(source)
   recovery=folder/'recovery-base';recover=[BAZEL,'--output_base='+str(recovery),'--output_user_root='+str(folder/'recovery-user'),'--ignore_all_rc_files']
   try:
    seconds=command('remote-recovery',recover+['build','//:benchmark','--remote_upload_local_results=false','--execution_log_json_file='+str(evidence/'remote-recovery.execution.json')]+remote,relocated)
    executed=actions('remote-recovery');assert len(executed)==len(inventory) and all(r.get('cacheHit') for r in executed),executed
    recovered_outputs=recovery/'execroot/_main/bazel-out'
    recovered={p.relative_to(next(parent for parent in p.parents if parent.name=='bin')).as_posix():digest(p) for p in recovered_outputs.glob('*/bin/*.runtime/**/*') if p.is_file()}
    assert recovered==runtime_hashes,'Remote runtime payload differs'
    recovered_refs={p.name:digest(p) for p in recovered_outputs.glob('*/bin/*.reference/*.dll')};assert recovered_refs==references
    record(dict(engine='bazel',case='remote-recovery',seconds=seconds,assemblyCacheHits=len(executed),matchingRuntimeFiles=len(recovered),producerDeleted=True))
   finally:command('recovery-shutdown',recover+['shutdown'],relocated)
  finally:server.shutdown();server.server_close()
 finally:
  (raw/edit['path']).write_text(orig)
  if source.exists():
   (source/edit['path']).write_text(orig);command('final-shutdown',startup+['shutdown'],source)
  command('final-dotnet-shutdown',[SDK/'dotnet','build-server','shutdown'],raw)
 summary=[]
 for case in ('cold','noop','body-edit'):
  row=dict(case=case)
  for engine in ('raw','bazel'):row[engine]=statistics.median(r['seconds'] for r in rows if r['case']==case and r['engine']==engine)
  row['bazelOverRaw']=row['bazel']/row['raw'];summary.append(row)
 (evidence/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
