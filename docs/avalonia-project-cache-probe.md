# MSBuild project-cache extension on an Avalonia graph

## Scope

This is a test-only expansion of the [synthetic graph probe](msbuild-project-cache-probe.md),
not a change to the production per-project Bazel rules. It uses Avalonia
11.3.12 (`37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`) and the
`Avalonia.Themes.Simple` graph with `net8.0`, Release, and
`AvsSkipBuildingLegacyTargetFrameworks=True`. MSBuild constructs and builds
the graph; a `ProjectCachePluginBase` implementation answers per-node hits.
The graph has 23 nodes: 17 compile/snapshot nodes and six coordination nodes.

The probe hashes project-local files, selected evaluated items, shared build
files, normalized restore assets, pinned NuGet package bytes, global properties,
and the selected reference or implementation artifact of each direct project
dependency. A hit checks every stored output digest before restoring the
project's `bin/Release` and reference outputs. After the graph finishes, the
probe updates copy-local DLL, PDB, and XML files from the current producers.
These are conservative inputs for this pinned graph, not a general MSBuild
input-discovery contract.

The Bazel experiment declares the source tree, 74 SHA-256-checked NuGet
archives, SDK, and probe binary. Each action copies the source tree into its
own workspace, restores from those archives, and builds the graph. Cached edit
actions consume a **fixed Base target** as their seed; clean controls have no
seed. This makes the comparison reproducible but does not solve how an ordinary
edited workspace obtains its previous result. The whole source tree is an
input to each grouped action, so this is not the production rule layout.

## Reproduce

From a checkout with the pinned SDK and Bazel 9.2.0, obtain the Avalonia
source revision above and restore the SimpleTheme project. Then prepare a
fresh workspace using the package directory populated by restore:

```sh
python3 tests/explicit_msbuild/cache_extension/prepare_avalonia_bazel.py \
  /path/to/avalonia /private/tmp/avalonia-cache-bazel "$NUGET_PACKAGES"
cd /private/tmp/avalonia-cache-bazel
bash /path/to/rules_msbuild/scripts/bazel-launcher.sh \
  build --jobs=1 --strategy=AvaloniaCacheGraphGroup=sandboxed \
  //:seed //:xaml //:xaml_control //:body //:body_control //:api //:api_control
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk \
  python3 /path/to/rules_msbuild/tests/explicit_msbuild/cache_extension/verify_avalonia_bazel.py \
  . /private/tmp/avalonia-cache-verification
```

For a same-path output comparison and raw MSBuild edit timings, build the probe
and run the qualification script on a separate Avalonia source copy:

```sh
bash scripts/dotnet.sh build \
  tests/explicit_msbuild/cache_extension/AvaloniaProbe.csproj -c Release
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk NUGET_PACKAGES=/path/to/packages \
  python3 tests/explicit_msbuild/cache_extension/qualify_avalonia.py \
  /path/to/avalonia-copy /private/tmp/avalonia-cache-qualification
```

The script restores the graph, applies and reverts each edit, and writes logs
and `summary.json` outside the checkout. It measures both ordinary MSBuild and
`-graphBuild` over the same SimpleTheme entry point.

## Observations

On macOS ARM64 with SDK 10.0.400 and Bazel 9.2.0, the same-path probe
produced the following hit counts. Every compile node's owned-output manifest
matched its no-cache control in that comparison. A clean replay had 17 hits and
six coordination-node misses.

| Edit | Hits | Misses | Probe wall (s) | Raw MSBuild edit (s) |
| --- | ---: | ---: | ---: | ---: |
| XAML style in SimpleTheme | 16 | 7 | 2.667 | 2.352 |
| Avalonia.Base method body | 13 | 10 | 4.541 | 3.281 |
| Avalonia.Base public API | 6 | 17 | 6.624 | 5.500 |

The raw numbers are single runs of `dotnet build -c Release -f net8.0
--no-restore -m:4` after a baseline build and reset between cases. The source
and NuGet packages were already local. They are a workflow comparator, not a
controlled performance distribution.

The final Bazel macOS `darwin-sandbox` actions had the same hit counts; each
clean control had 0 hits/23 misses. Single-run **action times** include source
copy, offline restore, graph evaluation, compilation/replay, and output staging:

| Edit | Cached action (s) | Clean control action (s) |
| --- | ---: | ---: |
| XAML | 6.797 | 18.594 |
| Body | 11.314 | 18.838 |
| API | 16.465 | 19.267 |

These are Bazel action durations, not the time to retrieve or build the seed
or a complete `bazel build` workflow. Every cached action was slower than the
corresponding raw MSBuild edit on this host. The output verifier found all
**17 reference assemblies byte-equal** to their respective clean controls for
each edit, matching embedded resource hashes and compiled XAML methods, matching
SimpleTheme runtime observations, and current copy-local producer bytes. Only
14 of 17 implementation assemblies were byte-equal across the separate action
paths; Avalonia-generated content in the others is path-sensitive. This does
not establish byte-identical full outputs or remote-cache portability.

The same Bazel experiment's seed and XAML edit succeeded in an Ubuntu 22.04
ARM64 Apple container using `processwrapper-sandbox`: 23 misses for the seed,
then 16 hits/7 misses. A Linux namespace sandbox was unavailable in that
container, so this does not qualify Linux filesystem hermeticity.

## API-edit phase profile

The earlier single-run API comparison had a 6.2-second gap between the
same-path probe and the probe inside a fresh Bazel action. We instrumented the
test-only action and probe to check that attribution. On macOS ARM64, one
seeded API action took **16.77 seconds**. Its measured wall phases were:

| Phase | Seconds |
| --- | ---: |
| Copy declared source into the action workspace | 1.33 |
| Copy pinned package archives | 0.12 |
| Offline restore | 1.64 |
| Probe process | 13.15 |

The small remainder is action setup and timing boundaries. The probe's own
report measured 0.30 seconds for graph construction, 12.70 for
`BuildManager.Build`, 0.04 for copy-local refresh, and 0.09 for output
snapshots. Package archive hashing took 0.10 seconds. Fingerprints accumulated
1.28 elapsed seconds across parallel cache callbacks, so that figure must not be
subtracted directly from wall time. Compilation is the main measured work:
another sandbox sample recorded 11 `CoreCompile` targets, with 18.35
aggregate target-seconds across concurrent nodes. A same-path run with task
events enabled recorded 11 `Csc` tasks and 16.59 aggregate task-seconds.

The graph scope matters. The ordinary raw `dotnet build -f net8.0` API edit
recorded **six** `Csc` tasks. A raw `dotnet build -f net8.0 -graphBuild` edit,
after a static-graph baseline, loaded the same 23-node graph and recorded
**11** `Csc` tasks. Both raw runs used `-clp:PerformanceSummary`; their edit
wall times were 8.92 and 9.25 seconds in separate one-sample sequences. The
probe builds `netstandard2.0` configurations for Avalonia.Base, Markup,
Controls, Markup.Xaml, Dialogs, and Remote.Protocol. That is real extra work
relative to the ordinary raw command, but compiler tasks overlap, so the count
alone does not quantify its wall cost. Those earlier one-sample times are
superseded by the matched graph-mode comparison below. The 17 owned-output
manifests from a profiled same-path API replay also matched its no-cache
control.

The 6.2-second **fresh-workspace penalty did not reproduce**: later same-path
probe runs took about 12.2 seconds, versus 12.2-13.1 seconds in the sandbox.
The earlier 6.6-second same-path result and its raw comparator were single
samples. These observations isolate staging/restore and identify compilation
as the main phase, but they do not establish a stable sandbox-path penalty.
To repeat the task breakdown, build `//:seed //:api` with
`--action_env=AVALONIA_TARGET_TIMINGS=1` and inspect `api.group/phase-times.log`
and `api.group/report.json`. The target/task totals are aggregate durations
across parallel work, not an additive wall-time breakdown. Task event logging
is opt-in because it can affect timing; use the ordinary probe for wall-time
comparisons.

## Matched static-graph comparison

The cache probe and raw `dotnet build -graphBuild` were run on the complete
**23-node SimpleTheme graph**, not the whole Avalonia solution. Both use the
pinned Avalonia revision, SDK 10.0.400, `net8.0`, Release, four MSBuild nodes,
and the same already-restored source/package directory on macOS ARM64. Each of
three qualification runs built a seed, then applied the XAML, body, and API
edits separately. The cache probe removed Release outputs and replayed its
seed snapshot before building each edit. Raw graph mode kept a baseline build
in place, built each edit incrementally, and reset the source with another
build. The qualification compared each cached probe result with its no-cache
control's owned-output manifest. These workflows process the same edits and
graph scope, but cache restoration and MSBuild's in-place incremental outputs
are different starting states.

| Edit | Probe wall median (range), s | Raw graph wall median (range), s | Raw graph `Csc` calls | Probe hits/misses |
| --- | ---: | ---: | ---: | ---: |
| XAML | 2.75 (2.69–2.99) | 2.64 (2.52–2.70) | 1 | 16/7 |
| Body | 4.48 (4.42–8.63) | 3.16 (3.14–3.17) | 2 | 13/10 |
| API | 7.07 (6.95–8.04) | 5.88 (5.87–6.01) | 11 | 6/17 |

The medians put the same-path cache probe about **0.10, 1.33, and 1.19
seconds slower** than raw graph mode for these edits, respectively. The first
body probe was a slow outlier, so the body delta is less stable than the raw
graph timing. `BuildManager.Build` accounted for medians of 2.27, 4.01, and
6.60 seconds inside the probe; graph construction and probe startup account
for most of its remaining wall time. This comparison excludes the source copy,
offline restore, and Bazel action overhead measured above. It does not show a
cache benefit over raw graph mode on these three edits.

### Body-edit dependency correction

The table above predates a correction to the test-only cache probe. Its
fingerprint treated a project-graph edge absent from the consumer's evaluated
`ProjectReference` items as an implementation dependency. The graph includes
transitive edges, so `Avalonia.Dialogs` acquired an implementation dependency
on `Avalonia.Base` even though it did not directly declare that reference.
The Base body edit changed both implementation DLLs but left both reference
assemblies byte-identical. Dialogs then had two avoidable cache misses and,
because the qualification removes Release outputs before replay, two avoidable
`Csc` calls. Raw graph mode kept the existing Dialogs outputs and made only
the two Base compiler calls.

The probe now uses implementation bytes only for evaluated direct references
marked as analyzer inputs or `ReferenceOutputAssembly=false`; an unmarked
graph edge uses the reference assembly. The full qualification passed twice
after this change, including output-manifest comparison against no-cache
controls for every edit. On the body edit, hits increased from **13 to 15**,
misses fell from **10 to 8**, and the timed probe made **two `Csc` calls**.
Two uninstrumented post-change body samples took **3.42 and 3.61 seconds**;
their paired raw graph runs took **3.18 and 3.04 seconds**. The earlier probe
median was 4.48 seconds across three runs, with one 8.63-second outlier.
The narrower fingerprint removes most of the measured gap, but does not show
a speed advantage over raw graph mode. This finding applies to the pinned
SimpleTheme graph; it is not a general dependency-discovery proof.

The graph's propagated `Build` target list includes ten `netstandard2.0`
nodes alongside seven `net8.0` nodes. Six Avalonia libraries have both
framework configurations; four tool/analyzer projects have a `netstandard2.0`
configuration without a `net8.0` counterpart. The API edit produced 11 `Csc`
calls in raw graph mode across all three runs, versus six in the earlier
ordinary MSBuild sample. A separate small fixture in
`tests/explicit_msbuild/cache_extension/qualify_graph_scope.py` confirms that
ordinary MSBuild builds only the needed `net8.0` library, while static graph
also builds its other framework. Setting `SetTargetFramework` on that
reference did not remove the extra static-graph build with SDK 10.0.400.
MSBuild's [static-graph design](https://github.com/dotnet/msbuild/blob/main/documentation/specs/static-graph.md)
describes this speculative framework edge behavior. Skipping every
`netstandard2.0` node in the cache plugin would also skip the tool/analyzer
projects that this build actually needs. Matching ordinary MSBuild's selected
framework work requires an execution path that resolves each reference's
configuration before scheduling it; the stock graph build does not provide a
safe framework-pruning switch for this probe.

## Decision and limits

The extension can skip substantial work in an actual Avalonia graph while
preserving the checked reference, resource, XAML, runtime, and copy-local
behavior. It remains experimental. The fixed seed, coarse source-tree action
input, full restore and staging for every action, path-sensitive generated
outputs, and incomplete general input discovery prevent replacing the
per-project Bazel actions. The edit cost must also be compared with raw
MSBuild rather than only with a forced clean graph rebuild.
