#!/usr/bin/env bash
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
python3 - <<'PY'
from pathlib import Path
import uuid,json
p=Path('mappings.json');data=json.loads(p.read_text());data['projectDefaults']['preparedRestore']=True;p.write_text(json.dumps(data))
p=Path('Directory.Build.props');p.write_text(p.read_text().replace('</PropertyGroup>',
    '<PathMap>/__rules_msbuild_graph/output/workspace=/_/workspace,/__rules_msbuild_graph/sdk=/_/sdk</PathMap>'
    '<QualificationNonce>'+uuid.uuid4().hex+'</QualificationNonce></PropertyGroup>'))
p=Path('BUILD.bazel');p.write_text(p.read_text().replace('app_graph(name = "build")',
    'app_graph(name = "build", linux_stable_paths = True, linux_worker = True)').replace(
    'name = "publish",','name = "publish", linux_stable_paths = True, linux_worker = True,'))
PY
cp -a "$scratch/consumer" "$scratch/authored"
bazel build @dotnet//:files @newtonsoft//file @humanizer//file
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
mkdir "$scratch/feed"
bazel cquery 'set(@newtonsoft//file @humanizer//file)' --output=files > "$TEST_TMPDIR/packages.paths" 2> "$TEST_TMPDIR/packages-query.log"
while read -r archive; do cp "$execroot/$archive" "$scratch/feed/"; done < "$TEST_TMPDIR/packages.paths"
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --remote_cache= --disk_cache=)
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$SDK_WEB_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
        --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_WEB_CACHE_URL")
fi
bazel run //:sync
bazel run //:sync -- --check
# Retain the privately generated fixture contract for diagnostics.
cp graph.generated.json graph.generated.bzl "$TEST_TMPDIR/"
run() {
    bazel run "//:$1" "${options[@]}" --execution_log_json_file="$TEST_TMPDIR/$2.execution.json" -- --smoke > "$TEST_TMPDIR/$2.log" 2>&1 || { cat "$TEST_TMPDIR/$2.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$2.log" "HTTP: $3"
    assert_contains "$TEST_TMPDIR/$2.log" 'ARCH: Arm64'
}
run app seed warehouse-v1
bazel test //:tests //:web_test "${options[@]}" --test_output=all > "$TEST_TMPDIR/seed-test.log" 2>&1
assert_contains "$TEST_TMPDIR/seed-test.log" 'UNIT: warehouse-v1'
products() { (cd "$1/Web/bin/Release/net10.0/publish"; find . -type f -print0 | sort -z | xargs -0 sha256sum); }
run published_app publish warehouse-v1
bazel test //:published_test "${options[@]}" --test_output=errors
products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/publish.sha256"
for mode in ordinary graph; do
    cp -a "$scratch/authored" "$scratch/raw-$mode"
    mkdir "$scratch/raw-$mode-scratch" "$scratch/raw-$mode/.package-source"
    cp "$scratch/feed/"* "$scratch/raw-$mode/.package-source/"
    graph=(); if [[ "$mode" == graph ]]; then graph=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-$mode" "$scratch/raw-$mode-scratch" msbuild Web/Web.csproj -restore -t:Publish -m:4 "${graph[@]}" -p:Configuration=Release -p:UseSharedCompilation=false -p:RestoreSources=/__rules_msbuild_graph/output/workspace/.package-source > "$TEST_TMPDIR/raw-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$mode.log" >&2; exit 1; }
    products "$scratch/raw-$mode" > "$TEST_TMPDIR/raw-$mode.sha256"
    cp "$scratch/raw-$mode/Web/bin/Release/net10.0/publish/Web.staticwebassets.endpoints.json" "$TEST_TMPDIR/raw-$mode.endpoints.json"
done
cp bazel-bin/publish.graph/workspace/Web/bin/Release/net10.0/publish/Web.staticwebassets.endpoints.json "$TEST_TMPDIR/graph.endpoints.json"
for mode in raw-ordinary raw-graph publish; do
    grep -v '  ./Web.staticwebassets.endpoints.json$' "$TEST_TMPDIR/$mode.sha256" > "$TEST_TMPDIR/$mode.stable.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.stable.sha256" "$TEST_TMPDIR/raw-graph.stable.sha256"
cmp "$TEST_TMPDIR/raw-graph.stable.sha256" "$TEST_TMPDIR/publish.stable.sha256"
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from email.utils import parsedate_to_datetime
from pathlib import Path
def manifest(name):
    data=json.loads(Path(sys.argv[1],name+'.endpoints.json').read_text());count=0
    for endpoint in data['Endpoints']:
        for header in endpoint['ResponseHeaders']:
            if header['Name']=='Last-Modified':
                assert parsedate_to_datetime(header['Value']).tzinfo is not None
                header['Value']='<timestamp>';count+=1
    assert count>0
    return data
assert manifest('raw-ordinary')==manifest('raw-graph')==manifest('graph')
PY
reference=bazel-bin/build.graph/workspace/Data/obj/Release/net10.0/ref/Data.dll
sha256sum "$reference" > "$TEST_TMPDIR/reference.sha256"
sed -i 's/warehouse-v1/warehouse-v2/' Data/CatalogStore.cs
run app body warehouse-v2
sha256sum -c "$TEST_TMPDIR/reference.sha256"
python3 - "$TEST_TMPDIR/body.execution.json" <<'PY'
import json,sys
from pathlib import Path
report=json.loads(Path('bazel-bin/build.graph/report.json').read_text());assert (report['hits'],report['misses'])==(4,1),report
s=Path(sys.argv[1]).read_text();decoder=json.JSONDecoder()
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    assert action.get('mnemonic')!='MSBuildGraphRestore',action
PY
bazel test //:tests //:web_test "${options[@]}" --test_output=all > "$TEST_TMPDIR/body-test.log" 2>&1
assert_contains "$TEST_TMPDIR/body-test.log" 'UNIT: warehouse-v2'
sed -i '/public static string Revision()/a\    public static int ApiVersion() => 2;' Data/CatalogStore.cs
run app api warehouse-v2
if sha256sum -c "$TEST_TMPDIR/reference.sha256" >/dev/null 2>&1; then echo 'API edit left reference bytes unchanged' >&2; exit 1; fi
python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('bazel-bin/build.graph/report.json').read_text());assert report['misses']>1 and report['hits']>=1,report
print('API cache:',report['hits'],report['misses'])
PY
bazel test //:tests //:web_test "${options[@]}" --test_output=all > "$TEST_TMPDIR/api-test.log" 2>&1
assert_contains "$TEST_TMPDIR/api-test.log" 'UNIT: warehouse-v2'
run published_app edited-publish warehouse-v2
products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/edited.sha256"
bazel shutdown
mkdir "$scratch/recovery"
tar -cf "$scratch/consumer.tar" Domain Data Services Web Tests MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json NuGet.Config Directory.Build.props mappings.json packages.bzl graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/recovery"
cd "$scratch/recovery"
fresh() {
    "$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/$1" "${@:2}" \
        --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}"
}
fresh recovered test //:published_test "${options[@]}" --lockfile_mode=error --test_output=all --execution_log_json_file="$TEST_TMPDIR/recovered.execution.json"
fresh recovered run //:published_app "${options[@]}" --lockfile_mode=error --run_under='env -u RUNFILES_DIR -u RUNFILES_MANIFEST_FILE -u TEST_SRCDIR' -- --smoke > "$TEST_TMPDIR/recovered-app.log" 2>&1 || { cat "$TEST_TMPDIR/recovered-app.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/recovered-app.log" 'HTTP: warehouse-v2'
products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/recovered.sha256"
cmp "$TEST_TMPDIR/edited.sha256" "$TEST_TMPDIR/recovered.sha256"
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovered.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
    fresh project-recovery test //:published_test "${options[@]}" --noremote_accept_cached --remote_upload_local_results=false --lockfile_mode=error --test_output=all
    python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('bazel-bin/publish.graph/report.json').read_text());assert (report['hits'],report['misses'])==(5,0),report
PY
    products bazel-bin/publish.graph/workspace > "$TEST_TMPDIR/project-recovery.sha256"
    cmp "$TEST_TMPDIR/edited.sha256" "$TEST_TMPDIR/project-recovery.sha256"
fi
echo 'PASS: five-project SDK-only catalog, packages, raw Publish parity, body/API edits, test invalidation and HTTP recovery'
