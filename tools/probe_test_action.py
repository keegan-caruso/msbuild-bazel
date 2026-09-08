#!/usr/bin/env python3
"""Native Bazel test-rule prototype over a pathmapped ordinary upstream build."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from prepare_graph import ROOT, DOTNET_ROOT
from prepare_graph_tests import add_tests
from starlark import value
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_serilog_adapter import REVISION

PROJECT = 'test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj'
RUNTIME = 'test/Serilog.ApprovalTests/bin/Release/net10.0'
TEST = 'ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally'
APPROVED = 'test/Serilog.ApprovalTests/Serilog.approved.txt'
DATA = ['test/Serilog.ApprovalTests/ApiApprovalTests.cs', APPROVED]


def probe(source, packages, output):
    source, packages, output = map(lambda p: Path(p).resolve(), (source, packages, output))
    output.mkdir(parents=True, exist_ok=False)
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION: raise ValueError('wrong upstream revision')
    workspace = output / 'ordinary'
    raw = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive: archive.extractall(workspace, filter='data')
    shutil.copytree(packages, workspace / '.nuget/packages')
    dotnet = DOTNET_ROOT / 'dotnet'
    def run(label, args, cwd, success=True):
        result = subprocess.run(list(map(str,args)), cwd=cwd, env=cache_environment(output,cwd),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=600)
        (output / (label + '.log')).write_text(result.stdout)
        if success and result.returncode: raise RuntimeError(label + ' failed: ' + result.stdout[-4000:])
        return result
    run('runner-build',[dotnet,'build',ROOT/'tools/TestRunner','-c','Release','-nodeReuse:false','--nologo'],ROOT)
    run('ordinary-restore',[dotnet,'msbuild',PROJECT,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-nodeReuse:false','-nologo'],workspace)
    run('ordinary-build',[dotnet,'msbuild',PROJECT,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0',
        '-p:PathMap='+str(workspace)+'=/_/workspace','-nodeReuse:false','-nologo','-bl:'+str(output/'ordinary.binlog')],workspace)
    generated=output/'generated';generated.mkdir()
    bundle=generated/'input-bundle';bundle.mkdir()
    artifacts=[]
    for path in sorted((workspace/RUNTIME).rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(workspace).as_posix();target=bundle/'artifacts'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        artifacts.append(dict(path=relative,size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (bundle/'artifacts.json').write_text(json.dumps(artifacts))
    (bundle/'results.json').write_text(json.dumps(dict(schemaVersion=1,sdkVersion='10.0.400',targetFramework='net10.0',project=PROJECT,properties={'configuration':'Release','targetframework':'net10.0','IsGraphBuild':'true'})))
    (bundle/'bundle.json').write_text(json.dumps(dict(schemaVersion=1,resultsSha256=hashlib.sha256((bundle/'results.json').read_bytes()).hexdigest(),artifactsSha256=hashlib.sha256((bundle/'artifacts.json').read_bytes()).hexdigest())))
    for name in ('graph.bzl','msbuild.bzl'):shutil.copyfile(ROOT/'bazel'/name,generated/name)
    (generated/'MODULE.bazel').write_text('module(name="graph_test_prototype")\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\nlocal_dotnet_sdk(name="dotnet",path='+json.dumps(str(DOTNET_ROOT))+')\n')
    (generated/'host-identity.json').write_text(json.dumps(dict(scope='ordinary-runtime test-rule prototype')))
    (generated/'fixture.bzl').write_text('''load(":graph.bzl", "GraphBundle")
def _fixture(ctx):
    tree = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    ctx.actions.run_shell(inputs = ctx.files.srcs, outputs = [tree], command = 'mkdir -p "$2"; cp -R "$1"/. "$2"', arguments = [ctx.file.anchor.dirname, tree.path], mnemonic = "TestFixtureBundle")
    return [DefaultInfo(files = depset([tree])), GraphBundle(bundles = depset([tree]))]
bundle_fixture = rule(implementation = _fixture, attrs = {"srcs": attr.label_list(allow_files=True), "anchor": attr.label(allow_single_file=True)})
''')
    node=dict(id='subject',project='workspace/'+PROJECT,globalProperties={'configuration':'Release','targetframework':'net10.0'},execution={'outputDirectory':'workspace/'+RUNTIME},outputs=[{'kind':'assembly', 'path':'workspace/'+RUNTIME+'/Serilog.ApprovalTests.dll'}])
    declarations=add_tests(workspace,generated,{'subject':node},[dict(node='subject',data=DATA,expectedTests=[TEST])],ROOT)
    build='load(":fixture.bzl","bundle_fixture")\nload(":graph_test.bzl","graph_test")\nbundle_fixture(name="node_subject",srcs=glob(["input-bundle/**"]),anchor="input-bundle/bundle.json")\n'+declarations
    shutil.rmtree(workspace)
    report=dict(schemaVersion=1,scope='native-test-rule-over-ordinary-build',preparationWorkspaceAbsent=not workspace.exists(),cases={},accepted=False)
    strategy='darwin-sandbox' if os.uname().sysname=='Darwin' else 'linux-sandbox'
    data_path=generated/'test-data'/APPROVED;data_bytes=data_path.read_bytes()
    for case in ('pass','changed','missing','zeroTests'):
        current=build
        data_path.write_bytes(data_bytes)
        if case=='changed':
            bad=b'wrong approval\n';data_path.write_bytes(bad)
            current=current.replace(hashlib.sha256(data_bytes).hexdigest(),hashlib.sha256(bad).hexdigest())
        if case=='missing':
            declaration = '    data = ' + value(['test-data/'+p for p in DATA]) + ','
            if current.count(declaration) != 1:
                raise AssertionError('missing-data control could not locate the generated data declaration')
            current = current.replace(declaration, '    data = ' + value(['test-data/'+DATA[0]]) + ',')
        if case=='zeroTests':current=current.replace('assembly = "Serilog.ApprovalTests.dll"','assembly = "Serilog.dll"')
        (generated/'BUILD.bazel').write_text(current)
        execution=output/(case+'-execution.json')
        result=run(case,[BAZEL,'--batch','--nohome_rc','--noworkspace_rc','--output_base='+str(output/'base'),'--output_user_root='+str(output/'bazel-user'),
            'test','//:test_subject','--nocache_test_results','--zip_undeclared_test_outputs','--test_output=errors','--spawn_strategy='+strategy,'--strategy=TestRunner='+strategy,
            '--execution_log_json_file='+str(execution),'--noshow_progress','--color=no','--curses=no'],generated,success=False)
        evidence=output/'evidence'/case;evidence.mkdir(parents=True)
        for path in (generated/'bazel-testlogs/test_subject').rglob('*'):
            if path.is_file():target=evidence/path.relative_to(generated/'bazel-testlogs/test_subject');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        archive=evidence/'test.outputs/outputs.zip'
        if not archive.exists():raise RuntimeError('missing retained test outputs: '+result.stdout[-6000:])
        with zipfile.ZipFile(archive) as contents:
            summary=json.loads(contents.read('report.json'))
        report['cases'][case]=dict(returncode=result.returncode,report=summary,evidence=str(evidence),executionLog=execution.name)
        (output/'report.json').write_text(json.dumps(report,indent=2))
        if (result.returncode==0)!= (case=='pass') or summary['passed']!=(case=='pass'):raise AssertionError('wrong native result '+case)
        if case!='zeroTests' and summary['total']!=1:raise AssertionError('did not execute real Fact: '+str(summary))
        if case=='zeroTests' and summary['total']!=0:raise AssertionError('zero-test control did not select no-test library')
    report['accepted'] = True
    (output/'report.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('source','packages','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();probe(args.source,args.packages,args.output)
