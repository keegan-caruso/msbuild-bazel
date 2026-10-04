#!/usr/bin/env bash
# Retained evaluation qualification; production workers keep fresh engines.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel build @dotnet//:files > "$TEST_TMPDIR/sdk.log" 2>&1 || { cat "$TEST_TMPDIR/sdk.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
mkdir "$scratch/probe"
cp "$runner_dir/EvaluationReuse.cs.txt" "$scratch/probe/Program.cs"
for file in BuildEvaluationCounter Contract GraphProfile; do
    cp "$scratch/msbuild-bazel/tools/GraphBuild/$file.cs" "$scratch/probe/$file.cs"
done
cat > "$scratch/probe/Probe.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup><Reference Include="Microsoft.Build" HintPath="$(MSBuildBinPath)/Microsoft.Build.dll" /><Reference Include="Microsoft.Build.Framework" HintPath="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" /><Reference Include="Microsoft.Build.Utilities.Core" HintPath="$(MSBuildBinPath)/Microsoft.Build.Utilities.Core.dll" /></ItemGroup></Project>
XML
"$sdk/dotnet" build "$scratch/probe/Probe.csproj" -c Release -p:UseSharedCompilation=false > "$TEST_TMPDIR/probe.log" 2>&1 || { cat "$TEST_TMPDIR/probe.log" >&2; exit 1; }
mkdir "$scratch/evaluated"
cp "$scratch/consumer/Directory.Build.props" "$scratch/evaluated/"
cp -R "$scratch/consumer/P0" "$scratch/consumer/P1" "$scratch/consumer/P2" "$scratch/evaluated/"
"$sdk/dotnet" restore "$scratch/evaluated/P2/P2.csproj" --source "$scratch/evaluated" -p:NuGetAudit=false > "$TEST_TMPDIR/restore.log" 2>&1
"$sdk/dotnet" "$scratch/probe/bin/Release/net10.0/Probe.dll" "$scratch/evaluated" "$sdk" "$TEST_TMPDIR/evaluation.json"
if [[ -n "${TEST_UNDECLARED_OUTPUTS_DIR:-}" ]]; then
    cp "$TEST_TMPDIR/evaluation.json" "$TEST_UNDECLARED_OUTPUTS_DIR/evaluation.json"
fi
