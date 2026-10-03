#!/usr/bin/env bash
# Manual two-container qualification. Producer must be stopped for consumer execution.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
phase=${NOTARGETS_CACHE_PHASE:?Set producer or consumer}
endpoint=${NOTARGETS_CACHE_URL:?Set the HTTP project cache URL}
[[ $phase == producer || $phase == consumer ]]
seed=${NOTARGETS_CACHE_SEED:-}
if [[ $phase == consumer ]]; then
    token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$seed")
else
    token=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
fi
[[ $token =~ ^[a-f0-9]{32}$ ]]
printf '\n<!-- NoTargets qualification token: %s -->\n' "$token" >> Directory.Build.props
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_output(name="proof", graph=":graph", path="Utility/out/proof.txt")
BUILD
bazel build //:proof --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 \
    --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$endpoint" --disk_cache= --remote_cache= \
    --build_event_json_file="$TEST_TMPDIR/recovery.bep" \
    > "$TEST_TMPDIR/$phase.log" 2>&1 || { cat "$TEST_TMPDIR/$phase.log" >&2; exit 1; }
python3 - "$phase" "$token" "$seed" "$TEST_TMPDIR" "${TEST_UNDECLARED_OUTPUTS_DIR:-$TEST_TMPDIR}" <<'PY'
import hashlib,json,sys
from pathlib import Path
phase,token,seed,logs,results=sys.argv[1:]
root=Path('bazel-bin/graph.graph/workspace')
files={str(p.relative_to(root)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':p.stat().st_mode&0o777}
       for p in sorted(root.rglob('*')) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
report=json.load(open('bazel-bin/graph.graph/report.json'))
assert (report['hits'],report['misses'])==((0,3) if phase=='producer' else (3,0)),report
assert report['preparedRestore'] and 'Utility/out/proof.txt' in files
assert (root/'Utility/out/proof.txt').read_bytes()==(root/'Consumer/bin/Release/net10.0/proof.txt').read_bytes()
metrics=next(json.loads(l)['buildMetrics'] for l in open(Path(logs)/'recovery.bep') if 'buildMetrics' in json.loads(l))
assert sum(int(a.get('actionsExecuted',0)) for a in metrics['actionSummary']['actionData'] if a['mnemonic']=='MSBuildGraph')>=1
record={'token':token,'files':files,'hits':report['hits'],'misses':report['misses']}
if phase=='consumer':
    expected=json.load(open(seed))
    assert files==expected['files'],'Recovered output bytes/modes differ'
Path(results).mkdir(parents=True,exist_ok=True)
(Path(results)/(phase+'.json')).write_text(json.dumps(record,indent=2)+'\n')
print('PASS:',phase,'fresh NoTargets graph/export execution;',report['hits'],'hits,',report['misses'],'misses;',len(files),'owned files')
PY
