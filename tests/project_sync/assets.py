"""Compare NuGet asset masks and central overrides with raw MSBuild."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

state=runpy.run_path(str(Path(__file__).with_name('compatibility.py')),run_name='__main__')
workspace=state['workspace'];folder=state['folder'];cmd=state['cmd'];put=state['put'];sdk=state['SDK'];rows=[]
base=state['project'].replace('PrivateAssets="all"','PrivateAssets="none"')
source='public static class Value { public static int Number => HiddenType.Value; }'
put('Shared/Value.cs',source)
put('App/Program.cs','System.Console.WriteLine(Value.Number);')
def command(case,args,cwd,success):
 p=subprocess.run([str(a) for a in args],cwd=cwd,text=True,capture_output=True)
 (folder/(case+'.log')).write_text(p.stdout+p.stderr)
 assert (p.returncode==0)==success,(case,(p.stdout+p.stderr)[-4000:])
 return p

def compare(name,metadata,compile_ok=True,run_ok=True,direct=False,override=False):
 project=base.replace('PrivateAssets="none"',metadata)
 put('Library/Library.csproj',project)
 put('App/Program.cs','System.Console.WriteLine('+('HiddenType.Value' if direct else 'Value.Number')+');')
 props='<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup><ItemGroup><PackageVersion Include="Hidden" Version="'+('2.0.0' if override else '1.0.0')+'"/></ItemGroup></Project>'
 put('Directory.Packages.props',props)
 command(name+'-sync',cmd+['run','//:sync'],workspace,True)
 raw=folder/('raw-'+name)
 shutil.copytree(workspace,raw,ignore=shutil.ignore_patterns('bazel-*','bin','obj'))
 flags=['-p:Flavor=extra','-p:TargetFrameworks=net10.0','-p:TargetFramework=net10.0','-p:NuGetAudit=false','-p:RestoreSources='+str(raw/'packages'),'--packages',str(raw/'nuget')]
 command(name+'-raw-build',[sdk/'dotnet','build',raw/'App/App.csproj','-c','Release',*flags],raw,compile_ok)
 command(name+'-bazel-build',cmd+['build','//:App_App','--jobs=2'],workspace,compile_ok)
 if compile_ok:
  raw_result=command(name+'-raw-run',[sdk/'dotnet',raw/'App/bin/Release/net10.0/App.dll'],raw,run_ok)
  bazel_result=command(name+'-bazel-run',cmd+['run','//:App_App','--jobs=2'],workspace,run_ok)
  if run_ok:assert raw_result.stdout.strip()=='7' and bazel_result.stdout.strip().splitlines()[-1]=='7'
 rows.append(dict(case=name,compile=compile_ok,run=run_ok if compile_ok else None,rawBazelParity=True))
 print(name,'parity',flush=True)
try:
 compare('private-compile-runtime-visible','PrivateAssets="compile"')
 compare('private-compile-direct-rejected','PrivateAssets="compile"',compile_ok=False,direct=True)
 compare('private-runtime-compile-visible','PrivateAssets="runtime"',run_ok=False,direct=True)
 compare('exclude-compile','ExcludeAssets="compile"',compile_ok=False)
 compare('exclude-runtime','ExcludeAssets="runtime"',run_ok=False)
 compare('include-compile-only','IncludeAssets="compile"',run_ok=False)
 compare('private-tooling-assets','PrivateAssets="analyzers;build;contentFiles"',direct=True)
 compare('central-version-override','VersionOverride="1.0.0"',direct=True,override=True)
finally:
 subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
 (folder/'asset-results.json').write_text(json.dumps(rows,indent=2)+'\n')
