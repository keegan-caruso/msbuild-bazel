#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
: "${QUALIFICATION_CACHE_URL:?Set an HTTP AC/CAS endpoint}"
# Separate this cold control from earlier runs using the same HTTP cache.
sed -i 's|</PropertyGroup>|<PackageOutputPath>bin/$(Configuration)/$(TargetFramework)/</PackageOutputPath></PropertyGroup>|' P0/P0.csproj P1/P1.csproj P2/P2.csproj
printf '<!-- Seed control: %s -->\n' "${scratch##*/}" >> Directory.Build.props
mkdir PDiscovery
printf 'unselected evaluation member\n' > PDiscovery/member.txt
sed -i 's|</Project>|<ItemGroup><DiscoveryFiles Include="$(MSBuildThisFileDirectory)PDiscovery/*.txt;not-a-file" /></ItemGroup></Project>|' Directory.Build.props
cat > Directory.Build.targets <<'HOOKS'
<Project><Target Name="ObserveBuild" BeforeTargets="Build"><WriteLinesToFile File="$(IntermediateOutputPath)hooks.txt" Lines="Build" Overwrite="false" /></Target><Target Name="ObservePack" AfterTargets="Pack"><WriteLinesToFile File="$(IntermediateOutputPath)hooks.txt" Lines="Pack" Overwrite="false" /></Target><Target Name="ObservePublish" AfterTargets="Publish"><WriteLinesToFile File="$(IntermediateOutputPath)hooks.txt" Lines="Publish" Overwrite="false" /></Target></Project>
HOOKS
python3 - <<'HOOKS'
import hashlib,json
from pathlib import Path
p=Path('Directory.Build.targets')
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'evaluationItems':['DiscoveryFiles'],'referenceBoundary':True,'documents':{'Directory.Build.targets':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'targets':['ObserveBuild','ObservePack','ObservePublish'],'tasks':[],'inputs':[]}}}}))
HOOKS
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="sync",mappings="mappings.json",projects=["P2/P2.csproj"],srcs=glob(["P*/**","global.json","Directory.Build.*"]),package_build=True,resolve_references=True,qualification_cache=True,seed_build_cache=True)
BUILD
sync() {
    bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" "$@" > "$TEST_TMPDIR/$label.log" 2>&1 || { cat "$TEST_TMPDIR/$label.log" >&2; return 1; }
    assert_contains "$TEST_TMPDIR/$label.log" "GRAPH_CACHE_SEED {\"seeded\":$seeded,"
}
seeded=3
label=seed; sync
execroot=$(bazel info execution_root 2> "$TEST_TMPDIR/info.log")
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
assert_contains "$TEST_TMPDIR/seed.log" '"hits":0,"misses":3,"uncacheable":0,"compilations":3'
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl","app_graph")
app_graph(name="pack",target="Pack",linux_stable_paths=True,profile_build=True,reuse_build_cache=True)
app_graph(name="publish",target="Publish",linux_stable_paths=True,profile_build=True,reuse_build_cache=True)
BUILD
target_products() {
    python3 - <<'PRODUCTS'
import hashlib,json,zipfile
from pathlib import Path
products={}
for package in Path('bazel-bin/pack.graph/workspace').glob('P*/bin/Release/**/*.nupkg'):
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if name.endswith(('.dll','.pdb','.nuspec')):
                products[str(package.relative_to('bazel-bin/pack.graph/workspace'))+'/'+name]=hashlib.sha256(archive.read(name)).hexdigest()
for path in Path('bazel-bin/publish.graph/workspace/P2/bin/Release/net10.0/publish').rglob('*'):
    if path.is_file():
        products[str(path.relative_to('bazel-bin/publish.graph/workspace'))]=hashlib.sha256(path.read_bytes()).hexdigest()
assert products
print(json.dumps(products,sort_keys=True))
PRODUCTS
}
# First-use Pack/Publish must execute their targets while reusing Build files.
bazel build //:pack //:publish --remote_cache= --disk_cache= --jobs=1 \
    --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/pack-publish.log" 2>&1 || { cat "$TEST_TMPDIR/pack-publish.log" >&2; exit 1; }
python3 - <<'TARGETS'
import json
from pathlib import Path
for target in ['pack','publish']:
    report=json.loads(Path('bazel-bin',target+'.graph/report.json').read_text())
    print('BUILD_SEED_TARGET',target,json.dumps(report))
    assert report['buildSeedHits']>0,report
    assert report['compilerTasks']==0,report
    hook=Path('bazel-bin',target+'.graph/workspace/P2/obj/Release/net10.0/hooks.txt').read_text().splitlines()
    assert hook==['Build',target.capitalize()],hook
assert list(Path('bazel-bin/pack.graph/workspace').glob('P*/bin/Release/**/*.nupkg'))
assert Path('bazel-bin/publish.graph/workspace/P2/bin/Release/net10.0/publish/P2.dll').is_file()
TARGETS
target_products > "$TEST_TMPDIR/seed-target-products.json"
# A fresh target action repeats Pack/Publish while its Build phase reuses seeds.
bazel build //:pack //:publish --remote_cache= --disk_cache= --jobs=1 \
    --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" \
    --action_env=RULES_MSBUILD_PROJECT_CACHE_REPLAY_CONTROL=1 > "$TEST_TMPDIR/pack-publish-replay.log" 2>&1 || { cat "$TEST_TMPDIR/pack-publish-replay.log" >&2; exit 1; }
python3 - <<'TARGETS'
import json
from pathlib import Path
for target in ['pack','publish']:
    report=json.loads(Path('bazel-bin',target+'.graph/report.json').read_text())
    assert report['buildSeedHits']==3 and report['hits']==0,report
    hook=Path('bazel-bin',target+'.graph/workspace/P2/obj/Release/net10.0/hooks.txt').read_text().splitlines()
    assert hook==['Build',target.capitalize()],hook
TARGETS
"$sdk/dotnet" bazel-bin/publish.graph/workspace/P2/bin/Release/net10.0/publish/P2.dll > "$TEST_TMPDIR/publish-run.log"
[[ $(cat "$TEST_TMPDIR/publish-run.log") == 1 ]]
target_products > "$TEST_TMPDIR/replayed-target-products.json"
cmp "$TEST_TMPDIR/seed-target-products.json" "$TEST_TMPDIR/replayed-target-products.json"
# With the HTTP project cache disabled, compiler instrumentation is nonzero.
bazel build //:pack //:publish --remote_cache= --disk_cache= --jobs=1 > "$TEST_TMPDIR/pack-publish-cold.log" 2>&1 || { cat "$TEST_TMPDIR/pack-publish-cold.log" >&2; exit 1; }
python3 - <<'TARGETS'
import json
from pathlib import Path
for target in ['pack','publish']:
    report=json.loads(Path('bazel-bin',target+'.graph/report.json').read_text())
    print('BUILD_SEED_TARGET_COLD',target,json.dumps(report))
    assert report['buildSeedHits']==0 and report['compilerTasks']==3,report
    assert {Path(path).stem:count for path,count in report['compilerProjects'].items()}=={'P0':1,'P1':1,'P2':1},report
    hook=Path('bazel-bin',target+'.graph/workspace/P2/obj/Release/net10.0/hooks.txt').read_text().splitlines()
    assert hook==['Build',target.capitalize()],hook
TARGETS
target_products > "$TEST_TMPDIR/cold-target-products.json"
cmp "$TEST_TMPDIR/seed-target-products.json" "$TEST_TMPDIR/cold-target-products.json"
changed_targets() {
    bazel build //:pack //:publish --remote_cache= --disk_cache= --jobs=1 \
        --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" --action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1 > "$TEST_TMPDIR/$1-targets.log" 2>&1 || { cat "$TEST_TMPDIR/$1-targets.log" >&2; return 1; }
    python3 - "$2" "$3" "$4" <<'TARGETS'
import json,sys
from pathlib import Path
for target in ['pack','publish']:
    report=json.loads(Path('bazel-bin',target+'.graph/report.json').read_text())
    print('BUILD_SEED_EDIT',target,json.dumps(report))
    assert (report['buildSeedHits'],report['buildSeedMisses'],report['compilerTasks'])==tuple(map(int,sys.argv[1:])),report
TARGETS
    "$sdk/dotnet" bazel-bin/publish.graph/workspace/P2/bin/Release/net10.0/publish/P2.dll > "$TEST_TMPDIR/$1-published.log"
    [[ $(cat "$TEST_TMPDIR/$1-published.log") == 2 ]]
    target_products > "$TEST_TMPDIR/$1-target-products.json"
}
sed -i 's/=> 1;/=> 2;/' P0/Code.cs
changed_targets body 2 1 1
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
changed_targets api 1 2 2
echo 'PASS: qualification Build snapshots feed Pack and Publish; hooks, compiler counts, products and edits match'
