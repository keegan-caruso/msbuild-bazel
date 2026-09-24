"""Qualify pinned upstream test suites using explicit BUILD declarations and raw VSTest controls.

Run after the synthetic protocol fixtures. Evaluation/restore is fixture preparation,
not part of the production rule or test action. Sources are copied before selection.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

RULES=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])
CONFIG=json.loads((RULES/'tests/explicit_msbuild/oss/projects.json').read_text())
ENTRIES={'serilog':['test/Serilog.Tests/Serilog.Tests.csproj'],'spectre':['src/Spectre.Console.Ansi.Tests/Spectre.Console.Ansi.Tests.csproj','src/Spectre.Console.Tests/Spectre.Console.Tests.csproj']}


def run(command,cwd,log,allow_failure=False):
    with log.open('w') as stream:p=subprocess.run([str(v) for v in command],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT)
    print(log.name,p.returncode,flush=True)
    if p.returncode and not allow_failure:raise RuntimeError(str(log))
    return p.returncode


def results(path):
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    return Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult',ns))


def qualify(name,checkout,folder,synthetic):
    config=CONFIG[name];folder.mkdir(parents=True,exist_ok=True);source=folder/'source'
    revision=subprocess.check_output(['git','-c','safe.directory='+str(checkout),'-C',str(checkout),'rev-parse','HEAD'],text=True).strip();assert revision==config['commit']
    if not source.exists():shutil.copytree(checkout,source,ignore=shutil.ignore_patterns('.git','bin','obj','artifacts','._*'))
    selection=[]
    for path in source.rglob('*.csproj'):
        text=path.read_text(encoding='utf-8-sig');new=re.sub(r'<TargetFrameworks(?:\s+[^>]*)?>[^<]*</TargetFrameworks>','<TargetFrameworks>net10.0</TargetFrameworks>',text)
        if new!=text:path.write_text(new);selection.append(str(path.relative_to(source)))
    for patch in config.get('patches',[]):
        p=source/patch['path'];text=p.read_text(encoding='utf-8-sig')
        if patch['before'] in text:p.write_text(text.replace(patch['before'],patch['after']))
    globaljson=source/'global.json';settings=json.loads(globaljson.read_text());settings['sdk']={'version':'10.0.400','rollForward':'disable'};globaljson.write_text(json.dumps(settings))
    entries=ENTRIES[name]
    config=dict(config,entries=entries,properties=dict(config['properties'],NuGetAudit='false',DebugType='portable',ProduceReferenceAssembly='true'))
    (folder/'config.json').write_text(json.dumps(config,indent=2));(folder/'framework-selection.json').write_text(json.dumps(selection,indent=2))
    props=['-p:'+k+'='+v for k,v in config['properties'].items()]+['-p:RestorePackagesPath='+str(folder/'nuget')]
    for index,entry in enumerate(entries):run([SDK/'dotnet','build',entry,'-c','Release',*props],source,folder/('raw-build-'+str(index)+'.log'))
    probe=folder/'probe';probe.mkdir(exist_ok=True)
    for src,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:shutil.copyfile(RULES/'tests/explicit_msbuild/oss'/src,probe/dest)
    run([SDK/'dotnet','build',probe/'Inventory.csproj','-c','Release'],folder,folder/'probe.log')
    run([SDK/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,folder/'config.json',folder/'inventory.json'],folder,folder/'inventory.log')
    if (folder/'bazel').exists():shutil.rmtree(folder/'bazel')
    run([sys.executable,RULES/'tests/explicit_msbuild/oss/prepare.py',folder,RULES],folder,folder/'prepare.log')
    workspace=folder/'bazel';build=workspace/'BUILD.bazel';text=build.read_text();text='load("@rules_msbuild//msbuild:defs.bzl","msbuild_test","msbuild_test_tool")\n'+text
    runner=synthetic/'vstest-lock/packages/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg'
    shutil.copyfile(runner,workspace/'locked-packages'/runner.name)
    text+='msbuild_nuget_package(name="test_runner_package",package_id="Microsoft.TestPlatform.CLI",version="17.14.1",archive="locked-packages/'+runner.name+'",archive_sha256="'+hashlib.sha256(runner.read_bytes()).hexdigest()+'",content_hash="'+base64.b64encode(hashlib.sha512(runner.read_bytes()).digest()).decode()+'")\n'
    text+='msbuild_test_tool(name="test_runner",package=":test_runner_package",path="contentFiles/any/net9.0/vstest.console.dll")\n'
    inventory=json.loads((folder/'inventory.json').read_text());test_names=[]
    for entry in entries:
        label=Path(entry).stem;test_names.append(label)
        row=next(r for r in inventory if r['project']==entry);assets=json.loads(Path(row['assets']).read_text())
        key=next(k for k in assets['targets'][row['framework']] if k.lower().startswith('xunit.runner.visualstudio/'));version=key.split('/')[1]
        archive=workspace/'locked-packages'/('xunit.runner.visualstudio.'+version+'.nupkg')
        with zipfile.ZipFile(archive) as z:
            paths=[str(Path(n).parent) for n in z.namelist() if n.endswith('xunit.runner.visualstudio.testadapter.dll') and '/net4' not in n]
        assert len(paths)==1,paths
        text+='msbuild_test_tool(name="'+label+'_adapter",package=":archive_'+key.replace('/','_').lower()+'",path="'+paths[0]+'")\n'
        lines=text.splitlines()
        for i,line in enumerate(lines):
            if line.startswith(('msbuild_library(name="'+label+'",','msbuild_binary(name="'+label+'",')):
                lines[i]=line.replace(line.split('(')[0]+'(','msbuild_test(',1)[:-1]+',test_protocol="vstest",test_runner=":test_runner",test_adapters=[":'+label+'_adapter"],size="large")'
        text='\n'.join(lines)+'\n'
    build.write_text(text)
    startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files'];report=[]
    try:
        for label in test_names:
            flags=['--test_output=errors','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--jobs=4','--local_test_jobs=1']
            bazel_exit=run(startup+['test','//:'+label,*flags,'--build_event_json_file='+str(folder/(label+'.bep'))],workspace,folder/(label+'-bazel.log'),allow_failure=True)
            row=next(r for r in inventory if Path(r['project']).stem==label)
            raw=source/Path(row['project']).parent/'bin/Release'/row['framework']/(row['properties']['AssemblyName']+'.dll')
            runner_dll=synthetic/'vstest-lock/packages/microsoft.testplatform.cli/17.14.1/contentFiles/any/net9.0/vstest.console.dll'
            rawresults=folder/('raw-'+label);rawresults.mkdir(exist_ok=True)
            run([SDK/'dotnet',runner_dll,raw,'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(rawresults)],source,folder/(label+'-raw-test.log'),allow_failure=True)
            actual=results(workspace/'bazel-testlogs'/label/'test.outputs/results.trx');expected=results(rawresults/'results.trx')
            report.append(dict(project=row['project'],cases=sum(actual.values()),outcomes=dict(Counter(outcome for (_,outcome),count in actual.items() for _ in range(count))),sameNamesAndOutcomes=actual==expected,rawOnly=[list(k)+[v] for k,v in (expected-actual).items()],bazelOnly=[list(k)+[v] for k,v in (actual-expected).items()]))
            if bazel_exit:continue
            run(startup+['test','//:'+label,*flags,'--build_event_json_file='+str(folder/(label+'-cached.bep'))],workspace,folder/(label+'-cached.log'))
            events=[json.loads(l) for l in (folder/(label+'-cached.bep')).read_text().splitlines()]
            assert next(e['testResult'] for e in events if 'testResult' in e)['cachedLocally']
    finally:
        (folder/'test-results.json').write_text(json.dumps(dict(repository=config['repository'],revision=revision,framework='net10.0',results=report),indent=2)+'\n')
        subprocess.run(startup+['shutdown'],cwd=workspace)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name',choices=ENTRIES);p.add_argument('checkout',type=Path);p.add_argument('folder',type=Path);p.add_argument('synthetic',type=Path);a=p.parse_args();qualify(a.name,a.checkout.resolve(),a.folder.resolve(),a.synthetic.resolve())
