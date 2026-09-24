"""Qualify the pinned Immutable net10 closure and unchanged upstream tests.

Start from qualify.py's source acquisition. Restore and declaration generation are
setup; this is a correctness gate, not a cold-build performance benchmark.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('control',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
source=args.control.resolve()/'source'
folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent
rules=here.parents[2]
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
entry='src/libraries/System.Collections.Immutable/tests/System.Collections.Immutable.Tests.csproj'
commit='60629d14374c56f1cb51819049ad1fa529307f8d'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit
records=[]
def run(name,command,cwd=folder,env=None):
    with (folder/(name+'.log')).open('w') as log:
        result=subprocess.run(list(map(str,command)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=900,env=env)
    records.append(dict(case=name,exitCode=result.returncode))
    (folder/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(name,result.returncode,flush=True)
    result.check_returncode()

full=['System.Collections.Immutable','System.Collections','System.Linq','System.Memory','System.Runtime','System.Threading','System.Collections.Concurrent','System.Private.Uri','System.Numerics.Vectors','System.Runtime.Intrinsics','System.Diagnostics.Tracing']
refs=['Microsoft.Win32.Primitives','System.Diagnostics.Contracts','System.Diagnostics.StackTrace','System.Reflection.Emit.ILGeneration','System.Reflection.Emit.Lightweight','System.Reflection.Emit','System.Reflection.Primitives','System.Runtime.Loader','System.Text.Encoding.Extensions','System.Threading.Overlapped','System.Threading.Thread','System.Threading.ThreadPool']
paths=['src/libraries/'+p for p in full]+['src/libraries/'+p+'/ref' for p in refs]+['src/coreclr/System.Private.CoreLib','src/coreclr/vm','src/coreclr/inc','src/coreclr/nativeaot/Common/src/System/Runtime','src/coreclr/nativeaot/Runtime.Base/src/System/Runtime']
run('acquire-slice',['git','sparse-checkout','add',*paths],source)
props=['-c','Release','-p:TargetFramework=net10.0','-p:TargetArchitecture=arm64','-p:TargetOS=linux','-p:RestoreUseStaticGraphEvaluation=false','-p:UseLocalTargetingRuntimePack=false','-p:NuGetAudit=false','-p:UseSharedCompilation=false','-p:RunApiCompatValidateAssembliesInInnerBuild=true','-p:NetCoreSdkRoot='+str(sdk/'sdk/10.0.400')]
run('raw-build',[sdk/'dotnet','build',entry,*props,'-bl:'+str(folder/'raw.binlog')],source)
archive=folder/'vstest.nupkg'
data=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg').read()
assert hashlib.sha256(data).hexdigest()=='3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
archive.write_bytes(data)
run('raw-test',[os.sys.executable,here/'immutable_raw_test.py',source,folder/'raw-test',archive])
probe=folder/'inventory';probe.mkdir()
for src,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:shutil.copyfile(here/src,probe/dest)
(probe/'selection.json').write_text(json.dumps(dict(entries=[entry])))
run('inventory-build',[sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'])
run('inventory',[sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,probe/'selection.json',probe/'inventory.json'])
workspace=folder/'bazel'
run('declarations',[os.sys.executable,here/'prepare.py',source,probe/'inventory.json',workspace,rules],env=dict(os.environ,RULES_MSBUILD_VSTEST_ARCHIVE=str(archive)))
run('host',[os.sys.executable,here/'immutable_host.py',workspace])
run('smoke',[os.sys.executable,here/'immutable_smoke.py',workspace])
start=[os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files']
try:
    run('bazel-test',start+['test','//upstream:src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10.0','//smoke','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--test_output=errors','--execution_log_json_file='+str(folder/'build.execution.json')],workspace)
    run('verify',[os.sys.executable,here/'immutable_verify.py',workspace,folder/'raw-test',folder/'report.json'])
    run('api-parity',[os.sys.executable,here/'immutable_api.py',source,workspace,folder/'api'])
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
finally:subprocess.run(start+['shutdown'],cwd=workspace,check=True)
