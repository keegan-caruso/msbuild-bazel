"""Qualify the production Linux compiler worker and measure sequential actions."""
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
RUNNER = ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['bash', 'scripts/dotnet.sh', 'build', 'tools/NativeProjectCache', '-c', 'Release', '--nologo', '-v:q'], cwd=ROOT, check=True)
    root = Path('/workspace/compiler-probe');root.mkdir()
    src = root/'src';src.mkdir()
    (src/'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Deterministic>true</Deterministic></PropertyGroup></Project>')
    (src/'Value.cs').write_text('public static class Value { public static int Get() => 7; }\n')
    (src/'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    subprocess.run([str(SDK/'dotnet'), 'restore', 'Library.csproj', '--nologo'], cwd=src, check=True, capture_output=True)
    restore = {str(p.relative_to(src)):p.read_text().replace(str(src), '${WORKSPACE}').replace(str(SDK), '${SDK}').replace('/root', '${HOME}')
               for p in (src/'obj').glob('*') if p.name=='project.assets.json' or p.name.endswith(('.nuget.g.props', '.nuget.g.targets'))}
    shutil.rmtree(src/'obj')
    plan = root/'plan';plan.mkdir()
    (plan/'restore.json').write_text(json.dumps(restore))
    def prepare():
        payload = {str(p.relative_to(src)):sha(p) for p in src.rglob('*') if p.is_file()}
        (plan/'payload.json').write_text(json.dumps(payload))
        (plan/'manifest.json').write_text(json.dumps(dict(toolchain=hashlib.sha256(b'worker-qualification').hexdigest(), policy='evaluated-api-runtime-v2', projects={'Library.csproj':dict(identity=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), dependencies=[])})))
    prepare()
    request = dict(entry='Library.csproj', output='result/bundle', diagnostics='result/diagnostics', apiOutput='result/api', runtimeOutput='result/runtime',
        manifest='plan/manifest.json', restore='plan/restore.json', preparedPlan='plan', projectAction=True, validatePublication=True, profileMsbuild=True,
        sources=[dict(source='src/'+str(p.relative_to(src)), destination=str(p.relative_to(src))) for p in src.rglob('*') if p.is_file()], seeds=[])
    request_file = root/'request.json'
    worker = None
    rows=[]
    baseline=None
    def launch():
        return subprocess.Popen([str(SDK/'dotnet'), str(RUNNER), '--bazel-worker', '--persistent_worker'], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=(output/'worker.stderr').open('w'), text=True)
    def invoke(label, mode, overrides=None, expected=0, tamper=False):
        nonlocal baseline
        shutil.rmtree(root/'result', ignore_errors=True)
        request_file.write_text(json.dumps(dict(request, **(overrides or {}))))
        inputs=[dict(path=str(p.relative_to(root)), digest=base64.b64encode(sha(p).encode()).decode()) for folder in [src,plan] for p in folder.rglob('*') if p.is_file()]
        inputs.append(dict(path='request.json',digest=base64.b64encode(sha(request_file).encode()).decode()))
        if tamper:inputs[0]['digest']=base64.b64encode(b'0'*64).decode()
        begin=time.perf_counter()
        if mode=='fresh':
            p=subprocess.run([str(SDK/'dotnet'), str(RUNNER), '--portable-request', 'request.json'], cwd=root, capture_output=True, text=True, timeout=120)
            response=dict(exitCode=p.returncode, output=p.stdout+p.stderr)
        else:
            worker.stdin.write(json.dumps(dict(arguments=['request.json'],inputs=inputs,requestId=len(rows)+1))+'\n');worker.stdin.flush()
            if not select.select([worker.stdout], [], [], 120)[0]:raise TimeoutError(label)
            response=json.loads(worker.stdout.readline())
            assert response['requestId']==len(rows)+1
        seconds=time.perf_counter()-begin
        (output/(label+'.log')).write_text(response['output'])
        if (root/'result/diagnostics').exists():shutil.copytree(root/'result/diagnostics', output/(label+'-diagnostics'), dirs_exist_ok=True)
        assert (response['exitCode']==0)==(expected==0), (label,response['output'][-5000:])
        row=dict(label=label, mode=mode, seconds=seconds, exitCode=response['exitCode'])
        if response['exitCode']==0:
            hashes={str(p.relative_to(root/'result')):sha(p) for field in ['bundle','api','runtime'] for p in (root/'result'/field).rglob('*') if p.is_file()}
            row['hashes']=hashes
            if baseline is None:baseline=hashes
            if label.startswith(('fresh','worker')):assert hashes==baseline, ('output mismatch',label)

        rows.append(row)
        (output/'report.json').write_text(json.dumps(rows,indent=2))
        print(label,round(seconds,3),response['exitCode'],flush=True)
        return row
    for i in range(3):invoke('fresh-'+str(i),'fresh')
    worker=launch()
    try:
        for i in range(5):invoke('worker-'+str(i),'worker')
        Path('/workspace/worker-secret').write_text('secret')
        invoke('absolute-read','worker',dict(readProbe='/workspace/worker-secret'),expected=1)
        invoke('write-input','worker',dict(writeProbe='/worker/in/src/Value.cs'),expected=1)
        invoke('digest-mismatch','worker',expected=1,tamper=True)
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen()
            with socket.create_connection(server.getsockname(), timeout=1):pass
            invoke('network','worker',dict(networkProbe='http://127.0.0.1:'+str(server.getsockname()[1])),expected=1)
        old=(src/'Value.cs').read_text();stamp=(src/'Value.cs').stat()
        (src/'Value.cs').write_text(old.replace('=> 7','=> 8'));os.utime(src/'Value.cs',ns=(stamp.st_atime_ns,stamp.st_mtime_ns));prepare()
        changed=invoke('source-edit','worker');assert changed['hashes']!=baseline
        (src/'Value.cs').write_text('invalid csharp');prepare();invoke('compile-failure','worker',expected=1)
        (src/'Value.cs').write_text(old);prepare();invoke('worker-after-failure','worker')
    finally:
        worker.stdin.close();worker.wait(timeout=30)
    bazel(root, output, request)
    print('All controls passed',flush=True)


def bazel(root, output, request):
    (root/'MODULE.bazel').write_text('module(name="compiler_worker_probe")\n')
    shutil.copy(ROOT/'tests/remote_workers/compiler_worker_rule.bzl', root/'probe.bzl')
    shutil.copytree(RUNNER.parent, root/'tools')
    (root/'dotnet').symlink_to(SDK/'dotnet')
    build='load(":probe.bzl", "compile")\nexports_files(["dotnet"])\n'
    for name in ['one','two']:
        build+='compile(name='+repr(name)+', request_json='+repr(json.dumps(request))+', srcs=glob(["src/**", "plan/**"]), support=glob(["tools/*"]), runner="tools/NativeProjectCache.dll", dotnet="dotnet")\n'
    (root/'BUILD.bazel').write_text(build)
    startup=[os.environ['RULES_MSBUILD_BAZEL'],'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base=/workspace/compiler-bazel']
    flags=['--incompatible_autoload_externally=','--strategy=CompilerWorkerProbe=worker','--worker_max_instances=1','--worker_verbose','--noshow_progress']
    results=[]
    try:
        for name in ['one','two']:
            begin=time.perf_counter()
            p=subprocess.run(startup+['build','//:'+name]+flags, cwd=root, capture_output=True,text=True,timeout=180)
            (output/('bazel-'+name+'.log')).write_text(p.stdout+p.stderr)
            assert p.returncode==0, p.stderr[-5000:]
            result=json.loads((root/'bazel-bin'/(name+'.diagnostics/worker.json')).read_text())
            result['wallSeconds']=time.perf_counter()-begin;results.append(result)
        assert results[0]['processId']==results[1]['processId'],results
        (output/'bazel-report.json').write_text(json.dumps(results,indent=2))
        print('Actual Bazel worker reuse passed',flush=True)
    finally:subprocess.run(startup+['shutdown'],cwd=root,capture_output=True,timeout=60)


if __name__=='__main__':run(Path(sys.argv[1]))
