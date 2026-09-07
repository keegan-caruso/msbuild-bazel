# R02–R04 rule and generated-workspace qualification

Starting revision: `5e78487`, branch `codex/r02-r04-qualification`.
The selected lane is native macOS ARM64, .NET SDK 10.0.100 and Bazel 8.4.2
using the pinned Nix tools. Earlier Linux results retain their original scope;
this extension does not claim Linux qualification or a hosted CI pass.

## Acceptance contract

The additional `starlark_packages`, `starlark_configured` and `starlark_tests`
gates pair assertions about registered Bazel actions with the existing real
MSBuild behavior, mutation, rejection and producer-free recovery probes.

- **Packages (R02):** inspect consuming actions for their own restore files,
  package manifests and reference/runtime payloads; exclude unrelated branch and
  private producer packages from consumers. Load real prepared package targets
  and exercise an upgrade. Native full-cache and ordinary/adapter PrivateAssets
  tests independently establish runtime use and compiler visibility.
- **Configurations (selected R03):** inspect effective global properties,
  configuration-specific restore/output paths and distinct bundle outputs.
  Load the configured fixture, compare direct edges with reachable replay bundles,
  and reprepare after edge/input changes. Existing native controls establish
  red/blue output behavior, convergence and producer-free recovery.
- **Tests (R04):** inspect the executable, runner/SDK/data/bundle runfiles,
  exact expected test identities, hashes and local execution policy. Test actions
  retain loopback access for VSTest; compilation retains `block-network`.
  Load generated test targets and pair analysis with unchanged upstream Serilog
  Build/Test, exact intentional failure controls and forced execution after
  relocated build-cache recovery.

`//tests/starlark:extensions` adds ten Skylib analysis tests to the ten baseline
tests. Its text `.dll` and `.nupkg` fixtures are deliberately analysis-only;
the separate generated and native suites use real compiled/package payloads.
The test rule now rejects empty, blank or duplicate expected names at analysis time,
matching preparation's existing contract. The blank-name control covers a nonempty list containing an empty test name. Missing hashes and missing subject
providers are independently rejected. The native prototype accepts the common
`RULES_MSBUILD_SERILOG_SOURCE` / `RULES_MSBUILD_SERILOG_PACKAGES` variables and retains its older
variable aliases for existing callers.

## Reproduction

Use `nix develop` and acquire Buildifier with `python3 scripts/setup-starlark.py`.
The opt-in Serilog suites require the pinned upstream checkout and acquired
packages documented in [library findings](serilog-adapter-findings.md):

```sh
export RULES_MSBUILD_SERILOG_SOURCE=/path/to/pinned/serilog/source
export RULES_MSBUILD_SERILOG_PACKAGES=/path/to/acquired/packages
export RULES_MSBUILD_SERILOG_NATIVE_TESTS=1
mkdir -p artifacts/r04-generator-acquisition
cat > artifacts/r04-generator-acquisition/Upgrade.csproj <<'PROJECT'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>
  <ItemGroup><PackageReference Include="PolySharp" Version="1.16.0" /></ItemGroup>
</Project>
PROJECT
bash scripts/dotnet.sh restore artifacts/r04-generator-acquisition/Upgrade.csproj --packages "$RULES_MSBUILD_SERILOG_PACKAGES"
bash scripts/check.sh
python3 -m unittest discover -s tests/starlark -v
python3 -m unittest discover -s tests/starlark_extensions -v
python3 -m unittest discover -s tests/graph_cache_full -v
python3 -m unittest discover -s tests/graph_packages -v
python3 -m unittest discover -s tests/configured_execution -v
python3 -m unittest discover -s tests/graph_handoff -v
python3 -m unittest discover -s tests/graph_execution -v
python3 -m unittest discover -s tests/serilog_inputs -v
python3 -m unittest discover -s tests/serilog_adapter -v
python3 -m unittest discover -s tests/test_action -v
python3 -m unittest discover -s tests/serilog_tests -v
```

The existing Starlark workflow now includes generated extension, full managed
cache, package and configured execution checks. Dedicated steps acquire the pinned
Serilog checkout and both generator versions, then enable the library, native-test
protocol and unchanged upstream Build/Test gates. The benchmark's protocol checks
also run in CI; repeated timings require a separate reserved local window.
These workflow changes are configured, not an observed hosted pass. The local
runs below supply acceptance evidence; prerequisite skips cannot qualify Serilog.

## Additional R04 controls

The unchanged library uses PolySharp 1.15.0. The version-mutation control uses
an independently acquired 1.16.0 archive from NuGet, with the same narrowly
inventoried analyzer/build/buildTransitive roots. This adds an exact policy pin;
it does not allow arbitrary generator versions or repacked qualified identities.
The archive SHA-256 is
`36b6daa6b98bcca5e618db1cdaa63cbbdea74f0153a62d4ad2deada58bbbc0e0`;
the resolved analyzer SHA-256 is
`1b1faa7d7f8efd1655264d23642192da9590ed57f4091df19b0129f68f07703a`.
Acquisition uses ordinary NuGet restore; preparation/runner verification retains
archive, restored-content and installed-payload integrity checks.

Cold and relocated reference handoff must compile a fresh consumer against the
adapter's reference assembly, then run that consumer with the implementation
assembly. Runtime observation and bundle equality alone cannot establish this
reference-consumption requirement.

## Recorded results

The initial regression logs are retained under
`/private/tmp/r04-qualification-evidence`; final package-policy and test reruns
are under `/private/tmp/r04-final-evidence`. Durations are correctness-suite
runtimes, not performance comparisons.

| Command/suite | Result | Evidence |
| --- | --- | --- |
| `bash scripts/check.sh` | Final check passed; nine owned Starlark files | `/private/tmp/r04-check-final.log` |
| `tests/starlark` | Passed, including ten baseline and nine initial extension analysis subjects | `/private/tmp/r04-qualification-evidence/starlark.log` |
| Final `//tests/starlark:extensions` | All ten analysis tests passed, including the added blank-name case | `/private/tmp/r04-analysis-final.log` |
| `tests/graph_cache_full` | All 13 tests passed again after the additional generator pin | `/private/tmp/r04-final-evidence/graph_cache_full.log` |
| `tests/graph_packages` | All 18 tests passed again after the additional pin | `/private/tmp/r04-final-evidence/graph_packages.log` |
| `tests/configured_execution` | Both native tests passed | `/private/tmp/r04-qualification-evidence/configured_execution.log` |
| `tests/graph_handoff` | All 12 discovery/replay/publication tests passed | `/private/tmp/r04-qualification-evidence/graph_handoff.log` |
| `tests/graph_execution` | All 35 tests passed, with signing and Nix prerequisites available | `/private/tmp/r04-qualification-evidence/graph_execution.log` |
| `tests/serilog_inputs` | Ordinary input oracle passed | `/private/tmp/r04-qualification-evidence/serilog_inputs.log` |
| Extended `tests/serilog_adapter` | Final nine-case run passed in 78.602 seconds after exact missing-input diagnostic checks | `/private/tmp/r04-final-evidence/serilog-adapter-final.log`; report below |
| `tests/starlark_extensions` | All five generated-workspace tests passed, no skips, in 106.637 seconds; nine published workspaces passed S01 | `starlark-extensions-ojxnguke` below |
| `tests/test_action` | All four tests passed on retry in 20.940 seconds | `/private/tmp/r04-final-evidence/test_action-retry.log` |
| `tests/serilog_tests` | Both ordinary and native upstream acceptance tests passed in 62.985 seconds, no skips | `/private/tmp/r04-final-evidence/serilog_tests.log` |
| `tests/serilog_performance` | All five measurement-protocol tests passed | `/private/tmp/r04-performance-protocol.log` |
| Repeated Serilog measurement probe | All 24 samples passed across three repetitions, four cases and two systems | `/private/tmp/serilog-performance-qualification-1/report.json`; [findings](serilog-performance-findings.md) |

Generated extension evidence is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/starlark-extensions-ojxnguke`.
The final suite runs pinned formatting/lint checks on every published workspace.
Those checks exposed reversed load declarations in generated test BUILD files;
`prepare_graph.py` now emits the build-rule load before the test-rule load.
The failing formatting check is retained in `/private/tmp/r04-generated-format.log`;
the complete generated suite passed after the fix.
Earlier harness attempts corrected wrapper invocation, separation of stderr from
Bazel JSON output, and the representation of test inputs through runfiles
middlemen. The final suite checks the generated runfiles provider, test request
contents and declared data hashes. It does not treat an input-insensitive aquery
action key as a complete cache key; actual data-only invalidation is independently
verified by the native Serilog test probe.

The final extended library report is at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-adapter-owdqzbod/probe/report.json`.
The earlier complete nine-case run also passed in 98.729 seconds at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-adapter-h0r6n4wr/probe/report.json`.
The final probe additionally requires the exact `missing-input:` diagnostic and
the removed package/analyzer path for each negative control.
The version edit executes exactly one `darwin-sandbox` project action, matches
its independently built ordinary result and changes both pinned package/archive
and resolved generator hashes. Missing generator and archive controls each fail
with `missing-input` and publish no plan. Cold and relocated reference consumers
both observe `Serilog`, version `4.4.0.0`, token `24C2F752A8E58A10`, and
`Hello "Ada"`; the relocated build recovers from disk without compilation.

The first new reference-consumer attempt failed at runtime because
`Private=false` omitted Serilog from the consumer dependency file. That failed
harness attempt is retained at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-adapter-lh9o8aai/probe/report.json`.
The corrected control compiles with only the reference DLL as its declared
Serilog reference, verifies that the copied DLL equals the reference and differs
from the implementation, then replaces that copy with the matching implementation
before execution. No adapter isolation or upstream source behavior was weakened.

The final unchanged upstream approval report is at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-native-tests-vk5wnqfu/probe/report.json`.
Cold and relocated runs execute exactly one named passing Fact. Approved-text
mutation executes a failed Fact without project compilation; injected test-source
failure recompiles only the test project. Relocation recovers both build bundles
and forces a fresh test action.

The native prototype initially failed its missing-data control because its old
single-line JSON string replacement no longer matched formatted multi-line
Starlark. The failure is retained in
`/private/tmp/r04-final-evidence/test_action.log`. The fix uses the production
Starlark value renderer, requires exactly one matching data declaration and
removes the approval file from declared test data. The test then observes a real
failed Fact. The probe now writes partial case results before checking outcomes,
so later failures retain a report as well as raw logs.

## Boundaries

This accepts selected Release/net10.0 managed packages and the selected
inner/direct-edge configurations, not general NuGet, outer multi-target builds,
arbitrary transitive configurations, solution formats or custom SDK entry points.
The R03 `entrypoints` work package remains a separate extension and release gate.
Serilog coverage is its pinned library and single unchanged approval Fact, not
all Serilog tests or arbitrary test frameworks. Remote workers and full host
closure remain R13/R14 work. Repeated comparative timings are recorded separately
from these correctness test durations in [measurement findings](serilog-performance-findings.md).
