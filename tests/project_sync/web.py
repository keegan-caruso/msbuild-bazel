"""Build Web/Razor sources with an explicit file item and exported target result."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
w = root / 'workspace'; w.mkdir()
rules = Path(__file__).resolve().parents[2]
def put(name, text):
    p = w / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
put('Directory.Build.props', '<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
view = '<Project Sdk="Microsoft.NET.Sdk.Razor"><PropertyGroup><AddRazorSupportForMvc>true</AddRazorSupportForMvc></PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App"/></ItemGroup><Target Name="Describe" Returns="@(Description)"><ItemGroup><Description Include="Views"/></ItemGroup></Target></Project>'
app = '<Project Sdk="Microsoft.NET.Sdk.Web"><ItemGroup><ProjectReference Include="../Views/Views.csproj"/></ItemGroup><Target Name="ValidateModule" BeforeTargets="CoreCompile"><Error Condition="\'@(ModuleNames)\' != \'Views\'" Text="Missing target-result handoff"/></Target></Project>'
put('Views/Views.csproj', view); put('Views/Marker.cs', 'namespace Views; public class Marker {}')
put('Views/Views/Hello.cshtml', '<p>hello</p>')
put('App/App.csproj', app)
put('App/Program.cs', 'using System; using System.Linq; using System.Reflection; using Microsoft.AspNetCore.Razor.Hosting; Console.WriteLine(typeof(Views.Marker).Assembly.GetCustomAttributes<RazorCompiledItemAttribute>().Single().Identifier);')
def document(text, targets):
    return dict(sha256=hashlib.sha256(text.encode()).hexdigest(), targets=targets, tasks=[])
put('sync.json', json.dumps(dict(projects={
    'Views/Views.csproj': dict(inputItems={'RazorGenerate': []}, exportTargets={'Describe': []}, documents={'Views/Views.csproj': document(view, ['Describe'])}),
    'App/App.csproj': dict(items=[':modules'], documents={'App/App.csproj': document(app, ['ValidateModule'])}),
})))
put('MODULE.bazel', 'module(name="sync_web")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
authored = '''load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_target_items")
msbuild_sync(name="sync", projects=["App/App.csproj"], mappings="sync.json")
msbuild_target_items(name="modules",deps=[":Views_Views_net10_0"],target="Describe",item_type="ModuleNames",before_targets=["ValidateModule"])
'''
put('BUILD.bazel', authored)
start = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(root / 'base'), '--ignore_all_rc_files']
def run(name, args, success=True):
    p = subprocess.run(start + args, cwd=w, capture_output=True, text=True)
    text = p.stdout + p.stderr; (root / (name + '.log')).write_text(text)
    assert (p.returncode == 0) == success, (name, text[-4000:])
    print(name, p.returncode, flush=True)
    return text
try:
    run('sync', ['run', '//:sync'])
    put('BUILD.bazel', 'load(":projects.generated.bzl", "app_projects")\n' + authored + '\napp_projects()\n')
    assert '/Views/Hello.cshtml' in run('run', ['run', '//:App_App'])
    generated = (w / 'projects.generated.bzl').read_bytes()
    run('repeat', ['run', '//:sync', '--', '--check'])
    (w / 'Views/Views/Hello.cshtml').unlink()
    run('missing-view', ['run', '//:sync', '--', '--check'], False)
    assert (w / 'projects.generated.bzl').read_bytes() == generated
    put('Views/Views/Hello.cshtml', '<p>hello</p>')
    run('repaired', ['run', '//:sync', '--', '--check'])
finally:
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
