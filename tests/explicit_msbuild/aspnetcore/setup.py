"""Prepare the pinned large workload in a new disposable Linux directory.

Requires the qualified .NET SDK and network access for NuGet setup. Bootstrap
outputs are explicit captured inputs; the benchmark measures managed compilation.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

checkout=Path(sys.argv[1]).resolve();folder=Path(sys.argv[2]).resolve()
rules=Path(__file__).resolve().parents[3];scripts=Path(__file__).parent
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);dotnet=sdk/'dotnet'
revision=subprocess.check_output(['git','-C',checkout,'rev-parse','HEAD'],text=True).strip()
assert revision=='7387de91234d3ef751fa50b3d1bfede4130213ff',revision
folder.mkdir(parents=True)
source=folder/'source';shutil.copytree(checkout,source,ignore=shutil.ignore_patterns('bin','obj','artifacts','.dotnet'))
data=json.loads((source/'global.json').read_text());data['sdk']['version']='10.0.400';data['tools']['dotnet']='10.0.400';(source/'global.json').write_text(json.dumps(data,indent=2)+'\n')
(source/'.dotnet').symlink_to(sdk)
def run(name,command,cwd=source):
    with (folder/(name+'.log')).open('w') as log:result=subprocess.run(list(map(str,command)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,folder/(name+'.log')
    print(name,'passed',flush=True)
run('bootstrap',[dotnet,'msbuild','eng/tools/GenerateFiles/GenerateFiles.csproj','-restore','-t:GenerateDirectoryBuildFiles','-p:Configuration=Release','-v:minimal'])
run('repo-tasks',[dotnet,'build','eng/tools/RepoTasks/RepoTasks.csproj','-c','Release','-m:2'])
for phase in ['select','restore','build']:
    run('baseline-'+phase,[sys.executable,scripts/'baseline.py',source,folder/'baseline','--phase',phase])
probe=folder/'inventory-tool';probe.mkdir()
(probe/'Inventory.csproj').write_text((scripts/'Inventory.csproj.txt').read_text())
(probe/'Program.cs').write_text((scripts/'Inventory.cs.txt').read_text())
run('inventory-tool',[dotnet,'build',probe/'Inventory.csproj','-c','Release'],probe)
run('inventory',[dotnet,probe/'bin/Release/net10.0/Inventory.dll',source,folder/'baseline/selection.json',folder/'baseline/inventory.json'],probe)
run('explicit-declarations',[sys.executable,scripts/'prepare.py',source,folder/'baseline/inventory.json',folder/'bazel',rules],rules)
subprocess.run([dotnet,'build-server','shutdown'],check=True)
