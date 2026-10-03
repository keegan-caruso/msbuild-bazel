# Support and limits

The graph workflow is the sole backend. Baselines: SDK 10.0.400, Bazel 8.8.0/9.2.0.
Inputs, package inventories, generated products, tool layouts and output ownership
must be declared. MSBuild retains SDK/project semantics; custom task reads require
reviewed contracts. Sync does not trace arbitrary file access or acquire missing packages.

Linux ARM64 controls passed small graph build/replay, dependency invalidation,
output ownership, signing, package SDKs, tools, MTP/VSTest, generated packages and
HTTP cache faults/recovery. Cached/uncached sandboxed workers passed Build/Publish
parity and failure recovery on both Bazel baselines. Workers stage inputs privately
and publish only owned products. Graph actions consume NuGet archives and extraction
validation records, avoiding expanded package trees as redundant inputs.

Build/Restore tree handoff, producer edits, missing-input rejection and executable
success-status controls passed all four worker cases. A test expecting 100 rejects
zero. Owned .NET/style, scaffold and analysis checks passed. Commands:
`bash scripts/bazel.sh test //tests/integration:quickstart
//tests/integration:workers --test_output=errors --lockfile_mode=off`.
See [CONTRIBUTING](../CONTRIBUTING.md) for contributor checks.

Main 8d83f0f now repeats 481-node compilation and local recovery: all 3,622
compiled files matched raw bytes through no-op/body/API edits, with six/17 Csc
calls per edit. The paired cold build also matched all 3,622 files. Independent
HTTP recovery on a fresh relocated container reproduced all 10,780 files with
481 hits / zero misses while the producer was stopped and Bazel action caches
were disabled. Both containers passed 118,952 tests / 64 skips / zero
failures, with matching normalized outcomes and source-product hash checks.
Command: `python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE RESULTS
--slice runtime-suites --qualified-raw-results RAW --output-base BASE --samples 3
--reseed-worker --diagnostics --trim-between-rows`. See [timings](performance.md). Recovery command: `python3
tests/graph_build/upstream/runtime_remote.py WORKSPACE RESULTS --phase consumer
--slice runtime-suites --seed-evidence PRODUCER/seed.json --version 9.2.0
--diagnostics`.

Current graph-only NoTargets controls passed package-SDK resolution, missing SDK
rejection and producer-edit invalidation. Commands: `python3
tests/source_sdk/notargets_handoff.py INPUTS RESULTS --acquire` and
`python3 tests/graph_build/package_sdks.py --prepared-restore`.
Source-built SDK Pack, Razor rendering and framework-dependent Publish/run passed:
`python3 tests/source_sdk/consumer_scenarios.py RESULTS --sdk-bundle BUNDLE`.
The pinned previously produced component bundle supplies both the SDK archive and
its StaticWebAssets package: the archive alone omits that SDK's targets/tasks.
These controls were repeated after the publication/package-input changes. They
qualify consumers; they do not rerun the full SDK producer.

Graph NativeAOT Build/Publish/run, body-edit invalidation and missing-compiler
rejection passed on Linux ARM64. Stopped-producer recovery in a separate container
had **1 project hit / 0 misses**, reproduced the same ELF bytes and executed a
fresh Bazel test with Bazel action caches disabled. Command: `python3
tests/graph_build/native_aot.py INPUTS RESULTS --phase producer --cache URL
--acquire`; consumer uses `--phase consumer --seed-report PRODUCER/report.json`.
This producer/recovery series was repeated after the publication/package-input
changes on healthy independent filesystems, with the same ELF hashes.
SDK 10.0.400, AOT packages 10.0.11 and 34 locked Ubuntu packages supply the tools;
GNU linker scripts are relocated with the assembled package paths. This qualifies
the downloaded AOT packs, not a source-built AOT compiler or Linux x86-64/RBE.

Unchanged upstream `src/tests/JIT/CodeGenBringUpTests/Add1_ro.csproj` (#74)
passed on Linux ARM64 / Bazel 9.2.0 at the pinned runtime revision. The authored
external/test-dependency bootstrap, wrapper generator and private compiler remain
explicit inputs. `test_dependencies` is a graph root because Add1 shares its
assets; merely passing that assets file does not expand the required packages.
Raw and graph DLL/PDB matched. Raw corerun returned 100 with the installed SDK
absent; the generic Bazel adapter accepted 100 and rejected the intentional 101.
A fresh body edit reused two of three projects. Missing reference/compiler inputs
failed. Healthy stopped-producer HTTP recovery had **three hits / zero misses**,
matching products/runtime bytes and a fresh test execution. Disposable RAR cache
files are excluded, as in the runtime baseline. The disk-damaged consumer attempt
is excluded. This is one unchanged test, not a CoreCLR/JIT suite qualification.

Commands: `python3 tests/graph_build/upstream/runtime_jit_raw.py SOURCE FEED REFS RAW`,
then `python3 tests/graph_build/upstream/runtime_jit_prepare.py WORKSPACE RAW/workspace`
and `python3 tests/graph_build/upstream/runtime_jit.py WORKSPACE RESULTS
--phase producer --output-base BASE --raw RAW/workspace`. The consumer uses a fresh
workspace and `--output-base BASE --phase consumer --seed-report PRODUCER/seed.json`,
and digest-locked source-runtime product artifacts. Recovery covers its three
compilation projects, not another large-runtime build. Set the HTTP endpoint with
`RULES_MSBUILD_PROJECT_CACHE_URL`. Keep producer and consumer containers separate.

Next: reduce repeated evaluation/snapshot replay, then expand unchanged upstream
test slices. Main correctness/recovery/timings and the listed qualification gaps
are now refreshed; limits below still apply.

This is not whole-repository runtime support. Linux x86-64, macOS persistent workers,
RBE, arbitrary SDKs/workloads and full native build parity are unqualified.
Linux workers require Bubblewrap and nested user/mount/PID namespaces; ordinary
container defaults may block them. Project-graph isolation alone does not establish
filesystem hermeticity. Build trusted targets; keep reports outside Git and summarize
commands, outcomes and remaining limits when extending support.

Traversal qualification in progress: the pinned Microsoft.Build.Traversal 4.1.82
fixture has two coordinators and three compilations. Ordinary and graph-mode raw
MSBuild matched DLL/PDB bytes at stable paths on Linux ARM64 / SDK 10.0.400.
Command: `bash tests/integration/traversal_raw.sh SDK ARCHIVE FIXTURE RESULTS`.
Coordinators inherit a nonempty TargetPath but emit no assembly; their NuGet assets
are real Restore products. Public sync/build/cache qualification remains pending.
