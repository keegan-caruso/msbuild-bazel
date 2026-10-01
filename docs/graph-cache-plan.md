# Graph cache performance and qualification plan

## Objective

Qualify the graph-cache backend on dotnet/runtime, then build a selected runtime
from source and use it to run an ordinary app. Incremental body/API edits and
fresh remote-cache consumers are the primary cases. Orchard and Avalonia results
remain historical evidence; further expansion of those workloads is deferred.

The graph-cache path remains the primary development direction. Keep MSBuild
evaluation, SDK targets and project scheduling. Bazel declares
sources, packages, tools, configuration and outputs. Changes must remain generic;
upstream-specific declarations belong in qualification mappings. Keep graph mode
opt-in until correctness, capability and performance gates pass.

Start with runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
SDK 10.0.400 and Linux ARM64. Qualify both Bazel 8.8.0 and 9.2.0. The existing
30-project Pipelines graph result is macOS ARM64; its mapping must be evaluated
for Linux, not copied with `TargetOS=osx`. Older per-project native/app results
are useful contracts to transfer, not evidence for the graph backend.

## Execution rules

For each change: small correctness fixture, larger measurement, review, commit.
Push validated checkpoints. Record failed checks and remaining gates honestly.
Use pinned tools and upstream revisions. CI remains manual-only. Do not weaken
input verification or hide output differences to meet timing targets.

## Ordered work

1. **Pipelines on Linux.** Reproduce the generated managed graph with explicit
   Linux properties, offline packages, task-host SDK inputs, API validation and
   per-file shared-binplace ownership. Compare cold builds and complete replay
   outputs with the equivalent raw upstream command. Check native sandbox and
   sandboxed workers before relying on worker timings.
2. **Paired incremental baseline.** Capture three paired samples for no-op,
   implementation-body and public-contract edits. Runtime separates reference
   and implementation projects: edit the producer that actually owns each role.
   Require the expected hits, compiler calls, reference bytes and runtime copies.
   Include a test consumer using an implementation reference; a body edit may
   legitimately recompile that consumer. Compare ordinary and prepared Restore,
   including the read-only worker packages candidate.
3. **Larger managed scope and edit matrix.** Inventory configured nodes and
   expand from Pipelines through selected library/test roots toward the existing
   281-managed-action qualification. Compare equivalent roots/frameworks rather
   than assuming those action counts transfer to graph mode. Cover leaf and
   shared body/API edits, propagation stopping at unchanged consumer contracts,
   friend assemblies, generators, resources, packages and configuration changes.
   Do not prune authored frameworks just to improve a comparison.
4. **Remove measured overhead.** Profile the larger scope before choosing work.
   Measure evaluation, Restore/preparation, SDK/package hashing, transfers,
   materialization, compilation and final verification. Prioritize repeated work
   that can be removed: verified immutable preparation, SDK identity reuse and
   immutable evaluated information with complete invalidation keys. Reuse Restore
   on body edits; changed packages, imports, globs, RID/configuration, SDK/tools
   and executable modes must invalidate the appropriate preparation. Never retain
   target-mutated project instances. Measure COW and retained outputs before
   changing their defaults; smaller fixtures found little wall-time benefit.
5. **Upstream test execution.** Transfer the selected eight-suite qualification
   using runtime's actual test harness and source-built host. Preserve
   implementation references, test names/outcomes and deliberate failure checks.
   Dependency body edits must refresh runtime files and invalidate test results
   even when test compilation is cached. Report build and test times separately.
6. **Native construction and app.** Declare native sources, generators,
   compiler/build tools, headers, sysroot and configuration. Preserve upstream
   CMake/Ninja or make behavior through declared producers; the managed graph
   alone does not build native components. Compose the selected source-built
   CoreCLR/JIT, CoreLib, libraries and host into the existing runtime provider.
   Run an ordinary app without the installed runtime or build checkout and
   verify loaded binaries against their producers. Missing CoreCLR must fail.
   Exercise native source/header/tool changes and managed library/app edits.
7. **Independent recovery and faults.** At managed and runnable-runtime
   milestones, stop the producer and use an independent Linux consumer with
   empty local caches and a different external workspace path. Verify declared
   stable internal paths, exact files/bytes/modes and runtime/test outcomes;
   measure SDK/package acquisition separately. Exercise corruption, eviction,
   conflicts, concurrent writers and interruption. Repeat public Bazel 8.8/9.2
   native-sandbox and worker checks. ARM64 evidence does not qualify x86-64 or RBE.
8. **Readiness, then broader integration.** Review correctness, paired timings,
   transfer volume, disk and peak memory before switching defaults. Proposed
   targets remain warm edits within about 20% of equivalent raw MSBuild and fresh
   recovery clearly faster than rebuilding. These are targets, not results.
   Qualify the runtime/app milestone first; full runtime tests, other platforms,
   source-built SDK and source-built Native AOT are later expansions. SDK source
   construction is a separate integration, not something the runtime managed
   graph proves. Remove the old compilation backend only after parity qualifies.

## First execution checkpoint

Implement and commit these bounded pieces before expanding the runtime scope:

1. **Linux contract fixture.** Add reviewed Linux ARM64 mappings and shared
   binplace outputs for `System.IO.Pipelines/src`, then its test project. Reuse
   the generic sync and replay machinery; do not put runtime-specific behavior
   into production rules. Record every configured node and required bootstrap
   input. Pass Build, full local replay and worker/native-action parity on both
   Bazel baselines. Use fresh raw builds for parity controls; do not score them
   as ordinary incremental builds.
2. **Runtime edit fixture.** Add unique body and public-contract mutations plus
   restoration checks. Assert expected compilation, reference hashes and current
   implementation copies. Include the authored implementation-reference test
   consumer. Fail on extra rebuilds or an unchanged implementation after an edit.
   Do not hardcode the earlier macOS graph's project count for Linux.
3. **Paired Linux scorecard.** Extend the existing edit harness to invoke public
   Bazel graph actions and collect full wall time, worker preparation, runner
   phases and raw graph-mode commands. It currently measures the standalone
   runner, not full Bazel. Preserve diagnostic standalone rows separately.
   Report ordinary Restore and prepared read-only worker packages as separate
   candidates, not an assumed improvement. Commit the compact measured summary.
4. **Choose the next change from the profile.** Expand the same fixture using
   the selected roots in `tests/explicit_msbuild/runtime/subset_slices.json`:
   collections, threading, filesystem, sockets, then loaded-library/shim roots
   and Pipelines tests. Check each expansion before combining it. Profile the
   larger graph and select the largest removable repeated cost. Commit each
   optimization after its synthetic invalidation controls and paired upstream
   measurements pass. Keep or revert it according to wall-time benefit and cost.

The first checkpoint is complete when the Linux contract and edit controls pass
and the scorecard has comparable graph/raw no-op, body, API and cold rows, plus
local/remote recovery rows. Capability failures remain work items; they must not
be converted into omitted inputs, disabled validation or reduced upstream scope.

## Measurement contract

Start with one 4-CPU/8-GiB Linux ARM64 build VM and four MSBuild nodes, matching the
current runner's fixed `MaxNodeCount=4` and edit harness's raw `-m:4`. Use one graph
worker and a 4096-MB worker-cache budget; record that the budget does not cap all
process memory. Check host headroom and prevent other build VMs/jobs from
competing during a scored run. Stop the producer before the independent consumer
runs. If the scope exceeds the VM budget, choose a new matched configuration and
rerun the paired baseline rather than comparing unlike resource settings.

Hold compiler reuse, architecture, configuration, entry points and frameworks
fixed within each pair. Start with shared compilation disabled on both sides,
matching the existing harness; qualify compiler reuse as a separate candidate.
Use raw graph-mode MSBuild with the same configured roots. Show normal raw
MSBuild separately if desired; do not silently substitute it in a graph comparison.

| Case | Graph state | Raw comparison |
| --- | --- | --- |
| Warm no-op | Same inputs and warm Bazel server; whole graph action may hit | Warm outputs; no Restore |
| Body edit | Unique implementation edit; graph executes with project-cache reuse | Same edit and warm outputs; no Restore |
| API edit | Unique authored public contract/source edit; graph executes | Same edit and warm outputs; no Restore |
| Fresh local recovery | Fresh outputs; local project snapshots retained | Clean compilation with available SDK/packages |
| Fresh remote recovery | Independent consumer; empty local snapshots and outputs | Clean compilation in the same consumer configuration |
| Cold build | Fresh outputs and empty build caches; available SDK/package archives | Clean outputs; separately measured Restore and Build |

For no-op/body/API, capture three pairs and report medians and ranges. Use unique
edits and alternate graph/raw order to reduce cache-warmth bias. Also collect
three local-recovery samples; repeat independent remote and cold cases where
practical, and label any single observation. Restore sources and verify original
outputs after each series. Profile diagnostic runs separately; leave profiling
off in scored runs unless its measured overhead is negligible and applied equally.

Report complete Bazel wall time and runner phases. Include worker broker
preparation/materialization in the total; concurrent operation sums are not wall
segments. Record raw Restore separately and show total workflow cost as well.
Distinguish warm raw outputs from fresh graph outputs. Record hits/misses,
compiler calls, output parity, bytes/files hashed/copied/transferred, and peak
process/VM memory. Source acquisition, initial sync, SDK/package downloads,
native build, host composition and test execution each get separate measurements.
Separate whole-graph Bazel action-cache hits from project-cache hits. Include a
unique edited remote consumer that must execute the graph and recover unchanged
projects; an unchanged whole-action hit does not qualify project-level replay.

Proposed acceptance: body/API medians within about 20% of equivalent raw build
and fresh recovery clearly faster than clean rebuilding. Preserve the earlier
per-project edit results as a secondary baseline on matched scopes. Cold may be
slower, but report both Build-only and Restore-plus-Build ratios and review the
regression before expanding or switching defaults. Do not declare success from
hit counts alone. Record raw commands, candidate revision, pins and limits with
compact summaries; keep large logs/binlogs outside Git.

## Status

The generic optimizations already implemented are retained. The next work is
runtime qualification and measurement, not repeating completed synthetic work.

| Step | Current evidence | Remaining gate |
| --- | --- | --- |
| 1. Linux Pipelines | Implementation and test Build/replay/native parity pass on Linux ARM64, Bazel 8.8/9.2; 819/998 snapshot files | Broader runtime contracts |
| 2. Incremental baseline | Ordinary/prepared paired edits and independent project recovery pass | Larger edit matrix |
| 3. Larger scope | Collections: 61 configured / 55 compiled with paired edits; sockets: 84 configured / 77 compiled with full-source parity; threading/filesystem compilation pass | Shared/generator/resource edits, other slices and graph-backed tests |
| 4. Removed work | Shared CAS, ownership/path reuse, shared evaluation context and read-only worker packages | Runtime phase profile; safe cross-request SDK/evaluation reuse and large-worker timing |
| 5. Tests | Older source-only host: 118,952 passes / 64 skips | Graph-backed test builds/execution, source host and edit invalidation |
| 6. Native/app | Per-project source-built app and native inputs qualified | Transfer native producers and host composition; app runs on graph-produced outputs |
| 7. Recovery | Independent 8.8 producer / 9.2 consumer recovers all 38 Pipelines projects and exact 998 files; body/API recovery matches fresh native builds | Larger managed/native/app recovery and runtime faults |
| 8. Readiness | Graph mode remains opt-in | Runtime capability/performance gates; later SDK/AOT/full-repository expansion |

The worker still starts a fresh MSBuild child per request. Read-only preparation
avoids package copying and final package rehash, but each child still validates
SDK/package bytes. The bounded Linux scorecard measures this option; larger
graphs and runtime-host qualification remain open.
The completed disk cleanup removed older qualification containers after preserving
compact reports; recreate only the workers needed for the selected milestone.

## Partial replay checkpoint

The paired Linux test-graph body edit exposed an initial-target replay bug.
Snapshots retained explicitly requested results but omitted
`ProjectInstance.InitialTargets`. Runtime's `ValidateTargetOSLowercase` therefore
made nested MSBuild requests unsatisfied after cache hits. The diagnostic binlog
showed cached linker/reference projects recompiling and a cached generator
executing translation tasks. The failed body run is excluded from timings.

Snapshots now retain initial-target results alongside requested results, without
duplicates. Skipped initial targets count as completed under the same input and
dependency fingerprint. Changed validation imports or conditions still invalidate
those results. No project state is retained between MSBuild requests.

On the pinned Linux ARM64 SDK, `initial_targets.py` reproduces the old failure,
then passes cold Build, complete replay, consumer-only body replay, changed
validation inputs and a changed condition that deliberately fails. The ordinary
three-project replay and source-built analyzer controls pass; owned-code checks
and all 54 ProjectSync tests pass. Reproduce with
`RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/initial_targets.py`
after building GraphBuild. CI was not run.

The corrected runtime body diagnostic gets 32 hits/six misses, exactly six Csc
calls (five implementation frameworks plus the test consumer), and no translation
tasks in cached generators. Its profiled runner time is 22.87 seconds, including
4.75 seconds Restore, 0.71 evaluation, 2.07 input hashing, 14.51 execution and
0.76 final verification. Worker staging adds 0.44 seconds. This single diagnostic
is excluded from the paired scorecard.

## Complete generator inputs

The runtime fixture now declares the 13 checked-in Common/Resources XLIFF files
for LibraryImportGenerator, DownlevelLibraryImportGenerator and
Microsoft.Interop.SourceGeneration. The package discovers these files during
translation targets; they are not ordinary evaluated source items. Each binding
attests the exact owning csproj hash. Production rules have no runtime-specific
logic. Missing declared files fail sync; file edits participate in fingerprints.
Earlier cold builds could synthesize absent XLIFF files from English resources,
so their parity against similarly staged raw inputs was insufficient.

Fresh Linux ARM64 Build/replay/native controls with complete inputs pass on
Bazel 9.2.0 and 8.8.0: 38 misses for each cold build, 38 hits for each complete
replay, and identical 998 snapshot files/bytes/modes. A separate raw graph-mode
Build from the complete upstream source archive matches all 412 persistent
DLL/PDB/resource files byte-for-byte. Both builds use the declared SDK/packages,
four MSBuild nodes and the same internal sandbox paths. Raw output files are
writable; Bazel freezes tree outputs to 0555. No file content was normalized.
SDK PreTrim intermediates are omitted from that compiled-product comparison
because a normal raw no-op removes them; full graph replay/native controls still
compare the complete snapshot scope.

Reproduce with `runtime_prepare.py SOURCE_ARCHIVE PACKAGE_FEED NEW_DIRECTORY
--entry src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`,
then `runtime_qualify.py WORKSPACE NEW_RESULTS --output-base NEW_BASE` under the
pinned Linux ARM64 image. Raw uses `runtime_raw.sh` for matching internal paths.
The qualification harness stops completed Bazel servers to bound VM memory.
These are correctness controls, not scored cold-build medians. CI was not run.
The paired scorecard below covers body/API/cold; independent Pipelines recovery is recorded later in this plan.

## Linux implementation checkpoint

The Linux ARM64 Pipelines implementation graph builds through the public Bazel
8.8/9.2 sandboxed workers: 30 configured projects, 86 declared package archives and
108 shared output files. Complete local replay gets 30 hits, and its 819
snapshotted files match fresh native-sandbox builds on both versions, including
modes. The test-consumer graph also passes all controls: 42 configured nodes, 38 compilation nodes and 998 captured output files.

Fresh controls exposed three differing SDK `GenerateResource.cache` files.
These serialize resource-source modification times; the SDK documents their
[optional dependency-cache role](https://learn.microsoft.com/en-us/visualstudio/msbuild/generateresource-task?view=visualstudio).
Implicit snapshots now omit only the expected state file in the evaluated
intermediate directory. Explicit output declarations still take precedence.
Actual resources, satellite assemblies and DLL/PDB outputs remain captured.
A synthetic resource edit changes executed values, regenerates state on a miss,
and replays compiled resources without it. An explicitly owned cache-named file
also survives replay. The remaining 819 files match without normalization.

Reproduce with the commit-addressed runtime source archive (SHA-256
`4fae24371e108a046d7bfd30785e9a2f4400552b165b70300a72f855370da3de`),
the reviewed offline package feed and the pinned Linux SDK:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py SOURCE_TAR_GZ PACKAGE_FEED NEW_DIRECTORY
python3 tests/graph_build/upstream/runtime_qualify.py NEW_DIRECTORY/workspace RESULTS --output-base NEW_BAZEL_BASE
python3 tests/graph_build/resource_state.py
```

Build GraphBuild and ProjectSync first; set `RULES_MSBUILD_DOTNET_ROOT` and the
Bazelisk override for the pinned tools. Preparation validates the source archive,
restores only in disposable sync copies and stages only declared project inputs.
The parity fixture uses an unused declared nonce to force graph execution; its
runs are correctness controls, not performance samples. Owned .NET/style/unit
checks and the existing replay/output-ownership experiments pass. No CI ran.

## Outer-build input correction

The Linux test expansion exposed a language-dependent `Compile` placeholder on
an SDK cross-targeting dispatcher. Sync omits absent compiler placeholders only when
`IsCrossTargetingBuild=true` and no `CoreCompile` target exists. Configured inner
nodes still declare and validate every compiler input. Absent evaluated items
under an outer dispatcher's intermediate directory are also omitted: these are
inner-target output placeholders. Existing outer files remain declared and verified. Missing inner source files and
explicit reviewed task inputs retain their checks. The first public runtime test
build exposed the need to retain existing outer files; that failed run is not
qualification evidence.

`python3 tests/graph_build/sync.py` passes on Linux ARM64, including a two-framework
Build and rejection of a missing inner `Helper.cs`. This qualifies the generic
correction, including an outer intermediate placeholder. The runtime test
contract now synchronizes 42 configured nodes / 38 compilation nodes. Complete
Build/replay and shared-binplace ownership for that expanded graph now pass the
supported-version controls.

## Linux test-consumer checkpoint

The Pipelines test graph compiles all configured dependency frameworks, including
Pipelines net8/net9/netstandard/.NET Framework variants. Five reviewed testing
documents declare the runner template and runsettings template explicitly.
Mobile tool and shell-command items are evaluation metadata for this managed
Linux Build; this does not qualify mobile builds or coverage execution.

A raw graph Build passes with authored-framework Restore and the declared
`NUGET_PACKAGES` directory. Its post-build BinPlace inventory confirms the same
108 explicitly owned shared files. Public worker seed (0/38), replay (38/0) and
fresh native seed (0/38) match all 998 captured files/modes on Bazel 8.8/9.2.
These remain correctness controls, not scored timings or source-host test
execution. Reproduce using `runtime_prepare.py --entry
src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`, then
`runtime_qualify.py` as above. The runner and test-harness contracts are retained;
source-built-host execution remains step 5.

## Public graph diagnostics

`app_graph(..., profile_build=True)` enables runner operation totals and a
`report.binlog` without imported project payloads. Linux worker reports add
staging, child-process, output-verification and cleanup times. Worker totals do
not include Bazel's input staging or the protocol reply; full Bazel wall time
remains the score. Nested/concurrent runner operation totals can overlap.

Profiling defaults to false for ordinary actions, generated facades and prepared
Restore. The public worker controls on Bazel 8.8/9.2 pass default-off checks,
profiled replay with unchanged outputs/hits, failure recovery, property changes
and worker/native Build/Publish parity. Owned .NET checks and pinned Buildifier
checks pass. Scored runs keep profiling off; diagnostic compiler counts and
phase profiles are collected separately.

## Linux Pipelines scorecard

The public graph worker at production revision `129ce14` uses the reviewed
Pipelines test graph: 42 configured nodes / 38 compiled nodes, including all
five authored implementation/reference frameworks. Runtime v10.0.0, SDK
10.0.400, Bazel 9.2.0, Linux ARM64, four CPUs, 8 GiB, four MSBuild nodes,
shared compilation disabled. Prepared Restore and profiling are off.

Three alternating pairs preserve unchanged source timestamps and compare full
Bazel wall time against warm raw graph-mode Build, excluding raw Restore:

| Case | Graph median (range) | Raw median (range) | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.169 s (0.154–0.236) | 1.945 s (1.883–2.077) | Whole graph action hit |
| Body | 23.318 s (22.355–26.009) | 17.281 s (15.572–17.387) | 32 hits / six rebuilds |
| API | 27.912 s (27.593–29.092) | 21.058 s (20.800–21.961) | 27 hits / eleven rebuilds |
| Fresh local outputs | 9.669 s | Not paired with warm raw | 38 project hits; three forced graph actions |
| Cold compilation (one observation) | 114.088 s | 95.912 s Build + 1.638 s Restore | Zero hits / 38 rebuilds |

Body/API are about 35%/33% slower than raw; the 20% target is not met.
Cold has available SDK/packages, fresh outputs, empty project snapshots and
warm Bazel repository/bootstrap state. It is about 19% above raw Build alone
and 17% above Restore-plus-Build; acquisition is a separate setup cost.
Each pair matches 412 persistent DLL/PDB/resource files byte for byte. Body
changes implementation bytes and retains reference bytes; API changes both.
The authored test consumer uses implementation references and must rebuild on
body edits. Separate profiled binlogs confirm exactly six/eleven compiler calls
for both engines. Bazel freezes tree-artifact modes to 0555; raw leaves 0644.
Full worker/native correctness controls still compare all 998 snapshot files
and modes across Bazel 8.8/9.2. Twenty PreTrim intermediates removed by ordinary
raw no-op targets are excluded only from the persistent-product scorecard.

Raw uses `runtime_raw.sh` for the same stable SDK/workspace namespace, because
ILLink embeds intermediate PDB paths beyond compiler PathMap. No output bytes
are normalized. These timings exclude acquisition/sync and bootstrap setup. Add
`--prepared-restore` to preparation to reproduce the later candidate.
At 250 ms sampling, scored VM memory used peaks near 1.90 GiB with at least
5.98 GiB available; this is VM availability, not summed process RSS.

The separate body diagnostic spends 4.12 s on Restore, 0.73 s evaluation,
1.84 s initial hashing, 14.27 s execution and 0.80 s final verification.
Worker staging is 0.51 s. Cumulative hashing reads 3.93 GB in 25,156 calls;
operation totals overlap and are not additional wall segments. This points to
repeated Restore and immutable SDK/package verification as candidates, rather
than extra compilation. Prepared read-only packages remove repeated Restore and final package rehash.
The later candidate at production revision `369aab0` uses the same scope,
resources and harness, with three new alternating pairs:

| Prepared case | Graph median (range) | Paired raw median (range) |
| --- | ---: | ---: |
| No-op | 0.122 s (0.112–0.199) | 1.811 s (1.798–1.891) |
| Body | 17.823 s (16.724–20.564) | 14.846 s (14.698–17.446) |
| API | 22.124 s (21.567–22.640) | 22.125 s (20.849–22.320) |
| Fresh local outputs | 4.023 s | Not paired with warm raw |

All pairs still match 412 compiled products; separate diagnostics retain six/
eleven compiler calls for both engines and the same 32/27 hits. Body overhead
is about 20%; API is effectively equal to raw. Graph body/API medians fall
about 24%/21% from ordinary Restore, but raw body timing also varies between
series; use each candidate's paired raw comparison. This is a bounded slice,
not a larger-graph or default-switch gate.

The first unprofiled prepared cold observation is 184.683 s versus raw
106.393 s Build plus 1.635 s Restore: about 71% workflow overhead, despite
matching all 412 products. A separate diagnostic is 129.013 s versus raw
100.095 s Build plus 1.773 s Restore. Both engines invoke Csc 77 times across
38 projects, including 13 translated satellite compilations for each of three
generators. Diagnostic graph execution is 101.34 s; worker staging adds 4.35 s.
The diagnostic also rebuilds preparation after changing profiling mode. It is
excluded from scored timings. Two further unprofiled observations match all 412 products: 129.473 s versus
raw 109.010 s Build + 1.533 s Restore, with one preparation action; and
126.612 s versus raw 107.197 s Build + 1.909 s Restore, with preparation
cached. Both have zero project hits/38 misses, no package extraction or runner
bootstrap actions, and profiling off. These are about 17%/16% workflow overhead.
Do not combine differing preparation states into a median or drop the earlier
185-second observation. Cold variation remains a limit; the diagnostic explains
no extra compiler work and points to preparation and worker startup overhead.
The binlog reader now reports cumulative task durations; these overlap across
nodes and are not wall-time segments.

Offline Restore no longer includes project-cache transport configuration in
its Bazel action environment. Preparation never reads or publishes snapshots;
changing the cache URL had needlessly rerun it. A small endpoint-change control
reproduces that action miss before the fix and passes afterward on Bazel
8.8/9.2 workers with packages, plus a 9.2 native sandbox. Body edits and endpoint
changes execute zero preparation actions; changed build properties execute one.
Current program values, project hits and read-only package-write rejection still
pass. Reproduce with `linux_prepared_restore.py --worker --package --version
8.8.0 --directory NEW_DIRECTORY` under the pinned Linux SDK/Bazel overrides and
`RULES_MSBUILD_PROJECT_CACHE_URL`; repeat on 9.2 and without worker/package flags
for the native control. Scaffold/Starlark checks pass; CI was not run.

The prepared body diagnostic spends 1.87 s applying preparation, 0.84 s
on evaluation, 0.39 s initial hashing, 14.35 s execution and 0.10 s final
verification. Worker staging is 0.32 s. Cumulative hashing falls from
3.93 GB/25,156 calls to 2.60 GB/18,988 calls; SDK/package bytes are still
validated. Scored VM memory used peaks near 1.95 GiB. No-op differences between
series are too small to attribute to preparation.

That candidate exposed a generic package-SDK preparation bug: bootstrap selected
`NUGET_PACKAGES` after the environment had been fingerprinted. The runner now
selects its owned `.nuget` root before Create/Apply; environment validation remains
complete. `package_sdks.py --prepared-restore` reproduces the failure before the
fix and passes preparation/body reuse, authored NuGet.Config preservation and
missing-archive rejection afterward. `prepared_restore.py` also passes
input/package/config/environment invalidation, corruption and relocation controls.
Owned .NET checks, including 54 ProjectSync tests, pass on Linux ARM64.

`runtime_prepare.py --prepared-restore` now generates the separate Restore
contract for every configured node. The prepared Pipelines fixture passes seed
(0/38), replay (38/0) and native (0/38) with all 998 files/bytes/modes matching
across Bazel 8.8/9.2. Workers use read-only prepared packages; native rules copy
them into the owned workspace. The qualifier now sets `linux_worker=False` for
native controls, since changing only Bazel's strategy still invokes the worker
adapter for a single request. The paired candidate comparison above passes compiled-byte and compiler-count controls; broader qualification remains open.

Reproduce after `runtime_prepare.py ... --entry
src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`:

```sh
python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE --samples 3 --diagnostics
python3 tests/graph_build/upstream/runtime_cold.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE
# Preserve additional cold observations; profile diagnostics separately.
python3 tests/graph_build/upstream/runtime_cold.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE --sample 2
python3 tests/graph_build/upstream/runtime_cold.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE --profile
```

Use the pinned Linux image and tool overrides from the preparation checkpoint.
The first comparison accidentally rewrote an unchanged reference source and
made raw compile five extra projects. It and incomplete/mismatched-path runs
are excluded. Only the corrected complete series above is scored. Large logs,
binlogs and memory samples stay in disposable results; older per-project and
macOS probes remain in [performance](performance.md#runtime-backend-comparison).

## Independent Pipelines recovery

The Bazel 8.8 producer seeds a dedicated HTTP project cache, then stops. A new
four-CPU/eight-GiB ARM64 consumer runs Bazel 9.2 with a different external SDK,
repository and workspace path. Only input/tool bundles and seed hashes transfer;
producer outputs and local project/Bazel caches remain behind. Whole-graph Bazel
disk/remote caches are disabled. Each case must execute the graph action; edited
cases restart the broker so unchanged projects also recover through HTTP.

At the Restore-environment fix, three unprofiled recoveries with fresh output
bases reuse all 38 projects: median 21.383 s, range 18.434–22.675 s. The matched
consumer raw control takes 104.191 s Build + 1.808 s Restore (one observation),
about five times longer. Raw package expansion (3.513 s) and graph SDK/package/
runner acquisition are separate setup costs. Every recovery matches all 998
snapshot files/bytes/modes and the producer runner hash; raw matches the 412
persistent compiled products. This is managed Build, not test execution or a
source-built runnable runtime.

| Unique edited remote case | HTTP hits / rebuilds | Full Bazel time | Fresh native graph control |
| --- | --- | ---: | ---: |
| Body | 32 / six | 25.980 s | 118.383 s |
| API | 27 / eleven | 28.248 s | 120.214 s |

These edited rows are single observations with empty local snapshots, compared
against fresh native graph compilation, not warm raw edits. Both match all 998
files/bytes/modes. Body changes implementation bytes while retaining reference
bytes; API changes both. The earlier API observation was 41.188 s with a redundant
Restore action caused by cache URL changes. The fixed case executes none; its
execution phase also varies, so the entire difference is not attributed to the
removed action. Native controls invoke the native rule, not the worker adapter.

A separate diagnostic downloads 56.824 MB in 579 successful logical payload/
manifest transfers and uploads none. Its runner takes 3.64 s and broker staging
4.00 s; the 24.13 s full wall time also includes preparation after changing
profiling mode. Profiling is off in scored cases. Counters exclude retries and
HTTP framing; they are not wire-level byte counts. Earlier pre-fix recovery
(16.840 s) remains a separate observation, outside the current median.

Reproduce producer/consumer phases with `runtime_remote.py WORKSPACE NEW_RESULTS
--output-base NEW_BASE --phase producer|consumer`. Set the pinned SDK/Bazelisk
and `RULES_MSBUILD_PROJECT_CACHE_URL`. For the consumer add `--seed-evidence
SEED_JSON --edits`; `--raw-control` adds the matched raw cold Build and
`--diagnostics` adds a separate transfer profile. Use an independent resource-
matched Linux container and stop the producer first. The fixture pins scope to
38 compilation nodes and restores sources/BUILD files. Large logs remain outside
Git. Runtime fault injection, wider graphs, source-host tests and native/app
composition remain open. CI was not run.

## Historical report summary

These Orchard/Avalonia results explain completed work; they are not the remaining
upstream acceptance plan or a prediction of runtime timings.

### Performance

Orchard measurements use SDK 10.0.400 on macOS ARM64, four MSBuild nodes and
202 configured projects. Each body sample reuses 201 projects and rebuilds one.
Times below are three-sample medians. Graph recovery starts with fresh declared
outputs and local snapshots; raw MSBuild keeps warm outputs and excludes Restore.
These are standalone runner measurements, not end-to-end Bazel or remote timings.

| Measurement | Graph | Paired raw | Meaning |
| --- | ---: | ---: | --- |
| Initial body baseline | 36.80 s | 14.27 s | Includes Restore, hashing and recovery |
| Initial API baseline | 120.22 s | 81.75 s | Nine hits, 193 rebuilds |
| Shared-evaluation body, retained packages | 19.18 s | 13.45 s | Latest measured ordinary retained-package candidate |
| Body, fresh expanded packages | 23.27 s | 13.83 s | Offline Restore expands the declared package feed |
| Prepared Restore, fresh packages | 35.75 s | 13.49 s | Slower than ordinary Restore; remains opt-in |

The original baseline had slower filesystem reads. Attribute changes using the
closer controls: ownership indexing reduced 25.67 to 21.63 s; path/hash metadata
reuse then measured 21.04 s. Shared evaluation reduced evaluation/check time
from 4.46 to 4.09 s; its total 20.21-to-19.18 s change also includes faster reads.
Do not attribute the entire historical reduction to code changes.

Fresh-package time splits into Restore 8.84 s, evaluation/checks 4.11 s, hashing
4.54 s, execution 3.97 s and final verification 1.78 s. Prepared recovery spends
14.45 s applying preparation and 10.90 s verifying inputs. Phase medians need not
sum to the median total. The later read-only worker package change has correctness
evidence but no large-workload timing yet; include broker materialization and
full Bazel wall time when measuring it. These timings predate that change and
the inactive-item fix. The roughly 20% overhead target is not met.

COW reduced cumulative copying but had only a small execution-time effect
(3.54 to 3.36 s); the whole 20.23-to-19.21 s result also includes faster hashing.
All six comparisons matched outputs. Linux retained outputs reduced copying
from 128.34 MB to 1.86 MB on 128 projects, but body time was unchanged
(4.14 s fresh versus 4.15 s retained). Copy remains the default; retention is opt-in.

### Correctness and removed work

- **Orchard parity:** random interceptor names explain the captured 896 DLL/PDB
  path differences, including downstream copies. A disposable deterministic-name
  control eliminates them. The remaining two resource-cache JSON differences
  contain apphost timestamp hashes with identical empty discovered assets.
  Production outputs are not normalized. Later unmodified runs retain these
  differences; this is not a general byte-determinism claim.
- **Directory inputs:** declaring empty `wwwroot` fixes a separate, real
  static-asset discovery mismatch. Full Orchard body controls then match compared
  outputs. Directory existence participates in cache identity and final checks.
- **Snapshot storage:** shared CAS eliminates repeated payload storage/downloads.
  A measured inventory has 16,946 payload paths / 2.65 GB logical data but only
  3,423 blobs / 0.76 GB distinct content. This spans builds, not one recovery.
  A small remote check downloads 35 payloads instead of 44 per-snapshot requests.
- **Input checks:** ownership is indexed once; common path ancestors and fingerprint
  metadata are shared within a pass. Fresh final checks still reject changed
  bytes, modes, new symlinks and target mutations. Timestamps do not authorize reuse.
- **Evaluation:** one shared context per graph pass reduces repeated work.
  Skipping false-condition IDE items prevents Avalonia's disabled platform globs
  from scanning the filesystem root. New imports/globs and changed conditions
  still refresh. No target-mutated project is reused across requests.
- **Prepared packages:** live Linux workers retain verified private preparation
  keyed by complete Bazel input digests and manifest bytes. Each child validates
  payloads, then uses a read-only package mount, avoiding a workspace copy and
  final package rehash. Changed bytes with an unchanged manifest are rejected;
  absent protocol digests force a fresh copy. The cache budget covers preparation
  and snapshots; zero-budget eviction and interruption cleanup are checked.
- **Isolation:** each worker request gets a fresh workspace, MSBuild process,
  PID namespace and `/proc` view. Read-only package writes fail; mutable inputs
  retain final verification. Retained evaluated projects and task assemblies are
  not part of this implementation.

### Qualification

| Scope | Verified result |
| --- | --- |
| Independent Linux workers | Bazel 8.8 producer stopped; relocated 9.2 consumer with empty local caches gets three remote hits, then two hits/one miss after a body edit. Runner bytes and executed values match. |
| Native Linux sandbox and workers | Bazel 8.8/9.2 pass Build/Publish, failed-build recovery, property invalidation and parity against fresh native actions. Private PID isolation also passes generated-preparation and same-VM remote reruns. |
| Tasks and tests | Normal/out-of-process task hosts and native generator implementation/data/mode controls pass. Dependency body edits retain identical reference assemblies and cached test compilation, but MTP/VSTest rerun and observe the changed implementation. |
| Avalonia SimpleTheme | Revision `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`: 11 physical projects, 29 configured nodes, 23 compiled nodes, 81 pinned package versions. Fresh HTTP recovery gets 23 hits with matching compared bytes/modes. |
| Avalonia edits | XAML: 22 hits/one miss and runtime style count changes from one to two. Body/API: seven hits/16 misses each. Generator: five hits/18 misses. Each matches a fresh native control; `.AssemblyReference.cache` is excluded. |
| Package inventories | Explicit graph-wide multi-version inventories pass separate-version resolution and upgrade controls. Default locks and per-project consumers still reject ambiguous versions and conflicting declarations. |
| Integrity and faults | Corruption, eviction repair, permission restoration, concurrent local publication, interrupted transfers, owned-state SIGKILL recovery and input mutations have focused controls. HTTP conflict prechecks cannot guarantee atomic competing publication without server-side compare-and-swap. |
| Repository checks | Owned-code/style checks, 54 ProjectSync tests, 47 Bazel analysis tests and scaffold/Starlark checks pass at their recorded checkpoints. CI was not run. |

Linux evidence is ARM64 in Apple containers; it does not establish x86-64 or RBE
support. Native sandbox qualification requires the documented guest `/proc`
configuration. Avalonia results cover SimpleTheme and dependencies, not all
applications/tests/native deployment. The generic runtime runner still has only
the bounded managed Pipelines slice; older per-project native/runtime results do
not qualify the new graph backend. Full upstream tests/Publish and source SDK
remain open. See [migration contracts](project-cache-migration.md).

### Invalid runs and reproduction

The first fresh prepared-Restore series accidentally reused all 202 snapshots.
It is excluded; the corrected series uses distinct edits and
`--expected-misses 1`. A disk-full Orchard parity run and the interrupted Avalonia
tool case are also excluded. Sources were restored; their replacement controls
passed. Overlapping setup/correctness runs are not scored as performance results.

Use `tests/graph_build/upstream_edits.py ... --samples 3 --only body api --profile`
for paired edits, adding `--package-state fresh --expected-misses 1` for body-only
fresh-package recovery. `upstream/orchard_deterministic.py` and
`upstream/static_web_cache.py` reproduce parity attribution.
`upstream/avalonia_worker.py WORKSPACE RESULTS --output-base PATH` checks the
prepared SimpleTheme fixture; `--seed-evidence` and `--only` support independent
recovery and scenario reruns. Linux worker controls are `linux_worker.py`,
`linux_bazel_remote.py --graph-worker --spawn-strategy linux-sandbox`, and
`linux_prepared_restore.py --worker --package`. Test prerequisites remain in the
individual fixtures; use pinned sources and disposable workspaces.

Retained roadmap logs and comparisons live under `/tmp/graph-roadmap-*` on the
qualification host. Cleanup preserved compact older outcomes under the ignored
`artifacts/disk-cleanup-20260930/` directory. Neither is a durable public artifact.
This summary preserves the conclusions, rejected runs and limits;
[performance](performance.md#current-graph-cache-optimization-checkpoint) is the
short timing scorecard. The status table above lists the remaining work.

## Collections graph checkpoint

The selected Immutable, Collections and LINQ test roots retain 43 project files,
61 configured nodes and 55 compiled projects, including Immutable's authored
net10/net9/net8/netstandard2/net462 variants. The offline feed grows from 86 to
87 archives: pinned System.Runtime.Serialization.Formatters 9.0.0 supplies the
SDK API compatibility baseline. An altered supplemental archive is rejected
before sync. Mixed-framework selections such as `loaded-platform` fail with an
explicit per-entry configuration requirement; their frameworks are not flattened.

Expansion exposed undeclared RDXML inputs, COM generator translations and the
Interop API suppression file. The first complete-source raw comparison then
found ten differing LINQ DLL/PDB paths, including copies: a property-selected
linker descriptor was absent from staged inputs. Owner-bound declarations retain
API validation and linker behavior. With that correction, all 615 persistent
DLL/PDB/resource files match the complete upstream raw source build byte-for-byte.
Raw files are 0644 and Bazel tree files are 0555. No content was normalized.

Worker Build, complete project replay and fresh native-sandbox controls compare
1,483 snapshot files, bytes and modes on Bazel 8.8/9.2. Each cold control compiles
55 projects; replay recovers all 55. The reviewed shared-binplace map contains
222 files with unique owners, including the earlier Pipelines scope. The inventory
comes from SDK BinPlace targets after Build, not from an output directory scan.
The qualification driver uses the same MSBuild graph API with all three roots,
four nodes, shared compilation disabled and matching stable paths.

```sh
python3 tests/graph_build/upstream/runtime_prepare.py SOURCE_TAR_GZ PACKAGE_FEED COLLECTIONS --slice collections --prepared-restore
python3 tests/graph_build/upstream/runtime_qualify.py COLLECTIONS/workspace RESULTS --output-base NEW_BASE
python3 tests/graph_build/upstream/runtime_full_source.py SOURCE_TAR_GZ COLLECTIONS/workspace RAW_RESULTS
```

Use the pinned Linux ARM64 image and SDK/Bazelisk overrides from the earlier
checkpoint. `RuntimeRawGraph.cs.txt` also supports `binplace OUTPUT_JSON` after
its raw Build to reproduce shared output ownership. These are correctness
controls; their elapsed times are not paired performance results. Larger edits,
other managed selections, source-host tests and native composition remain open.
CI was not run.

## Worker process lifetime

The first collections body benchmark exited 137 after its six expected compiler
calls, without a kernel or cgroup OOM event. It is excluded from edit timings.
The exact SDK/runner and retained snapshots pass a separate sandbox reproduction:
49 hits/six misses, 22.46 seconds profiled, about 1.3 GiB peak VM use. This is a
standalone diagnostic, not a public Bazel timing.

Linux [parent-death signals](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)
track the creating thread. A retiring .NET thread-pool thread can therefore kill
bubblewrap while its worker process remains alive. A dedicated launch thread now
starts the sandbox, drains both output pipes asynchronously and waits for exit.
`--die-with-parent` and namespace isolation stay enabled. The dedicated thread
stays alive for the whole child lifetime; parent termination still kills it.

`RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/linux_process_lifetime.py`
reproduces exit 137 on creator-thread retirement, passes three dedicated launches
and verifies parent-death cleanup on the qualified Linux ARM64 VM. Public
prepared-package worker controls pass on Bazel 8.8/9.2: body reuse, cache transport
changes, configuration refresh, executed values and rejected package writes.
Owned tooling builds/style checks and 107 unit/fixture checks pass. The synthetic
probe tests process lifetime, not filesystem hermeticity or x86-64. CI was not run.
The larger paired scorecard is rerun with the corrected launcher.

## Collections incremental scorecard

Three paired Linux ARM64 samples use the qualified 55-project graph, four CPUs,
8 GiB RAM, four MSBuild nodes, SDK 10.0.400 and Bazel 9.2.0. Both engines disable
shared compilation. Raw builds all three configured roots in one MSBuild graph,
retains warm outputs and excludes Restore. Bazel uses a sandboxed worker with
prepared read-only packages, fresh action outputs and a 4096-MiB cache budget.
Whole-action remote/disk caches and profiling are off in scored edits.

| Case | Bazel median (range) | Raw graph median (range) | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.153 s (0.141–0.207) | 2.548 s (2.312–2.576) | Whole action hit |
| Immutable body | 24.285 s (23.148–24.655) | 23.615 s (22.758–24.645) | 49 hits / six misses |
| Immutable API | 26.818 s (25.284–30.360) | 29.481 s (29.135–29.791) | 44 hits / eleven misses |
| Fresh local outputs | 4.408 s (4.383–7.672) | Not a warm-raw comparison | 55 hits |

Body overhead is about 3%; API is about 9% faster by medians. Unique edits change
implementation bytes; body edits retain reference bytes and API edits change
both. All 615 compiled products match raw bytes after each edit and original
source restoration. Separate diagnostics confirm six/eleven Csc calls on both
sides. The implementation-reference test consumer legitimately recompiles.
Peak sampled VM use is 3.31 GiB across setup, scored and diagnostic runs.

The body diagnostic spends 1.87 s applying preparation, 1.03 evaluation, 0.45
initial hashing, 19.12 execution, 0.07 final verification and 0.03 saving snapshots.
Worker staging adds 0.29 s. Its full Bazel wall time is 24.37 s. API execution is
23.78 s, with 1.39 s preparation, 1.05 evaluation and 0.47 initial hashing; full
wall time is 28.05 s. Each diagnostic hashes about 2.75 GB in 21,214 calls.
Operation sums overlap these phases; they are not extra wall-time segments.
These profiles are excluded from the medians. SDK/package validation remains a
removable-work candidate; measured compilation dominates this larger edit.

Bootstrap/setup takes 278.66 s graph versus 143.80 s raw Build plus 4.35 s Restore.
It includes fresh Bazel package/runner/preparation actions and is not a scored
cold control. Retain the slow observation: matched cold measurements and
attribution remain required. The earlier interrupted body run is excluded; it
motivated the creator-thread lifetime correction above.

```sh
python3 tests/graph_build/upstream/runtime_benchmark.py COLLECTIONS/workspace NEW_RESULTS --output-base NEW_BASE --slice collections --diagnostics
```

Run after the collections parity controls with the pinned SDK/Bazelisk overrides.
The harness validates all roots and the reviewed mutation scope, alternates pair
order, restores sources and preserves memory data even for failed processes.
Raw uses `RuntimeRawGraph.cs.txt` for combined roots; optional binlogs are only
used for diagnostics. This qualifies a selected managed build, not source-host
test execution, native construction, independent collections recovery or x86-64.
CI was not run.

## Threading compilation checkpoint

Both reviewed threading test roots build from the pinned source and an offline
89-archive feed. RemoteExecutor 10.0.0-beta.25509.106 and its ClrMD 1.0.5
dependency are hash-pinned; their versions come from upstream declarations.
The existing SDK-derived shared-output map covers all 15 shared files.

This slice has five project files, seven configured nodes and six compilation
nodes. Its tests use installed framework references: it does not build a
source threading runtime. All six worker/replay/native controls pass on Bazel
8.8/9.2, comparing 292 snapshot files/bytes/modes. All 170 DLL/PDB/resource
files match a raw Build from the complete upstream source. Test execution and
source-host composition remain open; these controls are not scored timings.

Reproduce with `runtime_prepare.py SOURCE FEED THREADING --slice threading
--prepared-restore`, then `runtime_qualify.py THREADING/workspace RESULTS
--output-base NEW_BASE`. `runtime_full_source.py SOURCE THREADING/workspace
RAW_RESULTS --inventory-only` builds complete source and inventories SDK
BinPlace ownership before graph qualification. The raw driver now checks its
configured-node scope against the declarations; deliberately mismatched counts
and selected properties fail before Build. CI was not run.

## Filesystem compilation checkpoint

The selected filesystem test root retains five project files, seven configured
nodes and six compilation nodes. Its authored Restore closure adds five pinned
packages to the offline feed (94 archives), including Windows dependency variants
and SDK API baselines. None of the authored frameworks were pruned.

All six worker/replay/native controls pass on Bazel 8.8/9.2, with 271 identical
snapshot files/bytes/modes. A complete upstream raw Build matches all 153
DLL/PDB/resource files, including complete declared output directories. SDK
BinPlace inventory is covered by the existing shared-output owners.
Reproduce using the threading commands above with `--slice filesystem`; tests
compile against framework references, so source-host execution remains open.
These are correctness controls, not scored timings. CI was not run.

## Collections cold controls

Two unprofiled Linux ARM64 controls keep the 55-node compilation scope and
4-CPU/8-GiB configuration above. SDK/package archives and Bazel bootstrap are
available; outputs and project snapshots are fresh. Both compare all 615
compiled-product bytes exactly and execute all three roots in one raw graph.

| Preparation state | Bazel | Raw Build | Raw Restore + Build | Observations |
| --- | ---: | ---: | ---: | ---: |
| Prepared Restore executes | 179.146 s | 142.596 s | 147.122 s | One |
| Prepared Restore retained | 165.985 s | 153.260 s | 157.397 s | One |

Workflow overhead is about 22% / 5%; Build-only overhead is about 26% / 8%.
Different preparation states and raw variation prevent a combined median.
The retained-preparation sample peaks at 3.11 GiB VM use for Bazel and
2.78 GiB for raw, sampled every 250 ms. The first sample has no memory series.
Neither observation includes SDK downloads or the earlier 278.66-second
bootstrap/setup. No runner bootstrap or package extraction action executes.

`runtime_cold.py COLLECTIONS/workspace SCORECARD --output-base SCORECARD_BASE`
now restores every configured root and uses the combined SDK graph driver.
`--sample 2` preserves the first observation; `--profile` records a separate
diagnostic excluded from scored controls. CI was not run.

The separate diagnostic matches 107 compiler calls by project/framework on both
engines. Graph execution is 152.39 s versus 151.22 s raw Build. Runner preparation
application/evaluation/input hashing take 1.75/1.10/0.48 s; final verification and
snapshot saving take 0.08/0.27 s. Worker staging adds 3.63 s and the child takes
156.24 s. Full Bazel wall time is 182.02 s, including a newly executed prepared
Restore action and startup. Snapshot saving is not the dominant cost. Csc task
duration sums are 207.97 s graph / 207.05 s raw; concurrent task sums are not wall
segments. This diagnostic is excluded from scored observations.

## Sockets source compilation checkpoint

The sockets implementation and functional-test roots retain 58 project files,
84 configured nodes and 77 compilation nodes. The offline feed has 96 pinned
archives, adding DiagnosticSource's 9.0.0 API baseline and upstream Templating
10.0.0-beta.25509.106. SDK BinPlace inventory adds 97 shared files; the combined
Linux map has 319 files with unique project/framework owners.

DiagnosticSource's authored `ThisAssembly.cs.in` is owner-attested. The first
staged worker then fails with duplicate `Dns.GetHostName` on NameResolution's
browser variant, while complete upstream source builds. Its property-selected
`ExcludeApiList.PNSE.Browser.txt` was missing. That input is now declared only for
`net10.0-browser` compilation and does not change prepared Restore inputs. The
browser framework and its normal PNS generation remain enabled.

The corrected worker matches all 731 DLL/PDB/resource files from the complete
upstream raw Build. All six worker/replay/native controls pass on Bazel 8.8/9.2. Each cold control compiles
77 projects; replay recovers all 77. The controls compare 1,937 snapshot files,
bytes and modes. These are compilation controls, not scored timings or executed
source-host tests. CI was not run.

Reproduce the earlier qualification commands with `--slice sockets`. Use
`runtime_full_source.py SOURCE WORKSPACE RAW_RESULTS --inventory-only` first to
reproduce SDK output ownership. The bindings are fixture declarations; production
rules contain no runtime-specific cases. Other source libraries, the larger edit
matrix, native composition and source-host execution remain open.

## Loaded-common source compilation checkpoint

The four reviewed `loaded-common` roots select Pipelines, Text.Encodings.Web,
Text.Json and ComponentModel.Primitives. On Linux ARM64 the graph contains
91 project paths, 182 configured nodes and 163 compilations, retaining authored
net10/net9/net8/netstandard/net462 variants and Roslyn generator configurations.
The offline feed has 162 verified archives. SDK BinPlace discovery added 245
required shared files to the Linux ownership mapping; the mapping now names
564 files across the qualified scopes.

Using SDK 10.0.400, four MSBuild nodes and the 4-CPU/8-GiB build VM,
`runtime_qualify.py` passed worker seed, complete local replay and fresh native
sandboxing on Bazel 9.2.0 and 8.8.0. Every control returned exactly 3,980 output
files with identical bytes and executable modes. Seeds had 163 misses; replays
had 163 hits. All 1,447 DLL/PDB/resource products matched the complete-source raw
SDK graph control. These runs establish correctness, not paired performance.

Two failures exposed missing contracts. The first omitted 13 Text.Json
source-generator XLIFF files and changed 169 satellite/copy products. Reviewed
project documents now declare those translations. The second found 47 optional
ASN intermediate-file differences between worker and native builds, with no
compiled-product differences. Parallel frameworks touch the same checked-in C#
files; subsequent transforms may skip their `asnxml` scratch output. The mappings
now declare 13 configured scratch directories through the generic temporary-output
contract. Only two or three existed in each fresh build; cleanup produced the
same final output set. Scratch is excluded from dependency fingerprints and
snapshots, and inputs are still verified before cleanup. ASN XML/XSL edits that
rewrite checked-in C# remain unsupported pending a declared generation contract.

Reproduce in a fresh owned directory with pinned source and package archives:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py "$source_archive" "$feed" "$prepared" --slice loaded-common --prepared-restore
python3 tests/graph_build/upstream/runtime_full_source.py "$source_archive" "$prepared/workspace" "$raw_results" --inventory-only
python3 tests/graph_build/upstream/runtime_qualify.py "$prepared/workspace" "$results" --output-base "$output_base"
```

The complete-source control retains raw outputs for byte comparison. Private
reports include both failed attempts and the passing six-control matrix; only
this summary is committed. Owned .NET style/build checks and all 107 unit tests
pass. Separate focused controls qualify temporary-output dependencies and rejection.
Body/API paired timings, broader edit types, source-host execution and independent
recovery of this larger graph remain open.
