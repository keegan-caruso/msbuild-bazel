#!/usr/bin/env bash
# Run serially inside the default pinned Nix shell, from a Git checkout.
set -euo pipefail
release_state=${1:?Usage: bash scripts/qualify-local-mvp.sh /private/tmp/short-new-directory}
case "$release_state" in /private/tmp/*) ;; *) echo 'Use a short, unsynchronized absolute /private/tmp path' >&2; exit 2;; esac
if [ -e "$release_state" ]; then echo 'Evidence directory must be new' >&2; exit 2; fi
mkdir -p "$release_state/tmp" "$release_state/home"
cd "$(dirname "$0")/.."
export TMPDIR="${release_state}/tmp"
export DOTNET_CLI_HOME="${release_state}/home/dotnet"
export NUGET_HTTP_CACHE_PATH="${release_state}/home/nuget-http"
export NUGET_PACKAGES="${release_state}/p"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
step() {
  printf '%s start %s\n' "$(date -u +%FT%TZ)" "$1" >> "${release_state}/steps.log"
  local step_name=$1
  shift
  if "$@" > "${release_state}/$step_name.log" 2>&1; then
    printf '%s passed %s\n' "$(date -u +%FT%TZ)" "$step_name" >> "${release_state}/steps.log"
  else
    local step_code=$?
    printf '%s failed %s %s\n' "$(date -u +%FT%TZ)" "$step_name" "$step_code" >> "${release_state}/steps.log"
    return "$step_code"
  fi
}
step acquire-source git clone --quiet https://github.com/serilog/serilog.git "${release_state}/upstream"
step pin-source git -C "${release_state}/upstream" checkout --detach 49b5339ce85385dc52d4d8e8f2b8308becf23506
step restore-approval bash scripts/dotnet.sh restore "${release_state}/upstream/test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj" -p:Configuration=Release -p:TargetFramework=net10.0 --packages "${release_state}/p"
mkdir "${release_state}/upgrade"
cat > "${release_state}/upgrade/Upgrade.csproj" <<'PROJECT'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="PolySharp" Version="1.16.0" /></ItemGroup></Project>
PROJECT
step restore-upgrade bash scripts/dotnet.sh restore "${release_state}/upgrade/Upgrade.csproj" --packages "${release_state}/p"
for tool in GraphExport EvaluationProbe ReplayPlugin ActionRunner; do step "build-$tool" bash scripts/dotnet.sh build "tools/$tool" -c Release --nologo; done
step setup-starlark python3 scripts/setup-starlark.py
step toolchain bash scripts/check.sh
step dotnet-style bash scripts/check-dotnet.sh
step runner bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
step preparation-unit python3 -m unittest discover -s tests/preparation_reuse -q
step graph-schema python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -q
step tool-output python3 -m unittest discover -s tests/msbuild_tools -q
step starlark python3 -m unittest discover -s tests/starlark -q
step starlark-generated python3 -m unittest discover -s tests/starlark_extensions -q
step reuse python3 tools/probe_preparation_reuse.py --output "${release_state}/r"
step invalidation python3 tests/preparation_reuse/probe_mvp_invalidation.py --output "${release_state}/i"
step discovery python3 tools/probe_discovery_contract.py --output "${release_state}/d"
step serilog-discovery python3 tools/probe_serilog_discovery.py --source "${release_state}/upstream" --packages "${release_state}/p" --output "${release_state}/sd"
step serilog-recovery python3 tests/preparation_reuse/probe_serilog_reuse.py --source "${release_state}/upstream" --packages "${release_state}/p" --output "${release_state}/sr"
step library python3 tools/probe_serilog_adapter.py --source "${release_state}/upstream" --package-cache "${release_state}/p" --output "${release_state}/l"
step approval python3 tools/probe_serilog_test_adapter.py --source "${release_state}/upstream" --packages "${release_state}/p" --output "${release_state}/t"

step prepare-inputs python3 scripts/prepare-local-mvp-inputs.py "${release_state}"
step packages python3 tests/preparation_reuse/probe_mvp_package_inputs.py --source "${release_state}/sc4" --output "${release_state}/pk"
step fallback python3 tests/preparation_reuse/probe_fresh_fallback.py --workspace "${release_state}/small" --output "${release_state}/f"
step lifecycle python3 scripts/check-local-mvp-lifecycle.py "${release_state}"
step calibration-small python3 tools/probe_preparation_performance.py --source "${release_state}/small" --entries "${release_state}/small-entries.json" --output "${release_state}/cs" --repetitions 5 --host-note "Serial final qualification; interactive Mac load uncontrolled; no concurrent agent builds or probes."
step calibration-serilog python3 tools/probe_preparation_performance.py --source "${release_state}/serilog" --entries "${release_state}/serilog-entries.json" --output "${release_state}/cl" --repetitions 5 --host-note "Serial final qualification; interactive Mac load uncontrolled; no concurrent agent builds or probes."
step build-test python3 tools/probe_serilog_performance.py --source "${release_state}/upstream" --packages "${release_state}/p" --output "${release_state}/b" --repetitions 5 --host-note "Serial final qualification; interactive Mac load uncontrolled; no concurrent agent builds or probes."
step performance-gate python3 tools/qualify_preparation_performance.py --budget docs/local-mvp-preparation-budget.json --small "${release_state}/cs/report.json" --serilog "${release_state}/cl/report.json" --end-to-end "${release_state}/b/report.json" --output "${release_state}/performance-gate.json"
