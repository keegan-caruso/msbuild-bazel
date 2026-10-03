#!/usr/bin/env bash
# Sourced after edit controls. SDK defaults remain authored; Pack declares its files.
python3 - <<'PY'
import json
from pathlib import Path
p=Path('mappings.json');m=json.loads(p.read_text())
m['projectDefaults']['outputFiles']=['$(MSBuildProjectDirectory)/bin/$(Configuration)/$(AssemblyName).1.0.0.nupkg']
p.write_text(json.dumps(m)+'\n')
PY
sync_graph pack
sed -i 's/linux_worker=True)/linux_worker=True, target="Pack")/' BUILD.bazel
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/pack.log" 2>&1 || { cat "$TEST_TMPDIR/pack.log" >&2; exit 1; }
assert_contains "$report" '"misses":3'
# Raw graph Pack uses the same restored inputs and namespace as the compilation control.
cp src/Library/Code.cs "$scratch/raw/graph/src/Library/Code.cs"
bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw/graph" "$scratch/raw/graph-scratch" \
    msbuild dirs.proj -graphBuild -t:Pack -m:4 -p:Configuration=Release -p:UseSharedCompilation=false \
    -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' \
    > "$TEST_TMPDIR/pack-raw.log" 2>&1 || { cat "$TEST_TMPDIR/pack-raw.log" >&2; exit 1; }
python3 - "$scratch/raw/graph" <<'PY'
import hashlib,sys,zipfile
from pathlib import Path
raw=Path(sys.argv[1]);graph=Path('bazel-bin/graph.graph/workspace')
for p in ['src/Library','src/App','tests/Tests']:
    name=p.rsplit('/',1)[-1]+'.1.0.0.nupkg'
    def payload(root):
        with zipfile.ZipFile(root/p/'bin/Release'/name) as z:
            return {n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                    if n.endswith('.nuspec') or n.startswith('lib/')}
    assert payload(raw)==payload(graph),name
PY
cat >> BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output")
msbuild_graph_output(name="library_package", graph=":graph", path="src/Library/bin/Release/Library.1.0.0.nupkg")
BUILD
bazel build //:library_package "${options[@]}" > "$TEST_TMPDIR/pack-export.log" 2>&1
# Pack snapshots restore package bytes without compiling/repacking.
sed -i 's/target="Pack"/target="Pack", profile_build=True/' BUILD.bazel
bazel build //:library_package "${options[@]}" > "$TEST_TMPDIR/pack-replay.log" 2>&1 || { cat "$TEST_TMPDIR/pack-replay.log" >&2; exit 1; }
assert_contains "$report" '"hits":3'
read_compilation bazel-bin/graph.graph/report.binlog > "$TEST_TMPDIR/pack-replay-compiled.json"
assert_contains "$TEST_TMPDIR/pack-replay-compiled.json" '[]'
# Return to ordinary output ownership and publish/run/test the children.
cp "$scratch/mappings.json" mappings.json
sync_graph publish
sed -i 's/target="Pack", profile_build=True/target="Publish"/' BUILD.bazel
run_app publish 1
bazel test //:tests "${options[@]}" --nocache_test_results --test_output=errors > "$TEST_TMPDIR/publish-tests.log" 2>&1
printf 'public class Library { public static int Value() => 1; }\n' > "$scratch/raw/graph/src/Library/Code.cs"
bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw/graph" "$scratch/raw/graph-scratch" \
    msbuild dirs.proj -graphBuild -t:Publish -m:4 -p:Configuration=Release -p:UseSharedCompilation=false \
    -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' \
    > "$TEST_TMPDIR/publish-raw.log" 2>&1 || { cat "$TEST_TMPDIR/publish-raw.log" >&2; exit 1; }
(cd "$scratch/raw/graph"; find . -path '*/publish/*' -type f -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/publish-raw.sha256"
(cd bazel-bin/graph.graph/workspace; find . -path '*/publish/*' -type f -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/publish-graph.sha256"
cmp "$TEST_TMPDIR/publish-raw.sha256" "$TEST_TMPDIR/publish-graph.sha256"
# Also verify an uncached worker publishes the same products.
sed -i 's/target="Publish"/target="Publish", worker_cache_mb=0/' BUILD.bazel
run_app publish-uncached 1
assert_contains "$report" '"misses":3'
(cd bazel-bin/graph.graph/workspace; find . -path '*/publish/*' -type f -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/publish-uncached.sha256"
cmp "$TEST_TMPDIR/publish-graph.sha256" "$TEST_TMPDIR/publish-uncached.sha256"
echo 'PASS: traversal Pack payload/export/replay and Publish raw parity/run/test/uncached worker'
