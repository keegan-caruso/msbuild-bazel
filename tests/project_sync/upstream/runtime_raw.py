"""Run raw runtime-library tests with a verified source-built assembly replacement."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import zipfile

source,out,archive=map(lambda p:Path(p).resolve(),sys.argv[1:4])
assembly=sys.argv[4] if len(sys.argv)>4 else 'System.IO.Pipelines'
out.mkdir(parents=True,exist_ok=False)
rules=Path(__file__).resolve().parents[3];sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
probe=out/'probe';probe.mkdir()
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
code=(rules/'tests/explicit_msbuild/runtime/LoadProbe.cs.txt').read_text().replace('System.Collections.Immutable',assembly).replace('QUALIFICATION_IMMUTABLE','QUALIFICATION_ASSEMBLY').replace('loaded-immutable','loaded-source').replace('wrong Immutable assembly','wrong source assembly')
(probe/'StartupHook.cs').write_text(code)
subprocess.run([sdk/'dotnet','build',probe/'Probe.csproj','-c','Release'],check=True,stdout=subprocess.DEVNULL)
host=out/'host';host.mkdir()
for relative in ['dotnet','host','shared/Microsoft.NETCore.App']:
    src=sdk/relative;dst=host/relative;dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_dir():shutil.copytree(src,dst)
    else:shutil.copyfile(src,dst);dst.chmod(src.stat().st_mode)
frameworks=list((host/'shared/Microsoft.NETCore.App').iterdir());assert len(frameworks)==1
replacement=frameworks[0]/(assembly+'.dll')
raw=source/('artifacts/bin/'+assembly+'/Release/net10.0/'+assembly+'.dll')
shutil.copyfile(raw,replacement)
wrapper=host/'host.sh'
wrapper.write_text('#!/bin/sh\nset -eu\nexport DOTNET_ROOT='+shlex.quote(str(host))+'\nexport DOTNET_STARTUP_HOOKS='+shlex.quote(str(probe/'bin/Release/net10.0/Probe.dll'))+'\nexport QUALIFICATION_ASSEMBLY='+shlex.quote(str(replacement))+'\nexec '+shlex.quote(str(host/'dotnet'))+' "$@"\n');wrapper.chmod(0o755)
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
with zipfile.ZipFile(archive) as z:z.extractall(out/'vstest')
tests=source/('artifacts/bin/'+assembly+'.Tests/Release/net10.0')
with (out/'tests.log').open('w') as log:
    result=subprocess.run([wrapper,out/'vstest/contentFiles/any/net9.0/vstest.console.dll',tests/(assembly+'.Tests.dll'),'/Settings:'+str(tests/'.runsettings'),'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(out/'results'),'--','RunConfiguration.DotNetHostPath='+str(wrapper)],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(out/'proof')),timeout=900)
proofs=[json.loads(p.read_text()) for p in (out/'proof').glob('loaded-source-*.json')]
expected=hashlib.sha256(raw.read_bytes()).hexdigest().upper();assert proofs and all(p['sha256']==expected for p in proofs)
(out/'report.json').write_text(json.dumps(dict(exitCode=result.returncode,loadedAssemblyProofs=proofs),indent=2)+'\n')
result.check_returncode()
