"""Qualify Primitives implementation and upstream tests using an existing raw control."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

control,folder=map(lambda p:Path(p).resolve(),sys.argv[1:]);folder.mkdir(parents=True,exist_ok=False)
rules=Path(__file__).resolve().parents[3];source=control/'source';sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL']
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()=='60629d14374c56f1cb51819049ad1fa529307f8d'
records=[]
def run(name,cmd,cwd=folder,env=None):
    with (folder/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=900,env=env)
    records.append(dict(case=name,exitCode=r.returncode));print(name,r.returncode,flush=True);r.check_returncode()
archive=folder/'vstest.nupkg';data=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg').read()
assert hashlib.sha256(data).hexdigest()=='3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab';archive.write_bytes(data)
with zipfile.ZipFile(archive) as z:z.extractall(folder/'vstest')
entry='src/libraries/Microsoft.Extensions.Primitives/tests/Microsoft.Extensions.Primitives.Tests.csproj'
props=json.loads((control/'report.json').read_text())['properties'];props['NetCoreSdkRoot']=str(sdk/'sdk/10.0.400')
run('raw-build',[sdk/'dotnet','build',entry,*['-p:'+k+'='+v for k,v in props.items()],'-bl:'+str(folder/'raw.binlog')],source)
raw=source/'artifacts/bin/Microsoft.Extensions.Primitives.Tests/Release/net10.0'
run('raw-test',[sdk/'dotnet',folder/'vstest/contentFiles/any/net9.0/vstest.console.dll',raw/'Microsoft.Extensions.Primitives.Tests.dll','/Settings:'+str(raw/'.runsettings'),'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(folder/'raw-results'),'--','RunConfiguration.DotNetHostPath='+str(sdk/'dotnet')])
probe=folder/'inventory';probe.mkdir()
for original,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:shutil.copyfile(Path(__file__).with_name(original),probe/dest)
(probe/'selection.json').write_text(json.dumps(dict(entries=[entry])))
run('inventory-build',[sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'])
run('inventory',[sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,probe/'selection.json',probe/'inventory.json'])
w=folder/'bazel'
run('declarations',[sys.executable,Path(__file__).with_name('prepare.py'),source,probe/'inventory.json',w,rules],env=dict(os.environ,RULES_MSBUILD_VSTEST_ARCHIVE=str(archive)))
run('smoke-setup',[sys.executable,Path(__file__).with_name('smoke.py'),w])
target='//upstream:src_libraries_Microsoft.Extensions.Primitives_tests_Microsoft.Extensions.Primitives.Tests_net10.0'
start=[bazel,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files']
try:
    run('bazel-test',start+['test',target,'//smoke','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--test_output=errors','--execution_log_json_file='+str(folder/'build.execution.json')],w)
    raw_xml=ET.parse(folder/'raw-results/results.trx').getroot();ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    raw_cases=Counter((t.get('testName'),t.get('outcome')) for t in raw_xml.findall('.//t:UnitTestResult',ns))
    test_xml=w/'bazel-testlogs/upstream'/target.split(':')[1]/'test.xml'
    bazel_cases=Counter((t.get('name'),'Failed' if t.find('failure') is not None or t.find('error') is not None else 'NotExecuted' if t.find('skipped') is not None else 'Passed') for t in ET.parse(test_xml).getroot().findall('.//testcase'))
    assert raw_cases==bazel_cases,(raw_cases-bazel_cases,bazel_cases-raw_cases)
    assert sum(raw_cases.values())==514 and all(outcome=='Passed' for _,outcome in raw_cases)
    implementation=w/'bazel-bin/upstream/src_libraries_Microsoft.Extensions.Primitives_src_Microsoft.Extensions.Primitives_net10.0.runtime/Microsoft.Extensions.Primitives.dll'
    digest=hashlib.sha256(implementation.read_bytes()).hexdigest()
    assert digest.upper() in (w/'bazel-testlogs/smoke/smoke/test.log').read_text()
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    report=dict(commands=records,bazel=subprocess.check_output([bazel,'--version'],text=True).strip(),sdk='10.0.400',runtime='10.0.11',platform='linux-arm64',testRunner='Microsoft.TestPlatform.CLI/17.14.1',testCount=514,testCaseNamesAndOutcomesMatch=True,usesUpstreamGeneratedSettings=True,smokeLoadedBazelImplementationSha256=digest,sourceUnchanged=True)
    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copyfile(test_xml,folder/'bazel-tests.xml')
finally:subprocess.run(start+['shutdown'],cwd=w,check=True)
