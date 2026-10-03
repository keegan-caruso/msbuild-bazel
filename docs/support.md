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

NoTargets **3.7.0** public sync passed on Linux ARM64 / Bazel 8.8 and 9.2:
`.proj` and `.csproj` roots, nested Traversal, prepared Restore, explicit text
products, cached/uncached workers and downstream invalidation. Raw ordinary/graph
DLL/PDB and product bytes matched; three project snapshots replayed. A text edit
reused the library while regenerating producer/consumer products; a dependency
body edit changed both copies. Missing SDKs/products, unreviewed targets and
compiler-reference misuse failed. Command: `bash scripts/bazel.sh test
//tests/integration:notargets`. This slice qualifies Build with explicit file
products, not arbitrary task side effects or NoTargets Pack/Publish pipelines.
Independent HTTP recovery on both pins had three hits / zero misses and matched
all 30 compared output files/modes with the producer stopped and Bazel action
caches disabled. Run `//tests/integration:notargets_remote_cases_bazel_8_8_0`
(or `_bazel_.bazelversion` for the default), setting `NOTARGETS_CACHE_PHASE=producer`
and `NOTARGETS_CACHE_URL`; stop that container, then use a fresh consumer with
`NOTARGETS_CACHE_PHASE=consumer` and `NOTARGETS_CACHE_SEED` pointing to producer.json.

Worker SDK public sync passed on Linux ARM64 / Bazel 8.8 and 9.2 with SDK
10.0.400 and Hosting 10.0.11. `//tests/integration:worker_sdk` covers ordinary/graph
MSBuild DLL/PDB parity, root/element SDK declarations, Build/Publish, configuration
and body/API edits, bounded execution, failure recovery and the unchanged SDK
Worker template. Package/content projects retain conservative dependency keys;
the bounded fixture explicitly reviews its standard managed reference boundary.
Both pins recovered 65 compared files/modes with two hits / zero misses in a
fresh container while the producer was stopped and Bazel action caches disabled.
Run `//tests/integration:worker_sdk_remote_cases_bazel_8_8_0` (or
`_bazel_.bazelversion`), with `SDK_CACHE_PHASE`, `SDK_CACHE_URL` and consumer
`SDK_CACHE_SEED` pointing to the matching producer.json. These are small correctness
controls, not a large Worker-service or workload qualification.

Earlier source-built NoTargets controls cover package-SDK resolution, missing SDK
rejection and producer-edit invalidation: `python3
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

## Traversal projects

`Microsoft.Build.Traversal` **4.1.82** is pinned in the native fixture:
two coordinators, three compilations, SDK 10.0.400 / Linux ARM64, Bazel
8.8.0 and 9.2.0. Coordinators inherit TargetPath without emitting assemblies; they keep their Restore assets
and execute normally while descendants use project snapshots.

`bash scripts/bazel.sh test //tests/integration:traversal` covers public sync,
prepared Restore, sandboxed workers, nested/duplicate/wildcard/conditional
references, property propagation and multi-target children. Ordinary and graph
MSBuild match DLL/PDB bytes at stable paths. A body edit compiles one project
(two hits); an API edit compiles three (zero hits), matching raw graph MSBuild.
No-op executes no graph action; body/API edits reuse the Restore action.
Pack payloads (nuspec/library files), exports and snapshot replay pass; Publish
matches raw bytes and runs/tests the children with cached and uncached workers.
Declare Pack files in mappings `outputFiles`; tests remain explicit Bazel targets.
Independent HTTP recovery on both Bazel pins had three hits / zero misses with
the producer stopped, matching all 52 compared output files and modes and
executing a fresh Bazel test. Disposable RAR caches are excluded.
For independent recovery, run the native
`//tests/integration:traversal_remote_cases_bazel_8_8_0` test (or
`//tests/integration:traversal_remote_cases_bazel_.bazelversion` for the default). Set
`TRAVERSAL_CACHE_PHASE=producer` and `TRAVERSAL_CACHE_URL`; stop that container,
then run in a fresh one with `TRAVERSAL_CACHE_PHASE=consumer` and
`TRAVERSAL_CACHE_SEED` pointing to the matching producer.json. Keep reports outside Git.

Sync rejects missing projects/SDKs, unsupported coordinators, dynamic skipping,
per-reference target filters/overrides and TraversalPublishGlobalProperties.
In the pinned SDK, Build=false skips a child in ordinary MSBuild but graph mode
still builds it. Use conditional ProjectReference items and explicit graph
properties instead. Arbitrary traversal SDKs/custom extensions are unqualified.
