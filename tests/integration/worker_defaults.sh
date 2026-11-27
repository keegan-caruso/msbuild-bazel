#!/usr/bin/env bash
# Worker defaults follow the qualified execution platform and retain explicit opt-outs.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
worker_evidence() {
    if [[ -n ${TEST_UNDECLARED_OUTPUTS_DIR:-} ]]; then
        for report in "$TEST_TMPDIR"/*.json "$TEST_TMPDIR"/*.log; do
            if [[ -f $report ]]; then cp "$report" "$TEST_UNDECLARED_OUTPUTS_DIR/"; fi
        done
    fi
    cleanup
}
trap worker_evidence EXIT
case "$(uname -m)" in
    aarch64) worker_cpu=aarch64 ;;
    x86_64) worker_cpu=x86_64 ;;
    *) echo 'Unqualified Linux worker architecture.' >&2; exit 1 ;;
esac
python3 - <<'PY_SDK'
import json
from pathlib import Path
path=Path('global.json');settings=json.loads(path.read_text())
settings['sdk']['version']='11.0.100';path.write_text(json.dumps(settings)+'\n')
for project in Path('.').glob('P*/*.csproj'):
    project.write_text(project.read_text().replace('net10.0','net11.0'))
PY_SDK
# The imported target is reviewed before sync. A declared source comment
# activates its delay without changing the reviewed target bytes.
python3 - <<'PY_TARGET'
import hashlib,json,os
from pathlib import Path
marker='rules-msbuild-cancel-'+str(os.getpid())
target=Path('P0/Directory.Build.targets')
target.write_text('<Project><Target Name="WorkerCancellationControl" BeforeTargets="CoreCompile">'
    '<Exec Command="bash -c &quot;exec -a '+marker+' sleep 600&quot;" '
    """Condition="$([System.IO.File]::ReadAllText('$(MSBuildProjectDirectory)/Code.cs').Contains('issue224-cancel'))" />"""
    '</Target></Project>')
Path('worker-mappings.json').write_text(json.dumps(dict(projects={'P0/P0.csproj':dict(documents={
    'P0/Directory.Build.targets':dict(sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        targets=['WorkerCancellationControl'],tasks=[],inputs=['P0/Code.cs'])})})))
p=Path('BUILD.bazel');p.write_text(Path('BUILD.bazel.in').read_text().replace(
    'projects = ["P2/P2.csproj"]','projects = ["P2/P2.csproj"], mappings = "worker-mappings.json"'))
PY_TARGET
bazel run //:sync
printf '\nbazel_dep(name="platforms", version="1.0.0")\n' >> MODULE.bazel
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_restore")
app_graph(name="graph", profile_build=True)
app_graph(name="pack", target="Pack")
app_graph(name="publish", target="Publish")
app_graph(name="explicit_publish", target="Publish", linux_worker=True)
msbuild_graph_restore(name="restore_control", runner=":graph_runner", contract="graph.generated.json", srcs=glob(["P*/**", "global.json", "Directory.Build.*"]), linux_stable_paths=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
printf '\nplatform(name="qualified", constraint_values=["@platforms//os:linux", "@platforms//cpu:%s", "@rules_msbuild//msbuild:qualified_linux_bwrap"])\n' "$worker_cpu" >> BUILD.bazel
requirements() {
    local expected=$1 label=$2; shift 2
    local query
    printf -v query 'mnemonic("%s", //:%s)' "${ACTION_MNEMONIC:-MSBuildGraph}" "$label"
    bazel aquery "$query" --output=jsonproto "$@" > "$TEST_TMPDIR/action.json"
    python3 - "$TEST_TMPDIR/action.json" "$expected" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))['actions'];assert len(rows)==1,rows
info={v['key']:v['value'] for v in rows[0].get('executionInfo',[])}
assert (info.get('supports-workers')=='1') == (sys.argv[2]=='worker'),info
PY
}
requirements portable graph
# A target-platform declaration cannot qualify the execution environment.
requirements portable graph --platforms=//:qualified
requirements worker graph --extra_execution_platforms=//:qualified
requirements portable pack --extra_execution_platforms=//:qualified
requirements portable publish --extra_execution_platforms=//:qualified
requirements worker explicit_publish --extra_execution_platforms=//:qualified
ACTION_MNEMONIC=MSBuildGraphRestore requirements portable restore_control --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified --execution_log_json_file="$TEST_TMPDIR/default-execution.json" > "$TEST_TMPDIR/default.log" 2>&1 || { cat "$TEST_TMPDIR/default.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/default.log") == 1 ]]
python3 - "$TEST_TMPDIR/default-execution.json" <<'PY'
import json,sys
text=open(sys.argv[1]).read();decoder=json.JSONDecoder();rows=[]
while text.strip():
 row,used=decoder.raw_decode(text.lstrip());rows.append(row);text=text.lstrip()[used:]
assert any(r.get('mnemonic')=='MSBuildGraph' and r.get('runner')=='worker' for r in rows),rows
assert 'worker' in json.load(open('bazel-bin/graph.graph/report.json'))
PY
cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/default-report.json"
# Keep automatic selection while editing one implementation. The persistent
# worker must reuse the two unaffected projects, without an HTTP cache backend.
sed -i 's/=> 1/=> 2/' P0/Code.cs
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/body.log" 2>&1 || { cat "$TEST_TMPDIR/body.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/body.log") == 2 ]]
python3 - <<'PY_BODY'
import json
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert 'worker' in r and (r['hits'],r['misses'])==(2,1),r
PY_BODY
cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/body-report.json"
# Cancel an actual automatically selected Bazel worker while an imported target
# owns a live child. Bazel may discard that worker; the following request must
# execute successfully, rather than relying on a cached action result.
python3 - "$BIT_BAZEL_BINARY" "$scratch/bazel" "$TEST_TMPDIR" <<'PY_CANCEL'
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

binary, output_base, reports = sys.argv[1:]
reports = Path(reports)
source = Path('P0/Code.cs')
original = source.read_text()
marker = re.search(r'exec -a (rules-msbuild-cancel-[0-9]+) ', Path('P0/Directory.Build.targets').read_text())[1]
source.write_text(original+'\n// issue224-cancel\n')
command = [binary, '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
           '--output_base=' + output_base, 'build', '//:graph',
           '--extra_execution_platforms=//:qualified']
start = time.monotonic()
owned = None
worker = None
try:
    with (reports / 'cancel.log').open('w') as log:
        client = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        try:
            deadline = time.monotonic() + 120
            while owned is None:
                assert client.poll() is None, 'Build ended before the controlled child started'
                assert time.monotonic() < deadline, 'Controlled worker child did not start'
                for process in Path('/proc').glob('[0-9]*'):
                    try:
                        arguments = (process / 'cmdline').read_bytes().split(b'\0')
                        if arguments[0] == marker.encode():
                            owned = int(process.name)
                    except (FileNotFoundError, PermissionError, ProcessLookupError):
                        pass
                time.sleep(.05)
            # Establish ownership using the real host PID ancestry, despite the
            # nested PID namespace used by the graph child.
            ancestor = owned
            while ancestor > 1:
                process = Path('/proc', str(ancestor))
                arguments = (process / 'cmdline').read_bytes().split(b'\0')
                if b'worker' in arguments and b'--persistent_worker' in arguments:
                    assert 'GraphBuild.dll' in b' '.join(arguments).decode(), arguments
                    assert str((process / 'cwd').resolve()).startswith(output_base + '/'), process
                    worker = ancestor
                    break
                status = (process / 'status').read_text().splitlines()
                ancestor = int(next(line.split()[1] for line in status if line.startswith('PPid:')))
            assert worker is not None, 'Controlled child is not descended from the owned Bazel worker'
            cancelled = time.monotonic()
            client.send_signal(signal.SIGINT)
            exit_code = client.wait(timeout=30)
            assert exit_code != 0, exit_code
            deadline = time.monotonic() + 15
            while Path('/proc', str(owned)).exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert not Path('/proc', str(owned)).exists(), 'Cancelled MSBuild child survived'
            assert not Path('bazel-bin/graph.graph/report.json').exists(), 'Cancelled graph published a report'
            (reports / 'cancellation.json').write_text(json.dumps(dict(
                clientExit=exit_code, childPid=owned, workerPid=worker,
                workerSurvived=Path('/proc', str(worker)).exists(),
                readySeconds=cancelled-start, cancellationSeconds=time.monotonic()-cancelled), indent=2))
        finally:
            if client.poll() is None:
                os.killpg(client.pid, signal.SIGKILL)
                client.wait(timeout=10)
finally:
    source.write_text(original)
PY_CANCEL
# A different body guarantees the next action executes after cancellation.
sed -i 's/=> 2/=> 3/' P0/Code.cs
bazel run //:app --extra_execution_platforms=//:qualified --execution_log_json_file="$TEST_TMPDIR/retry-execution.json" > "$TEST_TMPDIR/retry.log" 2>&1 || { cat "$TEST_TMPDIR/retry.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/retry.log") == 3 ]]
cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/retry-report.json"
python3 - "$TEST_TMPDIR/retry-execution.json" <<'PY_RETRY'
import json,sys
text=open(sys.argv[1]).read();decoder=json.JSONDecoder();rows=[]
while text.strip():
 row,used=decoder.raw_decode(text.lstrip());rows.append(row);text=text.lstrip()[used:]
assert any(r.get('mnemonic')=='MSBuildGraph' and r.get('runner')=='worker' and not r.get('cacheHit') for r in rows),rows
assert 'worker' in json.load(open('bazel-bin/graph.graph/report.json'))
PY_RETRY
sed -i 's/=> 3/=> 2/' P0/Code.cs
sed -i 's/=> 2/=> 1/' P0/Code.cs
sed -i 's/app_graph(name="graph", profile_build=True)/app_graph(name="graph", profile_build=True, linux_worker=False)/' BUILD.bazel
requirements portable graph --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/disabled.log" 2>&1 || { cat "$TEST_TMPDIR/disabled.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/disabled.log") == 1 ]]
python3 - <<'PY'
import json
assert 'worker' not in json.load(open('bazel-bin/graph.graph/report.json'))
PY
sed -i 's/profile_build=True, linux_worker=False/profile_build=True, linux_stable_paths=False/' BUILD.bazel
requirements portable graph --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/portable.log" 2>&1 || { cat "$TEST_TMPDIR/portable.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/portable.log") == 1 ]]
echo 'PASS: qualified execution defaults to actual Bazel workers; live cancellation and a subsequent worker request pass; target-only and explicit opt-outs remain non-worker'
