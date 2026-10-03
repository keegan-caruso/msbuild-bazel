# Support and limits

The graph workflow is the sole backend. Baselines: SDK 10.0.400, Bazel 8.8.0/9.2.0.
Inputs, package inventories, generated products, tool layouts and output ownership
must be declared. MSBuild retains SDK/project semantics; custom task reads require
reviewed contracts. Sync does not trace arbitrary file access or acquire missing packages.

The cutover passed small graph build/replay, dependency invalidation, output ownership,
signing, package SDK, tool, MTP/VSTest and generated-package controls on Linux ARM64.
Both Bazel baselines passed sandboxed worker Build/Publish parity and failure recovery.
Prepared Restore and HTTP cache fault/recovery controls passed.
Native integration passed six Linux ARM64 cases (quickstart and cached/uncached
workers) across both Bazel baselines. Command: `bash scripts/bazel.sh test
//tests/integration:quickstart //tests/integration:workers`. With caching, body/API edits reused
2/1 of 3 projects; fresh sandboxed Build/Publish outputs matched. This is local
worker evidence; HTTP recovery remains covered separately.
Linux worker publication also passed cached/uncached Build/Publish, body/API,
failure recovery and owned-file parity across both baselines. Workers stage inputs
privately and move only owned products into the Bazel result; large-graph timing
of this change remains pending. Command: `bash scripts/bazel.sh test
//tests/integration:workers --test_output=errors --lockfile_mode=off`.
Graph actions consume NuGet archives and extraction validation records, avoiding
expanded package trees as redundant inputs. Offline/transitive package, prepared
Restore, hash rejection and native analysis controls passed; large timing is pending.
Contributor commands are in [CONTRIBUTING](../CONTRIBUTING.md).

Earlier graph qualification built **481 runtime v10.0.0 compilation nodes**:
3,622 compiled files matched raw MSBuild, 10,780 snapshots matched bytes/modes,
and eight suites passed **118,952 tests / 64 skips / zero failures**. A source-built
runtime ran apps/tests with the installed SDK absent; stopped-producer/relocated-consumer
HTTP recovery passed. This large series predates the graph-only cutover.
[Detailed evidence and retired workflows](https://github.com/keegan-caruso/msbuild-bazel/tree/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs)
remain at the recorded revision. [Performance](performance.md) uses that same baseline.

Main 8d83f0f now repeats 481-node compilation and local recovery: all 3,622
compiled files matched raw bytes through no-op/body/API edits, with six/17 Csc
calls per edit. Cold, independent HTTP recovery and suite refreshes remain pending.
Command: `python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE RESULTS
--slice runtime-suites --qualified-raw-results RAW --output-base BASE --samples 3
--reseed-worker --diagnostics --trim-between-rows`. See [timings](performance.md).

Current graph-only NoTargets controls passed package-SDK resolution, missing SDK
rejection and producer-edit invalidation. Commands: `python3
tests/source_sdk/notargets_handoff.py INPUTS RESULTS --acquire` and
`python3 tests/graph_build/package_sdks.py --prepared-restore`.
Source-built SDK Pack, Razor rendering and framework-dependent Publish/run passed:
`python3 tests/source_sdk/consumer_scenarios.py RESULTS --sdk-bundle BUNDLE`.
The pinned previously produced component bundle supplies both the SDK archive and
its StaticWebAssets package: the archive alone omits that SDK's targets/tasks.
This qualifies consumers; it does not rerun the full SDK producer.

Graph NativeAOT Build/Publish/run, body-edit invalidation and missing-compiler
rejection passed on Linux ARM64. Stopped-producer recovery in a separate container
had **1 project hit / 0 misses**, reproduced the same ELF bytes and executed a
fresh Bazel test with Bazel action caches disabled. Command: `python3
tests/graph_build/native_aot.py INPUTS RESULTS --phase producer --cache URL
--acquire`; consumer uses `--phase consumer --seed-report PRODUCER/report.json`.
SDK 10.0.400, AOT packages 10.0.11 and 34 locked Ubuntu packages supply the tools;
GNU linker scripts are relocated with the assembled package paths. This qualifies
the downloaded AOT packs, not a source-built AOT compiler or Linux x86-64/RBE.

Remaining priorities:

1. Refresh large-runtime correctness, recovery and timings after the cutover.
2. Reduce large-graph publication/staging and unnecessary Restore invalidation, with matched body/API controls.
3. Expand reviewed runtime slices and qualify platforms independently.

This is not whole-repository runtime support. Linux x86-64, macOS persistent workers,
RBE, arbitrary SDKs/workloads and full native build parity are unqualified.
Linux workers require Bubblewrap and nested user/mount/PID namespaces; ordinary
container defaults may block them. Project-graph isolation alone does not establish
filesystem hermeticity. Build trusted targets; keep reports outside Git and summarize
commands, outcomes and remaining limits when extending support.

Current qualification sequence: NoTargets and source-SDK Pack/Razor/Publish;
graph NativeAOT build/run/recovery; refresh 481-node correctness, independent
HTTP recovery and paired cold/body/API timings; use those diagnostics to remove
staging/Restore work; qualify unchanged `Add1_ro.csproj` from #74. Keep large
reports outside Git and update the measured summaries here after each slice.
