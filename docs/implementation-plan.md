# Current implementation and qualification

The active rules in `msbuild/defs.bzl` build one project at a time through
`tools/ExplicitBuild`. Bazel tracks inputs, schedules projects and caches
actions. MSBuild still handles SDK compilation. Builds no longer run a
whole-graph discovery, preparation or replay step.

An opt-in generic MSBuild graph runner now supports explicit input contracts,
Build/Publish target-result replay, public graph actions and executable/MTP/VSTest tests.
Small independent Linux workers qualify shared project-cache recovery. A
128-project synthetic edit comparison is roughly at warm raw graph-mode MSBuild
time after removing repeated dependency traversal. Opt-in project sync now
emits graph contracts with declared managed packages, persistent configuration
and project-based run/test selections. Package-free graphs retain qualified
library reference boundaries and runtime-copy bindings. Configured outputs, custom restore layouts,
and offline package generation/replay pass small macOS/Linux ARM64 fixtures.
Opt-in disposable offline Restore now evaluates package build/content assets.
Reviewed task documents, generated file inputs, graph-wide properties and
Web/Razor SDKs now have small-fixture evidence. Opt-in stable Linux paths qualify
relocated project-cache replay through 128 projects. Managed property-bound tool
closures, source-built analyzers and declared package SDK bootstrap pass focused macOS fixtures. The generated Orchard CMS contract
builds all 202 projects and replays 16,250 snapshot files exactly. Avalonia.Controls
also builds and replays its 11 configured builds. The runtime System.IO.Pipelines
managed implementation slice builds and replays 30 compiled nodes; its Linux test
consumer expands that to 38, with worker/native parity on Bazel 8.8/9.2 and
998 matching snapshot files/modes. A partial-replay initial-target fix and explicit
generator translations preserve equivalent raw compilation. The selected
Collections, Immutable and LINQ test roots expand to 55 compiled projects and
1,483 snapshot files, with 615 compiled-product files matching a complete-source
raw Build. See the [collections checkpoint](graph-cache-plan.md#collections-graph-checkpoint).
The selected threading test compilation also passes worker/replay/native parity
on both baselines: six compilation nodes, 292 snapshot files and 170 compiled
products matching complete-source raw Build. It does not build or execute a
source threading host. See the [threading checkpoint](graph-cache-plan.md#threading-compilation-checkpoint).
The sockets implementation/test roots further expand to 77 compilations and
1,937 snapshot files, with all 731 compiled products matching complete-source
raw Build and worker/native parity on both baselines. See the
[sockets checkpoint](graph-cache-plan.md#sockets-source-compilation-checkpoint).
The loaded-common roots expand the graph to 163 compilations and 3,980 matching
snapshot files on both Bazel baselines; all 1,447 compiled products match the
complete-source raw build. Reviewed translations and disposable ASN task scratch
preserve parity. See the [loaded-common checkpoint](graph-cache-plan.md#loaded-common-source-compilation-checkpoint);
its paired body/API medians are effectively equal / about 9% slower than raw;
a bounded graph-built corerun probe now passes with source-built native products,
SDK-absent execution and runtime-input test invalidation. Upstream suite execution,
an ordinary app and independent recovery remain open.
The platform roots also pass 9.2 worker/replay/native parity for 215 compilations;
all 1,498 compiled products match the complete-source raw Build. Bazel 8.8 controls
are pending. See the [platform checkpoint](graph-cache-plan.md#platform-graph-checkpoint).
The collections paired body/API medians have about 3% overhead / 9% advantage
versus raw graph MSBuild. The public Linux
[scorecard](graph-cache-plan.md#linux-pipelines-scorecard) measures body/API overhead
of about 20%/0% with read-only prepared packages; graph mode remains opt-in. Generated Publish and layout-provider
extraction pass focused
public-rule tests. Reviewed dependency contracts now let package/custom-target
graphs distinguish compiler references from analyzer/task implementations.
Reviewed SDKs can also declare a [separately authored compiler artifact](project-cache-migration.md#separately-authored-compiler-references).
Four- and six-compilation Linux fixtures preserve body/API and implementation-edge
parity, including explicit consumer selection across coordination frameworks.
Reviewed snapshots reject undeclared dependency DLL/PDB/XML copies;
upstream use and independent recovery remain separate qualification gates.
Orchard's body-edit follow-up reuses 201 projects and rebuilds one, with exact
compared output parity; timings and remaining gates are in
[performance](performance.md#reviewed-orchard-dependency-contracts).
Full upstream migration parity remains open;
the per-project rules remain the default. See
[graph-cache migration](project-cache-migration.md) for commands, measured scope,
and the remaining default-switch gates.

## Supported building blocks

| Capability | Contract and evidence |
| --- | --- |
| Local project-to-BUILD synchronization and explicit test/package mappings | [Generator and limits](project-sync.md), [upstream inventory](project-sync-upstream.md), [explicit sync contracts](project-sync-bindings.md), [generated upstream qualification](project-sync-upstream-qualification.md), [Http.Abstractions/Immutable baseline](project-sync-expanded.md), [complete generated HTTP graph](project-sync-http-full.md), [complete generated Immutable graph](project-sync-immutable-full.md), [independent generated-graph cache recovery](project-sync-remote-cache.md), [generated Orchard/Avalonia graphs](project-sync-broader-graphs.md), [everyday change controls](project-sync-mutations.md), [paired workflow costs](project-sync-workflow-costs.md) |
| Libraries, binaries, packages and explicit configuration | [Rule API](explicit-bazel-rules.md) |
| Configured dependency selection and private project references | [API and qualification](configured-graphs.md), [incremental reference boundaries](reference-invalidation.md) |
| Project facades and per-framework test suites | [Facade API](explicit-bazel-rules.md#project-facade), [test suites](bazel-test.md#tests-across-frameworks) |
| Executable, MTP and VSTest tests | [Test API and invalidation](bazel-test.md) |
| Opt-in Linux remote compilation and tests | [SDK-free ARM64 worker qualification](remote-execution.md) |
| Persistent compiler workers with stable input paths | [Linux workers](explicit-linux-workers.md), [path limits](orchard-stable-worker-paths.md), [stable-path prototype](stable-project-paths.md) |
| Declared MSBuild task tools and generation | [Tool bindings](explicit-tool-bindings.md), [generation](explicit-generation.md) |
| Project-built analyzers and target-result items | [Analyzers](project-built-analyzers.md), [target items](msbuild-target-items.md) |
| Restore inputs and package trees | [Shared Restore](explicit-restore-inputs.md), [project-specific prepared Restore](prepared-project-restore.md), [package borrowing](explicit-package-borrowing.md) |
| SDK-only application setup and tracked global.json | [SDK acquisition and defaults](development.md#using-the-rules-in-an-application), [committed quickstart and independent consumers](adoption.md) |
| Downloaded and source-built execution runtimes | [Shared runtime provider and Bzlmod acquisition](runtime-primitives.md#downloaded-and-source-built-runtime-providers) |
| Linux ARM64 Native AOT publish with local or declared native tools | [Runnable binary and declared-toolchain qualification](native-aot.md), [smaller archive and chiseled runtime check](native-aot-closure.md), [locked Ubuntu package inputs](native-aot-packages.md) |
| Friend assemblies and separate contract/implementation roles | [InternalsVisibleTo](internals-visible-to.md), [runtime primitives](runtime-primitives.md) |

These are bounded contracts. See each guide for rejected inputs and unsupported
combinations; availability of an API does not qualify every upstream project.

## Real-project qualification

- **Orchard:** full 202-project graph, runtime/assets, cache recovery and
  [performance measurements](orchard-explicit-performance.md).
- **NBGV, Avalonia and ASP.NET Core:** declared task/generation integration and
  selected upstream slices. See [NBGV parity](nbgv-parity.md),
  [Avalonia XAML](avalonia-xaml-subset.md),
  [Avalonia remote compilation](avalonia-remote-execution.md),
  [expanded Avalonia suites and Desktop](avalonia-expanded.md),
  [Avalonia edit/Headless/native-input controls](avalonia-correctness.md), and
  [ASP.NET Core graph](aspnetcore-large-graph.md). These are not whole-repository support claims.
- **dotnet/runtime v10.0.0:** eight selected suites, **118,952 passes / 64 skips**,
  raw/Bazel outcome parity and no installed runtime components loaded in the
  **96 observed processes**. A fresh independent consumer, with the producer
  stopped, recovered 281 managed actions, five native actions, 121 layouts and
  all eight test results from HTTP cache. See the
  [Pipelines extension](runtime-pipelines.md) for hashes and invalidation controls.
  The [source-only host](runtime-source-host.md) removes unused installed template
  binaries and gives the source-built framework its correct 10.0.0 identity.

## Performance

The [dependency input audit](dependency-input-audit.md) records artifact roles,
consumers and input reductions that preserve MSBuild semantics.

A [test-only MSBuild project-cache extension probe](msbuild-project-cache-probe.md)
qualifies graph-level cache hits on synthetic 3-202-project chains. Its
[Avalonia SimpleTheme slice](avalonia-project-cache-probe.md) checks a real
23-node graph, XAML/body/API edits, and raw MSBuild timings. The
[Orchard CMS slice](orchard-project-cache-probe.md) covers 403 graph nodes,
clean replay, a body edit, and runtime assets. The
[dotnet/runtime Pipelines slice](runtime-project-cache-probe.md) checks evaluated
artifact paths, separate contract/implementation projects, and a body edit.
These probes are not production rules.

See [performance](performance.md) for cold builds, warm edits and remote-cache
recovery versus raw MSBuild, with measurement conditions and detailed evidence.

## Limits and next work

The pinned baselines are SDK 10.0.400 and Bazel 8.8.0/9.2.0 (default 9.2.0).
The expanded runtime qualification used Linux ARM64 and Bazel 9.2.0. It does not
establish support for other platforms, the entire runtime repository, JIT stress,
source-built NativeAOT, Mono/WASM, cross-compilation or crossgen/R2R. A separate
[Native AOT publish](native-aot.md) uses the downloaded SDK and a declared,
hash-checked native toolchain archive. An independent compiler-free consumer
recovered its build from HTTP cache and executed a body edit locally. Native
products in that archive experiment were built locally in a declared namespace;
HTTP cache recovery alone does not qualify remote execution. The later
[locked-package Native AOT fixture](native-aot-packages.md#bazel-selection-and-remote-execution)
ran initial and body-edited generation actions remotely on an SDK-free ARM64
worker, while native package assembly remained local. Separate
[remote-execution qualification](remote-execution.md)
covers bounded managed fixtures and the expanded Avalonia slices on an SDK-free
ARM64 worker with Bazel 8.8.0 and 9.2.0.
See [platform scope](platform-validation-scope.md) and
[next steps](roadmap.md).

Older implementations and experiments are available through [history](history.md).
Use the [documentation index](index.md) for current guides.

## Source-built runtime application goal

A normal app now runs on a selected source-built runtime, including SDK-absent
execution, incremental controls and independent HTTP cache recovery. See the
[qualified workflow and scope](runtime-application.md).

The [Bazel-managed SDK migration](sdk-toolchains.md) records removal of host-path
SDK setup and the shared downloaded/source-produced artifact contract.

The [SDK source-build qualification](source-sdk.md) now builds the pinned
22-component graph on Linux ARM64, emits the SDK layout as declared component
outputs, runs an app with that SDK, and recovers all component actions and the
layout from an HTTP cache. This remains a pinned qualification;
general source-built SDK distribution and byte-identical output are open.
