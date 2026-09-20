"""Qualify the production Linux compiler worker and measure sequential actions."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import time
import threading

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
    generator_bundle=root/'generator;$(literal)@x'
    (src/'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Deterministic>true</Deterministic><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="Value.cs" /></ItemGroup></Project>')
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
        payload.update({'.nuget/packages/'+str(p.relative_to(root/'packages')):sha(p)
                        for p in (root/'packages').rglob('*') if p.is_file()})
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
    def launch(cache=True):
        return subprocess.Popen([str(SDK/'dotnet'), str(RUNNER), '--bazel-worker']+([] if cache else ['--disable-input-cache'])+['--persistent_worker'], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=(output/'worker.stderr').open('w'), text=True)
    def invoke(label, mode, overrides=None, expected=0, tamper=False):
        nonlocal baseline
        shutil.rmtree(root/'result', ignore_errors=True)
        request_file.write_text(json.dumps(dict(request, **(overrides or {}))))
        inputs=[dict(path=str(p.relative_to(root)), digest=base64.b64encode(sha(p).encode()).decode()) for folder in [src,plan,root/'packages',root/'dependency',generator_bundle] for p in folder.rglob('*') if p.is_file()]
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
            if mode=='worker':
                validation=json.loads((root/'result/diagnostics/input-validation.json').read_text())
                row.update(validation)
                row.update(json.loads((root/'result/diagnostics/worker.json').read_text()))
                log=(root/'result/diagnostics/build.log').read_text()
                assert 'server processed compilation' in log, label
            hashes={str(p.relative_to(root/'result')):sha(p) for field in ['bundle','api','runtime'] for p in (root/'result'/field).rglob('*') if p.is_file()}
            row['hashes']=hashes
            if baseline is None:baseline=hashes
            if label.startswith(('fresh','worker')):assert hashes==baseline, ('output mismatch',label)

        rows.append(row)
        (output/'report.json').write_text(json.dumps(rows,indent=2))
        print(label,round(seconds,3),response['exitCode'],flush=True)
        return row
    for i in range(3):invoke('fresh-'+str(i),'fresh')
    worker=launch(False)
    try:
        for i in range(5):invoke('worker-no-cache-'+str(i),'worker')
    finally:
        worker.stdin.close();worker.wait(timeout=30)
    worker=launch()
    try:
        for i in range(5):invoke('worker-'+str(i),'worker')
        Path('/workspace/worker-secret').write_text('secret')
        invoke('absolute-read','worker',dict(readProbe='/workspace/worker-secret'),expected=1)
        invoke('write-input','worker',dict(writeProbe='/worker/in/forbidden'),expected=1)
        (plan/'temporary.txt').write_text('previous input')
        prior=invoke('temporary-present','worker')
        (plan/'temporary.txt').unlink()
        invoke('previous-input-read','worker',dict(readProbe='/worker/in/'+prior['identity']+'/plan/temporary.txt'),expected=1)
        invoke('digest-mismatch','worker',expected=1,tamper=True)
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen()
            with socket.create_connection(server.getsockname(), timeout=1):pass
            invoke('network','worker',dict(networkProbe='http://127.0.0.1:'+str(server.getsockname()[1])),expected=1)
        old=(src/'Value.cs').read_text();stamp=(src/'Value.cs').stat()
        (src/'Value.cs').write_text(old.replace('=> 7','=> 8'));os.utime(src/'Value.cs',ns=(stamp.st_atime_ns,stamp.st_mtime_ns));prepare()
        changed=invoke('source-edit','worker');assert changed['hashes']!=baseline
        changed_fresh=invoke('edited-fresh','fresh');assert changed['hashes']==changed_fresh['hashes']
        (src/'Value.cs').write_text('invalid csharp');prepare();invoke('compile-failure','worker',expected=1)
        (src/'Value.cs').write_text(old);prepare();invoke('worker-after-failure','worker')
    finally:
        worker.stdin.close();worker.wait(timeout=30)
    packages=root/'packages/test/1.0';packages.mkdir(parents=True)
    for i in range(4):
        with (packages/(str(i)+'.data')).open('wb') as stream:
            for _ in range(64):stream.write(bytes([i])*1024*1024)
        (packages/(str(i)+'.data')).chmod(0o444)
    prepare();request.update(packageDirectories=[dict(source='packages/test/1.0',package='test/1.0')],borrowPackageInputs=True)
    baseline=None
    for mode,cache in [('fresh',False),('worker-no-cache',False),('worker',True)]:
        worker=launch(cache) if mode!='fresh' else None
        try:
            for i in range(4):invoke(mode+'-package-'+str(i),'fresh' if mode=='fresh' else 'worker')
            if cache:
                (packages/'0.data').chmod(0o644)
                with (packages/'0.data').open('r+b') as stream:stream.write(b'changed')
                (packages/'0.data').chmod(0o444)
                invoke('stale-package-payload','worker',expected=1)
                prepare();edited=invoke('package-edit','worker')
                fresh=invoke('package-edit-oracle','fresh');assert fresh['hashes']==edited['hashes']
        finally:
            if worker:worker.stdin.close();worker.wait(timeout=30)
    # Exercise a real sealed API dependency, including byte corruption and an
    # API change that must invalidate the consumer's former successful build.
    dependency=root/'dependency';shutil.copytree(root/'result/api',dependency)
    producer=json.loads((plan/'manifest.json').read_text())['projects']['Library.csproj']
    consumer=src/'Consumer';consumer.mkdir()
    (consumer/'Consumer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="../Library.csproj" /></ItemGroup></Project>')
    (consumer/'Use.cs').write_text('public static class Use { public static int Get() => Value.Get(); }')
    subprocess.run([str(SDK/'dotnet'),'restore','Consumer/Consumer.csproj','--nologo'],cwd=src,check=True,capture_output=True)
    restore.update({str(p.relative_to(src)):p.read_text().replace(str(src),'${WORKSPACE}').replace(str(SDK),'${SDK}').replace('/root','${HOME}')
                    for p in (consumer/'obj').glob('*') if p.name=='project.assets.json' or p.name.endswith(('.nuget.g.props','.nuget.g.targets'))})
    shutil.rmtree(consumer/'obj');shutil.rmtree(src/'obj')
    (plan/'restore.json').write_text(json.dumps(restore))
    request['sources']=[dict(source='src/'+str(p.relative_to(src)),destination=str(p.relative_to(src))) for p in src.rglob('*') if p.is_file()]
    def consumer_plan():
        prepare();manifest=json.loads((plan/'manifest.json').read_text())
        manifest['projects']['Consumer/Consumer.csproj']=dict(identity=sha(plan/'payload.json'),dependencies=['Library.csproj'])
        manifest['projects']['Library.csproj']=producer
        (plan/'manifest.json').write_text(json.dumps(manifest))
        request.update(entry='Consumer/Consumer.csproj',prebuilt=['dependency'])
    consumer_plan();worker=launch()
    try:
        prior=invoke('staged-dependency-consumer','worker')
        request['directDependencies']=True
        first=invoke('dependency-consumer','worker');assert first['hashes']==prior['hashes']
        oracle=invoke('dependency-consumer-oracle','fresh');assert first['hashes']==oracle['hashes']
        artifact=next((dependency/'artifacts').rglob('*.dll'));data=artifact.read_bytes();artifact.write_bytes(b'corrupt')
        invoke('dependency-corrupt','worker',expected=1);artifact.write_bytes(data)
        (src/'Value.cs').write_text((src/'Value.cs').read_text().replace('Get()', 'GetNumber()'))
        prepare();request.update(entry='Library.csproj',prebuilt=[])
        invoke('producer-api-edit','worker')
        producer=json.loads((plan/'manifest.json').read_text())['projects']['Library.csproj']
        shutil.rmtree(dependency);shutil.copytree(root/'result/api',dependency)
        consumer_plan();invoke('stale-consumer-api','worker',expected=1)
        (consumer/'Use.cs').write_text((consumer/'Use.cs').read_text().replace('Value.Get()', 'Value.GetNumber()'))
        consumer_plan();edited=invoke('consumer-api-edit','worker')
        oracle=invoke('consumer-api-edit-oracle','fresh');assert edited['hashes']==oracle['hashes']
    finally:worker.stdin.close();worker.wait(timeout=30)
    # Real project analyzer, built against the pinned SDK Roslyn assemblies.
    # The implementation must be loaded from the prepared input tree and a
    # changed generator must not be served from Roslyn's earlier assembly cache.
    generator=src/'Generator';generator.mkdir()
    (generator/'Generator.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><Reference Include="Microsoft.CodeAnalysis"><HintPath>$(MSBuildBinPath)/Roslyn/bincore/Microsoft.CodeAnalysis.dll</HintPath><Private>false</Private></Reference><Reference Include="Microsoft.CodeAnalysis.CSharp"><HintPath>$(MSBuildBinPath)/Roslyn/bincore/Microsoft.CodeAnalysis.CSharp.dll</HintPath><Private>false</Private></Reference></ItemGroup></Project>')
    generator_source='using Microsoft.CodeAnalysis; [Generator] public sealed class Emit : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { c.AddSource("Generated.g.cs", "public static class Generated { public const int Value = 7; }"); } }'
    (generator/'Emit.cs').write_text(generator_source)
    project=consumer/'Consumer.csproj'
    project.write_text(project.read_text().replace('</ItemGroup>','<ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false" /></ItemGroup>'))
    (consumer/'Use.cs').write_text('public static class Use { public static int Get() => Value.GetNumber() + Generated.Value; }')
    subprocess.run([str(SDK/'dotnet'),'restore','Consumer/Consumer.csproj','--nologo'],cwd=src,check=True,capture_output=True)
    for folder in list(src.rglob('obj')):
        restore.update({str(p.relative_to(src)):p.read_text().replace(str(src),'${WORKSPACE}').replace(str(SDK),'${SDK}').replace('/root','${HOME}')
                        for p in folder.glob('*') if p.name=='project.assets.json' or p.name.endswith(('.nuget.g.props','.nuget.g.targets'))})
        shutil.rmtree(folder)
    (plan/'restore.json').write_text(json.dumps(restore))
    request['sources']=[dict(source='src/'+str(p.relative_to(src)),destination=str(p.relative_to(src))) for p in src.rglob('*') if p.is_file()]
    worker=launch()
    try:
        def build_generator(label):
            prepare();manifest=json.loads((plan/'manifest.json').read_text())
            declaration=dict(identity=sha(plan/'payload.json'),dependencies=[],implementation=True)
            manifest['projects']={'Generator/Generator.csproj':declaration}
            (plan/'manifest.json').write_text(json.dumps(manifest))
            request.update(entry='Generator/Generator.csproj',prebuilt=[],directDependencies=True)
            invoke(label,'worker')
            shutil.rmtree(generator_bundle,ignore_errors=True);shutil.copytree(root/'result/api',generator_bundle)
            for dll in generator_bundle.rglob('*.dll'):os.utime(dll,ns=(0,0))
            return declaration
        analyzer=build_generator('generator-producer')
        old_generator_size=(generator_bundle/'artifacts/Generator/bin/Release/net10.0/Generator.dll').stat().st_size
        def analyzer_plan():
            consumer_plan();manifest=json.loads((plan/'manifest.json').read_text())
            manifest['projects']['Generator/Generator.csproj']=analyzer
            manifest['projects']['Consumer/Consumer.csproj'].update(dependencies=['Library.csproj','Generator/Generator.csproj'],analyzers=['Generator/Generator.csproj'])
            (plan/'manifest.json').write_text(json.dumps(manifest));request['prebuilt']=['dependency',generator_bundle.name]
        analyzer_plan();request['directDependencies']=False
        prior=invoke('staged-analyzer-consumer','worker')
        request['directDependencies']=True
        first=invoke('direct-analyzer-consumer','worker');assert first['hashes']==prior['hashes']
        (generator/'Emit.cs').write_text(generator_source.replace('Value = 7','Value = 8'))
        analyzer=build_generator('generator-body-edit');analyzer_plan()
        assert (generator_bundle/'artifacts/Generator/bin/Release/net10.0/Generator.dll').stat().st_size==old_generator_size
        edited=invoke('direct-analyzer-edit','worker');assert edited['hashes']!=first['hashes']
        assert edited['preparedRoots'][generator_bundle.name]!=first['preparedRoots'][generator_bundle.name]
        assert edited['preparedRoots']['dependency']==first['preparedRoots']['dependency']
        request['directDependencies']=False
        oracle=invoke('analyzer-edit-oracle','fresh');assert edited['hashes']==oracle['hashes']
        request['directDependencies']=True
    finally:worker.stdin.close();worker.wait(timeout=30)
    bazel(root, output, request)
    print('All controls passed',flush=True)


def bazel(root, output, request):
    (root/'MODULE.bazel').write_text('module(name="compiler_worker_probe")\n')
    shutil.copy(ROOT/'tests/remote_workers/compiler_worker_rule.bzl', root/'probe.bzl')
    shutil.copytree(RUNNER.parent, root/'tools')
    (root/'dotnet').symlink_to(SDK/'dotnet')
    build='load(":probe.bzl", "compile")\nexports_files(["dotnet"])\n'
    for name in ['one','two']:
        build+='compile(name='+repr(name)+', request_json='+repr(json.dumps(request))+', srcs=glob(["src/**", "plan/**", "packages/**", "dependency/**", "generator*/**"]), support=glob(["tools/*"]), runner="tools/NativeProjectCache.dll", dotnet="dotnet")\n'
    (root/'BUILD.bazel').write_text(build)
    startup=[os.environ['RULES_MSBUILD_BAZEL'],'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base=/workspace/compiler-bazel']
    cache_root=output/'remote-cache';cache_root.mkdir()
    class Cache(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def path_for(self):
            parts=self.path.strip('/').split('/')
            if len(parts)!=2 or parts[0] not in ('ac','cas') or len(parts[1])!=64 or any(c not in '0123456789abcdef' for c in parts[1]):raise ValueError(self.path)
            return cache_root/(parts[0]+'-'+parts[1])
        def do_GET(self):
            path=self.path_for()
            if not path.exists():self.send_error(404);return
            self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
            with path.open('rb') as stream:shutil.copyfileobj(stream,self.wfile)
        def do_PUT(self):
            self.path_for().write_bytes(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Cache);threading.Thread(target=server.serve_forever,daemon=True).start()
    flags=['--remote_cache=http://127.0.0.1:'+str(server.server_port),'--incompatible_autoload_externally=','--strategy=CompilerWorkerProbe=worker','--worker_max_instances=1','--worker_verbose','--noshow_progress']
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
        assert results[0]['preparedRoots']==results[1]['preparedRoots'],results
        original={str(p.relative_to(root/'bazel-bin/one.output')):sha(p) for p in (root/'bazel-bin/one.output').rglob('*') if p.is_file()}
        subprocess.run(startup+['shutdown'],cwd=root,capture_output=True,check=True,timeout=60)
        remaining=list(Path('/tmp').glob('.msbuild-worker-*'))
        assert not remaining, ('Broker cache survived shutdown',remaining)
        shutil.rmtree('/workspace/compiler-bazel')
        for path in root.glob('bazel-*'):
            if path.is_symlink():path.unlink()
        p=subprocess.run(startup+['build','//:one']+flags,cwd=root,capture_output=True,text=True,timeout=180)
        (output/'bazel-recovery.log').write_text(p.stdout+p.stderr)
        assert p.returncode==0 and 'remote cache hit' in p.stderr,p.stderr[-5000:]
        recovered={str(p.relative_to(root/'bazel-bin/one.output')):sha(p) for p in (root/'bazel-bin/one.output').rglob('*') if p.is_file()}
        assert recovered==original
        (output/'bazel-report.json').write_text(json.dumps(dict(builds=results,producerStateDeleted=True,remoteRecoveryIdentical=True),indent=2))
        print('Actual Bazel worker reuse passed',flush=True)
    finally:
        subprocess.run(startup+['shutdown'],cwd=root,capture_output=True,timeout=60)
        server.shutdown();server.server_close()


if __name__=='__main__':run(Path(sys.argv[1]))
