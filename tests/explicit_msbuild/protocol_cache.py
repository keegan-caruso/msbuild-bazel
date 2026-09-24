"""Synthetic test-cache invalidation and independent HTTP recovery (standalone harness)."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def serve(root, port):
    root.mkdir(parents=True, exist_ok=True)
    class Cache(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args): pass
        def key(self):
            parts=self.path.strip('/').split('/')
            if len(parts)!=2 or parts[0] not in ('ac','cas') or not re.fullmatch('[0-9a-f]{64}',parts[1]): raise ValueError(self.path)
            return root/(parts[0]+'-'+parts[1])
        def do_GET(self):
            path=self.key()
            if not path.exists(): self.send_error(404);return
            self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
            with path.open('rb') as stream:shutil.copyfileobj(stream,self.wfile)
        def do_PUT(self):
            with tempfile.NamedTemporaryFile(dir=root,delete=False) as stream:
                stream.write(self.rfile.read(int(self.headers['Content-Length'])))
                temporary=Path(stream.name)
            temporary.replace(self.key())
            self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
    ThreadingHTTPServer(('0.0.0.0',port),Cache).serve_forever()


def run(folder,cache,consume=False):
    from protocol import BAZEL, command
    workspace=folder/'src'
    startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/('consumer-base' if consume else 'base')),'--ignore_all_rc_files']
    target='//Vstest/Xunit:Xunit'
    rows=[]
    def test(name,success=True,flags=()):
        bep=folder/(name+'.bep')
        p=command(startup+['test',target,'--test_output=all','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--jobs=4','--disk_cache=','--remote_cache='+cache,'--remote_download_outputs=all','--remote_cache_async=false','--remote_upload_local_results='+str(not consume).lower(),'--build_event_json_file='+str(bep),*flags],workspace,folder/(name+'.log'))
        assert (p.returncode==0)==success,(name,(p.stdout+p.stderr)[-4000:])
        events=[json.loads(line) for line in bep.read_text().splitlines()]
        result=next(e['testResult'] for e in events if 'testResult' in e)
        summary=next(e['buildMetrics']['actionSummary'] for e in events if 'buildMetrics' in e)
        row=dict(case=name,status=result['status'],cachedLocally=result.get('cachedLocally',False),cachedRemotely=result.get('executionInfo',{}).get('cachedRemotely',False),strategy=result.get('executionInfo',{}).get('strategy'),actions={a['mnemonic']:int(a.get('actionsExecuted',0)) for a in summary.get('actionData',[])},runners={a['name']:a['count'] for a in summary.get('runnerCount',[])})
        rows.append(row);print(json.dumps(row),flush=True)
        return row
    try:
        if consume:
            row=test('independent-cache')
            assert row['cachedRemotely'],row
            assert not row['runners'].get('worker') and not row['runners'].get('linux-sandbox'),row
            outputs=workspace/'bazel-testlogs/Vstest/Xunit/Xunit'
            assert (outputs/'test.xml').exists() and (outputs/'test.outputs/results.trx').exists()
            return
        lib=workspace/'Library';lib.mkdir(exist_ok=True)
        (lib/'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        source=lib/'Value.cs';source.write_text('public static class Value { public static int Get() => 7; }')
        (lib/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library")\nmsbuild_library(name="Library",project="Library.csproj",target_framework="net10.0",srcs=["Value.cs"],linux_worker=True,visibility=["//visibility:public"])\n')
        root=workspace/'Vstest/Xunit';project=root/'Xunit.csproj';build=root/'BUILD.bazel';code=root/'Tests.cs';data=root/'data.txt';settings=root/'settings.runsettings'
        originals={p:p.read_bytes() for p in (project,build,code,settings)}
        try:
            project.write_text(project.read_text().replace('</Project>','<ItemGroup><ProjectReference Include="../../Library/Library.csproj"/></ItemGroup></Project>'))
            build.write_text(build.read_text().replace('deps=[','deps=["//Library",',1).replace('size="small"','data=["data.txt"],size="small"'))
            code.write_text(code.read_text().replace('Assert.True(System.Environment', 'Assert.Equal(7,Value.Get()); Assert.Equal("good",System.IO.File.ReadAllText("data.txt")); Assert.Equal("declared",System.Environment.GetEnvironmentVariable("FROM_SETTINGS")); Assert.True(System.Environment'))
            data.write_text('good')
            # Seed the complete test action, not just assembly actions.
            test('cache-seed',flags=['--remote_accept_cached=false'])
            row=test('unchanged');assert row['cachedLocally'],row
            reference=workspace/'bazel-bin/Library/Library.reference/Library.dll';before=hashlib.sha256(reference.read_bytes()).hexdigest()
            source.write_text(source.read_text().replace('=> 7','=> 8'))
            row=test('body-edit',False);assert row['actions'].get('MSBuildAssembly')==1 and not row['cachedLocally'] and not row['cachedRemotely'],row
            assert hashlib.sha256(reference.read_bytes()).hexdigest()==before
            source.write_text(source.read_text().replace('=> 8','=> 7'));test('body-recovered')
            data.write_text('bad');row=test('data-edit',False);assert row['actions'].get('MSBuildAssembly',0)==0,row
            data.write_text('good');test('data-recovered')
            settings.write_text(settings.read_text().replace('declared','changed'));row=test('settings-edit',False);assert row['actions'].get('MSBuildAssembly',0)==0,row
            settings.write_bytes(originals[settings]);test('settings-recovered')
            row=test('filter-only',flags=['--test_filter=FullyQualifiedName~Passes']);assert row['actions'].get('MSBuildAssembly',0)==0,row
            row=test('final-seed');assert row['status']=='PASSED'
            # Retain this qualified workspace for the independent consumer.
            originals={}
        finally:
            for p,content in originals.items():p.write_bytes(content)
    finally:
        (folder/('cache-consumer-results.json' if consume else 'cache-results.json')).write_text(json.dumps(rows,indent=2)+'\n')
        subprocess.run(startup+['shutdown'],cwd=workspace,check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['serve','seed','consume']);parser.add_argument('folder',type=Path);parser.add_argument('--cache');parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
    if args.mode=='serve':serve(args.folder,args.port)
    else:run(args.folder.resolve(),args.cache,args.mode=='consume')
