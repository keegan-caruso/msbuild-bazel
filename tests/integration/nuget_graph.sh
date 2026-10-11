#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mv BUILD.template BUILD.bazel
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text());ids={(p['id'],p['version']) for p in m['packages']}
assert {('Newtonsoft.Json','12.0.3'),('Newtonsoft.Json','13.0.3'),('Microsoft.CodeAnalysis.NetAnalyzers','9.0.0'),('Microsoft.Extensions.Options','10.0.0')} <= ids
lock=json.loads(Path('Library/packages.lock.json').read_text())['dependencies']
assert lock['.NETStandard,Version=v2.1']['Newtonsoft.Json']['resolved']=='12.0.3'
assert lock['net10.0']['Newtonsoft.Json']['resolved']=='13.0.3'
app=json.loads(Path('App/packages.lock.json').read_text())['dependencies']['net10.0']
assert app['Microsoft.Extensions.Options']['type']=='Transitive'
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nnuget = use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")\nnuget.lock(name = "nuget", lockfile = "//:nuget.lock.json")\nuse_repo(nuget, "nuget")\n')
Path('mappings.json').write_text('{"projectDefaults":{"referenceBoundary":true}}\n')
p=Path('BUILD.bazel');p.write_text(p.read_text()+'\nload("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nmsbuild_sync(name="sync", projects=["App/App.csproj", "Library/Library.csproj"], package_lock="@nuget//:packages", package_build=True, package_inputs=["Library/.editorconfig"], resolve_references=True, mappings="mappings.json")\n')
PY
bazel run //:sync
cat >> BUILD.bazel <<'BZL'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
app_graph(name="build")
msbuild_graph_test(name="test", graph=":build", project="App/App.csproj")
BZL
options=(--disk_cache= --remote_cache=)
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$SDK_WEB_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_WEB_CACHE_URL")
fi
bazel test //:test "${options[@]}" --test_output=all > "$TEST_TMPDIR/graph.log" 2>&1 || { cat "$TEST_TMPDIR/graph.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/graph.log" 'PASS: central versions, transitive Options'
[[ -f bazel-bin/build.graph/workspace/Library/bin/Release/netstandard2.1/Library.dll ]]
[[ -f bazel-bin/build.graph/workspace/Library/bin/Release/net10.0/Library.dll ]]
# The package analyzer is a declared compiler input. Exercise its diagnostic.
python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('graph.generated.json').read_text())
assert 'Directory.Packages.props' in c['DefinitionDigests']
p=Path('Library/Library.cs');p.write_text(p.read_text().replace('    public static string Value()', '    public string BadAnalyzerMember() => "bad";\n    public static string Value()'))
PY
if bazel build //:build "${options[@]}" > "$TEST_TMPDIR/analyzer.log" 2>&1; then echo 'Analyzer failed to reject CA1822' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/analyzer.log" 'CA1822'
python3 - <<'PY'
from pathlib import Path
p=Path('Library/Library.cs');p.write_text(p.read_text().replace('    public string BadAnalyzerMember() => "bad";\n',''))
PY
bazel test //:test "${options[@]}" --test_output=errors
bazel run //:sync -- --check
# Independent source/output base: no NuGet resolution or metadata is permitted.
bazel shutdown
mkdir "$scratch/recovery"
tar -cf "$scratch/consumer.tar" App Library Directory.Packages.props MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json NuGet.Config mappings.json nuget.lock.json graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/recovery"
cd "$scratch/recovery"
"$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/recovered" test //:test "${options[@]}" \
    --lockfile_mode=error --repository_disable_download --test_output=all \
    --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}" \
    --execution_log_json_file="$TEST_TMPDIR/recovery.execution.json" > "$TEST_TMPDIR/recovery.log" 2>&1 || { cat "$TEST_TMPDIR/recovery.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/recovery.log" 'PASS: central versions, transitive Options'
if [[ -n "${SDK_WEB_CACHE_URL:-}" ]]; then
    python3 - "$TEST_TMPDIR/recovery.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();graphs=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraph':graphs.append(action)
assert len(graphs)==1 and graphs[0].get('cacheHit') and graphs[0].get('runner')=='remote cache hit',graphs
PY
fi
echo "PASS: $SDK_TEST_RID central/transitive packages, multi-TFM/version builds, analyzer diagnostics and strict independent recovery"
