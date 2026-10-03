#!/usr/bin/env bash
# Compare ordinary and graph MSBuild with identical source and namespace paths.
set -euo pipefail
sdk=$1; archive=$2; fixture=$3; results=$4
mkdir -p "$results"
[[ "$(sha256sum "$archive" | cut -d ' ' -f 1)" == 2a624920738a53b661e3d4b27a169a66da2921d174c8c742f02db8da839f0295 ]]
for mode in ordinary graph; do
    mkdir "$results/$mode" "$results/$mode-scratch"
    cp -R "$fixture/." "$results/$mode/"
    mkdir -p "$results/$mode/.package-source"
    cp "$archive" "$results/$mode/.package-source/microsoft.build.traversal.4.1.82.nupkg"
    cat > "$results/$mode/NuGet.Config" <<'XML'
<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>
XML
    graph=(); if [[ $mode == graph ]]; then graph=(-graphBuild); fi
    bash "$(dirname "${BASH_SOURCE[0]}")/raw_namespace.sh" "$sdk" "$results/$mode" "$results/$mode-scratch" \
        msbuild dirs.proj -restore -t:Build -m:4 "${graph[@]}" -p:Configuration=Release \
        -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' \
        > "$results/$mode.log" 2>&1 || { cat "$results/$mode.log" >&2; exit 1; }
    (cd "$results/$mode"; find src tests -path '*/bin/*' -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$results/$mode.sha256"
done
cmp "$results/ordinary.sha256" "$results/graph.sha256"
echo 'PASS: nested Traversal ordinary/graph DLL and PDB parity'
