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
and `summary.json` outside the checkout.

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
corresponding raw MSBuild edit on this host. The output verifier found all **17 reference
assemblies byte-equal** to their respective clean controls for each edit,
matching embedded resource hashes and compiled XAML methods, matching
SimpleTheme runtime observations, and current copy-local producer bytes. Only
14 of 17 implementation assemblies were byte-equal across the separate action
paths; Avalonia-generated content in the others is path-sensitive. This does
not establish byte-identical full outputs or remote-cache portability.

The same Bazel experiment's seed and XAML edit succeeded in an Ubuntu 22.04
ARM64 Apple container using `processwrapper-sandbox`: 23 misses for the seed,
then 16 hits/7 misses. A Linux namespace sandbox was unavailable in that
container, so this does not qualify Linux filesystem hermeticity.

## Decision and limits

The extension can skip substantial work in an actual Avalonia graph while
preserving the checked reference, resource, XAML, runtime, and copy-local
behavior. It remains experimental. The fixed seed, coarse source-tree action
input, full restore and staging for every action, path-sensitive generated
outputs, and incomplete general input discovery prevent replacing the
per-project Bazel actions. The edit cost must also be compared with raw
MSBuild rather than only with a forced clean graph rebuild.
