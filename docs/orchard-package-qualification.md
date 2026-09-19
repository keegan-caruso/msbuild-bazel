# Orchard input scoping and NuGet action qualification

Completed in the requested order: **2 → 1 → 3 → 4 → 5**.

## Changes

1. Compile actions use validated per-project structural inputs, including linked
   resources, imports, graph-wide inputs and dependency closures. Resource edits
   avoid unrelated compilations. Legacy layouts remain conservative.
2. Orchard static assets and generator invalidation are qualified with rendered
   output checks and changed generated types in real consumer assemblies.
3. Opt-in `"package-actions": true` moves verified NuGet archive extraction into
   native Bazel sandbox actions with declared directory outputs. Resolution and
   lock-file behavior remain with NuGet; archive acquisition stays in a repository.
4. Each compile receives its validated package closure. Across Orchard, package
   references fall from 57,974 to 9,888; median 34 packages, range 19–287.
5. The combined implementation is qualified with a producer-deleted fresh cache
   recovery, three no-ops, and C#, CSS, Razor and generator edits.

Large-graph qualification also found a 2 GiB controller upload-staging limit.
The bounded disk-backed cap is now 8 GiB, retaining the 256 MiB per-object cap
and publish-after-validation rule. Boundary tests verify rejection without
publication above the cap. The successful producer published 16,329 objects,
2,612,022,731 bytes, with zero cache failures.

## Measured times

All totals include the owned workflow and cache publication when enabled.
These are single-machine samples, not a repeated statistical performance study.

| Case | Original shared inputs | Structural scoping only | Combined changes | Compilations now |
| --- | ---: | ---: | ---: | ---: |
| Cold producer | 1,057.374 s | 1,096.917 s | 1120.087 s | 202 |
| Fresh remote recovery | 64.679 s | — | 36.825 s | 0 |
| No-op | 13.396 s, one sample | 16.064 s, median of 3 | 6.489 s, median of 3 | 0 |
| Host C# edit after recovery | 100.086 s | — | 102.465 s | 1 |
| Setup stylesheet edit | 1,108.482 s | 651.774 s | 687.674 s | 4 |
| Setup Razor edit | 1,108.225 s | — | 692.850 s | 4 |
| Generator edit | — | 596.610 s | 607.839 s | 202 |

Fresh recovery is **43.1% faster (1.76x)** than the earlier sample. The new no-op
samples are 6.989, 6.489 and 6.345 seconds. Their median is **59.6% below** the
structural-only median, though both short series show warm-up variability.

The combined CSS/Razor edits are **38.0% / 37.5% faster** than the original
shared-input cases and avoid 198 compilations. Package integration did not make
the measured CSS edit faster than structural scoping alone: it was 5.5% slower.
Discovery was 329.407 s versus the prior 305.356 s. The C# edit remains about
102 seconds and cold build time remains about 19 minutes; neither is a speedup.

## Correctness and cache evidence

- The producer's local Bazel output base and generated workspace were removed.
  Fresh recovery used a different checkout and fresh state with read-only cache
  access. All 202 compile actions and 287 extraction actions were remote hits.
- All **3,457 application files** matched the producer byte-for-byte. The fresh
  run downloaded **zero extracted package files**; empty directory placeholders
  are expected with Bazel's top-level output download policy.
- The recovered Production app returned HTTP 200 while both producer and recovery
  source checkouts were temporarily unavailable. Both paths were restored.
- C# changed the expected HTTP response header and compiled only the CMS host.
- CSS and Razor each compiled exactly Setup, Application.Cms.Core.Targets,
  Application.Cms.Targets and the CMS host. The changed CSS and rendered Razor
  markers were present at runtime, alongside earlier edits.
- The generator edit reused discovery, rebound one project and compiled all 202.
  Its new class prefix appeared in Navigation.Core, Navigation and Taxonomies
  assemblies. Runtime verification passed with all prior edit markers intact.
- The four-project package probe additionally proved a Newtonsoft consumer edit
  downloads its 24 required package files and zero unrelated PolySharp files.
  It also checked legacy/action-produced DLL/PDB equality and changed app output.
- The full local suite passed: 58 workflow tests with one Linux-only skip,
  33 preparation tests, 5 style tests, and warning-free builds. CI was not run.

## Remaining costs and scope

Resource edits still rerun whole-graph discovery and all 202 bindings. Razor
preparation was 333.034 seconds. Reducing that work is the next major iteration
opportunity; narrowing compile inputs alone does not remove it.

The first C# edit after fresh recovery downloaded 2.744 GB. Its Bazel profile
shows approximately 52.6 s in the compile action, 13.2 s in runtime composition
and 4.7 s in binding. Cache input staging was about 4.9 s cumulatively on the
loopback connection; transferring bytes is only part of the remaining cost.

This qualifies the pinned Orchard Release/Production graph on one macOS ARM64
host with Bazel 8.4.2 and .NET SDK 10.0.400. The cache is loopback and archive
acquisition uses a shared repository cache. It does not establish WAN,
independent-machine, cross-platform or Development hot-reload behavior. Standard
build-worker paths remain in accepted Razor debug metadata. Raw MSBuild was not
remeasured here, so there is no new claim of raw-MSBuild parity.

The final benchmark ran sequentially. Failed preflight runs are retained as
failures, including scratch exhaustion and upload-cap rejection. The accepted
cold producer was rerun after cleanup and the capacity fix. All runtime probes
and benchmark Bazel servers were stopped after verification.

## Commits

- `0dc17f1`: project structural input scoping.
- `223fc4d`: Orchard asset/generator qualification.
- `e202f17`: owned NuGet action integration (following extraction prototype commits).
- `4519f9e`: per-project package closure inputs.
- `7ba46c2`: bounded large-graph upload staging.

Final branch: `codex/orchard-package-qualification`. Changes are committed locally;
no push or merge was performed. Machine-readable results are in
`orchard-package-qualification-evidence.json`.
