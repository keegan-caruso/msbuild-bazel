"""Everyday graph edits, execution invalidation, failure, repair and cache reversion."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

rules = Path(__file__).resolve().parents[2]
root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
w = root / 'workspace'; w.mkdir()
rows = []
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(root / 'base'), '--ignore_all_rc_files']
def put(name, text):
    path = w / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
def run(name, args, error=None):
    p = subprocess.run(cmd + args, cwd=w, text=True, capture_output=True)
    output = p.stdout + p.stderr; (root / (name + '.log')).write_text(output)
    assert (p.returncode == 0) if error is None else (p.returncode != 0 and error.lower() in output.lower()), (name, output[-6000:])
    print(name, p.returncode, flush=True)
    return p

def sync(name, stale=False, error=None):
    before = (w / 'projects.generated.bzl').read_bytes() if (w / 'projects.generated.bzl').exists() else None
    if stale:
        run(name + '-stale', ['run', '//:sync', '--', '--check'], error='stale')
        assert (w / 'projects.generated.bzl').read_bytes() == before
    run(name + '-sync', ['run', '//:sync'], error=error)
    if error:
        assert (w / 'projects.generated.bzl').read_bytes() == before
    else:
        generated = (w / 'projects.generated.bzl').read_bytes()
        run(name + '-check', ['run', '//:sync', '--', '--check'])
        assert (w / 'projects.generated.bzl').read_bytes() == generated
    rows.append(dict(case=name, staleDetected=stale, rejected=error, preservedOnFailure=bool(error or stale)))

def execute(name, compiles, tests, failure=False):
    path = root / (name + '.execution.json')
    run(name, ['test', '//:App_App', '//:Other_Other', '--jobs=2', '--worker_max_instances=2', '--disk_cache=' + str(root / 'cache'), '--test_output=errors', '--execution_log_json_file=' + str(path)], error='FAIL' if failure else None)
    text = path.read_text().strip(); decoder = json.JSONDecoder(); actions = []
    while text:
        row, end = decoder.raw_decode(text); text = text[end:].lstrip()
        if not row.get('cacheHit'): actions.append(row)
    compiled = sorted(r['targetLabel'].split(':')[1] for r in actions if r.get('mnemonic') == 'MSBuildAssembly')
    tested = sorted({r['targetLabel'].split(':')[1] for r in actions if r.get('mnemonic') == 'TestRunner'})
    assert compiled == sorted(compiles), (name, 'compiled', compiled, compiles)
    assert tested == sorted(tests), (name, 'tested', tested, tests)
    rows.append(dict(case=name, compiled=compiled, tested=tested, failed=failure))
    (root / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')

put('MODULE.bazel', 'module(name="sync_mutations")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
for name in ['global.json', '.bazelversion']: shutil.copyfile(rules / name, w / name)
put('Directory.Build.props', '<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
core_project = '<Project Sdk="Microsoft.NET.Sdk"><Import Project="Flavor.props"/></Project>'
put('Core/Core.csproj', core_project)
props = '<Project><PropertyGroup><DefineConstants>FIRST</DefineConstants></PropertyGroup></Project>'
put('Core/Flavor.props', props)
core = 'public static class Core { public static int Value => 7; }'
put('Core/Core.cs', core)
put('Generator/Generator.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Reference Include="$(MSBuildBinPath)/Roslyn/bincore/Microsoft.CodeAnalysis.dll" Private="false"/></ItemGroup></Project>')
generator = 'using Microsoft.CodeAnalysis; [Generator] public class Generator : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { c.AddSource("Made.g.cs", "public static class Made { public static int Value => 1; }"); } }'
put('Generator/Code.cs', generator)
app_project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/><ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false"/></ItemGroup></Project>'
put('App/App.csproj', app_project)
put('App/Program.cs', 'return Core.Value > 0 && Made.Value > 0 && System.IO.File.ReadAllText("value.txt").Trim() != "fail" ? 0 : 1;')
put('value.txt', 'pass')
put('Other/Other.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>')
put('Other/Program.cs', 'return 0;')
mapping = dict(projects={'App/App.csproj':dict(projectReferences={'Generator/Generator.csproj':dict(role='analyzer',label=':Generator_Generator')})}, projectDefaults=dict(linuxWorker=True, useAppHost=False), tests={'App/App.csproj':dict(protocol='executable',dataPaths={':value.txt':'value.txt'}), 'Other/Other.csproj':dict(protocol='executable')})
put('runtime.bzl', '''load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo", "MSBuildLayoutInfo")
def _tree(ctx):
    directory = ctx.attr.runtime[MSBuildRuntimeInfo].directory
    return [DefaultInfo(files=depset([directory])), MSBuildLayoutInfo(directory=directory)]
runtime_tree = rule(implementation=_tree, attrs={"runtime":attr.label(providers=[MSBuildRuntimeInfo])})
''')
wrapper = '#!/bin/sh\nexec "$(dirname "$0")/dotnet" "$@"\n'
put('host.sh', wrapper); (w / 'host.sh').chmod(0o755)
mapping['projects']['App/App.csproj']['runtimeHost'] = ':host'
put('sync.json', json.dumps(mapping))
authored = 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name="Generator_Generator",project="Generator/Generator.csproj",srcs=["Generator/Code.cs"],msbuild_imports=["Directory.Build.props"],target_framework="net10.0",linux_worker=True)\nload("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nexports_files(["global.json"])\nmsbuild_sync(name="sync",projects=["App/App.csproj","Other/Other.csproj"],mappings="sync.json")\n'
authored += 'load(":runtime.bzl","runtime_tree")\nload("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\nruntime_tree(name="runtime_tree",runtime="@dotnet//:runtime")\nmsbuild_layout(name="host_tree",paths={":runtime_tree":".",":host.sh":"host.sh"})\nmsbuild_runtime(name="host",layout=":host_tree",entry_point="host.sh")\n'
put('BUILD.bazel', authored)
app, other, core_label, gen = 'App_App_net10_0', 'Other_Other_net10_0', 'Core_Core_net10_0', 'Generator_Generator'
# Test facade compilation targets have a private suffix; inspect actual labels once.
try:
    sync('initial')
    put('BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')
    execute('initial', [app, other, core_label, gen], [app, other])
    baseline = (w / 'projects.generated.bzl').read_bytes()
    execute('noop', [], [])
    put('Core/Core.cs', core.replace('=> 7;', '=> 8;'))
    sync('body')
    execute('body', [core_label], [app])
    put('Core/Core.cs', core); execute('body-reverted', [], [])
    put('Core/Added.cs', 'internal class Added {}')
    sync('source-added', stale=True); execute('source-added', [core_label, app], [app])
    (w / 'Core/Added.cs').unlink()
    sync('source-removed', stale=True); execute('source-removed', [], [])
    put('Extra/Extra.csproj', '<Project Sdk="Microsoft.NET.Sdk"/>')
    put('Extra/Extra.cs', 'public class Extra {}')
    put('Core/Core.csproj', core_project.replace('</Project>', '<ItemGroup><ProjectReference Include="../Extra/Extra.csproj"/></ItemGroup></Project>'))
    sync('project-reference-added', stale=True)
    execute('project-reference-added', ['Extra_Extra_net10_0', core_label, app], [app])
    put('Core/Core.csproj', core_project)
    sync('project-reference-removed', stale=True); execute('project-reference-removed', [], [])
    shutil.rmtree(w / 'Extra')
    sync('project-deleted'); execute('project-deleted', [], [])
    put('Core/Flavor.props', props.replace('FIRST', 'SECOND'))
    # Changing an existing import's contents needs no regenerated source list.
    sync('props-condition'); execute('props-condition', [core_label], [app])
    put('Core/Flavor.props', props); execute('props-reverted', [], [])
    put('Core/Core.csproj', core_project.replace('</Project>', '<PropertyGroup><TargetFrameworks>net10.0;netstandard2.1</TargetFrameworks><TargetFramework/></PropertyGroup><ItemGroup Condition="\'$(TargetFramework)\' == \'netstandard2.1\'"><Compile Remove="Core.cs"/></ItemGroup></Project>'))
    sync('framework-added', stale=True)
    text = (w / 'projects.generated.bzl').read_text(); assert 'netstandard2.1' in text
    execute('framework-added', [core_label], [])
    put('Core/Core.csproj', core_project)
    sync('framework-removed', stale=True); execute('framework-removed', [], [])
    put('Core/Core.csproj', core_project.replace('</Project>', '<ItemGroup><ProjectReference Include="../Missing/Missing.csproj"/></ItemGroup></Project>'))
    sync('missing-project', error='Missing')
    put('Core/Core.csproj', core_project); sync('missing-project-repaired'); execute('repaired', [], [])
    put('Generator/Code.cs', generator.replace('=> 1;', '=> 2;'))
    execute('analyzer-body', [gen, app], [app])
    put('Generator/Code.cs', generator); execute('analyzer-reverted', [], [])
    put('value.txt', 'changed'); execute('test-data', [], [app])
    put('value.txt', 'fail'); execute('test-failure', [], [app], failure=True)
    put('value.txt', 'pass'); execute('test-repaired', [], [])
    put('host.sh', wrapper + '# host input changed\n'); execute('runtime-host', [], [app])
    put('host.sh', '#!/bin/sh\nexit 19\n'); execute('runtime-host-failure', [], [app], failure=True)
    put('host.sh', wrapper); execute('runtime-host-repaired', [], [])
    assert (w / 'projects.generated.bzl').read_bytes() == baseline
finally:
    subprocess.run(cmd + ['shutdown'], cwd=w, check=True)
    (root / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
