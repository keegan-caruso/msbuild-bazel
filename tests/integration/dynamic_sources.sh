#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
token=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
printf '<Project><PropertyGroup><QualificationNonce>%s</QualificationNonce></PropertyGroup></Project>\n' "$token" > Directory.Build.props
sed -i 's#</Project>#<ItemGroup><Compile Remove="Sources/Excluded*.cs" /></ItemGroup></Project>#' Library/Library.csproj
mkdir -p Library/Sources
cat > Library/Sources/Value.cs <<'CS'
public static partial class SourceValue {
    public static int Value() { int value = 1; Added(ref value); return value; }
    static partial void Added(ref int value);
}
CS
printf 'System.Console.WriteLine(SourceValue.Value());\n' > App/Program.cs
cat > mappings.json <<'JSON'
{"projectDefaults":{"preparedRestore":true,"evaluationReuseInputs":["@(Compile)"]},"projects":{"Library/Library.csproj":{"compileGlobs":["Library/Sources/*.cs"]}}}
JSON
sed -i 's/name = "sync",/name = "sync", mappings = "mappings.json",/' BUILD.bazel
bazel run //:sync
sed -i 's/app_graph(name = "graph")/app_graph(name = "graph", linux_stable_paths = True, linux_worker = True, profile_build = True)/' BUILD.bazel
sha256sum graph.generated.json graph.generated.bzl > "$TEST_TMPDIR/generated.sha256"
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
if [[ -n "${DYNAMIC_SOURCE_CACHE_URL:-}" ]]; then
    options+=(--remote_cache="$DYNAMIC_SOURCE_CACHE_URL" --remote_cache_async=false --remote_download_outputs=all
        --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$DYNAMIC_SOURCE_CACHE_URL")
fi
report=bazel-bin/graph.graph/report.json
restore=bazel-bin/graph_restore.restore/prepared/manifest.json
run() {
    echo "CASE: $1"
    bazel run //:app "${options[@]}" --execution_log_json_file="$TEST_TMPDIR/$1.execution.json" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
    python3 - "$report" "$3" "$4" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert (r['hits'],r['misses'])==(int(sys.argv[2]),3-int(sys.argv[2])),r
s=r['evaluationState'];assert (s['loaded'],s['reused'])==(int(sys.argv[3]),3-int(sys.argv[3])),r
print('PASS:',s,'plugin',r['hits'],r['misses'])
PY
    sha256sum -c "$TEST_TMPDIR/generated.sha256"
    cp "$report" "$TEST_TMPDIR/$1.json"
}
unchanged_restore() {
    sha256sum -c "$TEST_TMPDIR/restore.sha256"
    # Source membership must never execute a second Restore action.
    python3 - "$TEST_TMPDIR/$1.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder()
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    assert action.get('mnemonic')!='MSBuildGraphRestore',action
PY
}
products() {
    (cd bazel-bin/graph.graph/workspace
     find App/bin Library/bin Tests/bin -type f -print0 | sort -z | xargs -0 sha256sum)
}
run seed 1 0 3
sha256sum "$restore" > "$TEST_TMPDIR/restore.sha256"
cat > Library/Sources/Added.cs <<'CS'
public static partial class SourceValue { static partial void Added(ref int value) { value = 2; } }
CS
run added 2 0 3
unchanged_restore added
sed -i 's/value = 2/value = 3/' Library/Sources/Added.cs
run body 3 2 0
unchanged_restore body
mv Library/Sources/Added.cs Library/Sources/Renamed.cs
run renamed 3 0 3
unchanged_restore renamed
rm Library/Sources/Renamed.cs
printf '\n// removed member\n' >> Library/Sources/Value.cs
run removed 1 2 3
unchanged_restore removed
# An empty glob is valid and removes every previous staged member.
printf 'System.Console.WriteLine(4);\n' > App/Program.cs
rm Library/Sources/Value.cs
run empty 4 0 3
unchanged_restore empty
bazel run //:sync "${options[@]}" -- --check
products > "$TEST_TMPDIR/worker.sha256"
# A fresh sandbox must produce identical app outputs.
sed -i 's/linux_worker = True/linux_worker = False/' BUILD.bazel
bazel run //:app "${options[@]}" --strategy=MSBuildGraph=linux-sandbox > "$TEST_TMPDIR/fresh.log" 2>&1 || { cat "$TEST_TMPDIR/fresh.log" >&2; exit 1; }
products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/worker.sha256" "$TEST_TMPDIR/fresh.sha256"
sed -i 's/linux_worker = False/linux_worker = True/' BUILD.bazel
# Reviewed patterns reject a new member excluded by MSBuild's item conditions.
printf 'public class Excluded {}\n' > Library/Sources/Excluded.cs
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/excluded.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/excluded.log" 'Compile items'
rm Library/Sources/Excluded.cs
printf '#error DynamicSourceFailure\n' > Library/Sources/Failure.cs
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/failure.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/failure.log" DynamicSourceFailure
rm Library/Sources/Failure.cs
printf '\n// after failed member\n' >> Library/Message.cs
run recovery 4 2 3
unchanged_restore recovery
products > "$TEST_TMPDIR/recovery.sha256"
if [[ -n "${DYNAMIC_SOURCE_CACHE_URL:-}" ]]; then
    # Drop broker snapshots and local action results; recover in a new output base.
    bazel shutdown
    scratch="$scratch/fresh-cache-client"
    mkdir -p "$scratch"
    sed -i 's/profile_build = True/profile_build = True, evaluation_cache_mb = 256/' BUILD.bazel
    options+=(--remote_upload_local_results=false)
    run remote-recovery 4 3 3
    products > "$TEST_TMPDIR/remote.sha256"
    cmp "$TEST_TMPDIR/recovery.sha256" "$TEST_TMPDIR/remote.sha256"
    python3 - "$TEST_TMPDIR/remote-recovery.execution.json" <<'PY'
import json,sys
s=open(sys.argv[1]).read();decoder=json.JSONDecoder();restore=[]
while s.strip():
    action,end=decoder.raw_decode(s.lstrip());s=s.lstrip()[end:]
    if action.get('mnemonic')=='MSBuildGraphRestore':restore.append(action)
assert len(restore)==1 and restore[0].get('cacheHit') and restore[0].get('runner')=='remote cache hit',restore
PY
    bazel shutdown
    scratch="${scratch%/fresh-cache-client}"
fi
# A new package boundary must not turn a live glob into an accepted empty set.
printf 'exports_files([])\n' > Library/Sources/BUILD.bazel
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/package.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/package.log" 'Compile glob crosses a Bazel package'
rm Library/Sources/BUILD.bazel
# A generated output cannot masquerade as a globbed authored source.
printf 'public class Generated {}\n' > Library/Sources/Generated.cs
cp BUILD.bazel "$TEST_TMPDIR/build.before-generated"
cat >> BUILD.bazel <<'BUILD'
genrule(name = "generated_source", outs = ["Library/Sources/Generated.cs"], cmd = "echo 'public class Generated {}' > $@")
BUILD
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/generated.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/generated.log" 'Compile globs require authored source files'
cp "$TEST_TMPDIR/build.before-generated" BUILD.bazel
rm Library/Sources/Generated.cs
# Definitions stay pinned even when source membership is dynamic.
printf '\n<!-- changed definition -->\n' >> Library/Library.csproj
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/stale.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/stale.log" 'Graph definition changed; rerun sync'
# Reject task-created members before publishing any project snapshots.
cat > Directory.Build.targets <<'XML'
<Project><Target Name="MutateMembership" BeforeTargets="CoreCompile" Condition="'$(MSBuildProjectName)' == 'Library'">
  <WriteLinesToFile File="$(MSBuildProjectDirectory)/Sources/TaskCreated.cs" Lines="public class TaskCreated {}" Overwrite="true" />
</Target></Project>
XML
python3 - <<'PY'
import hashlib,json
from pathlib import Path
p=Path('mappings.json');m=json.loads(p.read_text())
m['projectDefaults']['documents']={'Directory.Build.targets':{'sha256':hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),'targets':['MutateMembership'],'tasks':[],'inputs':[]}}
p.write_text(json.dumps(m))
PY
bazel run //:sync "${options[@]}"
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/mutation.log" 2>&1; then exit 1; fi
assert_contains "$TEST_TMPDIR/mutation.log" 'Build modified Compile glob membership'
# The default fresh-action path also consumes dynamic patterns without preparation.
rm Directory.Build.targets
printf '{"projects":{"Library/Library.csproj":{"compileGlobs":["Library/Sources/*.cs"]}}}\n' > mappings.json
printf 'public class NewValue { public static int Value() => 5; }\n' > Library/Sources/NewValue.cs
printf 'System.Console.WriteLine(NewValue.Value());\n' > App/Program.cs
bazel run //:sync "${options[@]}"
sed -i 's/app_graph(name = "graph".*)/app_graph(name = "graph")/' BUILD.bazel
sha256sum graph.generated.json graph.generated.bzl > "$TEST_TMPDIR/generated.sha256"
bazel run //:app "${options[@]}" --strategy=MSBuildGraph=linux-sandbox > "$TEST_TMPDIR/default-added.log" 2>&1 || { cat "$TEST_TMPDIR/default-added.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/default-added.log")" == 5 ]]
rm Library/Sources/NewValue.cs
printf 'System.Console.WriteLine(6);\n' > App/Program.cs
bazel run //:app "${options[@]}" --strategy=MSBuildGraph=linux-sandbox > "$TEST_TMPDIR/default-removed.log" 2>&1 || { cat "$TEST_TMPDIR/default-removed.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/default-removed.log")" == 6 ]]
sha256sum -c "$TEST_TMPDIR/generated.sha256"
bazel run //:sync "${options[@]}" -- --check
echo 'PASS: dynamic source additions/body edits/rename/removal/empty set, Restore reuse, evaluation reset, byte parity and failure recovery'
