#!/usr/bin/env bash
# A locked package may share its assembly name with a graph producer.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel build @dotnet//:files > "$TEST_TMPDIR/sdk.log" 2>&1 || { cat "$TEST_TMPDIR/sdk.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
cp -a "$sdk" "$scratch/package-sdk"
mkdir "$scratch/package"
cat > "$scratch/package/Package.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><AssemblyName>P0</AssemblyName></PropertyGroup></Project>
XML
printf 'public class P0 { public static int Value() => 7; }\n' > "$scratch/package/Code.cs"
"$scratch/package-sdk/dotnet" build "$scratch/package/Package.csproj" -c Release -p:UseSharedCompilation=false > "$TEST_TMPDIR/package-build.log" 2>&1 || { cat "$TEST_TMPDIR/package-build.log" >&2; exit 1; }
export PACKAGE_REF="$scratch/package/obj/Release/net10.0/ref/P0.dll"
export PACKAGE_DLL="$scratch/package/bin/Release/net10.0/P0.dll"
python3 - <<'PY'
import base64,hashlib,json,os,zipfile
from pathlib import Path
with zipfile.ZipFile('fixture.copy.1.0.0.nupkg','w') as archive:
    archive.writestr('Fixture.Copy.nuspec','<package><metadata><id>Fixture.Copy</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
    archive.write(os.environ['PACKAGE_DLL'],'lib/net10.0/P0.dll')
    archive.write(os.environ['PACKAGE_REF'],'tools/wrong/P0.dll')
data=Path('fixture.copy.1.0.0.nupkg').read_bytes()
Path('BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")
load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
msbuild_nuget_package(name="package",package_id="Fixture.Copy",version="1.0.0",archive="fixture.copy.1.0.0.nupkg",archive_sha256="%s",content_hash="%s")
msbuild_package_lock(name="packages",packages=[":package"])
msbuild_sync(name="sync",package_build=True,package_lock=":packages",projects=["P2/P2.csproj"],mappings="copies.json")
'''%(hashlib.sha256(data).hexdigest(),base64.b64encode(hashlib.sha512(data).digest()).decode()))
p=Path('P1/P1.csproj')
p.write_text(p.read_text().replace('</PropertyGroup>', '<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies></PropertyGroup>').replace('Include="../P0/P0.csproj"','Include="../P0/P0.csproj" ReferenceOutputAssembly="false"').replace('</ItemGroup>','<PackageReference Include="Fixture.Copy" Version="1.0.0" /></ItemGroup>'))
copies={f'{p}/bin/$(Configuration)/net10.0/P0.dll':'.nuget/fixture.copy/1.0.0/lib/net10.0/P0.dll' for p in ['P1','P2']}
bindings={p+'/'+p+'.csproj':{'dependencyCopies':{k:v for k,v in copies.items() if k.startswith(p+'/')}} for p in ['P1','P2']}
if os.environ.get('RESOLVE_REFERENCES')=='1':
    bindings={}
    build=Path('BUILD.bazel')
    build.write_text(build.read_text().replace('package_build=True,','package_build=True,resolve_references=True,'))
Path('copies.json').write_text(json.dumps({'projectDefaults':{'referenceBoundary':True,'preparedRestore':True},'projects':bindings}))
PY
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
if [[ "${RESOLVE_REFERENCES:-0}" != 1 ]]; then
# A different version is outside the declared lock, even if the assembly name matches.
cp copies.json copies.saved.json
sed -i 's|fixture.copy/1.0.0/|fixture.copy/9.0.0/|g' copies.json
if bazel run //:sync > "$TEST_TMPDIR/unlocked.log" 2>&1; then echo 'Accepted unlocked package copy' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/unlocked.log" 'prepared locked package'
mv copies.saved.json copies.json
bazel run //:sync > "$TEST_TMPDIR/sync-restored.log" 2>&1 || { cat "$TEST_TMPDIR/sync-restored.log" >&2; exit 1; }
fi
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() {
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
}
run seed 7
python3 - <<'PYMODE'
import json,os,stat
from pathlib import Path
root=Path('bazel-bin/graph.graph/workspace')
Path(os.environ['TEST_TMPDIR'],'copy-modes.json').write_text(json.dumps({p:stat.S_IMODE((root/p/'bin/Release/net10.0/P0.dll').stat().st_mode) for p in ['P1','P2']}))
PYMODE
printf 'System.Console.WriteLine(P1.Value() + 1);\n' > P2/Code.cs
run replay 8
python3 - <<'PY'
import json,os,stat
from pathlib import Path
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==(2,1),r
root=Path('bazel-bin/graph.graph/workspace')
package=Path(os.environ['PACKAGE_DLL']).read_bytes()
for p in ['P1','P2']:
    copied=root/p/'bin/Release/net10.0/P0.dll'
    assert copied.read_bytes()==package,p
    assert stat.S_IMODE(copied.stat().st_mode)==json.load(open(Path(os.environ['TEST_TMPDIR'],'copy-modes.json')))[p],(p,copied.stat().st_mode)
assert (root/'P0/bin/Release/net10.0/P0.dll').read_bytes()!=package
print('PASS: package copy replay preserves locked bytes and consumer mode despite project basename collision')
PY
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
products > "$TEST_TMPDIR/replay.sha256"
bazel shutdown
bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh 8
products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/replay.sha256" "$TEST_TMPDIR/fresh.sha256"
if [[ "${RESOLVE_REFERENCES:-0}" == 1 ]]; then
    echo 'PASS: generic sync selects locked package bytes despite producer basename collisions; replay matches fresh bytes and modes'
    exit 0
fi
sed -i 's|lib/net10.0/P0.dll|tools/wrong/P0.dll|g' copies.json
bazel run //:sync > "$TEST_TMPDIR/mismatch-sync.log" 2>&1 || { cat "$TEST_TMPDIR/mismatch-sync.log" >&2; exit 1; }
if bazel run //:app "${options[@]}" > "$TEST_TMPDIR/mismatch.log" 2>&1; then echo 'Accepted mismatched package bytes' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/mismatch.log" 'Declared dependency copy does not match its producer'
echo 'PASS: fresh and replayed package-copy products match; unlocked sources and mismatched bytes fail closed'
