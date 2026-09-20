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
sdk(name = "dotnet", path = {json.dumps(str(SDK))}, include_runtime_closure = {str(sys.platform == 'darwin')})
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
    records=[]
    def actions(case):
        text=(folder/(case+'.execution.json')).read_text()
        result=[]; decoder=json.JSONDecoder()
        while text.strip():
            row, end=decoder.raw_decode(text.lstrip()); text=text.lstrip()[end:]
            if row.get('mnemonic') == 'MSBuildAssembly': result.append(row)
        return result
    def bazel(case, *args, success=True):
        command=[str(BAZEL), '--output_user_root='+str(folder/'user'), '--output_base='+str(folder/'base'), '--ignore_all_rc_files', *args, '--repository_cache='+os.environ.get('RULES_MSBUILD_REPOSITORY_CACHE', str(folder/'repository-cache')), '--disk_cache='+str(folder/'disk-cache'), '--execution_log_json_file='+str(folder/(case+'.execution.json'))]
        if os.environ.get('RULES_MSBUILD_REMOTE_CACHE'):
            command += ['--disk_cache=', '--remote_cache='+os.environ['RULES_MSBUILD_REMOTE_CACHE'], '--remote_download_outputs=all']
        p=subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=240)
        (folder/(case+'.log')).write_text(p.stdout+p.stderr)
        assert (p.returncode == 0) == success, (case, (p.stdout+p.stderr)[-7000:])
        records.append(dict(case=case,exitCode=p.returncode))
        print(case,p.returncode,flush=True)
        return p.stdout+p.stderr
    assert '7:resource:runtime' in bazel('run', 'run', '//App')
    bazel('test', 'test', '//App:Tests', '--test_output=all')
    bazel('failure', 'test', '//App:Fails', '--test_output=all', success=False)
    bazel('filter', 'test', '//App:Tests', '--test_filter=unsupported', success=False)
    reference=workspace/'bazel-bin/Library/Library.reference/Library.dll'
    before=hashlib.sha256(reference.read_bytes()).hexdigest()
    library=workspace/'Library/Value.cs'; library.write_text('public static class Value { public static int Get() => 9; }')
    assert '9:resource:runtime' in bazel('body-edit', 'run', '//App')
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == before
    changed=actions('body-edit')
    assert '//Library:Library' in {a['targetLabel'] for a in changed}, changed
    assert {a['targetLabel'] for a in changed if not a.get('cacheHit')} <= {'//Library:Library'}, changed
    app=workspace/'App/App.csproj'; original=app.read_text(); app.write_text(original.replace('../Library/Library.csproj','../Missing/Missing.csproj'))
    assert 'ProjectReference declarations disagree' in bazel('missing-edge', 'build', '//App', success=False)
    app.write_text(original)
    bazel('recovered', 'test', '//App:Tests', '--test_output=all')
    # A declared custom target cannot read an undeclared host file or write sources.
    secret=folder/'undeclared.txt'; secret.write_text('must remain outside the sandbox')
    probe='<Target Name="BoundaryProbe" BeforeTargets="CoreCompile">{}</Target>'
    app.write_text(original.replace('</Project>', probe.format('<ReadLinesFromFile File="'+str(secret)+'"><Output TaskParameter="Lines" ItemName="_HostLines" /></ReadLinesFromFile><Error Condition="&apos;@(_HostLines)&apos; != &apos;must remain outside the sandbox&apos;" Text="Host read blocked" />')+'</Project>'))
    bazel('undeclared-read', 'build', '//App', success=False)
    app.write_text(original.replace('</Project>', probe.format('<WriteLinesToFile File="$(MSBuildProjectDirectory)/forbidden.txt" Lines="write" />')+'</Project>'))
    bazel('source-write', 'build', '//App', success=False)
    app.write_text(original)
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
    (folder/'report.json').write_text(json.dumps(records,indent=2))
    subprocess.run([str(BAZEL),'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/'base'),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
