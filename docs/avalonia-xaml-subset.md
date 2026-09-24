# Actual Avalonia Simple theme graph

Revision 37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0 (11.3.12) now builds through the
explicit rules: 11 original projects, 1,979 evaluated source inputs and 71 locked
NuGet archives. The graph includes Avalonia.Base, Controls, Dialogs, Markup,
Markup.Xaml, Remote.Protocol, Themes.Simple, Build.Tasks and three analyzer/
generator projects. SDK 10.0.400 builds their original net8.0/netstandard2.0 targets.
`AvsSkipBuildingLegacyTargetFrameworks=True` skips legacy net6 targeting; the
fixture updates global.json to the qualified SDK. Project sources and XAML are
otherwise unchanged for the baseline. These settings also apply to raw MSBuild.

The fixture places sources beneath an `upstream` Bazel package to avoid the
collision between Avalonia's external/ directory and Bazel's reserved execroot
external/ directory. Actual upstream imports, analyzers, source generators,
resources, task-host declarations and XAML compilation remain enabled. There are
no Avalonia branches in production code. Fixture setup evaluates the selected
configuration once and emits explicit BUILD declarations; no discovery runs in
build actions. Build-only task edges and properties use the generic tool API.

## Results

On Ubuntu 22.04 ARM64 with four CPUs and Bazel 9.2.0:

- All eleven reference assemblies match raw MSBuild byte-for-byte, including the
  reference outputs after XAML compilation.
- Embedded-resource content and compiled XAML method identities match.
- The raw and Bazel runtime assemblies both construct SimpleTheme successfully.
- A real XAML edit adds a style: both runtime instances change from count 1 to 2.
  Exactly one Bazel assembly action executes. Reverting restores count 1.
- Runtime assembly bytes are recorded individually rather than assumed identical;
  debug paths and rewriting can affect implementation bytes.

[Parity evidence](avalonia-xaml-parity.json), [timings](avalonia-xaml-timings.json).

The initial clean-output build after restore took raw MSBuild 9.024 s and Bazel
37.024 s (Bazel-reported time, including analysis and package extraction). These
are single observations, not cold-machine medians. Restore setup took 5.812 s and
is outside those numbers. Subsequent warm no-ops measured raw 0.63–0.66 s and
Bazel 0.14–0.19 s; the first Bazel request after server restart was 4.287 s.
An uncached XAML edit measured raw 2.008 s versus Bazel 3.101 s; Bazel started its
compiler worker on this edit. Reverting to cached content took Bazel 0.193 s.

## Reproduction

1. Run `tests/explicit_msbuild/avalonia/setup.py <pinned-checkout> <fresh-folder>`
   in the qualified Linux environment. It restores/builds raw, inventories the
   selected graph and emits the Bazel fixture.
2. In `<folder>/bazel`, build `//upstream:benchmark` with four jobs, the
   MSBuildAssembly worker strategy and `--remote_download_outputs=all`. Use a
   dedicated output base and repository/disk caches.
3. Run `avalonia/verify.py <folder> <output-base>` for parity and runtime checks.
4. Run `avalonia/benchmark.py <folder> <output-base> [new-opacity-value]` for paired
   no-op and XAML edit checks. It rejects a cache-hit edit; choose a new opacity
   when reusing a fixture. It restores original XAML and shuts down Bazel.

The helpers live under tests/explicit_msbuild and are test scaffolding. This
qualifies the managed theme graph, not native rendering, UI automation, platform
backends, packaging or all Avalonia projects. The subsequent
[HTTP cross-container recovery](avalonia-http-cache.md) qualifies that additional
boundary for this selected graph.
