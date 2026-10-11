#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
bazel build @dotnet//:files
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
export DOTNET_CLI_HOME="$scratch/cli" DOTNET_ROOT="$sdk" DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
python3 - <<'PY'
from pathlib import Path
Path('NuGet.Config').write_text('<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="12.0.3" /></ItemGroup></Project>'))
Path('Directory.Build.props').write_text('<Project><PropertyGroup><Deterministic>true</Deterministic></PropertyGroup></Project>')
for name in ['Prerequisite','Excluded']:
    Path(name).mkdir();Path(name+'/'+name+'.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    if name=='Prerequisite':
        p=Path(name+'/'+name+'.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" /></ItemGroup></Project>'))
    Path(name+'/Source.cs').write_text('invalid excluded source' if name=='Excluded' else 'public class Prerequisite {}')
guids={n:'{00000000-0000-0000-0000-'+str(i).zfill(12)+'}' for i,n in enumerate(['App','Library','Tests','Prerequisite','Excluded'],1)}
rows=['Microsoft Visual Studio Solution File, Format Version 12.00']
for n,g in guids.items():
    rows += ['Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "'+n+'", "'+n+'/'+n+'.csproj", "'+g+'"']
    if n=='Tests': rows += ['ProjectSection(ProjectDependencies) = postProject',guids['Prerequisite']+' = '+guids['Prerequisite'],'EndProjectSection']
    rows += ['EndProject']
rows += ['Global','GlobalSection(SolutionConfigurationPlatforms) = preSolution','Release|Any CPU = Release|Any CPU','EndGlobalSection','GlobalSection(ProjectConfigurationPlatforms) = postSolution']
for n,g in guids.items():
    config='Debug' if n=='Library' else 'Release'
    rows += [g+'.Release|Any CPU.ActiveCfg = '+config+'|Any CPU']
    if n!='Excluded': rows += [g+'.Release|Any CPU.Build.0 = '+config+'|Any CPU']
rows += ['EndGlobalSection','EndGlobal']
Path('Sample.sln').write_text('\n'.join(rows)+'\n')
PY
"$sdk/dotnet" sln Sample.sln migrate
phase=${SDK_CACHE_PHASE:-}
if [[ -n "$phase" ]]; then
    [[ $phase == producer || $phase == consumer ]]
    if [[ $phase == producer ]]; then token=$(python3 -c 'import uuid; print(uuid.uuid4().hex)'); else token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$SDK_CACHE_SEED"); fi
    [[ $token =~ ^[a-f0-9]{32}$ ]]
    printf '\n<!-- solution recovery %s -->\n' "$token" >> Directory.Build.props
    printf '{"token":"%s","formats":{}}\n' "$token" > "$TEST_UNDECLARED_OUTPUTS_DIR/$phase.json"
fi
cp MODULE.bazel "$scratch/module.before"
for ext in sln slnx; do
    cp "$scratch/module.before" MODULE.bazel
    cat > BUILD.bazel <<BZL
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")
msbuild_nuget_update(name="update_packages", projects=["Sample.$ext"])
BZL
    bazel run //:update_packages
    bazel run //:update_packages -- --check
    cat >> MODULE.bazel <<'BZL'
nuget=use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")
nuget.lock(name="nuget", lockfile="//:nuget.lock.json")
use_repo(nuget,"nuget")
BZL
    cat >> BUILD.bazel <<BZL
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="sync", projects=["Sample.$ext"], package_lock="@nuget//:packages", package_build=True)
BZL
    bazel run //:sync
    bazel run //:sync -- --check
    python3 - "$ext" <<'PY'
import json,sys
from pathlib import Path
r=json.loads(Path('graph.generated.json').read_text())
assert 'Sample.'+sys.argv[1] in r['DefinitionDigests']
assert len(r['Projects'])==4 and 'Excluded/Excluded.csproj' not in r['Projects'],r['Projects'].keys()
assert r['Projects']['Library/Library.csproj']['Configurations'][0]['Properties']['Configuration']=='Debug'
assert '/tmp/' not in Path('graph.generated.json').read_text()
PY
    cat >> BUILD.bazel <<'BZL'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
app_graph(name="graph")
msbuild_graph_test(name="test", graph=":graph", project="Tests/Tests.csproj")
BZL
    if [[ -n "$phase" ]]; then
        python3 - <<'PY'
from pathlib import Path
p=Path('BUILD.bazel');p.write_text(p.read_text().replace('app_graph(name="graph")','app_graph(name="graph", linux_worker=True, linux_stable_paths=True)'))
PY
        bazel test //:test --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --action_env=RULES_MSBUILD_PROJECT_CACHE_URL="$SDK_CACHE_URL" --remote_cache= --disk_cache= --nocache_test_results --test_output=errors
        python3 - "$phase" "$ext" "$SDK_CACHE_SEED" "$TEST_UNDECLARED_OUTPUTS_DIR/$phase.json" <<'PY'
import json,hashlib,sys
from pathlib import Path
phase,ext,seed,output=sys.argv[1:]
r=json.loads(Path('bazel-bin/graph.graph/report.json').read_text());assert (r['hits'],r['misses'])==((0,4) if phase=='producer' else (4,0)),r
root=Path('bazel-bin/graph.graph/workspace')
files={str(p.relative_to(root)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':p.stat().st_mode&0o777} for p in sorted(root.rglob('*')) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
assert files
if phase=='consumer':assert files==json.load(open(seed))['formats'][ext]
m=json.load(open(output));m['formats'][ext]=files;Path(output).write_text(json.dumps(m))
PY
        continue
    fi
    bazel test //:test --remote_cache= --disk_cache= --test_output=errors
    [[ -f bazel-bin/graph.graph/workspace/Prerequisite/bin/Release/net10.0/Prerequisite.dll ]]
    # Compare the same SDK's native graph products and configuration mapping.
    mkdir -p "$scratch/raw-$ext"
    cp -R App Library Tests Prerequisite Excluded Sample.* Directory.Build.props NuGet.Config global.json "$scratch/raw-$ext/"
    (cd "$scratch/raw-$ext"; "$sdk/dotnet" msbuild "Sample.$ext" -restore -graphBuild -m:4 -p:Configuration=Release -p:UseSharedCompilation=false -p:PathMap="$scratch/raw-$ext=/_/workspace%2C$sdk=/_/sdk") > "$TEST_TMPDIR/raw-$ext.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$ext.log"; exit 1; }
    for project in App Library Tests Prerequisite; do
        config=Release; [[ $project != Library ]] || config=Debug
        cmp "$scratch/raw-$ext/$project/bin/$config/net10.0/$project.dll" "bazel-bin/graph.graph/workspace/$project/bin/$config/net10.0/$project.dll"
    done
    cp Library/Library.csproj "$scratch/library.before"
    python3 - <<'PY'
from pathlib import Path
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('12.0.3','13.0.3'))
PY
    if bazel run //:sync > "$TEST_TMPDIR/stale-lock-$ext.log" 2>&1; then echo 'Solution Restore rewrote child lock' >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/stale-lock-$ext.log" 'NU1004'
    cp "$scratch/library.before" Library/Library.csproj
    # A solution-only change must invalidate both check and build.
    cp "Sample.$ext" "$scratch/solution.before"
    printf '\n' >> "Sample.$ext"
    if bazel run //:sync -- --check > "$TEST_TMPDIR/stale-$ext.log" 2>&1; then echo 'Accepted stale solution' >&2; exit 1; fi
    if bazel build //:graph > "$TEST_TMPDIR/stale-build-$ext.log" 2>&1; then echo 'Built stale solution' >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/stale-build-$ext.log" 'Graph definition changed'
    cp "$scratch/solution.before" "Sample.$ext"
done
if [[ -n "$phase" ]]; then echo "PASS: $phase four-project recovery and execution, sln/slnx"; exit 0; fi
printf '<Project/>\n' > Directory.Solution.targets
if bazel run //:sync > "$TEST_TMPDIR/hooks.log" 2>&1; then echo 'Accepted custom solution hooks' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/hooks.log" 'Custom solution build hooks'
echo 'PASS: sln/slnx update, configuration/exclusion/dependency parity, sync/test and stale-solution guards'
