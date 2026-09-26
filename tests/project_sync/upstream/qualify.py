"""Qualify generated ObjectPool/Pipelines on a fresh Linux ARM64 workspace.

Usage: qualify.py ASPNET_CHECKOUT RUNTIME_CHECKOUT OUTPUT_DIR
Tool and NuGet acquisition are setup, not performance measurements. Both checkouts
must contain their referenced source files at the revisions asserted below.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

aspnet,runtime,out=map(lambda p:Path(p).resolve(),sys.argv[1:])
out.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent;rules=here.parents[2]
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);dotnet=sdk/'dotnet'
bazel=os.environ.get('RULES_MSBUILD_BAZEL',str(rules/'scripts/bazel-launcher.sh'))
records=[]
def run(name,cmd,cwd=rules,env=None):
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run([str(x) for x in cmd],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
    records.append(dict(case=name,exitCode=result.returncode));(out/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(name,result.returncode,flush=True);result.check_returncode()
for source,commit in [(aspnet,'7387de91234d3ef751fa50b3d1bfede4130213ff'),(runtime,'60629d14374c56f1cb51819049ad1fa529307f8d')]:
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit
runner=out/'vstest.nupkg'
run('runner-acquisition',['curl','-fsSL','https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg','-o',runner])
run('aspnet-bootstrap',[dotnet,'msbuild',aspnet/'eng/tools/GenerateFiles/GenerateFiles.csproj','-restore','-t:GenerateDirectoryBuildFiles','-p:Configuration=Release','-p:NetCoreTargetingPackRoot='+str(sdk/'packs')+'/','-v:minimal'])
objtest='src/ObjectPool/test/Microsoft.Extensions.ObjectPool.Tests.csproj'
run('objectpool-raw',[dotnet,'test',aspnet/objtest,'-c','Release','-f','net10.0','-p:TargetFrameworks=net10.0','-p:NetCoreTargetingPackRoot='+str(sdk/'packs')+'/','-p:RepositoryCommit=7387de91234d3ef751fa50b3d1bfede4130213ff','-p:SourceRevisionId=7387de91234d3ef751fa50b3d1bfede4130213ff','--logger','trx;LogFileName=results.trx','--results-directory',out/'objectpool-raw'])
run('objectpool-inventory',[sys.executable,here.parent/'evaluation_inventory.py',aspnet,out/'objectpool-inventory.json','src/ObjectPool/src/Microsoft.Extensions.ObjectPool.csproj',objtest,'src/Testing/src/Microsoft.AspNetCore.InternalTesting.csproj','eng/tools/GenerateFiles/GenerateFiles.csproj'],env=dict(os.environ,RULES_MSBUILD_INVENTORY_PROPERTIES='{"TargetFrameworks":"net10.0"}'))
run('objectpool-prepare',[sys.executable,here/'objectpool.py',aspnet,out/'objectpool-inventory.json',out/'objectpool',runner])
work=out/'objectpool/workspace';base=out/'objectpool-base'
run('objectpool-sync',[bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//:sync','--jobs=2'],work)
build=work/'BUILD.bazel';build.write_text('load(":projects.generated.bzl","app_projects")\n'+build.read_text()+'\napp_projects()\n')
run('objectpool-controls',[sys.executable,here/'controls.py',work,base,out/'objectpool-raw/results.trx',out/'objectpool-controls','//:src_ObjectPool_test_Microsoft.Extensions.ObjectPool.Tests_net10_0','src/ObjectPool/src/DefaultObjectPool.cs','var item = _fastItem;','GC.KeepAlive(this);\n        var item = _fastItem;','src_ObjectPool_src_Microsoft.Extensions.ObjectPool_net10_0'])
run('objectpool-shutdown',[bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],work)
pipetest='src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj'
run('pipelines-raw-build',[dotnet,'build',runtime/pipetest,'-c','Release','-p:TargetFramework=net10.0','-p:TargetArchitecture=arm64','-p:TargetOS=linux','-p:UseLocalTargetingRuntimePack=false','-p:RestoreUseStaticGraphEvaluation=false','-p:NuGetAudit=false','-p:UseSharedCompilation=false','-p:NetCoreSdkRoot='+str(sdk/'sdk/10.0.400')])
run('pipelines-raw-tests',[sys.executable,here/'pipelines_raw.py',runtime,out/'pipelines-raw',runner])
probe=out/'inventory';probe.mkdir();old=rules/'tests/explicit_msbuild/runtime'
(probe/'Inventory.csproj').write_text((old/'Inventory.csproj.txt').read_text());(probe/'Program.cs').write_text((old/'Inventory.cs.txt').read_text());(probe/'selection.json').write_text(json.dumps(dict(entries=[pipetest],framework='net10.0')))
run('pipelines-inventory-build',[dotnet,'build',probe/'Inventory.csproj','-c','Release'])
run('pipelines-graph',[dotnet,probe/'bin/Release/net10.0/Inventory.dll',runtime,probe/'selection.json',probe/'inventory.json'])
run('pipelines-authored',[sys.executable,old/'prepare.py',runtime,probe/'inventory.json',out/'pipelines',rules],env=dict(os.environ,RULES_MSBUILD_VSTEST_ARCHIVE=str(runner)))
run('pipelines-evaluation',[sys.executable,here.parent/'evaluation_inventory.py',runtime,out/'pipelines-evaluation.json','src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj',pipetest],env=dict(os.environ,RULES_MSBUILD_INVENTORY_PROPERTIES='{"TargetArchitecture":"arm64","TargetOS":"linux","UseLocalTargetingRuntimePack":"false"}'))
run('pipelines-mapping',[sys.executable,here/'pipelines.py',out/'pipelines',probe/'inventory.json',out/'pipelines-evaluation.json','linux'])
work=out/'pipelines/upstream';base=out/'pipelines-base'
run('pipelines-sync',[bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//:sync','--jobs=2'],work)
run('pipelines-host',[sys.executable,here/'pipelines_host.py',work])
run('pipelines-test',[bazel,'--output_base='+str(base),'--ignore_all_rc_files','test','//:src_libraries_System.IO.Pipelines_tests_System.IO.Pipelines.Tests','--jobs=2','--test_output=errors'],work)

run('pipelines-controls',[sys.executable,here/'controls.py',work,base,out/'pipelines-raw/results/results.trx',out/'pipelines-controls','//:src_libraries_System.IO.Pipelines_tests_System.IO.Pipelines.Tests_net10_0','src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/ThrowHelper.cs','internal static void ThrowArgumentNullException(ExceptionArgument argument) => throw CreateArgumentNullException(argument);','internal static void ThrowArgumentNullException(ExceptionArgument argument) { GC.KeepAlive(typeof(ThrowHelper)); throw CreateArgumentNullException(argument); }','src_libraries_System.IO.Pipelines_ref_System.IO.Pipelines_net10.0'])
run('pipelines-shutdown',[bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],work)
