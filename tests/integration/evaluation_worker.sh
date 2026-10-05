#!/usr/bin/env bash
# Production engine: fresh instances, nodes, inputs and verification on each request.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel build @dotnet//:files > "$TEST_TMPDIR/sdk.log" 2>&1
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
# Direct CLI builds may update workload metadata. Keep Bazel's declared SDK
# untouched, just as the production runner's read-only bind does.
cp -a "$sdk" "$scratch/task-sdk"
mkdir "$scratch/task" task
cat > "$scratch/task/Proof.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="Microsoft.Build.Framework" HintPath="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" /><Reference Include="Microsoft.Build.Utilities.Core" HintPath="$(MSBuildBinPath)/Microsoft.Build.Utilities.Core.dll" /></ItemGroup></Project>
XML
cat > "$scratch/task/Task.cs" <<'CS'
public sealed class ProofTask : Microsoft.Build.Utilities.Task {
 public string Project {get;set;} = ""; public string File {get;set;} = ""; public string Value {get;set;} = "";
 private static readonly HashSet<string> Seen = new();
 public override bool Execute() {
  var marker=Path.Combine(Path.GetTempPath(),"qualification-"+Path.GetFileNameWithoutExtension(Project));
  if(!Seen.Add(Project)||System.IO.File.Exists(marker)) throw new Exception("Retained task/request scratch leaked");
  System.IO.File.WriteAllText(marker,"first"); System.IO.File.WriteAllText(File,"v1:"+Value); return true;
 }
}
CS
task_build() {
    "$scratch/task-sdk/dotnet" build "$scratch/task/Proof.csproj" -c Release -p:UseSharedCompilation=false > "$TEST_TMPDIR/task-build.log" 2>&1 || { cat "$TEST_TMPDIR/task-build.log" >&2; exit 1; }
    cp "$scratch/task/bin/Release/net10.0/Proof.dll" task/Proof.dll
}
task_build
printf 'first' > evaluation.txt
cat > Directory.Build.targets <<'XML'
<Project>
  <UsingTask TaskName="ProofTask" AssemblyFile="$(MSBuildThisFileDirectory)task/Proof.dll" />
  <PropertyGroup><EvaluatedProof>$([System.IO.File]::ReadAllText('$(MSBuildThisFileDirectory)evaluation.txt'))</EvaluatedProof></PropertyGroup>
  <Target Name="Proof" BeforeTargets="CoreCompile">
    <Error Condition="'$(StateMutation)' != ''" Text="Retained build instance leaked" />
    <PropertyGroup><StateMutation>dirty</StateMutation></PropertyGroup>
    <ProofTask Project="$(MSBuildProjectFullPath)" File="$(IntermediateOutputPath)proof.txt" Value="$(EvaluatedProof)" />
  </Target>
</Project>
XML
python3 - <<'PY'
import hashlib,json
from pathlib import Path
m={'projectDefaults':{'preparedRestore':True,'evaluationReuseInputs':['@(Compile)'],'restoreInputs':['evaluation.txt'],'documents':{'Directory.Build.targets':{
 'sha256':hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),'targets':['Proof'],'tasks':['ProofTask'],'inputs':['evaluation.txt','task/Proof.dll']}}},
 'projects':{p:{'referenceBoundary':True} for p in ['src/Library/Library.csproj','src/App/App.csproj','tests/Tests/Tests.csproj']}}
# Defaults merge into per-project bindings.
Path('mappings.json').write_text(json.dumps(m))
PY
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
# Keep preparation identical while forcing a second compilation action through profiling.
freeze_restore_profile() {
    python3 - <<'PY2'
from pathlib import Path
p=Path('graph.generated.bzl');prefix,graph=p.read_text().split('    msbuild_graph(\n',1)
p.write_text(prefix.replace('profile_build = profile_build','profile_build = False')+'    msbuild_graph(\n'+graph)
PY2
}
freeze_restore_profile
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph",linux_worker=True,linux_stable_paths=True,profile_build=True)
msbuild_graph_binary(name="app",graph=":graph",project="src/App/App.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() {
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
    cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/$1.json"
    python3 - "$TEST_TMPDIR/$1.json" "$3" "$4" "$5" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));s=r['evaluationState'];expected=int(sys.argv[2]);assert s['loaded']==expected and s['reused']==5-expected,r
assert (r['hits'],r['misses'])==(int(sys.argv[3]),int(sys.argv[4])),r
assert r['buildNodeEvaluations'] in [None,0],r
print('PASS:',sys.argv[1],s,'plugin',r['hits'],r['misses'])
PY
}
products() {
    python3 - <<'PY3'
import hashlib,json
from pathlib import Path
root=Path('bazel-bin/graph.graph/workspace');c=json.load(open('graph.generated.json'))
variants=[v for p in c['Projects'].values() for v in p.get('Configurations') or [p]]
files={p for v in variants for d in v['OutputDirectories'] for p in (root/d).rglob('*') if p.is_file() and (p.suffix in ['.dll','.pdb'] or p.name=='proof.txt')}
for p in sorted(files):print(hashlib.sha256(p.read_bytes()).hexdigest(),str(p.relative_to(root)))
PY3
}
run seed 1 5 0 3
sed -i 's/profile_build=True/profile_build=False/' BUILD.bazel
run reused 1 0 3 0
sed -i 's/=> 1/=> 2/' src/Library/Code.cs
run body 2 0 2 1
sed -i 's/=> 2/=> 2; public static int Added() => 3/' src/Library/Code.cs
run api 2 0 0 3
products > "$TEST_TMPDIR/api.sha256"
# A fresh process must produce identical bytes, including evaluated/task proof.
sed -i 's/linux_worker=True/linux_worker=False/' BUILD.bazel
bazel run //:app > "$TEST_TMPDIR/fresh.log" 2>&1 || { cat "$TEST_TMPDIR/fresh.log" >&2; exit 1; }
products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/fresh.sha256"
sed -i 's/linux_worker=False/linux_worker=True/' BUILD.bazel
printf 'second' > evaluation.txt
run evaluation-read 2 5 0 3
[[ "$(cat bazel-bin/graph.graph/workspace/src/Library/obj/Release/net10.0/proof.txt)" == v1:second ]]
sed -i 's/v1:/v2:/' "$scratch/task/Task.cs"
task_build
run changed-task 2 5 0 3
[[ "$(cat bazel-bin/graph.graph/workspace/src/Library/obj/Release/net10.0/proof.txt)" == v2:second ]]
cp src/Library/Code.cs "$TEST_TMPDIR/good.cs"
printf 'not C sharp' > src/Library/Code.cs
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/failure.log" 2>&1; then echo 'Invalid source unexpectedly built' >&2; exit 1; fi
cp "$TEST_TMPDIR/good.cs" src/Library/Code.cs
# A unique valid edit prevents the previous whole-action hit from hiding recovery.
printf '\n// recovery\n' >> src/Library/Code.cs
run failed-build-recovery 2 5 2 1
# File membership and definition changes go through sync and reset evaluation.
printf 'public class AddedType {}\n' > src/Library/Added.cs
bazel run //:sync > "$TEST_TMPDIR/membership-sync.log" 2>&1 || { cat "$TEST_TMPDIR/membership-sync.log" >&2; exit 1; }
freeze_restore_profile
run membership 2 5 0 3
printf '\n<!-- changed definition -->\n' >> src/Library/Library.csproj
if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/stale.log" 2>&1; then echo 'Stale definition unexpectedly built' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/stale.log" 'Graph definition changed; rerun sync'
bazel run //:sync > "$TEST_TMPDIR/definition-sync.log" 2>&1 || { cat "$TEST_TMPDIR/definition-sync.log" >&2; exit 1; }
freeze_restore_profile
run definition 2 5 0 3
products > "$TEST_TMPDIR/final.sha256"
sed -i 's/linux_worker=True/linux_worker=False/' BUILD.bazel
bazel run //:app > "$TEST_TMPDIR/final-fresh.log" 2>&1 || { cat "$TEST_TMPDIR/final-fresh.log" >&2; exit 1; }
products > "$TEST_TMPDIR/final-fresh.sha256"
cmp "$TEST_TMPDIR/final.sha256" "$TEST_TMPDIR/final-fresh.sha256"
sed -i 's/linux_worker=False/linux_worker=True,evaluation_cache_mb=1/' BUILD.bazel
printf '\n// budget one\n' >> src/Library/Code.cs
run bounded-one 2 5 0 3
printf '\n// budget two\n' >> src/Library/Code.cs
run bounded-two 2 5 0 3
products > "$TEST_TMPDIR/bounded.sha256"
sed -i 's/evaluation_cache_mb=1/evaluation_cache_mb=0/' BUILD.bazel
bazel run //:app "${options[@]}" > "$TEST_TMPDIR/disabled.log" 2>&1 || { cat "$TEST_TMPDIR/disabled.log" >&2; exit 1; }
products > "$TEST_TMPDIR/disabled.sha256"
cmp "$TEST_TMPDIR/bounded.sha256" "$TEST_TMPDIR/disabled.sha256"
python3 - <<'PY4'
import json
assert json.load(open('bazel-bin/graph.graph/report.json'))['evaluationState'] is None
PY4
echo 'PASS: production retained worker, body/API reuse, byte parity, fresh task state, evaluation/tool invalidation, membership/definition and failure recovery'
