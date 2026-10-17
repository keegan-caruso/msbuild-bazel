#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
printf 'public static class Extra { public static int Value() => 1; }\n' > Extra.input
printf 'public class P0 { public static int Value() => Extra.Value(); }\n' > P0/Code.cs
sed -i 's|</Project>|<ItemGroup><Compile Include="../inputs/Extra.cs" /></ItemGroup></Project>|' P0/P0.csproj
cat > Directory.Build.targets <<'TARGETS'
<Project><Target Name="ShellProbe" BeforeTargets="CoreCompile"><Exec Command="sh -c &quot;exit 0&quot;" /></Target></Project>
TARGETS
python3 - <<'MAPPING'
import hashlib,json
from pathlib import Path
Path('mappings.json').write_text(json.dumps({'projectDefaults': {'referenceBoundary': True, 'properties': {'DefineConstants':'FIRST'},
    'documents': {'Directory.Build.targets': {'sha256': hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),
        'targets': ['ShellProbe'], 'tasks': [], 'inputs': []}}}}))
MAPPING
printf '<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>\n' > NuGet.Config
cat > producer.bzl <<'RULE'
def _tree(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".tree")
    ctx.actions.run_shell(inputs=[ctx.file.src], outputs=[output], arguments=[ctx.file.src.path, output.path], command='mkdir -p "$2"; cp "$1" "$2/Extra.cs"')
    return [DefaultInfo(files=depset([output]))]
source_tree = rule(implementation=_tree, attrs={"src": attr.label(allow_single_file=True)})
RULE
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load(":producer.bzl", "source_tree")
source_tree(name="extra", src="Extra.input")
msbuild_sync(name="baseline", projects=["P2/P2.csproj"], mappings="mappings.json", inputs={":extra":"inputs"}, package_build=True, resolve_references=True)
msbuild_sync(name="sync", projects=["P2/P2.csproj"], mappings="mappings.json", inputs={":extra":"inputs"}, srcs=glob(["P*/**", "global.json", "Directory.Build.*", "NuGet.Config"]), package_build=True, resolve_references=True)
BUILD
sync_run() {
    local name=$1; shift
    bazel run //:sync --execution_log_json_file="$TEST_TMPDIR/$name.actions.json" -- "$@" > "$TEST_TMPDIR/$name.log" 2>&1 || { cat "$TEST_TMPDIR/$name.log" >&2; return 1; }
}
preparations() {
    python3 - "$TEST_TMPDIR/$1.actions.json" "$2" <<'PY'
import json,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text(); d=json.JSONDecoder(); rows=[]
while text.strip():
    row,end=d.raw_decode(text.lstrip()); rows.append(row); text=text.lstrip()[end:]
rows=[r for r in rows if r.get('mnemonic')=='MSBuildSyncPrepare']
assert len(rows)==int(sys.argv[2]),[(r.get('cacheHit'), r.get('exitCode')) for r in rows]
PY
}
bazel run //:baseline > "$TEST_TMPDIR/baseline.log" 2>&1 || { cat "$TEST_TMPDIR/baseline.log" >&2; exit 1; }
cp graph.generated.json "$TEST_TMPDIR/baseline.json"
cp graph.generated.bzl "$TEST_TMPDIR/baseline.bzl"
sync_run cold; preparations cold 1
diff -u "$TEST_TMPDIR/baseline.json" graph.generated.json
diff -u "$TEST_TMPDIR/baseline.bzl" graph.generated.bzl
sync_run warm --check; preparations warm 0
printf 'public class P0 { public static int Value() => Extra.Value() + 1; }\n' > P0/Code.cs
sync_run body --check; preparations body 1
sync_run body-warm --check; preparations body-warm 0
printf 'public static class Extra { public static int Value() => 2; }\n' > Extra.input
sync_run producer --check; preparations producer 1
sed -i 's|<LangVersion>latest</LangVersion>|<LangVersion>latest</LangVersion><DefineConstants>ROOT</DefineConstants>|' Directory.Build.props
if sync_run props --check; then echo 'Accepted stale props' >&2; exit 1; fi
preparations props 1
sync_run props-publish; preparations props-publish 0
sed -i 's/FIRST/SECOND/' mappings.json
if sync_run mappings --check; then echo 'Accepted stale mappings' >&2; exit 1; fi
preparations mappings 1
sync_run mappings-publish; preparations mappings-publish 0
sed -i 's|</PropertyGroup>|<ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup>|' P1/P1.csproj
if sync_run definition --check; then echo 'Accepted stale compiler selection' >&2; exit 1; fi
preparations definition 1
sync_run definition-publish; preparations definition-publish 0
python3 - <<'CHECK'
import json
row=json.load(open('graph.generated.json'))['Projects']['P2/P2.csproj']['Configurations'][0]
assert row['CompilerReferences']=={'P1/P1.csproj':'P1/bin/Release/net10.0/P1.dll'},row
CHECK
printf 'public class Added {}\n' > P0/Added.cs
if sync_run membership --check; then echo 'Accepted stale membership' >&2; exit 1; fi
preparations membership 1
sync_run membership-publish; preparations membership-publish 0
python3 - <<'CHECK'
import json
assert 'P0/Added.cs' in json.load(open('graph.generated.json'))['Projects']['P0/P0.csproj']['Configurations'][0]['Inputs']
CHECK
cp graph.generated.json "$TEST_TMPDIR/current.json"
cp graph.generated.bzl "$TEST_TMPDIR/current.bzl"
bazel run //:baseline > "$TEST_TMPDIR/updated-baseline.log" 2>&1 || { cat "$TEST_TMPDIR/updated-baseline.log" >&2; exit 1; }
diff -u "$TEST_TMPDIR/current.json" graph.generated.json
diff -u "$TEST_TMPDIR/current.bzl" graph.generated.bzl
cp BUILD.bazel "$TEST_TMPDIR/sync.BUILD"
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph")
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
bazel run //:app --disk_cache= --remote_cache= > "$TEST_TMPDIR/app.log" 2>&1 || { cat "$TEST_TMPDIR/app.log" >&2; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/app.log") == 3 ]]
cp "$TEST_TMPDIR/sync.BUILD" BUILD.bazel
printf 'not valid C#\n' > P0/Code.cs
if sync_run failed; then echo 'Accepted broken qualification' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failed.log" 'qualification Build failed'
cmp graph.generated.json "$TEST_TMPDIR/current.json"
cmp graph.generated.bzl "$TEST_TMPDIR/current.bzl"
printf 'public class P0 { public static int Value() => Extra.Value() + 1; }\n' > P0/Code.cs
# A failed action removes its output tree. Without a CAS, local action metadata
# cannot restore the older bytes, so ordinary Bazel correctly prepares again.
sync_run recovered --check; preparations recovered 1
printf '# Authored content\n' > graph.generated.bzl
if sync_run authored; then echo 'Overwrote authored output' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/authored.log" 'Refusing to overwrite'
cmp graph.generated.json "$TEST_TMPDIR/current.json"
cp "$TEST_TMPDIR/current.bzl" graph.generated.bzl
if sync_run runtime-flags --configuration Debug; then echo 'Accepted an unkeyed configuration' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/runtime-flags.log" 'accepts only --check'
cp P0/P0.csproj "$TEST_TMPDIR/declared.csproj"
printf 'public class Undeclared {}\n' > Undeclared.cs
sed -i 's|</Project>|<ItemGroup><Compile Include="../Undeclared.cs" /></ItemGroup></Project>|' P0/P0.csproj
if sync_run undeclared; then echo 'Read outside the declared snapshot' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/undeclared.log" 'input does not exist and has no project producer: Undeclared.cs'
cmp graph.generated.json "$TEST_TMPDIR/current.json"
cmp graph.generated.bzl "$TEST_TMPDIR/current.bzl"
cp "$TEST_TMPDIR/declared.csproj" P0/P0.csproj
# Exercise directory artifacts from the native package inventory as cache inputs.
cat > NuGet.Config <<'CONFIG'
<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>
CONFIG
sed -i 's|</Project>|<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" /></ItemGroup></Project>|' P0/P0.csproj
cat >> BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")
msbuild_nuget_update(name="update_packages", projects=["P2/P2.csproj"], mappings="mappings.json")
BUILD
bazel run //:update_packages > "$TEST_TMPDIR/packages-update.log" 2>&1 || { cat "$TEST_TMPDIR/packages-update.log" >&2; exit 1; }
cat >> MODULE.bazel <<'MODULE'
packages=use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")
packages.lock(name="packages", lockfile="//:nuget.lock.json")
use_repo(packages,"packages")
MODULE
sed -i 's/package_build=True/package_lock="@packages\/\/:packages", package_build=True/g' BUILD.bazel
bazel run //:baseline > "$TEST_TMPDIR/packages-baseline.log" 2>&1 || { cat "$TEST_TMPDIR/packages-baseline.log" >&2; exit 1; }
cp graph.generated.json "$TEST_TMPDIR/packages.json"
cp graph.generated.bzl "$TEST_TMPDIR/packages.bzl"
sync_run packages --check; preparations packages 1
diff -u "$TEST_TMPDIR/packages.json" graph.generated.json
diff -u "$TEST_TMPDIR/packages.bzl" graph.generated.bzl
sync_run packages-warm --check; preparations packages-warm 0
cp BUILD.bazel "$TEST_TMPDIR/valid.BUILD"
cat >> BUILD.bazel <<'BUILD'
msbuild_sync(name="bad_generated", projects=["P2/P2.csproj"], srcs=[":extra"])
BUILD
if bazel build //:bad_generated > "$TEST_TMPDIR/generated-source.log" 2>&1; then echo 'Accepted generated srcs' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/generated-source.log" 'use inputs for producers'
cp "$TEST_TMPDIR/valid.BUILD" BUILD.bazel
cat >> BUILD.bazel <<'BUILD'
msbuild_sync(name="bad_empty", projects=["P2/P2.csproj"], srcs=[])
BUILD
if bazel build //:bad_empty > "$TEST_TMPDIR/empty-source.log" 2>&1; then echo 'Accepted empty srcs' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/empty-source.log" 'requires a nonempty srcs'
cp "$TEST_TMPDIR/valid.BUILD" BUILD.bazel
echo 'PASS: cached qualification, normal-mode parity, source/producer/config/package inputs and protected publication'
