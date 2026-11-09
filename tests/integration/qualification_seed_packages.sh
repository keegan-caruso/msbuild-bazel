#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
: "${QUALIFICATION_CACHE_URL:?Set an HTTP AC/CAS endpoint}"
printf '<!-- Package SDK seed: %s -->\n' "${scratch##*/}" >> Directory.Build.props
cp BUILD.bazel.in BUILD.bazel
python3 - <<'PY'
from pathlib import Path
p=Path('BUILD.bazel')
p.write_text(p.read_text().replace('package_build = True,', 'package_build = True, resolve_references = True, qualification_cache = True, seed_build_cache = True, srcs = glob(["**"], exclude=["BUILD.bazel", "MODULE.bazel", "MODULE.bazel.lock", "graph.generated.*", "bazel-*/**", "**/bin/**", "**/obj/**", "Utility/out/**"]),'))
PY
bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/package-seed.log" 2>&1 || { cat "$TEST_TMPDIR/package-seed.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/package-seed.log" 'GRAPH_CACHE_SEED {"seeded":2,'
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output")
app_graph(name="graph",linux_stable_paths=True)
msbuild_graph_output(name="proof",graph=":graph",path="Consumer/bin/Release/net10.0/proof.txt")
BUILD
build() {
    local options=()
    if [[ $1 == seeded ]]; then options+=(--action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL"); fi
    bazel build //:proof --remote_cache= --disk_cache= "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; return 1; }
    [[ $(head -1 bazel-bin/proof/proof.txt) == 42 ]]
    python3 - "$2" "$3" <<'PY'
import json,sys
from pathlib import Path
r=json.loads(Path('bazel-bin/graph.graph/report.json').read_text())
assert (r['hits'],r['misses'])==tuple(map(int,sys.argv[1:])),r
PY
}
products() {
    (cd bazel-bin/graph.graph/workspace
     find Library/bin Consumer/bin Utility/out -type f -print0 | sort -z | xargs -0 sha256sum)
}
# The two assemblies recover; the NoTargets producer executes its declared work.
build seeded 2 1
products > "$TEST_TMPDIR/package-seeded.sha256"
build uncached 0 3
products > "$TEST_TMPDIR/package-uncached.sha256"
cmp "$TEST_TMPDIR/package-seeded.sha256" "$TEST_TMPDIR/package-uncached.sha256"
echo 'PASS: Traversal/NoTargets SDK archives retain data modes; compilation seeds recover and NoTargets products match uncached Build'
