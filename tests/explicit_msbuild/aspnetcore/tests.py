"""Run a managed ASP.NET Core test slice from the pinned large-graph fixture.

The workspace is prepared by prepare.py plus the qualified remote overlay. This
harness changes only the selected BUILD rules into tests and declares their runner.
"""
import argparse
import ast
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

NAMES=['Microsoft.Net.Http.Headers','Microsoft.AspNetCore.Http.Abstractions','Microsoft.AspNetCore.Http.Extensions','Microsoft.AspNetCore.Http.Results','Microsoft.AspNetCore.Http','Microsoft.AspNetCore.Mvc.Routing.Abstractions','Microsoft.AspNetCore.WebUtilities','Microsoft.AspNetCore.DataProtection.Abstractions','Microsoft.AspNetCore.Cryptography.Internal','Microsoft.AspNetCore.Cryptography.KeyDerivation','Microsoft.AspNetCore.RequestDecompression','Microsoft.AspNetCore.ResponseCompression']
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])


def call(rule,**attrs):
    return rule+'('+','.join(k+'='+(str(v) if isinstance(v,bool) else json.dumps(v)) for k,v in attrs.items())+')'


def result(path):
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    return Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult',ns))


def run(args,cwd,log):
    with log.open('w') as stream:p=subprocess.run([str(v) for v in args],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT)
    print(log.name,p.returncode,flush=True);return p.returncode


def prepare(workspace,synthetic):
    build=workspace/'upstream/BUILD.bazel';backup=workspace/'original-test-build.txt'
    if not backup.exists():shutil.copyfile(build,backup)
    text=backup.read_text();lines=text.splitlines();records={}
    for i,line in enumerate(lines):
        if not line.startswith(('msbuild_library(', 'msbuild_binary(', 'msbuild_package_lock(', 'msbuild_nuget_package(')):continue
        node=ast.parse(line).body[0].value;attrs={k.arg:ast.literal_eval(k.value) for k in node.keywords};records[attrs['name']]=(i,attrs)
        if node.func.id=='msbuild_binary':attrs['_test_exe']=True
    extra=['load("@rules_msbuild//msbuild:defs.bzl","msbuild_test","msbuild_test_tool")'];selected=[]
    for prefix in NAMES:
        name=prefix+'.Tests_net10.0';i,attrs=records[name];selected.append(dict(name=name,project=attrs['project'],assembly=attrs['assembly_name']))
        locked=records[attrs['package_lock'].removeprefix(':')][1]['packages']
        adapter=next(label for label in locked if records[label.removeprefix(':')][1]['package_id'].lower()=='xunit.runner.visualstudio')
        archive=records[adapter.removeprefix(':')][1]
        with zipfile.ZipFile(workspace/'upstream'/archive['archive']) as z:
            paths=[str(Path(p).parent) for p in z.namelist() if p.endswith('xunit.runner.visualstudio.testadapter.dll') and '/net4' not in p]
        assert len(paths)==1,paths
        extra.append(call('msbuild_test_tool',name=name+'_adapter',package=adapter,path=paths[0]))
        attrs['adapter_imports']=attrs.get('adapter_imports',[])+['test-layout.targets']
        if prefix=='Microsoft.AspNetCore.Http.Results':
            attrs['data_paths']=dict(attrs.get('data_paths',{}),**{'src/Http/Http.Results/test/ResultsOfTTests.Generated.cs':'Shared/GeneratedContent/ResultsOfTTests.Generated.cs'})
        attrs.update(test_output_type='exe' if attrs.pop('_test_exe',False) else 'library',test_output_dirs=['test-logs'],test_protocol='vstest',test_runner=':test_runner',test_adapters=[':'+name+'_adapter'],size='large')
        lines[i]=call('msbuild_test',**attrs)
    archive=synthetic/'vstest-lock/packages/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg'
    shutil.copyfile(archive,workspace/'upstream/locked-packages'/archive.name)
    extra.append(call('msbuild_nuget_package',name='test_runner_package',package_id='Microsoft.TestPlatform.CLI',version='17.14.1',archive='locked-packages/'+archive.name,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),content_hash=base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()))
    extra.append(call('msbuild_test_tool',name='test_runner',package=':test_runner_package',path='contentFiles/any/net9.0/vstest.console.dll'))
    (workspace/'upstream/test-layout.targets').write_text('<Project><PropertyGroup><LoggingTestingFileLoggingDirectory>test-logs</LoggingTestingFileLoggingDirectory></PropertyGroup></Project>')
    build.write_text('\n'.join(extra[:1]+lines+extra[1:])+'\n');(workspace/'test-selection.json').write_text(json.dumps(selected,indent=2)+'\n');return selected


def bazel(workspace,synthetic,output):
    selected=prepare(workspace,synthetic);output.mkdir(parents=True,exist_ok=True)
    startup=[BAZEL,'--host_jvm_args=-Xmx1024m','--output_base='+str(output/'base'),'--ignore_all_rc_files']
    targets=['//upstream:'+r['name'] for r in selected]
    flags=['--keep_going','--test_output=errors','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--jobs=4','--local_test_jobs=1','--disk_cache=','--remote_cache=']
    try:
        exitcode=run(startup+['test',*targets,*flags,'--build_event_json_file='+str(output/'tests.bep')],workspace,output/'tests.log')
        events=[json.loads(line) for line in (output/'tests.bep').read_text().splitlines()]
        tested={e['id']['testResult']['label'] for e in events if 'testResult' in e}
        rows=[]
        for row in selected:
            trx=workspace/'bazel-testlogs/upstream'/row['name']/'test.outputs/results.trx'
            if '//upstream:'+row['name'] in tested and trx.exists():
                counts=result(trx);shutil.copyfile(trx,output/(row['name']+'.trx'))
                rows.append(dict(**row,tests=sum(counts.values()),outcomes=dict(Counter(outcome for (_,outcome),n in counts.items() for _ in range(n)))))
            else:rows.append(dict(**row,missingReport=True))
        (output/'results.json').write_text(json.dumps(dict(exitCode=exitcode,results=rows),indent=2)+'\n')
        if exitcode==0:
            assert run(startup+['test',*targets,*flags,'--build_event_json_file='+str(output/'cached.bep')],workspace,output/'cached.log')==0
            events=[json.loads(l) for l in (output/'cached.bep').read_text().splitlines()]
            tests=[e['testResult'] for e in events if 'testResult' in e];assert len(tests)==len(selected) and all(t.get('cachedLocally') for t in tests)
    finally:subprocess.run(startup+['shutdown'],cwd=workspace)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('synthetic',type=Path);p.add_argument('output',type=Path);a=p.parse_args();bazel(a.workspace.resolve(),a.synthetic.resolve(),a.output.resolve())
