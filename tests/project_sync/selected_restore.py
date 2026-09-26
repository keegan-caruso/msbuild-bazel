"""Selected assemblies retain each framework in a mixed-framework restore diamond."""
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
archive=w/'payload.1.0.0.nupkg'
with zipfile.ZipFile(archive,'w') as z:
    z.writestr('Payload.nuspec','<package><metadata><id>Payload</id><version>1.0.0</version><authors>fixture</authors><description>private restore edge</description></metadata></package>')
data=archive.read_bytes()
put('Directory.Build.props','<Project><PropertyGroup><ProduceReferenceAssembly>true</ProduceReferenceAssembly></PropertyGroup></Project>')
put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>netstandard2.1;net10.0</TargetFrameworks></PropertyGroup><ItemGroup><PackageReference Include="Payload" Version="1.0.0"/></ItemGroup></Project>')
put('Core/Value.cs','public static class Core { public static int Number => 42; }')
put('Helper/Helper.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>netstandard2.1</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup></Project>')
put('Helper/Value.cs','public static class Helper { public static int Number => Core.Number; }')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/><ProjectReference Include="../Helper/Helper.csproj"/></ItemGroup></Project>')
put('App/Program.cs','System.Console.WriteLine(Core.Number + Helper.Number);')
import urllib.request
reference=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/netstandard.library.ref/2.1.0/netstandard.library.ref.2.1.0.nupkg').read()
assert hashlib.sha256(reference).hexdigest()=='46ea2fcbd10a817685b85af7ce0c397d12944bdc81209e272de1e05efd33c78a'
(w/'netstandard.library.ref.2.1.0.nupkg').write_bytes(reference)
put('MODULE.bazel','module(name="selected_restore")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules/'.bazelversion',w/'.bazelversion')
authored='''load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")
load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
msbuild_nuget_package(name="payload",package_id="Payload",version="1.0.0",archive="payload.1.0.0.nupkg",archive_sha256=%s,content_hash=%s)
msbuild_nuget_package(name="standard_ref",package_id="NETStandard.Library.Ref",version="2.1.0",archive="netstandard.library.ref.2.1.0.nupkg",archive_sha256=%s,content_hash=%s)
msbuild_package_lock(name="lock",packages=[":payload",":standard_ref"])
msbuild_sync(name="sync",projects=["App/App.csproj"],mappings="sync.json",package_lock=":lock")
'''%tuple(json.dumps(value) for value in [hashlib.sha256(data).hexdigest(),base64.b64encode(hashlib.sha512(data).digest()).decode(),hashlib.sha256(reference).hexdigest(),base64.b64encode(hashlib.sha512(reference).digest()).decode()])
put('BUILD.bazel',authored)
put('sync.json',json.dumps(dict(projects={'App/App.csproj':dict(assemblySelections=[':Core_Core_net10_0'])},packages={'Payload/1.0.0':dict(label=':payload',roles=['deps'])})))
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
    p,text=run('selected-frameworks',['run','//:App_App','--jobs=2'])
    if '--expect-failure' in sys.argv:
        assert p.returncode and "NU1201" in text,text[-2500:]
        print('reproduced lost framework record',flush=True)
    else:
        assert p.returncode==0 and p.stdout.strip().splitlines()[-1]=='84',text[-2500:]
        raw=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),'run','--project','App/App.csproj','-c','Release','-p:RestoreSources='+str(w),'-p:RestorePackagesPath='+str(root/'raw-packages'),'-p:NuGetAudit=false'],cwd=w,text=True,capture_output=True)
        (root/'raw.log').write_text(raw.stdout+raw.stderr)
        assert raw.returncode==0 and raw.stdout.strip().splitlines()[-1]=='84',raw.stdout+raw.stderr
        assets=json.loads((w/'App/obj/project.assets.json').read_text())
        assert 'Payload/1.0.0' in assets['libraries']
        print('selected-framework restore and raw runtime parity passed',flush=True)
finally:
    subprocess.run(cmd+['shutdown'],cwd=w,check=True)
