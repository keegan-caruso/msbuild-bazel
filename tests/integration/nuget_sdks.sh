#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# Start with no handwritten package repositories or package inventory.
python3 - <<'PY'
import json,uuid
from pathlib import Path
# Keep this control's cache namespace fresh across repeated/pin-specific runs.
p=Path('mappings.json');m=json.loads(p.read_text());m['projectDefaults']['properties']={'QualificationIdentity':uuid.uuid4().hex};p.write_text(json.dumps(m))
p=Path('global.json');g=json.loads(p.read_text());g['msbuild-sdks']['RulesMSBuild.Unused.Sdk']='99.0.0';p.write_text(json.dumps(g))
p=Path('MODULE.bazel');p.write_text(p.read_text().split('http_file =')[0])
p=Path('Directory.Build.props');p.write_text(p.read_text().replace('<RestoreSources>$(MSBuildThisFileDirectory).package-source</RestoreSources>','').replace('<RestorePackagesPath>$(MSBuildThisFileDirectory).nuget</RestorePackagesPath>',''))
Path('BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")\nmsbuild_nuget_update(name="update_packages", projects=["dirs.proj"])\n')
Path('NuGet.Config').write_text('<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
for project,version in [('Library/Library.csproj','12.0.3'),('Consumer/Consumer.csproj','13.0.3')]:
    p=Path(project);p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="'+version+'" /></ItemGroup></Project>'))
PY
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text());ids={(p['id'],p['version']) for p in m['packages']}
assert {('Microsoft.Build.Traversal','4.1.82'),('Microsoft.Build.NoTargets','3.7.0'),('Newtonsoft.Json','12.0.3'),('Newtonsoft.Json','13.0.3')} <= ids,ids
assert 'Library/packages.lock.json' in m['lockFiles']
assert not any(p['id']=='RulesMSBuild.Unused.Sdk' for p in m['packages'])
assert 'packages.lock.json' in m['lockFiles'], 'The coordinator native lock must also be committed'
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nnuget=use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")\nnuget.lock(name="nuget", lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
p=Path('BUILD.bazel');p.write_text(p.read_text()+'\nload("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nmsbuild_sync(name="sync", projects=["dirs.proj"], package_lock="@nuget//:packages", package_build=True, mappings="mappings.json")\n')
PY
bazel run //:sync
bazel run //:sync -- --check
cat >> BUILD.bazel <<'BZL'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_output(name="proof", graph=":graph", path="Utility/out/proof.txt")
BZL
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$SDK_WEB_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_WEB_CACHE_URL")
fi
bazel build //:proof "${options[@]}"
[[ "$(head -1 bazel-bin/graph.graph/workspace/Utility/out/proof.txt)" == 42 ]]
cmp bazel-bin/graph.graph/workspace/Utility/out/proof.txt bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt
# Both package versions are available, so only native locked mode can reject drift.
cp graph.generated.json "$TEST_TMPDIR/contract.before"
sed -i 's/12.0.3/13.0.3/' Library/Library.csproj
if bazel run //:sync > "$TEST_TMPDIR/stale-child.log" 2>&1; then echo 'Traversal silently rewrote a child native lock' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/stale-child.log" 'NU1004'
cmp graph.generated.json "$TEST_TMPDIR/contract.before"
sed -i 's/13.0.3/12.0.3/' Library/Library.csproj
# A successful but nonrecursive Restore is not a complete graph inventory.
cp Directory.Build.props "$TEST_TMPDIR/props.before"
cp nuget.lock.json "$TEST_TMPDIR/incomplete-manifest.before"
sed -i 's#</PropertyGroup>#<RestoreRecursive>false</RestoreRecursive></PropertyGroup>#' Directory.Build.props
if bazel run //:update_packages > "$TEST_TMPDIR/incomplete-restore.log" 2>&1; then echo 'Published incomplete Restore graph' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/incomplete-restore.log" 'existing locks were left unchanged'
cmp nuget.lock.json "$TEST_TMPDIR/incomplete-manifest.before"
cp "$TEST_TMPDIR/props.before" Directory.Build.props
# Used SDKs must remain explicit even after a warm resolver/build.
cp global.json "$TEST_TMPDIR/global.before"
sed -i 's/3.7.0/99.0.0/' global.json
if bazel run //:sync > "$TEST_TMPDIR/missing-sdk.log" 2>&1; then echo 'Used undeclared SDK from host state' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/missing-sdk.log" 'Microsoft.Build.NoTargets'
cp nuget.lock.json "$TEST_TMPDIR/sdk-manifest.before"
if bazel run //:update_packages > "$TEST_TMPDIR/missing-sdk-update.log" 2>&1; then echo 'Resolved nonexistent SDK' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/missing-sdk-update.log" 'existing locks were left unchanged'
cmp nuget.lock.json "$TEST_TMPDIR/sdk-manifest.before"
cmp graph.generated.json "$TEST_TMPDIR/contract.before"
cp "$TEST_TMPDIR/global.before" global.json
# A real SDK version change is resolved explicitly and changes the graph package key.
sed -i 's/3.7.0/3.7.56/' global.json Empty/Empty.csproj
if bazel run //:update_packages > "$TEST_TMPDIR/sdk-update.log" 2>&1; then :; else cat "$TEST_TMPDIR/sdk-update.log" >&2; exit 1; fi
bazel run //:update_packages -- --check
bazel run //:sync
bazel run //:sync -- --check
bazel build //:proof "${options[@]}"
python3 - "$TEST_TMPDIR/contract.before" <<'PY'
import json,sys
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text());ids={(p['id'],p['version']) for p in m['packages']}
assert ('Microsoft.Build.NoTargets','3.7.56') in ids and ('Microsoft.Build.NoTargets','3.7.0') not in ids
before=json.loads(Path(sys.argv[1]).read_text());after=json.loads(Path('graph.generated.json').read_text())
assert before['PackageDigests']!=after['PackageDigests']
r=json.loads(Path('bazel-bin/graph.graph/report.json').read_text());assert r['misses']==3 and r['hits']==0,r
PY
# Independent strict-lock consumer: no resolver downloads, recovered products match.
(cd bazel-bin/graph.graph/workspace; find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/products.before"
bazel shutdown
mkdir "$scratch/recovery"
tar -cf "$scratch/consumer.tar" Library Consumer Utility Empty dirs.proj Directory.Build.props global.json MODULE.bazel MODULE.bazel.lock BUILD.bazel NuGet.Config mappings.json packages.lock.json nuget.lock.json graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/recovery"
cd "$scratch/recovery"
"$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/recovered" build //:proof "${options[@]}" \
    --lockfile_mode=error --repository_disable_download \
    --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}" \
    --execution_log_json_file="$TEST_TMPDIR/recovery.execution.json" > "$TEST_TMPDIR/recovery.log" 2>&1 || { cat "$TEST_TMPDIR/recovery.log" >&2; exit 1; }
(cd bazel-bin/graph.graph/workspace; find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/products.after"
cmp "$TEST_TMPDIR/products.before" "$TEST_TMPDIR/products.after"
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovery.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();actions=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic') in ['MSBuildGraph','MSBuildGraphRestore']:actions.append(action)
assert len(actions)==2 and all(a.get('cacheHit') and a.get('runner')=='remote cache hit' for a in actions),actions
PY
fi
echo 'PASS: generated Traversal/NoTargets inventories, locked children, SDK version invalidation and independent offline recovery'
