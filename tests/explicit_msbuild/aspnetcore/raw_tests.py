"""Raw SDK/VSTest control for the same ASP.NET Core managed test selection."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])


def run(args,root,log):
    with log.open('w') as stream:p=subprocess.run([str(v) for v in args],cwd=root,stdout=stream,stderr=subprocess.STDOUT)
    print(log.name,p.returncode,flush=True);return p.returncode


def counts(path):
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    return Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult',ns))


def main(workspace,results,synthetic):
    source=results/'raw-source';output=results/'raw';output.mkdir(exist_ok=True)
    if not source.exists():shutil.copytree(workspace/'upstream',source,ignore=shutil.ignore_patterns('locked-packages','.git','bin','obj','bazel-*'))
    config=json.loads((source/'global.json').read_text());config['sdk']['version']='10.0.400';config['tools']['dotnet']='10.0.400';(source/'global.json').write_text(json.dumps(config,indent=2)+'\n')
    if not (source/'.dotnet').exists():(source/'.dotnet').symlink_to(SDK)
    cache=Path.home()/'.nuget/packages';cache.mkdir(parents=True,exist_ok=True)
    execution=results/'base/execroot/_main'
    for manifest in (execution/'bazel-out').glob('*/bin/upstream/*.package.json'):
        row=json.loads(manifest.read_text());target=cache/row['id'].lower()/row['version'];package=execution/row['output']
        if not target.exists() and package.exists():shutil.copytree(package,target)
    assert run([SDK/'dotnet','msbuild','eng/tools/GenerateFiles/GenerateFiles.csproj','-restore','-t:GenerateDirectoryBuildFiles','-p:Configuration=Release','-v:minimal'],source,output/'bootstrap.log')==0
    assert run([SDK/'dotnet','build','eng/tools/RepoTasks/RepoTasks.csproj','-c','Release','-m:2'],source,output/'repo-tasks.log')==0
    selected=json.loads((workspace/'test-selection.json').read_text());rows=[]
    runner=synthetic/'vstest-lock/packages/microsoft.testplatform.cli/17.14.1/contentFiles/any/net9.0/vstest.console.dll'
    for row in selected:
        name=row['name'];directory=output/name;directory.mkdir(exist_ok=True)
        code=run([SDK/'dotnet','build',row['project'],'-c','Release','-f','net10.0','-m:2','-p:WarningsNotAsErrors=CS8629%3BIDE0031','-p:NuGetAudit=false','-p:LoggingTestingFileLoggingDirectory='+str(output/'logs')],source,directory/'build.log')
        if code:rows.append(dict(**row,buildExit=code));continue
        assembly=source/'artifacts/bin'/Path(row['project']).stem/'Release/net10.0'/(row['assembly']+'.dll')
        code=run([SDK/'dotnet',runner,assembly,'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(directory)],source,directory/'test.log')
        actual=counts(results/(name+'.trx'));expected=counts(directory/'results.trx')
        rows.append(dict(**row,exitCode=code,tests=sum(expected.values()),outcomes=dict(Counter(outcome for (_,outcome),n in expected.items() for _ in range(n))),sameNamesAndOutcomes=actual==expected,rawOnly=[list(k)+[v] for k,v in (expected-actual).items()],bazelOnly=[list(k)+[v] for k,v in (actual-expected).items()]))
        (output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    (output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    subprocess.run([SDK/'dotnet','build-server','shutdown'],cwd=source,check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('results',type=Path);p.add_argument('synthetic',type=Path);a=p.parse_args();main(a.workspace.resolve(),a.results.resolve(),a.synthetic.resolve())
