# Current implementation and qualification

The active rules in `msbuild/defs.bzl` build one project at a time through
`tools/ExplicitBuild`. Bazel tracks inputs, schedules projects and caches
actions. MSBuild still handles SDK compilation. Builds no longer run a
whole-graph discovery, preparation or replay step.

An opt-in generic MSBuild graph runner now supports explicit input contracts,
Build/Publish target-result replay, public graph actions and executable tests.
Small independent Linux workers qualify shared project-cache recovery. A
128-project synthetic edit comparison is roughly at warm raw graph-mode MSBuild
time after removing repeated dependency traversal. Opt-in project sync now
emits package-free graph contracts. Configured outputs, custom restore layouts,
and offline package generation/replay pass small macOS/Linux ARM64 fixtures.
Rich sync mappings, stable Bazel worker paths, and existing feature/upstream
parity remain open;
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
