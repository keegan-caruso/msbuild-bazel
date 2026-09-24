"""Exercise explicit Bazel assembly, item and executable-test boundaries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL = Path(os.environ['RULES_MSBUILD_BAZEL'])


def run(folder):
    folder.mkdir(parents=True, exist_ok=True)
    workspace = folder/'src'; workspace.mkdir(exist_ok=True)
    def put(name, value):
        p = workspace/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
    put('MODULE.bazel', f'''module(name = "explicit_acceptance")
bazel_dep(name = "rules_msbuild", version = "0.0.0")
local_path_override(module_name = "rules_msbuild", path = {json.dumps(str(ROOT))})
sdk = use_repo_rule("@rules_msbuild//bazel:msbuild.bzl", "local_dotnet_sdk")
sdk(name = "dotnet", path = {json.dumps(str(SDK))}, include_runtime_closure = {str(str(SDK.resolve()).startswith('/nix/store/'))})
register_toolchains("//:registered")
''')
    put('BUILD.bazel', '''load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
msbuild_toolchain(name="implementation", dotnet="@dotnet//:sdk/dotnet", sdk="@dotnet//:files", runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll", runner_support=["@rules_msbuild//tools/ExplicitBuild:files"], runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered", toolchain=":implementation", toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''')
    project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
    put('Library/Library.csproj', project.format('', ''))
    put('Library/library-data.txt', 'dependency-data')
    put('Library/Value.cs', 'public static class Value { public static int Get() => 7; }')
    put('Library/BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library")
msbuild_library(name="Library", project="Library.csproj", target_framework="net10.0", srcs=["Value.cs"], data=["library-data.txt"], visibility=["//visibility:public"])
''')
    put('App/App.csproj', project.format('<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="../Library/Library.csproj" /></ItemGroup>'))
    put('App/Program.cs', 'using System; using System.IO; using System.Reflection; using var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("message"); using var r = new StreamReader(s!); Console.WriteLine(Value.Get() + ":" + r.ReadToEnd() + ":" + File.ReadAllText("data.txt")); return args.Length > 0 || File.ReadAllText("library-data.txt") != "dependency-data" ? 1 : 0;')
    put('App/message.txt', 'resource')
    put('App/data.txt', 'runtime')
    put('App/BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_binary", "msbuild_test", "msbuild_items")
msbuild_items(name="resources", item_type="EmbeddedResource", srcs=["message.txt"], metadata={"LogicalName":"message"})
msbuild_binary(name="App", project="App.csproj", target_framework="net10.0", srcs=["Program.cs"], deps=["//Library"], items=[":resources"], data=["data.txt"])
msbuild_test(name="Tests", project="App.csproj", target_framework="net10.0", srcs=["Program.cs"], deps=["//Library"], items=[":resources"], data=["data.txt"])
msbuild_test(name="Fails", args=["fail"], project="App.csproj", target_framework="net10.0", srcs=["Program.cs"], deps=["//Library"], items=[":resources"], data=["data.txt"])
''')
    worker=os.environ.get('RULES_MSBUILD_EXPLICIT_WORKER') == '1'
    if worker:
        for build in workspace.rglob('BUILD.bazel'):
            text=build.read_text()
            for rule in ('msbuild_library','msbuild_binary','msbuild_test'):
                text=text.replace(rule+'(', rule+'(linux_worker=True, ')
            build.write_text(text)
    if os.environ.get('RULES_MSBUILD_PROFILE_BUILD') == '1':
        for build in workspace.rglob('BUILD.bazel'):
            text=build.read_text()
            for rule in ('msbuild_library','msbuild_binary','msbuild_test'):
                text=text.replace(rule+'(', rule+'(profile_build=True, ')
            build.write_text(text)
    shared_restore=os.environ.get('RULES_MSBUILD_SHARED_RESTORE') == '1'
    if shared_restore:
        with (workspace/'BUILD.bazel').open('a') as f:
            f.write('load("@rules_msbuild//msbuild:defs.bzl", "msbuild_restore")\nmsbuild_restore(name="restore_lib",target_framework="net10.0",visibility=["//visibility:public"])\nmsbuild_restore(name="restore_exe",target_framework="net10.0",executable=True,visibility=["//visibility:public"])\n')
        for build in workspace.rglob('BUILD.bazel'):
            text=build.read_text().replace('msbuild_library(', 'msbuild_library(restore="//:restore_lib", ').replace('msbuild_binary(', 'msbuild_binary(restore="//:restore_exe", ').replace('msbuild_test(', 'msbuild_test(restore="//:restore_exe", ')
            build.write_text(text)
    tool_marker=None
    if worker and os.environ.get('RULES_MSBUILD_CHECK_TOOL_RESTART') == '1':
        tool_marker=ROOT/'tools/ExplicitBuild/bin/Release/net10.0/worker-key-control.txt'
        assert not tool_marker.exists()
        tool_marker.write_text('tool-v1')
    records=[]
    def actions(case, mnemonic="MSBuildAssembly"):
        text=(folder/(case+'.execution.json')).read_text()
        result=[]; decoder=json.JSONDecoder()
        while text.strip():
            row, end=decoder.raw_decode(text.lstrip()); text=text.lstrip()[end:]
            if row.get('mnemonic') == mnemonic: result.append(row)
        return result
    def bazel(case, *args, success=True):
        command=[str(BAZEL), '--output_user_root='+str(folder/'user'), '--output_base='+str(folder/'base'), '--ignore_all_rc_files', *args, '--repository_cache='+os.environ.get('RULES_MSBUILD_REPOSITORY_CACHE', str(folder/'repository-cache')), '--disk_cache='+str(folder/'disk-cache'), '--execution_log_json_file='+str(folder/(case+'.execution.json'))]
        if os.environ.get('RULES_MSBUILD_REMOTE_CACHE'):
            command += ['--disk_cache=', '--remote_cache='+os.environ['RULES_MSBUILD_REMOTE_CACHE'], '--remote_download_outputs=all']
        if worker: command += ['--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1']
        p=subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=240)
        (folder/(case+'.log')).write_text(p.stdout+p.stderr)
        assert (p.returncode == 0) == success, (case, (p.stdout+p.stderr)[-7000:])
        records.append(dict(case=case,exitCode=p.returncode))
        print(case,p.returncode,flush=True)
        return p.stdout+p.stderr
    assert '7:resource:runtime' in bazel('run', 'run', '//App')
    if os.environ.get('RULES_MSBUILD_PROFILE_BUILD') == '1':
        for name in ('Library','App'):
            profile=json.loads((workspace/f'bazel-bin/{name}/{name}.diagnostics/compile-profile.json').read_text())
            for target in (('Build',) if shared_restore else ('Restore','Build')):
                for phase in ('ManagerSetup','BeginBuild','Request','EndBuild','ManagerDispose'):
                    assert profile['phases'][target+phase]['wallSeconds'] >= 0, profile
            assert profile['tasks']['Csc']['count'] == 1, profile
    resource_build=workspace/'App/BUILD.bazel'; resource_original=resource_build.read_text()
    for item_type,message in (('_bazeloriginalprojectreference','Reserved validation item type'),('analyzer','Dependency items require typed dependency attributes')):
        resource_build.write_text(resource_original.replace('item_type="EmbeddedResource"','item_type="'+item_type+'"'))
        assert message in bazel('reserved-item-'+item_type, 'build', '//App', success=False)
    resource_build.write_text(resource_original)
    bazel('test', 'test', '//App:Tests', '--test_output=all')
    bazel('failure', 'test', '//App:Fails', '--test_output=all', success=False)
    bazel('filter', 'test', '//App:Tests', '--test_filter=unsupported', success=False)
    reference=workspace/'bazel-bin/Library/Library.reference/Library.dll'
    before=hashlib.sha256(reference.read_bytes()).hexdigest()
    first_worker=json.loads((workspace/'bazel-bin/Library/Library.diagnostics/worker.json').read_text()) if worker else None
    library=workspace/'Library/Value.cs'; library.write_text('public static class Value { public static int Get() => 9; }')
    assert '9:resource:runtime' in bazel('body-edit', 'run', '//App')
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == before
    if worker:
        second_worker=json.loads((workspace/'bazel-bin/Library/Library.diagnostics/worker.json').read_text())
        assert first_worker['processId'] == second_worker['processId']
        assert 'server processed compilation' in (workspace/'bazel-bin/Library/Library.diagnostics/build.log').read_text()
    changed=actions('body-edit')
    assert '//Library:Library' in {a['targetLabel'] for a in changed}, changed
    assert {a['targetLabel'] for a in changed if not a.get('cacheHit')} <= {'//Library:Library'}, changed
    if worker:
        valid=library.read_text(); timestamp=library.stat().st_mtime_ns
        library.write_text('invalid C#')
        bazel('worker-compile-failure','build','//App',success=False)
        library.write_text(valid.replace('=> 9','=> 8'))
        os.utime(library,ns=(timestamp,timestamp))
        assert '8:resource:runtime' in bazel('worker-recovery','run','//App')
        recovered_worker=json.loads((workspace/'bazel-bin/Library/Library.diagnostics/worker.json').read_text())
        assert recovered_worker['processId'] == first_worker['processId']
        library.write_text(valid)
    if tool_marker:
        tool_marker.write_text('tool-v2')
        assert '9:resource:runtime' in bazel('changed-worker-tool', 'run', '//App')
        replaced=json.loads((workspace/'bazel-bin/Library/Library.diagnostics/worker.json').read_text())
        assert replaced['processId'] != first_worker['processId'], replaced
    app=workspace/'App/App.csproj'; original=app.read_text(); app.write_text(original.replace('../Library/Library.csproj','../Missing/Missing.csproj'))
    assert 'ProjectReference declarations disagree' in bazel('missing-edge', 'build', '//App', success=False)
    app.write_text(original)
    # The combined evaluation must retain declaration checks before replacements.
    app.write_text(original.replace('Include="../Library/Library.csproj"', 'Include="../Library/Library.csproj" Aliases="hidden"'))
    assert 'Unsupported ProjectReference metadata' in bazel('edge-metadata', 'build', '//App', success=False)
    app.write_text(original.replace('Include="../Library/Library.csproj"', 'Include="../Library/Library.csproj" GlobalPropertiesToRemove=";WebPublishProfileFile"'))
    bazel('absent-global-removal', 'build', '//App')
    app.write_text(original.replace('Include="../Library/Library.csproj"', 'Include="../Library/Library.csproj" GlobalPropertiesToRemove="Configuration"'))
    assert 'Configured ProjectReference removal disagrees' in bazel('active-global-removal', 'build', '//App', success=False)
    app.write_text(original.replace('Include="../Library/Library.csproj"', 'Include="../Library/Library.csproj" Condition="false"'))
    assert 'ProjectReference declarations disagree' in bazel('conditional-edge', 'build', '//App', success=False)
    app.write_text(original.replace('</Project>', '<ItemGroup><Compile Include="undeclared.cs" /></ItemGroup></Project>'))
    assert 'Undeclared Compile input' in bazel('undeclared-source', 'build', '//App', success=False)
    app.write_text(original.replace('</Project>', '<ItemGroup><Compile Include="undeclared.cs" NuGetItemType="Compile" /></ItemGroup></Project>'))
    assert 'Undeclared Compile input' in bazel('forged-package-source', 'build', '//App', success=False)
    app.write_text(original)
    if shared_restore:
        app.write_text(original.replace('</Project>', '<PropertyGroup><RuntimeIdentifier>linux-arm64</RuntimeIdentifier></PropertyGroup></Project>'))
        assert 'Shared restore requires' in bazel('restore-incompatible-property','build','//App',success=False)
        app.write_text(original.replace('</Project>', '<Target Name="AlterRestore" BeforeTargets="Restore" /></Project>'))
        assert 'Shared restore requires' in bazel('restore-custom-target','build','//App',success=False)
        app.write_text(original)
        build=workspace/'App/BUILD.bazel'; saved=build.read_text()
        build.write_text(saved.replace('restore="//:restore_exe"','restore="//:restore_lib"'))
        assert 'output kind must match' in bazel('restore-kind-mismatch','build','//App',success=False)
        build.write_text(saved)
        # General projects deliberately use the existing per-project restore lane.
        build.write_text(saved.replace('restore="//:restore_exe", ', ''))
    bazel('recovered', 'test', '//App:Tests', '--test_output=all')
    app.write_text(original.replace('</Project>', '<ItemGroup><PackageReference Include="Undeclared.Package" Version="1.0.0" /></ItemGroup></Project>'))
    assert 'Undeclared PackageReference' in bazel('undeclared-package', 'build', '//App', success=False)
    app.write_text(original.replace('</Project>', '<ItemGroup><Reference Include="undeclared.dll" /></ItemGroup></Project>'))
    assert 'Undeclared assembly/analyzer dependency' in bazel('undeclared-reference', 'build', '//App', success=False)
    app.write_text(original)
    # A declared custom target cannot read an undeclared host file or write sources.
    secret=folder/'undeclared.txt'; secret.write_text('must remain outside the sandbox')
    probe='<Target Name="BoundaryProbe" BeforeTargets="CoreCompile">{}</Target>'
    app.write_text(original.replace('</Project>', probe.format('<ReadLinesFromFile File="'+str(secret)+'"><Output TaskParameter="Lines" ItemName="_HostLines" /></ReadLinesFromFile><Error Condition="&apos;@(_HostLines)&apos; != &apos;must remain outside the sandbox&apos;" Text="Host read blocked" />')+'</Project>'))
    bazel('undeclared-read', 'build', '//App', success=False)
    app.write_text(original.replace('</Project>', probe.format('<WriteLinesToFile File="$(MSBuildProjectDirectory)/forbidden.txt" Lines="write" />')+'</Project>'))
    bazel('source-write', 'build', '//App', success=False)
    app.write_text(original)
    if shared_restore: (workspace/'App/BUILD.bazel').write_text(saved)
    bazel('cache-seed', 'run', '//App')
    subprocess.run([str(BAZEL),'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/'base'),'--ignore_all_rc_files','shutdown'], cwd=workspace,check=True)
    # Delete producer execution state and relocate the source before recovery.
    for directory, _, _ in os.walk(folder/'base', followlinks=False):
        os.chmod(directory, 0o700)
    shutil.rmtree(folder/'base')
    destination=folder/'relocated'
    shutil.copytree(workspace,destination,ignore=shutil.ignore_patterns('bazel-*'),dirs_exist_ok=True)
    workspace=destination
    assert '9:resource:runtime' in bazel('cache-recovery','run','//App')
    recovered=actions('cache-recovery')
    assert {a['targetLabel'] for a in recovered} == {'//Library:Library','//App:App'}, recovered
    assert all(a.get('cacheHit') for a in recovered), recovered
    if shared_restore:
        restores=actions('cache-recovery', 'MSBuildRestore')
        assert len(restores)==2 and all(a.get('cacheHit') for a in restores), restores
        # Consume recovered restore metadata in an actual compilation at the new path.
        (workspace/'App/Program.cs').write_text((workspace/'App/Program.cs').read_text()+'\n// relocation rebuild\n')
        assert '9:resource:runtime' in bazel('restore-relocated-compile','run','//App')
        assert any(not a.get('cacheHit') for a in actions('restore-relocated-compile'))
    (folder/'report.json').write_text(json.dumps(records,indent=2))
    subprocess.run([str(BAZEL),'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/'base'),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
    if tool_marker: tool_marker.unlink()


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
