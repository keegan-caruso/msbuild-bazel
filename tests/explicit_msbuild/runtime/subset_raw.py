"""Execute unchanged upstream slice tests against independent raw-built artifacts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
for name in ['source','inventory','workspace','native','output']:parser.add_argument(name,type=Path)
a=parser.parse_args();w=a.workspace.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent;sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
manifest=json.loads((w/'subset.json').read_text());rows=json.loads(a.inventory.read_text())
def label(r):return '//upstream:'+r['project'].removesuffix('.csproj').replace('/','_')+'_'+r['framework']
by={label(r):r for r in rows if r['framework']}
host=out/'host';shutil.copytree(w/'runtime',host)
shared=host/'shared/Microsoft.NETCore.App'/manifest.get('frameworkVersion','10.0.11')
for name,target in manifest['managed'].items():
    row=by[target];shutil.copy2(Path(row['properties']['OutputPath'])/name,shared/name)
for name,target in manifest.get('private',{}).items():
    (host/'private').mkdir(exist_ok=True)
    shutil.copy2(Path(by[target]['properties']['OutputPath'])/name,host/'private'/name)
for name in manifest['native']:
    dest=host/manifest.get('nativePaths',{}).get(name,str(shared.relative_to(host)/name))
    # Remove superseded hostfxr versions before composing the raw host, too.
    # Otherwise the muxer could prefer a newer installed hostfxr directory.
    for previous in host.rglob(name):
        if previous.is_file():previous.unlink()
    if name=="libhostfxr.so" and (host/"host/fxr").exists():
        for version in (host/"host/fxr").iterdir():
            if version.is_dir() and not any(version.iterdir()):version.rmdir()
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(a.native/name,dest)
probe=out/'probe';probe.mkdir()
shutil.copyfile(here/'SubsetProbe.cs.txt',probe/'Program.cs')
shutil.copyfile(w/'load_probe/Probe.csproj',probe/'Probe.csproj')
with (out/'probe.log').open('w') as log:
    subprocess.run([sdk/'dotnet','build',probe/'Probe.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
shutil.copytree(probe/'bin/Release/net10.0',host/'probe')
archive=w/'upstream/locked-packages/test-runner.nupkg'
with zipfile.ZipFile(archive) as z:z.extractall(out/'vstest')
reports=[]
for test in manifest['tests']:
    row=by[test['label']];directory=Path(row['properties']['OutputPath']);name=test['assembly']
    folder=out/name;folder.mkdir()
    settings=w/'upstream'/test['settings'] if test.get('settings') else directory/'.runsettings'
    command=[host/'host.sh',out/'vstest/contentFiles/any/net9.0/vstest.console.dll',directory/(name+'.dll'),'/Settings:'+str(settings),'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(folder/'results'),'--','RunConfiguration.DotNetHostPath='+str(host/'host.sh')]
    start=time.monotonic()
    with (folder/'tests.log').open('w') as log:
        p=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(folder/'proof')),timeout=900)
    reports.append(dict(assembly=name,exitCode=p.returncode,seconds=round(time.monotonic()-start,3)))
    (out/'report.json').write_text(json.dumps(reports,indent=2)+'\n');print(reports[-1],flush=True)
    p.check_returncode()
