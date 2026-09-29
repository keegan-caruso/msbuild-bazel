# MSBuild project-cache extension on Orchard

## Scope and reproduction

This test-only extension of the [Avalonia probe](avalonia-project-cache-probe.md)
builds Orchard Core at commit `04467a3438d4255627c1a478598a1585b3ff2947`.
The entry point is `src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj`, using
SDK 10.0.400, `net10.0`, Release, and four MSBuild nodes. The graph contains
202 configured build nodes and 201 outer coordination nodes. This is an
MSBuild graph build with per-project cache hits; the production Bazel rules
still build projects separately.

Use a disposable Orchard source copy at the commit above. With the pinned SDK
installed and the NuGet packages available, run:

```sh
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk bash scripts/dotnet.sh build \
  tests/explicit_msbuild/cache_extension/AvaloniaProbe.csproj -c Release
RULES_MSBUILD_DOTNET_ROOT=/path/to/sdk \
NUGET_PACKAGES=/path/to/packages \
  python3 tests/explicit_msbuild/cache_extension/qualify_orchard.py \
  /path/to/disposable/orchard /path/to/results
```

The script restores the CMS entry, deletes Release outputs in that disposable
copy, seeds a cache, replays from empty outputs, makes and reverts a body edit
in `OrchardCore.Abstractions`, builds the edited tree with and without the
cache, and replays from a derived snapshot after deleting the original seed.
It writes logs and `summary.json` under the result path. The setup-page smoke
creates `App_Data` in the source tree; the script removes it between builds to
keep build inputs stable.

## Observed result

One macOS ARM64 run with local SDK 10.0.400 and restored packages gave:

| Case | Hits / misses | Graph (s) | MSBuild (s) | Snapshot (s) | Wall (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Seed, empty outputs | 0 / 403 | 1.915 | 36.676 | 4.408 | 43.050 |
| Clean replay | 202 / 201 | 2.134 | 4.025 | 1.596 | 7.807 |
| Abstractions body edit | 201 / 202 | 1.978 | 4.909 | 1.628 | 8.589 |
| Edited no-cache control | 0 / 403 | 2.010 | 20.431 | 4.408 | 26.905 |
| Replay from derived snapshot | 202 / 201 | 2.048 | 4.306 | 1.587 | 7.991 |

The clean and derived replays each reproduced all **16,448** `bin/Release`
and `obj/Release` files byte-for-byte from the seed. The body edit changed
the Abstractions implementation but left its reference assembly unchanged;
only that configured project missed. Its own DLL, PDB, and reference assembly
matched a fresh no-cache build. The clean replay, edited cached build, and
edited control all served the setup page and three embedded static assets;
asset hashes matched between the two edited builds.

The body-edit control was **not** byte-identical across the whole graph:
752 of 12,800 compared semantic outputs differed, including six reference
outputs in `OrchardCore.Navigation.Core`, `OrchardCore.Navigation`, and
`OrchardCore.Taxonomies`. Orchard's interceptor generator uses `Guid.NewGuid()`
in generated class names, as described in the
[stable-path investigation](orchard-stable-worker-paths.md). The test checks
the edited project's exact outputs and runtime assets, and reports the wider
differences rather than treating them as cache equivalence proof.

For a raw MSBuild comparator, we started from the independently replayed
output tree, built once before the edit, made the same Abstractions edit, and
built again with:

```sh
dotnet build src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj \
  -f net10.0 -c Release --no-restore -graphBuild -m:4 \
  -p:NuGetAudit=false -p:RestorePackagesPath=/path/to/packages \
  -p:DebugType=portable -p:ProduceReferenceAssembly=true \
  -p:PathMap=/path/to/disposable/orchard=/_/workspace \
  -clp:PerformanceSummary
```

The warm baseline took **13.358 s** and the body edit took **12.437 s**, with
two Csc calls in each run. The cached edited build took **8.589 s**. These
are single runs with different starting conditions:
the plugin restores an empty Release tree from its seed, while raw MSBuild
reuses the warm output tree. They indicate the scale of the work but are not a
controlled speedup estimate.

Orchard requires the probe to snapshot all `obj/Release/<framework>` files,
including Razor/static-web-assets intermediates. Restoring only `bin` and
reference assemblies made a clean replay fail. Input discovery and this broad
intermediate snapshot remain specific to the pinned graph. The probe runs at
one local workspace path; this result does not establish cross-path replay,
remote-cache correctness, or a production Bazel integration.

The original 23-node Avalonia SimpleTheme qualification was rerun with this
probe: clean and derived replays hit all 17 configured nodes; XAML, body, and
API edit cases and their no-cache controls passed. `dotnet build` and
`dotnet format --verify-no-changes` also passed for the probe project.
