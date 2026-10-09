#!/usr/bin/env bash
set -euo pipefail
metadata=()
for file in $RUNTIME_TEST_METADATA; do metadata+=("$(realpath "$file")"); done
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp MODULE.bazel original.module
cp BUILD.bazel original.build
mkdir -p archive/shared/Microsoft.NETCore.App/42.0.7
printf '#!/bin/sh\nexit 0\n' > archive/dotnet
chmod +x archive/dotnet
tar -czf runtime.tar.gz -C archive .
cp runtime.tar.gz good.tar.gz
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path.cwd()
files=[]
for rid in ['linux-arm64','linux-x64']:
    # Apphost packs share the RID and extension, but are not runtime archives.
    files.extend([
        {'rid':rid,'name':'dotnet-apphost-pack-'+rid+'.tar.gz','url':'file:///missing-apphost','hash':'bad'},
        {'rid':rid,'name':'dotnet-runtime-'+rid+'.tar.gz','url':(root/'runtime.tar.gz').as_uri(),'hash':hashlib.sha512((root/'runtime.tar.gz').read_bytes()).hexdigest()}
    ])
(root/'releases.json').write_text(json.dumps({'releases':[{'runtime':{'version':'42.0.7','files':files}}]}))
(root/'MODULE.bazel').write_text('''module(name="runtime_lock_fixture")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path="../msbuild-bazel")
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.runtime(name="supplied",version="42.0.7",platforms=["linux-arm64"],metadata_urls=['''+json.dumps((root/'releases.json').as_uri())+'''])
use_repo(dotnet,"supplied")
''')
PY
echo '' > BUILD.bazel
fresh() {
    local base="$1"; shift
    local cache=()
    if [[ -n "${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-}" ]]; then cache=(--repository_cache="$RULES_MSBUILD_TEST_REPOSITORY_CACHE"); fi
    for argument in "$@"; do
        if [[ "$argument" == --repository_cache=* ]]; then cache=(); fi
    done
    "$BIT_BAZEL_BINARY" --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$scratch/$base" "$@" "${cache[@]}"
}
query() { bazel query 'deps(@supplied//:runtime)'; }
expect_failure() {
    if "$@" > "$TEST_TMPDIR/failure.log" 2>&1; then
        cat "$TEST_TMPDIR/failure.log" >&2; echo 'Expected failure' >&2; exit 1
    fi
}
query
python3 - <<'PY'
import base64,hashlib,json
from pathlib import Path
lock=json.loads(Path('MODULE.bazel.lock').read_text())
facts=next(v['runtime-v1'] for v in lock['facts'].values() if 'runtime-v1' in v)
selection=next(iter(facts.values()))
assert selection['platforms']['linux-arm64']['integrity']=='sha512-'+base64.b64encode(hashlib.sha512(Path('runtime.tar.gz').read_bytes()).digest()).decode()
PY
sed -i 's/platforms=\["linux-arm64"\]/platforms=["linux-arm64","linux-x64"]/' MODULE.bazel
query
python3 - <<'PY'
import json
from pathlib import Path
facts=next(v['runtime-v1'] for v in json.loads(Path('MODULE.bazel.lock').read_text())['facts'].values() if 'runtime-v1' in v)
assert sorted(next(iter(facts.values()))['platforms'])==['linux-arm64','linux-x64']
PY
mv releases.json unavailable.json
fresh locked query 'deps(@supplied//:runtime)' --lockfile_mode=error
# Re-evaluation and extension changes retain the recorded runtime selection.
python3 - <<'PY'
from pathlib import Path
p=Path('MODULE.bazel');text=p.read_text();declaration=next(line for line in text.splitlines() if line.startswith('dotnet.runtime('))
p.write_text(text+declaration.replace('name="supplied"','name="second"')+'\nuse_repo(dotnet,"second")\n')
PY
bazel query 'deps(@second//:runtime)'
printf '\n# Force extension re-evaluation.\n' >> "$scratch/msbuild-bazel/msbuild/private/sdk_metadata.bzl"
query
sed -i 's/42.0.7/42.0.8/g' MODULE.bazel
expect_failure bazel query 'deps(@supplied//:runtime)' --lockfile_mode=error
assert_contains "$TEST_TMPDIR/failure.log" 'lockfile'
mv unavailable.json releases.json
expect_failure query
assert_contains "$TEST_TMPDIR/failure.log" 'Release metadata must identify exactly one runtime'
sed -i 's/42.0.8/42.0.7/g' MODULE.bazel
python3 - <<'PY'
import json
from pathlib import Path
p=Path('releases.json');data=json.loads(p.read_text());data['releases'][0]['runtime']['files'][1]['hash']='bad'
Path('bad-releases.json').write_text(json.dumps(data))
PY
sed -i 's@/releases.json@/bad-releases.json@g' MODULE.bazel
expect_failure query
assert_contains "$TEST_TMPDIR/failure.log" 'Release metadata runtime hash must be SHA-512 hex'
sed -i 's@/bad-releases.json@/releases.json@g' MODULE.bazel
query
printf corrupt > runtime.tar.gz
expect_failure fresh corrupt query 'deps(@supplied//:runtime)' --lockfile_mode=error --repository_cache="$scratch/empty-cache"
assert_contains "$TEST_TMPDIR/failure.log" 'Checksum'
cp good.tar.gz runtime.tar.gz
python3 - <<'PY'
import base64,hashlib,json
from pathlib import Path
p=Path('MODULE.bazel');archive=Path('runtime.tar.gz').resolve()
p.write_text(p.read_text()+'\ndotnet.runtime_archive(name="private_runtime",version="custom",platform="linux-arm64",urls=['+json.dumps(archive.as_uri())+'],integrity='+json.dumps('sha512-'+base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())+')\nuse_repo(dotnet,"private_runtime")\n')
PY
bazel query @private_runtime//:runtime
sed -i 's/platform="linux-arm64"/platform="unknown"/' MODULE.bazel
expect_failure bazel query @private_runtime//:runtime
assert_contains "$TEST_TMPDIR/failure.log" 'Unsupported runtime platform'
sed -i 's/platform="unknown"/platform="linux-arm64"/' MODULE.bazel
python3 - <<'PY'
import re
from pathlib import Path
p=Path('MODULE.bazel');p.write_text(re.sub(r'integrity="[^"]+"','integrity=""',p.read_text()))
PY
expect_failure bazel query @private_runtime//:runtime
assert_contains "$TEST_TMPDIR/failure.log" 'Runtime archives require integrity'

# Compile with SDK 9, selecting independently acquired execution runtimes.
cp original.module MODULE.bazel
cp original.build BUILD.bazel
python3 - "${metadata[@]}" <<'PY'
import json,sys
from pathlib import Path
p=Path('MODULE.bazel');text=p.read_text()
for name,file in zip(['older','patched','future'],sys.argv[1:],strict=True):
    target=Path(name+'-metadata.json');target.write_bytes(Path(file).read_bytes())
    version=json.loads(target.read_text())['releases'][0]['runtime']['version']
    text+='\ndotnet.runtime(name='+json.dumps(name)+',version='+json.dumps(version)+',platforms=["linux-arm64"],metadata_urls=['+json.dumps(target.resolve().as_uri())+'])\nuse_repo(dotnet,'+json.dumps(name)+')\n'
p.write_text(text)
p=Path('BUILD.bazel');text=p.read_text().replace('app_graph(name = "graph")','app_graph(name = "graph", linux_stable_paths = True)')
for name in ['older','patched','future']:
    text+='\nmsbuild_graph_binary(name='+json.dumps(name+'_app')+',graph=":graph",project="App/App.csproj",runtime_host="@'+name+'//:runtime")\n'
text+='\nmsbuild_graph_test(name="future_test",graph=":graph",project="App/App.csproj",runtime_host="@future//:runtime")\n'
p.write_text(text)
p=Path('App/Program.cs');p.write_text(p.read_text().replace('return Message.Text()', 'Console.WriteLine(System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription);\nreturn Message.Text()'))
p=Path('global.json');p.write_text(p.read_text().replace('10.0.400','9.0.318'))
for p in Path('.').glob('*/*.csproj'):
    p.write_text(p.read_text().replace('net10.0','net9.0'))
PY
options=(--remote_cache= --disk_cache=)
if [[ -n "${RUNTIME_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$RUNTIME_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
        --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$RUNTIME_CACHE_URL")
fi
bazel run //:sync
bazel run //:patched_app "${options[@]}" > "$TEST_TMPDIR/patched.log" 2>&1
assert_contains "$TEST_TMPDIR/patched.log" 'Hello from MSBuild and Bazel'
assert_contains "$TEST_TMPDIR/patched.log" '.NET 9.0.20'
assert_contains graph.generated.json '"SdkVersion": "9.0.318"'
expect_failure bazel run //:older_app "${options[@]}"
assert_contains "$TEST_TMPDIR/failure.log" 'You must install or update .NET'
expect_failure bazel run //:future_app "${options[@]}"
assert_contains "$TEST_TMPDIR/failure.log" 'You must install or update .NET'
# The app author explicitly permits a newer major host; the rules do not force it.
sed -i 's@<TargetFramework>@<RollForward>Major</RollForward><TargetFramework>@' App/App.csproj
bazel run //:sync
bazel run //:future_app "${options[@]}" > "$TEST_TMPDIR/future.log" 2>&1
assert_contains "$TEST_TMPDIR/future.log" '.NET 10.0.12'
bazel test //:future_test "${options[@]}" --test_output=errors
cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/seed-report.json"
products() { (cd bazel-bin/graph.graph/workspace; find App/bin Library/bin Tests/bin -type f -print0 | sort -z | xargs -0 sha256sum); }
products > "$TEST_TMPDIR/seed.sha256"
bazel shutdown
rm older-metadata.json patched-metadata.json future-metadata.json
fresh recovered test //:future_test "${options[@]}" --lockfile_mode=error --test_output=errors --execution_log_json_file="$TEST_TMPDIR/recovered.execution.json"
products > "$TEST_TMPDIR/recovered.sha256"
cmp "$TEST_TMPDIR/seed.sha256" "$TEST_TMPDIR/recovered.sha256"
if [[ -n "${RUNTIME_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovered.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
fi
case "$("$BIT_BAZEL_BINARY" --version)" in
    'bazel 9.3.'*)
        printf 'block .*\n' > "$scratch/downloader.config"
        fresh blocked query 'deps(@older//:runtime) + deps(@patched//:runtime) + deps(@future//:runtime)' \
            --lockfile_mode=error --downloader_config="$scratch/downloader.config"
        ;;
esac
echo 'PASS: runtime metadata, lock facts, private archives, SDK/runtime separation, roll-forward and fresh-cache recovery'
