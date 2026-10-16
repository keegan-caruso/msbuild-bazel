#!/usr/bin/env bash
# Build-only producer content does not invalidate Restore; layout stays explicit.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="sync",projects=["P0/P0.csproj"],mappings="producer.json",package_build=True)
BUILD
printf '{"projectDefaults":{"preparedRestore":true}}\n' > producer.json
printf 'public class P0 { public const int Value = 1; }\n' > P0/Code.cs
sync() { bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }; }
sync producer
mv graph.generated.json producer.generated.json
sed 's/graph.generated.json/producer.generated.json/g' graph.generated.bzl > producer.generated.bzl
rm graph.generated.bzl
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_output")
load(":producer.generated.bzl", producer_graph="app_graph")
producer_graph(name="producer",linux_stable_paths=True,linux_worker=True)
msbuild_graph_output(name="references",graph=":producer",path="P0/bin/Release/net10.0",directory=True)
msbuild_sync(name="sync",projects=["Use/Use.csproj"],mappings="consumer.json",package_build=True,build_inputs={":references":"refs"})
BUILD
python3 - <<'PY'
import hashlib,json
from pathlib import Path
Path('Use').mkdir()
p=Path('Use/Use.csproj')
p.write_text('''<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType>
<ProducerPresent Condition="Exists('$(MSBuildThisFileDirectory)../refs/P0.dll')">yes</ProducerPresent></PropertyGroup>
<ItemGroup><Reference Include="P0" HintPath="../refs/P0.dll" /><ProducerFiles Include="../refs/*.dll" /></ItemGroup>
<Target Name="RestoreLayout" BeforeTargets="Restore"><WriteLinesToFile File="obj/layout.txt" Lines="$(ProducerPresent);@(ProducerFiles->'%(Filename)')" Overwrite="true" /></Target>
</Project>''')
Path('Use/Code.cs').write_text('System.Console.WriteLine(P0.Value);')
Path('consumer.json').write_text(json.dumps({'projectDefaults':{'preparedRestore':True,'restoreOutputs':['Use/obj/layout.txt'],'evaluationItems':['ProducerFiles'],
    'documents':{'Use/Use.csproj':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'targets':['RestoreLayout'],'tasks':[],'inputs':[]}}}}))
PY
sync consumer
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", consumer_graph="app_graph")
consumer_graph(name="consumer",linux_stable_paths=True,linux_worker=True)
msbuild_graph_binary(name="app",graph=":consumer",project="Use/Use.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() {
    bazel run //:app "${options[@]}" --execution_log_json_file="$TEST_TMPDIR/$1.actions.json" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
    [[ "$(cat bazel-bin/consumer_restore.restore/prepared/Use/obj/layout.txt)" == $'yes\nP0' ]]
}
run seed 1
cp bazel-bin/consumer_restore.restore/prepared/Use/obj/layout.txt "$TEST_TMPDIR/restore-layout.txt"
printf 'public class P0 { public const int Value = 2; }\n' > P0/Code.cs
run api 2
# Keep fresh-output correctness independent of project snapshots and Bazel state.
cp bazel-bin/consumer.graph/workspace/Use/bin/Release/net10.0/Use.dll "$TEST_TMPDIR/api.dll"
bazel shutdown
bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh 2
cmp "$TEST_TMPDIR/api.dll" bazel-bin/consumer.graph/workspace/Use/bin/Release/net10.0/Use.dll
cmp "$TEST_TMPDIR/restore-layout.txt" bazel-bin/consumer_restore.restore/prepared/Use/obj/layout.txt
# Conservative inputs still rerun Restore on byte edits. Its outputs must match
# the content-independent declaration, including the Exists/glob receipt.
cp bazel-bin/consumer_restore.restore/prepared/manifest.json "$TEST_TMPDIR/build-only-manifest.json"
sed -i 's/build_inputs=/inputs=/' BUILD.bazel
sync conservative
run conservative 2
python3 - "$TEST_TMPDIR/build-only-manifest.json" <<'PY'
import json,sys
old=json.load(open(sys.argv[1]))['Files']
new=json.load(open('bazel-bin/consumer_restore.restore/prepared/manifest.json'))['Files']
assert old==new,(old,new)
PY
printf 'public class P0 { public const int Value = 3; }\n' > P0/Code.cs
run conservative-api 3
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
for case,expected in [('seed',False),('api',True),('conservative',False),('conservative-api',False)]:
    text=(root/(case+'.actions.json')).read_text()
    decoder=json.JSONDecoder(); position=0; actions=[]
    while position < len(text):
        while position < len(text) and text[position].isspace(): position+=1
        if position == len(text): break
        action,position=decoder.raw_decode(text,position); actions.append(action)
    actions=[a for a in actions if a.get('mnemonic')=='MSBuildGraphRestore' and a.get('targetLabel')=='//:consumer_restore']
    # Unchanged actions need not appear in the execution log at all.
    if expected:
        assert all(a.get('cacheHit') for a in actions),actions
    else:
        assert len(actions)==1 and not actions[0].get('cacheHit'),actions
report=json.load(open('bazel-bin/consumer.graph/report.json'))
assert report['misses']==1,report
PY
echo 'PASS: API producer bytes reach Csc, Restore reuses unchanged inputs, Exists/globs retain layout and fresh output bytes match'
