#!/usr/bin/env bash
# Sourced after the base graph control; every change is made in private scratch.
# Duplicate references name one configured node, not duplicate compilation work.
sed -i 's@</ItemGroup>@<ProjectReference Include="src/Library/Library.csproj"/></ItemGroup>@' dirs.proj
sync_graph duplicate
run_app duplicate 1
raw_variant duplicate
python3 - <<'PY'
import json
c=json.load(open('graph.generated.json'))
assert len(c['Projects'])==5
for p in ['dirs.proj','src/dirs.proj']:
    assert c['Projects'][p]['OutputDirectories']==[]
    assets=(p.rsplit('/',1)[0]+'/' if '/' in p else '')+'obj/project.assets.json'
    assert assets in c['Restore']['Outputs']
assert '"dirs.proj|net45"' not in open('graph.generated.bzl').read()
PY
# Glob membership is evaluated by MSBuild at sync; additions require resync.
sed -i 's@<ProjectReference Include="Library/Library.csproj"/><ProjectReference Include="App/App.csproj"/>@<ProjectReference Include="**/*.csproj"/>@' src/dirs.proj
sync_graph wildcard
mkdir src/Extra
cat > src/Extra/Extra.csproj <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>
XML
printf 'public class Extra { public static int Value() => 42; }\n' > src/Extra/Code.cs
stale_graph wildcard-added
sync_graph wildcard-added
run_app wildcard-added 1
raw_variant wildcard-added
[[ -f bazel-bin/graph.graph/workspace/src/Extra/bin/Release/net10.0/Extra.dll ]]
rm -r src/Extra
stale_graph wildcard-removed
cp "$scratch/nested.proj" src/dirs.proj
cp "$scratch/root.proj" dirs.proj
# Conditional selection plus a configured child property must survive sync.
mkdir Optional
cat > Optional/Optional.csproj <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>
XML
printf 'public class Optional {}\n' > Optional/Code.cs
sed -i 's@</ItemGroup>@<ProjectReference Include="Optional/Optional.csproj" Condition="\x27$(IncludeOptional)\x27 == \x27true\x27" AdditionalProperties="Configuration=Debug"/></ItemGroup>@' dirs.proj
sync_graph optional-off
python3 - <<'PY'
import json
assert 'Optional/Optional.csproj' not in json.load(open('graph.generated.json'))['Projects']
PY
printf '{"projectDefaults":{"preparedRestore":true,"properties":{"IncludeOptional":"true"}}}\n' > mappings.json
raw_properties=(-p:IncludeOptional=true)
sync_graph optional-on
run_app optional-on 1
raw_variant optional-on
[[ -f bazel-bin/graph.graph/workspace/Optional/bin/Debug/net10.0/Optional.dll && ! -e bazel-bin/graph.graph/workspace/Optional/bin/Release ]]
# The SDK's TraversalGlobalProperties uses authored ProjectReference metadata.
cp "$scratch/root.proj" dirs.proj
sed -i 's@<ItemGroup>@<PropertyGroup><TraversalGlobalProperties>Flavor=Blue</TraversalGlobalProperties></PropertyGroup><ItemGroup>@' dirs.proj
sed -i 's@</PropertyGroup>@<DefineConstants Condition="\x27$(Flavor)\x27 == \x27Blue\x27">$(DefineConstants);BLUE</DefineConstants></PropertyGroup>@' Directory.Build.props
cat > src/Library/Code.cs <<'CS'
public class Library {
    public static int Value() =>
#if BLUE
        7;
#else
        1;
#endif
}
CS
cp "$scratch/mappings.json" mappings.json
raw_properties=()
sync_graph propagated-properties
run_app propagated-properties 7
raw_variant propagated-properties
# Multi-targeted children retain their outer and both inner configurations.
cp "$scratch/root.proj" dirs.proj
cp "$scratch/library.cs" src/Library/Code.cs
sed -i '/^$/d; s@<DefineConstants.*</DefineConstants>@@' Directory.Build.props
sed -i 's@<TargetFramework>net10.0</TargetFramework>@<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>@' src/Library/Library.csproj
sync_graph multi-target
run_app multi-target 1
raw_variant multi-target
[[ -f bazel-bin/graph.graph/workspace/src/Library/bin/Release/net10.0-windows/Library.dll ]]
# Graph MSBuild ignores the Traversal SDK's task-time Build=false filter.
# Reject target-specific filters/overrides rather than silently building extra projects.
for target in Build Pack Publish; do
    sed -i 's@Include="tests/Tests/Tests.csproj"@Include="tests/Tests/Tests.csproj" '"$target"'="false"@' dirs.proj
    reject_sync "filtered-$target" 'Traversal per-reference target selection requires conditional ProjectReference'
    cp "$scratch/root.proj" dirs.proj
done
sed -i 's@Include="tests/Tests/Tests.csproj"@Include="tests/Tests/Tests.csproj" Targets="Custom"@' dirs.proj
reject_sync target-override 'Traversal per-reference target selection requires conditional ProjectReference'
cp "$scratch/root.proj" dirs.proj
sed -i 's@<ItemGroup>@<PropertyGroup><TraversalPublishGlobalProperties>Flavor=Blue</TraversalPublishGlobalProperties></PropertyGroup><ItemGroup>@' dirs.proj
reject_sync publish-properties 'Traversal per-reference target selection requires conditional ProjectReference'
cp "$scratch/root.proj" dirs.proj
# Fail closed before allowing dynamic removal or unsupported SDKs into the graph.
sed -i 's@<ItemGroup>@<PropertyGroup><TraversalSkipUnsupportedProjects>true</TraversalSkipUnsupportedProjects></PropertyGroup><ItemGroup>@' dirs.proj
reject_sync dynamic-skip 'Traversal execution-time project skipping is not supported'
cp "$scratch/root.proj" dirs.proj
sed -i 's@src/dirs.proj@missing.proj@' dirs.proj
reject_sync missing-project 'missing.proj'
cp "$scratch/root.proj" dirs.proj
cat > unsupported.proj <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>
XML
sed -i 's/projects = \["dirs.proj"\]/projects = ["unsupported.proj"]/' BUILD.bazel
reject_sync unsupported-coordinator 'Graph sync requires a supported .NET SDK project'
sed -i 's/projects = \["unsupported.proj"\]/projects = ["dirs.proj"]/' BUILD.bazel
rm unsupported.proj
sed -i 's/4.1.82/99.0.0/' global.json
reject_sync missing-sdk 'Microsoft.Build.Traversal'
sed -i 's/99.0.0/4.1.82/' global.json
cp "$scratch/library.csproj" src/Library/Library.csproj
rm -r Optional
sync_graph restored-selection
run_app restored-selection 1
echo 'PASS: traversal duplicates, wildcards/stale sync, conditions, properties, multi-target children and rejection controls'
