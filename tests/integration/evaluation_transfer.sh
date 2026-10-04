#!/usr/bin/env bash
# Positive and negative controls for MSBuild's public full-state handoff.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel build @dotnet//:files > "$TEST_TMPDIR/sdk.log" 2>&1 || { cat "$TEST_TMPDIR/sdk.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
mkdir "$scratch/probe"
cp "$runner_dir/EvaluationTransfer.cs.txt" "$scratch/probe/Program.cs"
cp "$scratch/msbuild-bazel/tools/GraphBuild/BuildEvaluationCounter.cs" "$scratch/probe/BuildEvaluationCounter.cs"
cat > "$scratch/probe/Probe.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup><Reference Include="Microsoft.Build" HintPath="$(MSBuildBinPath)/Microsoft.Build.dll" /><Reference Include="Microsoft.Build.Framework" HintPath="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" /></ItemGroup></Project>
XML
"$sdk/dotnet" build "$scratch/probe/Probe.csproj" -c Release > "$TEST_TMPDIR/probe.log" 2>&1 || { cat "$TEST_TMPDIR/probe.log" >&2; exit 1; }
for mode in partial full; do
    cp -R "$scratch/consumer" "$scratch/$mode"
    "$sdk/dotnet" restore "$scratch/$mode/P2/P2.csproj" --source "$scratch/$mode" -p:NuGetAudit=false > "$TEST_TMPDIR/restore-$mode.log" 2>&1
    "$sdk/dotnet" "$scratch/probe/bin/Release/net10.0/Probe.dll" "$scratch/$mode" "$sdk" "$mode"
    (cd "$scratch/$mode"; find P*/bin -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/$mode.sha256"
done
cmp "$TEST_TMPDIR/partial.sha256" "$TEST_TMPDIR/full.sha256"
echo 'PASS: full-state handoff eliminates build-node evaluation and preserves DLL/PDB bytes'
