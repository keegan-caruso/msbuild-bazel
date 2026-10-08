#!/usr/bin/env bash
set -euo pipefail
metadata=()
for file in $SDK_VERSION_METADATA; do metadata+=("$(realpath "$file")"); done
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp -R "$scratch/consumer" "$scratch/template"
consumer="$scratch/consumer"
original_scratch="$scratch"
cleanup_versions() {
    if [[ "$scratch" != "$original_scratch" ]]; then bazel shutdown >/dev/null 2>&1 || true; fi
    rm -rf "$original_scratch"
}
trap cleanup_versions EXIT
for file in "${metadata[@]}"; do
    read -r version framework < <(python3 - "$file" <<'PY'
import json,sys
sdk=json.load(open(sys.argv[1]))['releases'][0]['sdk']
print(sdk['version'], 'net'+'.'.join(sdk['runtime-version'].split('.')[:2]))
PY
    )
    echo "SDK: $version ($framework)"
    cd "$original_scratch"
    rm -rf "$consumer"
    cp -R template consumer
    cd "$consumer"
    cp "$file" sdk-metadata.json
    export SDK_TEST_VERSION="$version" SDK_TEST_FRAMEWORK="$framework"
    python3 - <<'PY'
import json, os
from pathlib import Path
Path('global.json').write_text(json.dumps({'sdk':{'version':os.environ['SDK_TEST_VERSION'],'rollForward':'disable'}}))
for p in Path('.').glob('*/*.csproj'):
    p.write_text(p.read_text().replace('net10.0',os.environ['SDK_TEST_FRAMEWORK']))
p=Path('MODULE.bazel');p.write_text(p.read_text().replace('global_json = "//:global.json",','global_json = "//:global.json", platforms = ["linux-arm64"], metadata_urls = ['+json.dumps(Path('sdk-metadata.json').resolve().as_uri())+'],') )
Path('BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
exports_files(["global.json"])
msbuild_sync(name="sync", projects=["App/App.csproj", "Tests/Tests.csproj"])
''')
PY
    scratch="$original_scratch/$version-seed"
    mkdir -p "$scratch"
    bazel run //:sync
    cp "$original_scratch/template/BUILD.bazel" BUILD.bazel
    sed -i 's/app_graph(name = "graph")/app_graph(name = "graph", linux_stable_paths = True)/' BUILD.bazel
    options=(--remote_cache= --disk_cache=)
    if [[ -n "${SDK_VERSION_CACHE_URL:-}" ]]; then
        options+=(--remote_cache="$SDK_VERSION_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
            --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_VERSION_CACHE_URL")
    fi
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$version-app.log" 2>&1 || { cat "$TEST_TMPDIR/$version-app.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$version-app.log" 'Hello from MSBuild and Bazel'
    bazel test //:tests "${options[@]}" --test_output=errors
    bazel run //:sync -- --check
    # The adapters themselves must use the selected SDK's framework and engine.
    python3 - "$framework" "$version" <<'PY'
import json, sys
from pathlib import Path
framework,version=sys.argv[1:]
runner=next(Path('bazel-out').glob('*/bin/graph_runner.runner/GraphBuild.runtimeconfig.json')).parent
for name,p in [('ProjectSync',Path('bazel-bin/sync.project-sync')),('GraphBuild',runner)]:
    assert json.loads((p/(name+'.runtimeconfig.json')).read_text())['runtimeOptions']['tfm']==framework
    deps=json.loads((p/(name+'.deps.json')).read_text())
    assert any(k.startswith('Microsoft.Build/') for k in deps['libraries']),deps
assert json.loads(Path('graph.generated.json').read_text())['SdkVersion']==version
PY
    products() { (cd bazel-bin/graph.graph/workspace; find App/bin Library/bin Tests/bin -type f -print0 | sort -z | xargs -0 sha256sum); }
    products > "$TEST_TMPDIR/$version-seed.sha256"
    ref="bazel-bin/graph.graph/workspace/Library/obj/Release/$framework/ref/Library.dll"
    sha256sum "$ref" | cut -d' ' -f1 > "$TEST_TMPDIR/$version-ref.sha256"
    # A method body edit changes implementation bytes while preserving the API.
    sed -i 's/=> "Hello from MSBuild and Bazel";/=> string.Concat("Hello from ", "MSBuild and Bazel");/' Library/Message.cs
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$version-body.log" 2>&1 || { cat "$TEST_TMPDIR/$version-body.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$version-body.log" 'Hello from MSBuild and Bazel'
    products > "$TEST_TMPDIR/$version-body.sha256"
    ! cmp -s "$TEST_TMPDIR/$version-seed.sha256" "$TEST_TMPDIR/$version-body.sha256"
    [[ "$(sha256sum "$ref" | cut -d' ' -f1)" == "$(cat "$TEST_TMPDIR/$version-ref.sha256")" ]]
    # An additive API edit must invalidate the reference assembly.
    sed -i '/public static string Text()/a\    public static int Added() => 42;' Library/Message.cs
    bazel test //:tests "${options[@]}" --test_output=errors
    [[ "$(sha256sum "$ref" | cut -d' ' -f1)" != "$(cat "$TEST_TMPDIR/$version-ref.sha256")" ]]
    products > "$TEST_TMPDIR/$version-api.sha256"
    bazel shutdown
    # A new output base uses native SDK facts with metadata unavailable.
    rm sdk-metadata.json
    scratch="$original_scratch/$version-recovery"
    mkdir -p "$scratch"
    bazel test //:tests "${options[@]}" --lockfile_mode=error --test_output=errors \
        --execution_log_json_file="$TEST_TMPDIR/$version-recovery.execution.json"
    if [[ -n "${SDK_VERSION_CACHE_URL:-}" ]]; then
        python3 - "$TEST_TMPDIR/$version-recovery.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
    fi
    products > "$TEST_TMPDIR/$version-recovery.sha256"
    cmp "$TEST_TMPDIR/$version-api.sha256" "$TEST_TMPDIR/$version-recovery.sha256"
    if [[ -n "${SDK_VERSION_CACHE_URL:-}" ]]; then
        # Force graph execution in another base to exercise the project plugin too.
        bazel shutdown
        scratch="$original_scratch/$version-project-recovery"
        mkdir -p "$scratch"
        bazel test //:tests "${options[@]}" --noremote_accept_cached --remote_upload_local_results=false \
            --lockfile_mode=error --test_output=errors
        python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('bazel-bin/graph.graph/report.json').read_text())
assert (report['hits'],report['misses'])==(3,0),report
PY
        products > "$TEST_TMPDIR/$version-project-recovery.sha256"
        cmp "$TEST_TMPDIR/$version-api.sha256" "$TEST_TMPDIR/$version-project-recovery.sha256"
    fi
    bazel shutdown
    scratch="$original_scratch"
    rm -rf "$original_scratch/$version-seed" "$original_scratch/$version-recovery" "$original_scratch/$version-project-recovery"
    echo "PASS: $version sync, adapters, app/test, body/API and fresh-cache recovery"
done
