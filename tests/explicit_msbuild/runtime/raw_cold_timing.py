"""Measure restore and one raw managed build with an initially empty artifacts tree."""
import argparse
import json
import shutil
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from benchmarks.measure import command as timed_command
import subprocess
import xml.etree.ElementTree as ET

from timing_tools import verify_tools

p=argparse.ArgumentParser(description=__doc__)
for name in ['source','selection','report']:p.add_argument(name,type=Path)
a=p.parse_args();source=a.source.resolve();out=a.report.resolve()
assert not (source/'artifacts').exists(),'Raw cold control needs a fresh upstream checkout'
assert not out.is_relative_to(source)
out.mkdir(parents=True,exist_ok=False)
tools=verify_tools(cwd=out);sdk=Path(tools['sdkRoot'])
commit='60629d14374c56f1cb51819049ad1fa529307f8d'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit
assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=source)
entries=json.loads(a.selection.read_text())['entries'];records=[]
properties=['Configuration=Release','TargetArchitecture=arm64','TargetOS=linux','UseLocalTargetingRuntimePack=false','RestoreUseStaticGraphEvaluation=false','NuGetAudit=false','UseSharedCompilation=true','NetCoreSdkRoot='+str(sdk/'sdk/10.0.400')]
flags=['-p:'+v for v in properties]

def run(case,args):
    command=[str(sdk/'dotnet'),'msbuild',*map(str,args),'-m:2','-nr:true',*flags,'-bl:'+str(out/(case+'.binlog'))]
    result,wall=timed_command(command,source,out/(case+'.log'),timeout=2400)
    row=dict(case=case,wallSeconds=round(wall,3),exitCode=result.returncode,command=command)
    records.append(row)
    (out/'report.json').write_text(json.dumps(dict(toolchain=tools,commit=commit,roots=entries,records=records),indent=2)+'\n')
    print({k:v for k,v in row.items() if k!='command'},flush=True);result.check_returncode()

# Restore without forcing an inner TargetFramework into upstream tool projects.
# The later build retains each selected root's exact framework. Restore can visit
# other authored frameworks; acquisition is warm and its time is reported apart.
for i,entry in enumerate(entries):
    run('restore-'+str(i),[entry['project'],'-t:Restore'])
assert not list((source/'artifacts/bin').rglob('*.dll')),'Restore unexpectedly compiled assemblies'
project=ET.Element('Project');group=ET.SubElement(project,'ItemGroup')
for entry in entries:
    item=ET.SubElement(group,'SelectedProject',Include=str(source/entry['project']))
    ET.SubElement(item,'AdditionalProperties').text='TargetFramework='+entry['framework']
target=ET.SubElement(project,'Target',Name='Build')
ET.SubElement(target,'MSBuild',Projects='@(SelectedProject)',Targets='Build',BuildInParallel='true')
ET.indent(project);traversal=out/'selected.proj';ET.ElementTree(project).write(traversal,encoding='unicode')
run('build',[traversal,'-t:Build'])
run('noop',[traversal,'-t:Build'])
# Inspect compilation after both timed commands, so the reader build cannot
# prewarm the compiler used by the cold sample.
here=Path(__file__).resolve().parent;reader=out/'reader';reader.mkdir()
shutil.copyfile(here/'Inventory.csproj.txt',reader/'Reader.csproj')
shutil.copyfile(here/'RawTimingLog.cs.txt',reader/'Program.cs')
with (out/'reader-build.log').open('w') as log:
    subprocess.run([sdk/'dotnet','build',reader/'Reader.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
for case in ['build','noop']:
    details=json.loads(subprocess.check_output([sdk/'dotnet',reader/'bin/Release/net10.0/Reader.dll',out/(case+'.binlog')],text=True))
    (out/(case+'.compilation.json')).write_text(json.dumps(details,indent=2)+'\n')
    assert bool(details['compiled'])==(case=='build'),(case,details['compiled'])
(out/'summary.json').write_text(json.dumps(dict(restoreSeconds=round(sum(r['wallSeconds'] for r in records if r['case'].startswith('restore-')),3),buildSeconds=records[-2]['wallSeconds'],noopSeconds=records[-1]['wallSeconds']),indent=2)+'\n')
assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=source)
