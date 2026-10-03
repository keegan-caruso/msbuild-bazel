#!/usr/bin/env bash
# Sourced by the native integration test. Diagnostics establish work counts, not scores.
sed -i 's/linux_worker=True)/linux_worker=True, profile_build=True)/' BUILD.bazel
run_app profile-replay 1
assert_contains "$report" '"hits":3'
bazel run //:app "${options[@]}" --build_event_json_file="$TEST_TMPDIR/no-op.bep" > "$TEST_TMPDIR/no-op.log" 2>&1
python3 - "$TEST_TMPDIR/no-op.bep" <<'PY'
import json,sys
m=next(json.loads(l)['buildMetrics'] for l in open(sys.argv[1]) if 'buildMetrics' in json.loads(l))
assert not any(int(a.get('actionsExecuted',0)) for a in m['actionSummary'].get('actionData',[]) if a['mnemonic'] in ['MSBuildGraph','MSBuildGraphRestore'])
PY
for edit in body api; do
    printf 'public class Library { public static int Value() => 2;' > src/Library/Code.cs
    if [[ $edit == api ]]; then printf ' public static int Extra() => 3;' >> src/Library/Code.cs; fi
    printf ' }\n' >> src/Library/Code.cs
    cp src/Library/Code.cs "$scratch/raw/graph/src/Library/Code.cs"
    run_app "$edit" 2
    read_compilation bazel-bin/graph.graph/report.binlog > "$TEST_TMPDIR/$edit-compiled.json"
    cp "$report" "$TEST_TMPDIR/$edit-report.json"
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw/graph" "$scratch/raw/graph-scratch" \
        msbuild dirs.proj -graphBuild -t:Build -m:4 -p:Configuration=Release -p:UseSharedCompilation=false \
        -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' \
        -bl:"/__rules_msbuild_graph/scratch/$edit.binlog;ProjectImports=None" > "$TEST_TMPDIR/$edit-raw.log" 2>&1 || { cat "$TEST_TMPDIR/$edit-raw.log" >&2; exit 1; }
    read_compilation "$scratch/raw/graph-scratch/$edit.binlog" > "$TEST_TMPDIR/$edit-raw-compiled.json"
    cmp "$TEST_TMPDIR/$edit-compiled.json" "$TEST_TMPDIR/$edit-raw-compiled.json"
    (cd "$scratch/raw/graph"; find . -path '*/bin/*' -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/$edit-raw.sha256"
    (cd bazel-bin/graph.graph/workspace; find . -path '*/bin/*' -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/$edit-graph.sha256"
    cmp "$TEST_TMPDIR/$edit-raw.sha256" "$TEST_TMPDIR/$edit-graph.sha256"
done
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from pathlib import Path
r=Path(sys.argv[1])
for case,hits,compiled in [('body',2,1),('api',0,3)]:
    assert len(json.loads((r/(case+'-compiled.json')).read_text()))==compiled
    report=json.loads((r/(case+'-report.json')).read_text())
    assert report['hits']==hits and report['misses']==3-hits and report['preparedRestore']
    metrics=next(json.loads(l)['buildMetrics'] for l in (r/(case+'.bep')).read_text().splitlines() if 'buildMetrics' in json.loads(l))
    assert not any(int(a.get('actionsExecuted',0)) for a in metrics['actionSummary'].get('actionData',[]) if a['mnemonic']=='MSBuildGraphRestore')
PY
# Restore's action remains reusable through source edits; graph profiling is explicit.
sed -i 's/, profile_build=True//' BUILD.bazel
printf 'public class Library { public static int Value() => 1; }\n' > src/Library/Code.cs
run_app restored-edits 1
sed -i 's/latest/preview/' Directory.Build.props
if bazel run //:app "${options[@]}" > "$TEST_TMPDIR/stale-import.log" 2>&1; then echo 'Unexpected stale import success' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/stale-import.log" 'Graph definition changed'
sync_graph import-edit
run_app import-edit 1
assert_contains "$report" '"misses":3'
sed -i 's/preview/latest/' Directory.Build.props
sync_graph restored-import
run_app restored-import 1
echo 'PASS: traversal no-op action reuse, body/API compiler parity and snapshots, import invalidation'
