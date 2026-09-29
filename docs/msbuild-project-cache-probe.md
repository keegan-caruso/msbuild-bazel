# MSBuild project-cache extension inside a Bazel action

## Question and boundary

Can one Bazel action build a project graph while MSBuild's project-cache
extension skips unchanged projects? This experiment uses the public MSBuild
`ProjectCacheDescriptor` API, not the Microsoft MSBuildCache package. It is a
test-only probe under `tests/explicit_msbuild/cache_extension/`; the production
rules still use one Bazel action per project.
The [MSBuildCache implementation](https://github.com/microsoft/MSBuildCache)
is useful reference code for this extension API, but its file-access-based
input discovery is not part of this portable probe.

The probe accepts only generated, package-free `net10.0` C# chains. Each
project has one source directory, ordinary `ProjectReference` edges, Release
configuration and the pinned SDK. It rejects `PackageReference`. Its explicit
fingerprint includes the project file, top-level C# files, `global.json`, SDK
and configuration marker, and each direct dependency's reference assembly.
Its cache entry contains only the project's DLL, PDB, deps/runtimeconfig and
reference DLLs. A hit checks the fingerprint and every stored file digest
before MSBuild skips `Build`. The app's current dependency implementations
are copied into its output after the graph build. These assumptions are too
narrow for imports, generated sources, resources, analyzers, NuGet, native
assets, tests, Razor or arbitrary target outputs.

The original Bazel rule declares the sources, project files, SDK, probe
executable, `global.json` and a **fixed seed output tree**. The seed comes
from another Bazel target and can itself be recovered from the disk action
cache. A later [shared-cache experiment](project-cache-migration.md) removes
that fixed seed for bounded actions by storing project snapshots through a
Bazel HTTP cache service. It still needs a generic input/output contract
before it can replace the current rules. The extension's optional file-access
reporting is not used: the [MSBuild design](https://github.com/dotnet/msbuild/blob/main/documentation/specs/project-cache.md)
documents `/ReportFileAccesses` for Windows x64 MSBuild.exe, and that does not
establish a portable input-discovery mechanism for this `dotnet` probe.

## Qualification

Run from a checkout with pinned tools installed:

```sh
python3 tests/explicit_msbuild/cache_extension/qualify.py \
  --output /private/tmp/msbuild-cache-graph --sizes 3 16 64 202 --recover
```

Add `--raw` to measure raw incremental MSBuild in each generated graph. The
raw comparison below was measured with equivalent commands against the
202-project generated chain.

The script generates Base, body-edit and API-edit variants. For each edit it
builds a no-cache control and a seeded group, checks the app result and hashes
every project's owned output snapshot against the control. A body edit at P0
must miss once. Adding a public method at P0 must miss twice (P0 and P1); the
reference boundary stops further recompilation. `--recover` creates a fresh
workspace and Bazel output base, recovers the seed from disk action cache,
edits P0 again and checks its result.

Single-run Bazel **group-action times**, in seconds, on macOS ARM64 with SDK
10.0.400, Bazel 9.2.0 and `--jobs=2`:

| Projects | Body, no cache | Body, cache | API, no cache | API, cache |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 1.772 | 1.546 | 1.882 | 1.544 |
| 16 | 3.632 | 2.084 | 3.632 | 2.232 |
| 64 | 9.355 | 5.138 | 9.955 | 4.924 |
| 202 | 36.712 | 15.548 | 37.894 | 16.703 |

The 202-project body edit had 201 hits/1 miss; the API edit had 200 hits/2
misses. All owned output hashes matched the no-cache controls and both app
results were correct. The recovered 202-project seed was a disk-cache hit in
an independent workspace/output base; a new body edit then had 201 hits/1
miss and ran the updated app. In the cached 202-project actions, graph
construction took about 3.2-3.7 seconds and MSBuild's graph build about
1.1-1.4 seconds. Copying inputs, restore, output handling and process startup
account for most of the remaining action time.

The same command with `--sizes 3 16 --recover` passed in an Ubuntu 22.04
Apple Container on Linux ARM64 using the pinned SDK and Bazel. At 16 projects,
body-edit actions took 5.246 seconds without cache and 3.208 with cache;
API-edit actions took 5.145 and 3.047 seconds. The fresh-workspace disk-cache
recovery and app/output checks passed there too.

These are action timings, not end-to-end developer build times. Each variant
has a declared, already-built seed; producing or fetching that seed has a
cost. The chains are synthetic and much simpler than Orchard or dotnet/runtime.
No remote execution or remote-cache correctness is claimed.

For a separate raw-MSBuild control on the 202-project chain, an initial
`dotnet restore` and Release `dotnet build --no-restore -m:2` established the
incremental state in one directory. Copying the Body P0 source over Base and
running the same build took **13.089 seconds**; resetting to Base, then
copying the API P0 source and building took **15.333 seconds**. The command
also set `DisableTransitiveProjectReferences=true`, `Deterministic=true`, a
stable `PathMap`, `UseSharedCompilation=false` and `NuGetAudit=false`.
Logs and the timing JSON are under `/private/tmp/msbuild-cache-raw-202` on
the measuring host. This single-run raw control is faster than the cached
Bazel group action for both edits (15.548 and 16.703 seconds, respectively),
even before accounting for seed retrieval or Bazel overhead. The plugin
therefore demonstrates a saving against forced graph rebuilds, **not** a
developer-workflow speedup over raw MSBuild on this fixture.

## Decision

The extension can avoid repeated MSBuild project builds inside a graph action,
and the gain grows on a long chain. It does not make the grouped action a
production replacement yet. The [Avalonia qualification](avalonia-project-cache-probe.md)
expands this probe to a real XAML graph. It preserves the checked outputs but
leaves fixed-seed and input-discovery limits open. Next, choose how a prior
graph result is supplied without depending on a fixed Base target, and compare
with the existing per-project Bazel actions and raw MSBuild on edit workflows.
The [shared-cache migration](project-cache-migration.md) now exercises an
ordinary edit without a fixed seed. Keep the per-project rules as the default
until the cache and remote-execution contracts are preserved.
