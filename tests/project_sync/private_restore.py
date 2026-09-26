"""Private project edges must keep their packages out of downstream restore graphs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False)
w=root/'workspace';w.mkdir();rules=Path(__file__).resolve().parents[2]
def put(path,text):
    p=w/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
archive=w/'privatepayload.1.0.0.nupkg'
with zipfile.ZipFile(archive,'w') as z:
    z.writestr('PrivatePayload.nuspec','<package><metadata><id>PrivatePayload</id><version>1.0.0</version><authors>fixture</authors><description>private restore edge</description></metadata></package>')
data=archive.read_bytes()
put('Directory.Build.props','<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
put('Hidden/Hidden.csproj','<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="PrivatePayload" Version="1.0.0"/></ItemGroup></Project>')
put('Hidden/Value.cs','public static class Hidden { public static int Number => 42; }')
put('Middle/Middle.csproj','<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Hidden/Hidden.csproj" PrivateAssets="all"/></ItemGroup></Project>')
put('Middle/Value.cs','public static class Middle { public static int Number => Hidden.Number; }')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Middle/Middle.csproj"/></ItemGroup></Project>')
put('App/Program.cs','System.Console.WriteLine(Middle.Number);')
put('MODULE.bazel','module(name="private_restore")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules/'.bazelversion',w/'.bazelversion')
authored='''load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")
load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
msbuild_nuget_package(name="payload",package_id="PrivatePayload",version="1.0.0",archive="privatepayload.1.0.0.nupkg",archive_sha256=%s,content_hash=%s)
msbuild_package_lock(name="with_private",packages=[":payload"])
msbuild_package_lock(name="empty",packages=[])
msbuild_sync(name="sync",projects=["App/App.csproj","Middle/Middle.csproj","Hidden/Hidden.csproj"],mappings="sync.json",package_locks=[":with_private",":empty"])
'''%(json.dumps(hashlib.sha256(data).hexdigest()),json.dumps(base64.b64encode(hashlib.sha512(data).digest()).decode()))
put('BUILD.bazel',authored)
put('sync.json',json.dumps(dict(projects={
    'Hidden/Hidden.csproj':dict(packageLock=':with_private'),
    'Middle/Middle.csproj':dict(packageLock=':with_private',projectReferences={'Hidden/Hidden.csproj':dict(role='private',label=':Hidden_Hidden_net10_0')}),
    'App/App.csproj':dict(packageLock=':empty'),
},packages={'PrivatePayload/1.0.0':dict(label=':payload',roles=['deps'])})))
cmd=[os.environ['RULES_MSBUILD_BAZEL'],'--output_base='+str(root/'base'),'--ignore_all_rc_files']
def run(name,args):
    p=subprocess.run(cmd+args,cwd=w,text=True,capture_output=True)
    text=p.stdout+p.stderr
    text+='\n'.join(f.read_text() for f in (w/'bazel-bin').glob('*.diagnostics/build.log'))
    (root/(name+'.log')).write_text(text)
    return p,text
try:
    p,text=run('sync',['run','//:sync']);assert p.returncode==0,text[-2500:]
    put('BUILD.bazel','load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
    p,text=run('private-project-packages',['run','//:App_App','--jobs=2'])
    if '--expect-failure' in sys.argv:
        assert p.returncode and "Unable to resolve 'PrivatePayload" in text,text[-2500:]
        print('reproduced private package leakage',flush=True)
    else:
        assert p.returncode==0 and p.stdout.strip().splitlines()[-1]=='42',text[-2500:]
        raw=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),'run','--project','App/App.csproj','-c','Release','-p:RestoreSources='+str(w),'-p:RestorePackagesPath='+str(root/'raw-packages'),'-p:NuGetAudit=false'],cwd=w,text=True,capture_output=True)
        (root/'raw.log').write_text(raw.stdout+raw.stderr)
        assert raw.returncode==0 and raw.stdout.strip().splitlines()[-1]=='42',raw.stdout+raw.stderr
        assets=json.loads((w/'App/obj/project.assets.json').read_text())
        assert 'PrivatePayload/1.0.0' not in assets['libraries']
        print('private project restore and raw runtime parity passed',flush=True)
finally:
    subprocess.run(cmd+['shutdown'],cwd=w,check=True)
