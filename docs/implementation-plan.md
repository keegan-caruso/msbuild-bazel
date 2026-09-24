# Current implementation and qualification

The active interface is explicit per-project BUILD declarations in
`msbuild/defs.bzl`, backed by `tools/ExplicitBuild`. Bazel owns declared inputs,
dependency scheduling and action caching; MSBuild retains SDK compilation.
There is no whole-graph discovery/preparation/replay step on this path.

## Supported building blocks

| Capability | Contract and evidence |
| --- | --- |
| Libraries, binaries, packages and explicit configuration | [Rule API](explicit-bazel-rules.md) |
| Executable, MTP and VSTest tests | [Test API and invalidation](bazel-test.md) |
| Opt-in Linux remote compilation and tests | [SDK-free ARM64 worker qualification](remote-execution.md) |
| Persistent compiler workers with stable input paths | [Linux workers](explicit-linux-workers.md), [path limits](orchard-stable-worker-paths.md) |
| Declared MSBuild task tools and generation | [Tool bindings](explicit-tool-bindings.md), [generation](explicit-generation.md) |
| Project-built analyzers and target-result items | [Analyzers](project-built-analyzers.md), [target items](msbuild-target-items.md) |
| Shared restore inputs and package trees | [Restore inputs](explicit-restore-inputs.md), [package borrowing](explicit-package-borrowing.md) |
| Downloaded and source-built execution runtimes | [Shared runtime provider and Bzlmod acquisition](runtime-primitives.md#downloaded-and-source-built-runtime-providers) |
| Friend assemblies and separate contract/implementation roles | [InternalsVisibleTo](internals-visible-to.md), [runtime primitives](runtime-primitives.md) |

These are bounded contracts. See each guide for rejected inputs and unsupported
combinations; availability of an API does not qualify every upstream project.

## Real-project qualification

- **Orchard:** full 202-project graph, runtime/assets, cache recovery and
  [performance measurements](orchard-explicit-performance.md).
- **NBGV, Avalonia and ASP.NET Core:** declared task/generation integration and
  selected upstream slices. See [NBGV parity](nbgv-parity.md),
  [Avalonia XAML](avalonia-xaml-subset.md) and
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

See [performance](performance.md) for cold builds, warm edits and remote-cache
recovery versus raw MSBuild, with measurement conditions and detailed evidence.

## Limits and next work

The pinned baselines are SDK 10.0.400 and Bazel 8.8.0/9.2.0 (default 9.2.0).
The expanded runtime qualification used Linux ARM64 and Bazel 9.2.0. It does not
establish support for other platforms, the entire runtime repository, JIT stress,
NativeAOT, Mono/WASM, cross-compilation or crossgen/R2R. Native products are built
locally in a declared namespace; HTTP cache recovery does not qualify remote
execution of that graph. A separate [remote-execution synthetic](remote-execution.md)
now passes on an SDK-free ARM64 worker with Bazel 8.8.0 and 9.2.0.
See [platform scope](platform-validation-scope.md) and
[next steps](roadmap.md).

Older implementations and experiments are available through [history](history.md).
Use the [documentation index](index.md) for current guides.
