#!/usr/bin/env bash
# SDK-selected inputs are captured by sync without dependency-specific mappings.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
sed -i 's|</Project>|<Target Name="DropUnusedCompilerReference" BeforeTargets="FindReferenceAssembliesForReferences"><ItemGroup><ReferencePath Remove="@(ReferencePath)" Condition="\x27%(Filename)\x27 == \x27P0\x27" /></ItemGroup></Target></Project>|' P2/P2.csproj
# SDK targets can append bookkeeping references after compilation. Capture roles
# from the static graph, before the private qualification Build mutates items.
python3 - <<'SDK'
from pathlib import Path
p=Path('P2/P2.csproj')
p.write_text(p.read_text().replace('</Project>', '<Target Name="LateAnalyzerBookkeeping" AfterTargets="Build"><ItemGroup><ProjectReference Include="../P0/P0.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false" /></ItemGroup></Target></Project>'))
SDK
mapping() {
    python3 - "$1" <<'PY'
import hashlib,json,sys
from pathlib import Path
binding={}
if '<Target ' in Path('P2/P2.csproj').read_text():
    binding['documents']={'P2/P2.csproj':dict(sha256=hashlib.sha256(Path('P2/P2.csproj').read_bytes()).hexdigest(),targets=['DropUnusedCompilerReference','LateAnalyzerBookkeeping'],tasks=[],inputs=[])}
if sys.argv[1]=='tool': binding['implementationDependencies']=['P1/P1.csproj']
Path('resolved.json').write_text(json.dumps(dict(projectDefaults=dict(referenceBoundary=True,preparedRestore=True),projects={'P2/P2.csproj':binding})))
PY
}
mapping narrow
sed -i 's/projects = \["P2\/P2.csproj"\]/projects = ["P2\/P2.csproj"], mappings = "resolved.json", package_build = True, resolve_references = True/' BUILD.bazel
sync() { bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }; }
sync seed
[[ ! -d P0/bin && ! -d P1/obj ]]
python3 - <<'PY'
import json
c=json.load(open('graph.generated.json'))
assert c['Version']==10
p=c['Projects']['P2/P2.csproj']['Configurations'][0]
assert p['CompilerReferencesComplete'] and set(p['CompilerReferences'])=={'P1/P1.csproj'},p
assert p['ImplementationDependencies']==[],p
assert p['DependencyCopies']['P2/bin/Release/net10.0/P0.dll']=='P1/bin/Release/net10.0/P0.dll',p
PY
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() { bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }; [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]; }
counts() {
    python3 - "$1" "$2" <<'PY'
import json,sys
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==(int(sys.argv[1]),int(sys.argv[2])),r
PY
}
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
run seed 1; counts 0 3
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run body 2; counts 2 1
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
run api 2; counts 1 2
products > "$TEST_TMPDIR/api.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh 2; products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/fresh.sha256"
# Capture an implementation DLL selected by the SDK, rather than hardcoding it.
sed -i 's|</PropertyGroup>|<ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup>|' P1/P1.csproj
sed -i 's|Include="../P1/P1.csproj"|Include="../P1/P1.csproj" SkipUseReferenceAssembly="true"|' P2/P2.csproj
mapping implementation; sync implementation
python3 - <<'PY'
import json
p=json.load(open('graph.generated.json'))['Projects']['P2/P2.csproj']['Configurations'][0]
assert p['CompilerReferences']=={'P1/P1.csproj':'P1/bin/Release/net10.0/P1.dll'},p
PY
run implementation-seed 2
printf 'public class P0 { public static int Value() => 2 + 0; public static int Added() => 3; }\n' > P0/Code.cs
run implementation-body 2; counts 2 1
printf 'public class P1 { public static int Value() => P0.Value() + 0; }\n' > P1/Code.cs
run implementation-producer 2; counts 1 2
products > "$TEST_TMPDIR/implementation.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/implementation-clean.log" 2>&1
run implementation-fresh 2; products > "$TEST_TMPDIR/implementation-fresh.sha256"
cmp "$TEST_TMPDIR/implementation.sha256" "$TEST_TMPDIR/implementation-fresh.sha256"
mapping tool; sync tool; run tool-seed 2
printf 'public class P0 { public static int Value() => 2 + 0 + 0; public static int Added() => 3; }\n' > P0/Code.cs
run tool-body 2; counts 1 2
# Outer dispatchers evaluate analyzer items but schedule only inner builds.
# Keep the implementation edge on each inner consumer and exercise real codegen.
python3 - <<'OUTER'
from pathlib import Path
for name in ['Multi','Generator']: Path(name).mkdir()
Path('Multi/Multi.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Generator/Generator.csproj" ReferenceOutputAssembly="false" OutputItemType="Analyzer" /></ItemGroup></Project>')
Path('Multi/Code.cs').write_text('System.Console.WriteLine(Generated.Value);')
refs=''.join('<Reference Include="'+n+'" HintPath="$(MSBuildBinPath)/Roslyn/bincore/'+n+'.dll" Private="false" />' for n in ['Microsoft.CodeAnalysis','Microsoft.CodeAnalysis.CSharp'])
Path('Generator/Generator.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup>'+refs+'</ItemGroup></Project>')
Path('Generator/Code.cs').write_text('using Microsoft.CodeAnalysis; [Generator] public class Generate : ISourceGenerator { public void Initialize(GeneratorInitializationContext context) {} public void Execute(GeneratorExecutionContext context) { context.AddSource("Value.g.cs", "public static class Generated { public const int Value = 1; }"); } }')
Path('outer.json').write_text('{"projectDefaults":{"referenceBoundary":true,"preparedRestore":true}}')
Path('BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nmsbuild_sync(name="sync",projects=["Multi/Multi.csproj"],mappings="outer.json",package_build=True,resolve_references=True)\n')
OUTER
sync outer
python3 - <<'OUTER'
import json
rows=json.load(open('graph.generated.json'))['Projects']['Multi/Multi.csproj']['Configurations']
outer=next(r for r in rows if not r['Properties']['TargetFramework'])
assert outer['ImplementationDependencies']==[],outer
inner=[r for r in rows if r['Properties']['TargetFramework']]
assert len(inner)==2 and all(r['ImplementationDependencies']==['Generator/Generator.csproj'] for r in inner),inner
OUTER
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl","app_graph")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")
app_graph(name="graph",linux_stable_paths=True,linux_worker=True)
msbuild_graph_binary(name="multi",graph=":graph",project="Multi/Multi.csproj",framework="net10.0")
BUILD
bazel run //:multi "${options[@]}" > "$TEST_TMPDIR/outer-seed.log" 2>&1 || { cat "$TEST_TMPDIR/outer-seed.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/outer-seed.log")" == 1 ]]; counts 0 3
sed -i 's/Value = 1/Value = 2/' Generator/Code.cs
bazel run //:multi "${options[@]}" > "$TEST_TMPDIR/outer-generator.log" 2>&1 || { cat "$TEST_TMPDIR/outer-generator.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/outer-generator.log")" == 2 ]]; counts 0 3
echo 'PASS: SDK compiler/copy selections, body/API parity, static tool roles, outer dispatch and generator implementation invalidation'
