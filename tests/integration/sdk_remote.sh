#!/usr/bin/env bash
# Manual producer/fresh-consumer qualification; stop producer before consumer.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
phase=${SDK_CACHE_PHASE:?Set producer or consumer}
endpoint=${SDK_CACHE_URL:?Set project cache URL}
count=${SDK_CACHE_NODES:?Set expected cacheable project count}
seed=${SDK_CACHE_SEED:-}
[[ $phase == producer || $phase == consumer ]]
if [[ $phase == producer ]]; then token=$(python3 -c 'import uuid;print(uuid.uuid4().hex)'); else token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$seed"); fi
[[ $token =~ ^[a-f0-9]{32}$ ]]
printf '\n<!-- SDK recovery token: %s -->\n' "$token" >> Directory.Build.props
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
app_graph(name="graph", linux_worker=True, linux_stable_paths=True)
msbuild_graph_test(name="recovered_app", graph=":graph", project="App/App.csproj")
BUILD
bazel test //:recovered_app --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$endpoint" --disk_cache= --remote_cache= --nocache_test_results --build_event_json_file="$TEST_TMPDIR/recovery.bep" --test_output=errors > "$TEST_TMPDIR/$phase.log" 2>&1 || { cat "$TEST_TMPDIR/$phase.log" >&2; exit 1; }
python3 - "$phase" "$count" "$token" "$seed" "$TEST_TMPDIR" "${TEST_UNDECLARED_OUTPUTS_DIR:-$TEST_TMPDIR}" <<'PY'
import json,hashlib,sys
from pathlib import Path
phase,count,token,seed,logs,results=sys.argv[1:]
r=json.load(open('bazel-bin/graph.graph/report.json'));count=int(count)
assert (r['hits'],r['misses'])==((0,count) if phase=='producer' else (count,0)),r
root=Path('bazel-bin/graph.graph/workspace')
files={str(p.relative_to(root)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':p.stat().st_mode&0o777} for p in sorted(root.rglob('*')) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
assert files
metrics=next(json.loads(l)['buildMetrics'] for l in open(Path(logs,'recovery.bep')) if 'buildMetrics' in json.loads(l))
assert sum(int(a.get('actionsExecuted',0)) for a in metrics['actionSummary']['actionData'] if a['mnemonic']=='MSBuildGraph')>0
assert any('testResult' in json.loads(l) for l in open(Path(logs,'recovery.bep')))
record={'token':token,'files':files,'hits':r['hits'],'misses':r['misses']}
if phase=='consumer':assert record['files']==json.load(open(seed))['files'],'Recovered bytes/modes differ'
Path(results).mkdir(parents=True,exist_ok=True);Path(results,phase+'.json').write_text(json.dumps(record,indent=2)+'\n')
print('PASS:',phase,'actual graph/test execution;',r['hits'],'hits;',len(files),'owned files matched')
PY
