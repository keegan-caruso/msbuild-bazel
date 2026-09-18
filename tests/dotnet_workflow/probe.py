"""Exercise the production .NET controller with Python denied in child PATH."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_http_cache import CacheServer
from probe_serilog_tests import REVISION, PROJECT, APPROVED
from probe_native_workflow import TESTS

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL = Path(os.environ['RULES_MSBUILD_BAZEL'])


def probe(checkout, packages, output):
    output.mkdir(parents=True, exist_ok=False)
    denied = output / 'denied'; denied.mkdir()
    for name in ('python', 'python3'):
        path = denied / name; path.write_text('#!/bin/sh\necho "PYTHON WAS INVOKED" >&2\nexit 97\n'); path.chmod(0o755)
    environment = dict(os.environ, PATH=str(denied) + ':/usr/bin:/bin', RULES_MSBUILD_TRACE='1')
    archive = subprocess.check_output(['git', '-C', str(checkout), 'archive', REVISION])
    report = dict(accepted=False, cases=[], pythonDeniedInChildPath=True)
    def fixture(base, cache=packages):
        base.mkdir(); source = base / 'source'
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents: contents.extractall(source, filter='data')
        restore(source, cache)
        return source
    def restore(source, cache=packages):
        result = subprocess.run([str(SDK/'dotnet'), 'msbuild', PROJECT, '-t:Restore', '-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], cwd=source, env=dict(environment, NUGET_PACKAGES=str(cache)), capture_output=True, text=True)
        (source.parent/'restore.log').write_text(result.stdout+result.stderr)
        assert result.returncode == 0, result.stderr
    def shutdown(base):
        state = base/'state'
        if (state/'g').exists():
            subprocess.run([str(BAZEL),'--nohome_rc','--noworkspace_rc','--output_base='+str(state/'b'),'--output_user_root='+str(state/'u'),'shutdown'],cwd=state/'g',env=environment,capture_output=True,check=True)
    def run(base, source, endpoint, snapshot=None, label='build', fail=False, cache=packages, mutate=False):
        request = dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(source),state=str(base/'state'),entry=PROJECT,output=str(base/label),operation='test',tests=TESTS,reuse=True,**{'incremental-sources':True,'nuget-packages':str(cache),'force-tests':True,'remote-endpoint':endpoint})
        if snapshot: request['remote-snapshot']=snapshot
        path=base/(label+'-request.json');path.write_text(json.dumps(request))
        applied = threading.Event(); stop = threading.Event()
        def mutation():
            while not stop.wait(.01):
                if (base/'state/g/BUILD.bazel').exists():
                    path=base/'state/workspace/src/Serilog/Log.cs';path.write_bytes(path.read_bytes()+b'\n// lease mutation\n');applied.set();return
        worker=threading.Thread(target=mutation,daemon=True) if mutate else None
        if worker:worker.start()
        result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'workflow','--request',str(path)],env=environment,cwd=ROOT,capture_output=True,text=True,timeout=900)
        stop.set()
        if worker:worker.join();assert applied.is_set(), 'lease mutation was not exercised'
        (base/(label+'.log')).write_text(result.stdout+result.stderr)
        value=json.loads((base/label/'report.json').read_text())
        assert (result.returncode==0) != fail, result.stderr
        assert value['accepted'] != fail, value
        if not fail:
            assert value['test']['passed'] and value['test']['runtimeHashes']==value['runtimeHashes']
            assert 'publishedSnapshot' in value['remote'], value
        return value
    def save(): (output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        with CacheServer(delay_ms=10) as server:
            endpoint=server.url+'/native';base=output/'producer';source=fixture(base)
            before=len(server.events);producer=run(base,source,endpoint);report['producer']=producer
            assert producer['compiles']==2,producer
            key=producer['remote']['publishedSnapshot'];original=server.data.copy()
            for label,edit in [('unchanged',False),('body',True)]:
                if edit:
                    path=source/'src/Serilog/Log.cs';path.write_text(path.read_text().replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);','public static bool IsEnabled(LogEventLevel level) => false;'))
                before=len(server.events);value=run(base,source,endpoint,label='local-'+label)
                assert value['preparation']['reused'] and value['compiles']==(1 if edit else 0),value
                report['cases'].append(dict(case='local-'+label,result=value,transport=server.totals(before)));save();print('local-'+label,value['seconds'],value['compiles'],flush=True)
            receipt_path=base/'state/preparation/receipt.json'
            receipt=json.loads(receipt_path.read_text());receipt['context']=[];receipt_path.write_text(json.dumps(receipt))
            before=len(server.events);value=run(base,source,endpoint,label='local-malformed-proof')
            assert value['preparation']['discoveryExecuted'] and not value['preparation']['reused'],value
            report['cases'].append(dict(case='local-malformed-proof',result=value,transport=server.totals(before)));save()
            print('local-malformed-proof',value['seconds'],value['compiles'],flush=True)
            shutdown(base)
            for directory, dirs, files in os.walk(base, followlinks=False):
                os.chmod(directory, 0o700)
            shutil.rmtree(base)
            for label in ('unchanged','body','api','package','corrupt-preparation','corrupt-project','namespace','missing-global','tampered-global','lease-mutation','failed-test'):
                base=output/label; cache=packages
                if label in ('missing-global','tampered-global'):
                    cache=output/(label+'-packages');shutil.copytree(packages,cache)
                source=fixture(base,cache)
                with server.lock:server.data=original.copy()
                if label=='missing-global':shutil.rmtree(cache/'shouldly/4.2.1')
                if label=='tampered-global':
                    path=cache/'shouldly/4.2.1/buildTransitive/Shouldly.targets';path.write_bytes(path.read_bytes()+b'\n<!-- changed -->\n')
                if label=='namespace':(source/'src/Serilog/NewInternal.cs').write_text('namespace Serilog; internal class NewInternal {}')
                if label=='body':
                    path=source/'src/Serilog/Log.cs';path.write_text(path.read_text().replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);','public static bool IsEnabled(LogEventLevel level) => false;'))
                if label=='api':
                    path=source/'src/Serilog/Log.cs';path.write_text(path.read_text()+'\n/// <summary>Cache probe.</summary>\npublic class CacheAddition {}\n')
                    # An API addition intentionally fails the approval test; use
                    # the failure to prove current runtime reaches test execution.
                if label=='package':
                    path=source/'src/Serilog/Serilog.csproj';path.write_text(path.read_text().replace('Version="1.15.0"','Version="1.16.0"'));restore(source)
                snapshot=json.loads(server.data['/native/cas/'+key])
                if label=='corrupt-preparation':server.data['/native/cas/'+snapshot['preparation']]=b'corrupt'
                if label=='corrupt-project':
                    for record in snapshot['projects']:server.data['/native/cas/'+record['blob']]=b'corrupt'
                if label=='failed-test':
                    path=source/APPROVED;path.write_text(path.read_text()+'\nintentional failure\n')
                before=len(server.events);failure=label in ('api','failed-test','missing-global','tampered-global','lease-mutation');value=run(base,source,endpoint,key,fail=failure,cache=cache,mutate=label=='lease-mutation')
                events=server.events[before:]
                if failure:
                    assert not any(e['method']=='PUT' for e in events)
                    assert not (base/'state/cache').exists()
                else:
                    expected=1 if label=='body' else 2 if label in ('package','corrupt-project') else 0
                    if label=='namespace':assert value['preparation']['discoveryExecuted'] and value['compiles']>=1,value
                    else:assert value['compiles']==expected,(label,value)
                    if label=='package':assert json.loads(server.data['/native/cas/'+value['remote']['publishedSnapshot']])['preparation'] is None
                    if label in ('unchanged','body','corrupt-project'):assert value['preparation']['reused'],value
                    if label=='unchanged':assert value['runtimeHashes']==producer['runtimeHashes']
                    if label=='missing-global':shutil.rmtree(cache/'shouldly/4.2.1')
                if label=='tampered-global':
                    path=cache/'shouldly/4.2.1/buildTransitive/Shouldly.targets';path.write_bytes(path.read_bytes()+b'\n<!-- changed -->\n')
                if label=='namespace':(source/'src/Serilog/NewInternal.cs').write_text('namespace Serilog; internal class NewInternal {}')
                if label=='body':assert value['runtimeHashes']!=producer['runtimeHashes']
                report['cases'].append(dict(case=label,result=value,transport=server.totals(before)));save();print(label,value['seconds'],value.get('compiles'),flush=True);shutdown(base)
            report['accepted']=True
    finally:save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('checkout','packages','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();probe(a.checkout,a.packages,a.output.resolve())
