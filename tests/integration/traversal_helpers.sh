#!/usr/bin/env bash
# Shared native fixture operations.
raw_variant() {
    local fixture="$scratch/$1-authored"
    mkdir "$fixture"
    find . -path './bazel-*' -prune -o -type f \( -name '*.cs' -o -name '*.csproj' -o -name '*.proj' -o -name '*.props' -o -name '*.targets' -o -name global.json \) -exec cp --parents '{}' "$fixture" \;
    bash "$runner_dir/traversal_raw.sh" "$sdk" "$archive" "$fixture" "$scratch/$1-raw" "${raw_properties[@]}"
    (cd bazel-bin/graph.graph/workspace; find . -path '*/bin/*' -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/$1.sha256"
    cmp "$scratch/$1-raw/graph.sha256" "$TEST_TMPDIR/$1.sha256"
}
sync_graph() {
    bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }
    bazel run //:sync -- --check > "$TEST_TMPDIR/$1-check.log" 2>&1 || { cat "$TEST_TMPDIR/$1-check.log" >&2; exit 1; }
}
run_app() {
    bazel run //:app "${options[@]}" --build_event_json_file="$TEST_TMPDIR/$1.bep" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]] || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
}
stale_graph() {
    if bazel run //:sync -- --check > "$TEST_TMPDIR/$1.log" 2>&1; then echo "Unexpected current graph: $1" >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/$1.log" 'stale'
}
reject_sync() {
    if bazel run //:sync > "$TEST_TMPDIR/$1.log" 2>&1; then echo "Unexpected sync success: $1" >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/$1.log" "$2"
}
raw_properties=()
cp dirs.proj "$scratch/root.proj"
cp src/dirs.proj "$scratch/nested.proj"
cp src/Library/Library.csproj "$scratch/library.csproj"
cp src/Library/Code.cs "$scratch/library.cs"
cp mappings.json "$scratch/mappings.json"
prepare_reader() {
    if [[ -f "$scratch/reader/bin/Release/net10.0/Reader.dll" ]]; then return; fi
    mkdir "$scratch/reader" "$scratch/empty"
    cp "$runner_dir/CompilationLog.cs.txt" "$scratch/reader/Program.cs"
    cat > "$scratch/reader/Reader.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="Microsoft.Build" HintPath="$(MSBuildBinPath)/Microsoft.Build.dll"/><Reference Include="Microsoft.Build.Framework" HintPath="$(MSBuildBinPath)/Microsoft.Build.Framework.dll"/></ItemGroup></Project>
XML
    DOTNET_ROOT="$sdk" "$sdk/dotnet" build "$scratch/reader/Reader.csproj" -c Release -p:UseSharedCompilation=false -p:NuGetAudit=false -p:RestoreSources="$scratch/empty" > "$TEST_TMPDIR/reader.log" 2>&1 || { cat "$TEST_TMPDIR/reader.log" >&2; exit 1; }
}
read_compilation() {
    prepare_reader
    DOTNET_ROOT="$sdk" "$sdk/dotnet" "$scratch/reader/bin/Release/net10.0/Reader.dll" "$1"
}
