"""Build a raw slice, evaluate its configured graph and emit explicit declarations."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path)
parser.add_argument('slice')
parser.add_argument('output',type=Path)
parser.add_argument('--vstest',type=Path,required=True)
a=parser.parse_args()
source=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent;rules=here.parents[2]
selection=json.loads((here/'subset_slices.json').read_text())
slice=next(s for s in selection['slices'] if s['name']==a.slice)
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==selection['commit']
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);records=[]
def run(name,cmd,cwd=out,env=None):
    start=time.monotonic()
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=1800)
    records.append(dict(case=name,seconds=round(time.monotonic()-start,3),exitCode=result.returncode))
    (out/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(name,result.returncode,flush=True);result.check_returncode()
def configured(entry,framework):
    return dict(project=entry,framework=framework) if isinstance(entry,str) else entry
for index,value in enumerate(slice['entries']):
    entry=configured(value,slice['framework'])
    run('raw-'+str(index),[sdk/'dotnet','build',entry['project'],'-c','Release','-p:TargetFramework='+entry['framework'],'-p:TargetArchitecture=arm64','-p:TargetOS=linux','-p:UseLocalTargetingRuntimePack=false','-p:RestoreUseStaticGraphEvaluation=false','-p:NuGetAudit=false','-p:UseSharedCompilation=false','-p:NetCoreSdkRoot='+str(sdk/'sdk/10.0.400'),'-bl:'+str(out/('raw-'+str(index)+'.binlog'))],source)
probe=out/'inventory';probe.mkdir()
for src,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:shutil.copyfile(here/src,probe/dest)
# Keep earlier implementation producers and suites in each expanded host.
# OS-specific entries retain their own authored target framework.
expanded=[];filters={}
for previous in selection['slices']:
    expanded=[e for e in expanded if e['project'] not in previous.get('removeRoots',[])]
    expanded.extend(configured(p,previous['framework']) for p in previous['entries'])
    filters.update(previous.get('filters',{}))
    if previous['name']==a.slice:break
(probe/'selection.json').write_text(json.dumps(dict(entries=expanded,filters=filters,hostFrameworks=selection.get("hostFrameworks",{}),privateFrameworks=selection.get("privateFrameworks",{})))+'\n')
run('inventory-build',[sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'])
run('inventory',[sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,probe/'selection.json',probe/'inventory.json'])
run('declarations',[os.sys.executable,here/'prepare.py',source,probe/'inventory.json',out/'bazel',rules],env=dict(os.environ,RULES_MSBUILD_VSTEST_ARCHIVE=str(a.vstest.resolve())))
