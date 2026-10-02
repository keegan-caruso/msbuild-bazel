# MSBuild project-cache extension on dotnet/runtime

## Scope

The test-only [project-cache probe](msbuild-project-cache-probe.md) now accepts
the upstream `System.IO.Pipelines` implementation project from dotnet/runtime
v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`). This macOS ARM64
run used SDK 10.0.400, `net10.0`, Release, and four MSBuild nodes. Its graph has
32 nodes: 30 configured projects and two coordination nodes. It includes the
Pipelines contract and implementation, other runtime libraries, CoreLib, source
generators, and ILLink tools. It is a managed library slice, not a whole-runtime
build or test run.

Runtime projects place outputs under repository-level `artifacts/bin` and
`artifacts/obj`, often with separate contract and implementation projects. The
probe now reads each node's evaluated `OutputPath`, `IntermediateOutputPath`,
and `TargetPath` for this profile. It snapshots the project output and
intermediate directories, resolves producer copies from evaluated target
paths, and fingerprints the produced assembly of each project reference.
Upstream projects were not changed. The production Bazel rules still use
per-project actions; this is an experimental MSBuild graph cache.

## Reproduce

Start from a disposable checkout of the revision above, without built outputs.
The run reported below used an existing source archive with SHA-256
`0a8e7607647578590f4231de18fe190c6254beb6553f54c0d852dcb3f371e38a`.
With SDK 10.0.400 and its required NuGet packages available:

```sh
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk \
  bash scripts/dotnet.sh build \
  tests/explicit_msbuild/cache_extension/AvaloniaProbe.csproj -c Release
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk \
NUGET_PACKAGES=/path/to/packages \
  python3 tests/explicit_msbuild/cache_extension/qualify_runtime.py \
  /path/to/disposable/runtime /path/to/new-results
```

The script restores all of the graph's target frameworks, seeds the cache,
removes produced files, replays, changes and restores one method body in
`ThrowHelper.cs`, compares the cached edit with a fresh no-cache build, then
replays from the derived snapshot. It writes commands' logs, graph reports,
and a compact `summary.json` under the results directory. Forcing `net10.0`
on `dotnet restore` is incorrect here: the graph also needs assets for
`net462`, `net472`, `net8.0`, `net9.0`, and `netstandard2.0` projects.

## Observed result

One fresh-source macOS ARM64 run produced these single-run wall times:

| Case | Hits / misses | Graph (s) | MSBuild (s) | Snapshot (s) | Wall (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Seed | 0 / 32 | 0.448 | 77.742 | 0.250 | 78.473 |
| Clean replay | 30 / 2 | 0.459 | 1.289 | 0.229 | 2.009 |
| Pipelines body edit | 29 / 3 | 0.457 | 3.844 | 0.227 | 4.561 |
| Edited no-cache control | 0 / 32 | 0.473 | 79.815 | 0.315 | 80.637 |
| Replay from derived snapshot | 30 / 2 | 0.467 | 1.287 | 0.232 | 2.018 |

The clean and derived replays reproduced all 30 seed manifests exactly. The
fresh run saved 770 owned files and four producer-linked copies. Its body edit
rebuilt only the Pipelines implementation; the separate contract assembly
remained byte-identical. The edited implementation DLL and all 172 captured
`artifacts/bin` files matched the no-cache control. Full intermediate manifests
did not match: MSBuild's assembly-reference caches, file lists, generated XML,
and other `artifacts/obj` bookkeeping changed during the independent build.
This limits the byte-equality claim to the stated outputs.

The no-cache control deliberately removes outputs and recompiles every node;
it is an output-parity control, not the cost of an ordinary warm MSBuild edit.
From the independently replayed output tree, a warm raw graph-mode MSBuild
baseline took **4.584 s**. The same body edit then took **4.360 s**, with one
Csc call. The command was:

```sh
dotnet build src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj \
  -f net10.0 -c Release --no-restore -graphBuild -m:4 \
  -p:TargetArchitecture=arm64 -p:TargetOS=osx \
  -p:UseLocalTargetingRuntimePack=false -p:RestoreUseStaticGraphEvaluation=false \
  -p:NuGetAudit=false -p:UseSharedCompilation=false -p:DebugType=portable \
  -p:RestorePackagesPath=/path/to/packages \
  -p:NetCoreSdkRoot=/path/to/sdk/sdk/10.0.400
```

The cached edit took **4.561 s**. At this
size and in these single runs, the cache plugin did not improve the warm edit
time relative to raw MSBuild; its large advantage was the clean output replay.

The same-path probe does not establish cross-path or remote-cache correctness,
and its input discovery is qualified only for this pinned slice.

## Expanded Pipelines test build

The same `runtime` profile also built the unchanged
`src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj` on
macOS ARM64. This entry has **42 graph nodes**, 38 configured and four
coordination nodes. Its test project has an authored
`SkipUseReferenceAssembly="true"` reference to the Pipelines implementation.
The profile was invoked with that project as `ENTRY_RELATIVE`; the source and
package inputs remained the same.

| Case | Hits / misses | Probe total (s) |
| --- | ---: | ---: |
| Seed after a raw test-project build | 0 / 42 | 58.895 |
| Clean replay | 38 / 4 | 2.427 |
| Pipelines body edit | 32 / 10 | 15.480 |
| Edited no-cache control | 0 / 42 | 97.352 |

The clean replay reproduced all 38 seed manifests: 953 owned files and ten
producer-linked copies. The body edit rebuilt five Pipelines target-framework
nodes and the test assembly; its other 32 configured nodes hit. The test DLL
changed as expected. All **232** captured `artifacts/bin` files, including
that test DLL, matched the fresh no-cache control. Intermediate manifests
differed as in the smaller graph.

A warm raw `-graphBuild` reversal took **14.596 s**; the matching body edit
took **13.233 s** with six Csc calls. The cached body edit took **15.480 s**.
These single runs show no edit-time advantage for the plugin on this test
graph. This section qualifies the **test build**, not test execution or a
source-built runtime host.

The existing Avalonia SimpleTheme qualification passed again with the probe
changes: clean and derived replay plus XAML, body, and API edits and controls.
The probe project built with no warnings and passed `dotnet format
--verify-no-changes`.
