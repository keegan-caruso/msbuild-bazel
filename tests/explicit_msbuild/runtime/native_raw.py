"""Execute unchanged Immutable tests on source-built CoreCLR, JIT and CoreLib.

Other framework assemblies, native support libraries, and hostfxr remain the
explicit installed control. This qualifies a runtime slice, not a complete pack.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

source, baseline, output = [Path(p).resolve() for p in sys.argv[1:]]
output.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
host=output/'host'
shutil.copytree(baseline/'host',host)
framework=host/'shared/Microsoft.NETCore.App/10.0.11'
native=source/'artifacts/bin/coreclr/linux.arm64.Release'
for name in ['libcoreclr.so','libclrjit.so']:
    shutil.copyfile(native/name,framework/name)
shutil.copyfile(native/'IL/System.Private.CoreLib.dll',framework/'System.Private.CoreLib.dll')
probe=output/'probe';probe.mkdir()
shutil.copyfile(here/'NativeProbe.cs.txt',probe/'StartupHook.cs')
shutil.copyfile(baseline/'probe/Probe.csproj',probe/'Probe.csproj')
with (output/'probe.log').open('w') as log:
    subprocess.run([sdk/'dotnet','build',probe/'Probe.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
wrapper=host/'host.sh'
import shlex
wrapper.write_text('#!/bin/sh\nset -eu\nulimit -c 0\n'+''.join('export '+k+'='+shlex.quote(str(v))+'\n' for k,v in {'DOTNET_ROOT':host,'DOTNET_STARTUP_HOOKS':probe/'bin/Release/net10.0/Probe.dll','QUALIFICATION_NATIVE':framework,'QUALIFICATION_IMMUTABLE':framework/'System.Collections.Immutable.dll','DOTNET_ReadyToRun':'0'}.items())+'exec '+shlex.quote(str(host/'dotnet'))+' "$@"\n')
wrapper.chmod(0o755)
tests=source/'artifacts/bin/System.Collections.Immutable.Tests/Release/net10.0'
start=time.monotonic()
with (output/'tests.log').open('w') as log:
    result=subprocess.run([wrapper,baseline/'vstest/contentFiles/any/net9.0/vstest.console.dll',tests/'System.Collections.Immutable.Tests.dll','/Settings:'+str(tests/'.runsettings'),'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(output/'results'),'--','RunConfiguration.DotNetHostPath='+str(wrapper)],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(output/'proof')),timeout=900)
proofs=[json.loads(p.read_text()) for p in (output/'proof').glob('*.json')]
(output/'report.json').write_text(json.dumps({'exitCode':result.returncode,'seconds':round(time.monotonic()-start,3),'loadedBinaryProofs':proofs},indent=2)+'\n')
result.check_returncode()
assert {'System.Private.CoreLib.dll','libcoreclr.so','libclrjit.so','System.Collections.Immutable.dll'} <= {Path(p['path']).name for p in proofs}
# A direct corerun invocation proves the source-built host as well as the runtime.
smoke=output/'smoke';smoke.mkdir()
(smoke/'Smoke.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="Probe" HintPath="../probe/bin/Release/net10.0/Probe.dll" /></ItemGroup></Project>')
(smoke/'Program.cs').write_text('using System; using System.Collections.Immutable; StartupHook.Initialize(); var values=ImmutableArray.Create(1,2,3); GC.Collect(); Console.WriteLine(values.Length); return values.Length==3 ? 0 : 1;')
with (output/'smoke-build.log').open('w') as log:
    subprocess.run([sdk/'dotnet','build',smoke/'Smoke.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
shutil.copy2(native/'corerun',framework/'corerun')
with (output/'corerun.log').open('w') as log:
    subprocess.run([framework/'corerun',smoke/'bin/Release/net10.0/Smoke.dll'],stdout=log,stderr=subprocess.STDOUT,check=True,env=dict(os.environ,DOTNET_ReadyToRun='0',DOTNET_STARTUP_HOOKS=str(probe/'bin/Release/net10.0/Probe.dll'),QUALIFICATION_NATIVE=str(framework),QUALIFICATION_IMMUTABLE=str(framework/'System.Collections.Immutable.dll'),TEST_UNDECLARED_OUTPUTS_DIR=str(output/'corerun-proof')))
assert len(list((output/'corerun-proof').glob('loaded-*.json')))==4
print('Source-built native runtime tests and corerun smoke passed',flush=True)
