# SDK 10.0.400 baseline refresh

Microsoft's .NET 10 release metadata identified 10.0.400 (released 2026-08-11)
as the latest stable SDK on 2026-09-07. Its bundled runtime is 10.0.11.
Source: https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json

The upgrade keeps net10.0 and Bazel 8.4.2. It updates global.json, fixture pins,
setup archive URLs/hashes, SDK paths in preparation/action/test runners, replay
payload identity and test expectations. Loader experiments now use runtime
10.0.11. Old SDK replay payloads are rejected by the updated identity checks.

Linux x64, Linux ARM64 and macOS ARM64 SDK archives were downloaded and checked
against Microsoft's SHA-512 release metadata. Setup retains SHA-256 pins computed
from those verified archives. Nix has a separate locked SDK input at
42f17a57f4f6e33b3de3dca0a2a5ea5233169d02; the existing Nixpkgs input continues
to supply Bazel 8.4.2. The SDK's native dependency closure changes with that input.

The unchanged pinned Serilog source now restores Microsoft.NET.ILLink.Tasks
10.0.11, with PolySharp still at 1.15.0. The pilot policy adds the exact archive
and restore-content hashes for that SDK-selected package and retains the older
qualified package entry. This does not allow arbitrary package versions.

## Validation

Evidence is local to `/private/tmp/msbuild-sdk-latest/artifacts` unless noted.
Use `nix develop path:. -c` before the commands below, or the explicit pinned
RULES_MSBUILD_DOTNET_ROOT and RULES_MSBUILD_BAZEL overrides.

- `bash scripts/check.sh`: passed, including 9 Starlark files.
- `bash scripts/check-dotnet.sh`: passed owned builds, format checks and 5 policy tests.
- `nix develop path:. -c bash scripts/check.sh --toolchain-only`: passed on macOS ARM64.
- `nix eval --raw path:.#devShells.x86_64-linux.default.drvPath`: evaluated successfully;
  this is not a Linux execution result.
- `python3 tests/serilog_inputs/probe.py --source /private/tmp/msbuild-pilot-serilog --package-cache /private/tmp/msbuild-serilog-baseline-3/packages --output /private/tmp/sdk400-serilog-inputs`:
  ordinary selected-framework build and behavior controls passed; report records
  SDK 10.0.400 and ILLink 10.0.11.
- `python3 -m unittest discover -s tests/bootstrap -v`: 8 passed.
- Preparation validation and dependency-closure unit suites: 24 passed.
- `python3 -m unittest discover -s tests/e2e -v`: 14 passed, one opt-in native
  runtime test skipped (218.702 seconds). Includes action identity, deterministic
  staging, package handoff, disk-cache recovery and public-API replay.
- `python3 -m unittest discover -s tests/graph_packages -p test_pilot_package_policy.py -v`
  with the pinned Serilog source and newly restored package cache: 3 passed,
  including ILLink 10.0.11 export/staging and archive-integrity rejection.
- `python3 tools/probe_generator_roles.py --output /private/tmp/sdk400-generator-roles --cold-only` and
  `python3 tools/probe_generator_combinations.py --output <new-directory> --cold-only --analyzer-delivery <project-or-package>`:
  all three native sandbox cold-build oracles passed. Reports are under
  `/private/tmp/sdk400-generator-{roles,project,package}`. This is cold-build
  upgrade coverage; the prior 35-case mutation/recovery matrix was not rerun.
- `RULES_MSBUILD_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -k test_native_runtime_closure -v`:
  passed. Covers native closure integrity, copied-library identity, actual JIT
  substitution, fresh/disk-cache recovery and missing/corrupt/invalid payload rejection.

## Spectre and R09 scope

Running the new SDK's `dotnet --version` from the pinned Spectre checkout
`2dc90b90add956c2f6777cb659120900ac2eb740` now exits zero with 10.0.400.
This removes the SDK-selection failure (previously exit 155). Full Spectre
acceptance still needs netstandard2.0 generator support, central package
management and build-time input closure; this upgrade does not claim those gates.

R09's uncommitted discovery-identity work remains in its separate worktree.
New performance baselines must record the new SDK and native closure; historical
10.0.100 timings cannot serve as an unchanged-toolchain comparison.
No GitHub CI or Linux execution was requested. Historical findings are preserved.
