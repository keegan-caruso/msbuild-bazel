#!/usr/bin/env bash
# Batch configured SDK output directories without changing their contents.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_layout", "msbuild_graph_layouts", "msbuild_layout")
app_graph(name="graph")
msbuild_graph_layout(name="p0",graph=":graph",project="P0/P0.csproj",framework="net10.0")
msbuild_graph_layout(name="p1",graph=":graph",project="P1/P1.csproj",framework="net10.0")
msbuild_graph_layout(name="p2",graph=":graph",project="P2/P2.csproj",framework="net10.0")
msbuild_layout(name="legacy",paths={":p0":"lib",":p1":"lib",":p2":"app"})
msbuild_graph_layouts(name="batch",graph=":graph",projects={
    "P0/P0.csproj|net10.0":"lib",
    "P1/P1.csproj|net10.0":"lib",
    "P2/P2.csproj|net10.0":"app",
})
BUILD
compare() {
    bazel build //:batch //:legacy --disk_cache= --remote_cache=
    python3 - <<'PY'
import hashlib
from pathlib import Path
def files(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode & 0o777)
        for p in root.rglob('*') if p.is_file()}
actual, expected = files(Path('bazel-bin/batch.layout')), files(Path('bazel-bin/legacy.layout'))
assert actual == expected and 'lib/P0.dll' in actual and 'app/P2.dll' in actual
print('PASS: batched layout matches all legacy files and modes, including shared dependencies')
PY
}
compare
python3 - <<'PY'
from pathlib import Path
p=Path('P0/Code.cs'); text=p.read_text(); assert text.count('=> 1;')==1
p.write_text(text.replace('=> 1;', '=> 7;'))
PY
compare
# One batch action selects all three projects; filegroup expansion creates no
# extra per-project extraction actions in this dependency closure.
bazel aquery 'mnemonic("MSBuildGraphLayout", //:batch)' --output=text > "$TEST_TMPDIR/actions.log"
[[ $(grep -c 'Mnemonic: MSBuildGraphLayout' "$TEST_TMPDIR/actions.log") == 1 ]]
echo 'PASS: one graph-layout action on the current Bazel pin'
