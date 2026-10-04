#!/usr/bin/env bash
# Independent phases: stop the producer before running a fresh consumer container.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
phase=${COMPLETE_CACHE_PHASE:?Set producer or consumer}
endpoint=${COMPLETE_CACHE_URL:?Set the Bazel/project HTTP cache URL}
seed=${COMPLETE_CACHE_SEED:-}
[[ $phase == producer || $phase == consumer ]]
if [[ $phase == consumer ]]; then
    token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$seed")
else
    token=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
fi
[[ $token =~ ^[a-f0-9]{32}$ ]]
printf '\n<!-- Complete-cache qualification: %s -->\n' "$token" >> Directory.Build.props
cat > Directory.Build.targets <<'XML'
<Project>
  <PropertyGroup><MSBuildAllProjects>$(MSBuildAllProjects);$(MSBuildThisFileFullPath)</MSBuildAllProjects></PropertyGroup>
  <Target Name="RecordImportState" BeforeTargets="CoreCompile">
    <WriteLinesToFile File="$(IntermediateOutputPath)import-state.txt" Lines="$([System.String]::Copy('$(MSBuildAllProjects)').Contains('$(MSBuildThisFileFullPath)'))" Overwrite="true" />
  </Target>
</Project>
XML
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('mappings.json'); mappings = json.loads(p.read_text())
mappings['projectDefaults']['documents'] = {'Directory.Build.targets': {
    'sha256': hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),
    'targets': ['RecordImportState'], 'tasks': [], 'inputs': []}}
# The reviewed target only records imports; managed consumers still use reference
# assemblies. Custom targets otherwise select conservative dependency keys.
mappings['projects'] = {p: {'referenceBoundary': True} for p in [
    'src/Library/Library.csproj', 'src/App/App.csproj', 'tests/Tests/Tests.csproj']}
p.write_text(json.dumps(mappings))
PY
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_test(name="tests", graph=":graph", project="tests/Tests/Tests.csproj")
BUILD
# Only the compilation action sees this nonce. Restore's declared inputs stay intact.
python3 - <<'PY'
from pathlib import Path
p=Path('graph.generated.bzl');prefix,graph=p.read_text().split('    msbuild_graph(\n',1)
p.write_text(prefix+'    msbuild_graph(\n'+graph.replace('        srcs = [','        srcs = ["cache-request.txt",',1))
Path('cache-request.txt').write_text('seed')
PY
bazel shutdown
options=(--spawn_strategy=linux-sandbox --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1
    --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$endpoint" --disk_cache= --remote_cache="$endpoint"
    --remote_cache_async=false --remote_download_outputs=all --remote_upload_local_results="$([[ $phase == producer ]] && echo true || echo false)")
run() {
    bazel test //:tests "${options[@]}" --nocache_test_results --test_output=errors \
        --execution_log_json_file="$TEST_TMPDIR/$1.execution.json" \
        > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    python3 "$runner_dir/complete_remote_check.py" "$phase" "$1" "$token" "$seed" "$TEST_TMPDIR" "${TEST_UNDECLARED_OUTPUTS_DIR:-$TEST_TMPDIR}"
}
run "$phase"
if [[ $phase == consumer ]]; then
    # No retained broker or local Bazel action cache may satisfy this control.
    bazel shutdown
    bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
    printf 'forced-recovery\n' > cache-request.txt
    run project-recovery
    # A source edit must reuse Restore while rebuilding only the affected project.
    sed -i 's/=> 1/=> 2/' src/Library/Code.cs
    run body
fi
