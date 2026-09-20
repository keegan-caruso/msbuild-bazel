"""Exercise actual Bazel hardened workers inside a disposable Linux guest."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

WORKER = r'''#!/usr/bin/python3
import json,os,socket,sys
count=0
for line in sys.stdin:
 request=json.loads(line);args=request['arguments'];count+=1
 def readable(path):
  try:
   with open(path) as f:f.read()
   return True
  except OSError:return False
 def writable(path):
  try:
   with open(path,'w') as f:f.write('unexpected')
   return True
  except OSError:return False
 try:
  with open(args[0]) as f:content=f.read()
  try:
   with socket.create_connection(('127.0.0.1',int(args[5])),timeout=.5):network=True
  except OSError:network=False
  result=dict(pid=os.getpid(),request=count,content=content,previousInputReadable=readable(args[2]),
   absoluteUndeclaredReadable=readable(args[3]),blockedPathReadable=readable('/workspace/worker-hidden'),
   outsideWrite=writable('/workspace/worker-outside/new-file'),network=network)
  with open(args[1],'w') as f:json.dump(result,f)
  response=dict(exitCode=0,requestId=request.get('requestId',0))
 except Exception as error:response=dict(exitCode=1,output=str(error),requestId=request.get('requestId',0))
 print(json.dumps(response),flush=True)
'''
RULE = '''def _probe(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    args = ctx.actions.args()
    args.add(ctx.file.src.path)
    args.add(output.path)
    args.add(ctx.attr.other)
    args.add(ctx.attr.absolute)
    args.add("unused")
    args.add(ctx.attr.port)
    args.use_param_file("@%s", use_always = True)
    args.set_param_file_format("multiline")
    ctx.actions.run(executable = ctx.executable.worker, arguments = [args], inputs = [ctx.file.src], outputs = [output], mnemonic = "IsolationProbe", execution_requirements = {"supports-workers": "1", "requires-worker-protocol": "json", "block-network": "1"})
    return [DefaultInfo(files = depset([output]))]
probe = rule(implementation = _probe, attrs = {"src": attr.label(allow_single_file = True), "other": attr.string(), "absolute": attr.string(), "port": attr.string(), "worker": attr.label(executable = True, cfg = "exec", allow_files = True)})
'''


def run(output):
    root = Path('/workspace/worker-probe')
    root.mkdir()
    Path('/workspace/worker-bazel').mkdir()
    output.mkdir(parents=True, exist_ok=True)
    (root / 'MODULE.bazel').write_text('module(name="worker_probe")\n')
    (root / 'worker.py').write_text(WORKER)
    (root / 'worker.py').chmod(0o755)
    (root / 'probe.bzl').write_text(RULE)
    (root / 'first.txt').write_text('first')
    (root / 'second.txt').write_text('second')
    (root / 'undeclared.txt').write_text('undeclared')
    Path('/workspace/worker-hidden').write_text('blocked')
    Path('/workspace/worker-outside').mkdir()
    Path('/workspace/worker-outside').chmod(0o777)
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0));server.listen()
        port = str(server.getsockname()[1])
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
        build = 'load(":probe.bzl", "probe")\nexports_files(["worker.py"])\n'
        for name, other in [('first', 'second'), ('second', 'first')]:
            build += 'probe(name="'+name+'",src="'+name+'.txt",other="'+other+'.txt",absolute="/workspace/worker-probe/undeclared.txt",port="'+port+'",worker=":worker.py")\n'
        (root / 'BUILD.bazel').write_text(build)
        startup = [os.environ['RULES_MSBUILD_BAZEL'], '--nosystem_rc', '--nohome_rc', '--noworkspace_rc', '--output_base=/workspace/worker-bazel']
        flags = ['--incompatible_autoload_externally=', '--worker_sandboxing', '--sandbox_fake_username', '--experimental_worker_sandbox_hardening', '--strategy=IsolationProbe=worker', '--worker_max_instances=1', '--worker_verbose', '--sandbox_block_path=/workspace/worker-hidden', '--noshow_progress']
        rows = []
        try:
            for name in ['first', 'second']:
                p = subprocess.run(startup+['build', '//:'+name]+flags, cwd=root, capture_output=True, text=True, timeout=180)
                (output / (name+'.log')).write_text(p.stdout+p.stderr)
                if p.returncode:raise RuntimeError(name+' failed: '+p.stderr[-6000:])
                rows.append(json.loads((root / 'bazel-bin' / (name+'.json')).read_text()))
            assert rows[0]['pid'] == rows[1]['pid'] and rows[1]['request'] == 2, rows
            assert [r['content'] for r in rows] == ['first', 'second']
            assert all(not r[k] for r in rows for k in ['previousInputReadable', 'blockedPathReadable', 'outsideWrite', 'network']), rows
            report = dict(accepted=True, platform=os.uname().machine, requests=rows,
                          limitation='Absolute undeclared host reads are measured, not assumed denied.')
            (output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(report), flush=True)
        finally:
            subprocess.run(startup+['shutdown'], cwd=root, capture_output=True, timeout=60)


if __name__ == '__main__':
    run(Path(sys.argv[1]))
