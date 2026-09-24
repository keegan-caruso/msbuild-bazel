# Full Orchard explicit-rule qualification and performance

Pinned Orchard: `04467a3438d4255627c1a478598a1585b3ff2947`.
Rules base: `998f5382be5ef3d601b0d1f3e282565f28b1c583`.
Linux Ubuntu 22.04 ARM64 Apple container, 4 CPUs / 8 GiB, SDK 10.0.400,
Bazel 8.4.2. All build files and outputs live on native Linux storage; only
logs/reports use a host mount. The workload is the complete CMS application's
202-project closure, including its netstandard2.0 source generator, 103 modules
and themes, and 287 distinct package archives.

## Qualification changes

- `msbuild_package_lock(packages = [...])` declares a consumer's resolved package
  set. `package_lock` on an assembly selects that set instead of unioning producer
  versions. Direct package closures must match it. The ordinary no-lock path still
  rejects inherited version conflicts. Locks come from NuGet resolution outside
  the timed build; this is not a new dependency solver.
- `msbuild_nuget_dependencies(package = ..., deps = [...])` separates canonical
  archive extraction from a framework/project-specific resolved dependency set.
  One archive can participate in several dependency sets without being extracted
  repeatedly. Framework references declared on project dependencies propagate.
- `directories` declares empty **logical workspace-relative** directories needed
  by original targets. They are created before entering the read-only sandbox.
  Other item identities stay relative to their project, preserving MSBuild's
  `RelativeDir` behavior and embedded resource names.
- SDK-added `GlobalPropertiesToRemove` is allowed only for absent global
  properties. Removing an active global property still fails declaration checks.
- NuGet archives with redundant internal separators are normalized, with traversal
  and normalized-name collision checks retained. This accepts the pinned
  MessagePackAnalyzer archive.
- Runtime composition records actual SDK `ReferenceCopyLocalPaths` owned by NuGet.
  An application's selected package file wins over a dependency's version of the
  same package. Project-file collisions and collisions between different package
  IDs still fail. Recorded files must match the SDK's source package bytes.
- The test BUILD graph explicitly supplies transitive module-name target results.
  This matters: direct-only results compiled successfully but produced HTTP 404.
  No Orchard-specific production rule attributes were introduced. Fresh-checkout
  recovery also caught and removed three unused raw `bin/obj` artifacts from the
  source-generator declarations; generated setup outputs are not source inputs.

The complete application serves the setup Razor page and embedded setup CSS,
setup JavaScript, and Font Awesome CSS. The three asset hashes match raw MSBuild.
No tenant was created; this is not qualification of every optional feature,
publish/deployment, all tests, or all execution platforms.

## Measurement protocol

The harness is in `tests/explicit_msbuild/orchard_compatibility/`. Inventory,
initial NuGet restore, BUILD generation, SDK/archive acquisition and cleanup are
outside timing. Cold means empty build outputs and fresh Bazel/compiler processes,
with warm filesystem caches and packages already available. Bazel cold includes
startup and analysis, package extraction and all 202 project actions. Raw cold
includes restore against the local feed and all project compilation. Neither is a
cold network/package-download test.

Bazel uses `--jobs=4` and two isolated MSBuild workers; raw uses `-m:4` on the same
VM. Four isolated compiler servers exhausted practical memory headroom before the
end of this graph. Raw and Bazel servers never run together during timed builds.
Evaluation profiling is disabled. Worker phase counters remain enabled in every
variant. Implementation edits change `NotFoundManifestInfo.Description`; the
harness asserts an unchanged reference assembly and restores the original source.

Results below are individual runs, not a statistically stable speedup estimate.
The first runs preceded correction of the transitive module metadata on the final
application targets. They compiled the same 202 projects but are useful primarily
as exploratory phase measurements; the final runs use the runtime-qualified graph.

| Case | Bazel explicit rules | Raw MSBuild | Comparison |
| --- | ---: | ---: | --- |
| Cold build | 128.59 s | 70.15 s | 1.83× raw time |
| No-op | 1.60 s | 13.59 s | 8.5× faster |
| Core-library body edit | 1.59 s | 10.85 s | 6.8× faster |
| Setup module CSS edit | 15.46 s | 11.80 s | 1.31× raw time |

The CSS edit changes the module reference and rebuilds four projects: Setup,
Application.Cms.Core.Targets, Application.Cms.Targets, and Cms.Web. The core-library
edit rebuilds only that library. These are different invalidation cases.

Cold progression: exploratory baseline **209.01 s**, input-index run **175.93 s**,
runtime-qualified graph with 1 GiB retention **163.03 s**, with 4 GiB **144.19 s**,
and final clean-source declarations **128.59 s**. The first-to-final difference is
38.5% less wall time (1.63× throughput), but includes graph corrections and run
variation; it is not an isolated estimate of either production optimization.

Final worker phase totals across all 202 actions are 153.43 s in MSBuild children,
30.67 s snapshotting, 6.95 s preparation, 11.99 s publication and 6.12 s request
identity calculation. These are **cumulative across two workers**, not additive
wall-clock segments. Child time is now the largest measured component.

Compact [measurement evidence](evidence/orchard-explicit-performance/) includes
individual timings, phase totals, runtime hashes and resource invalidation results.

### Fresh-checkout HTTP cache recovery

Seeding the loopback HTTP cache took **169.25 s**, including compilation and
uploads. After shutting down Bazel and deleting the producer output base, a new
checkout at `/orchard-relocated` recovered **all outputs in 37.00 s** using a fresh
Bazel output base: **489 remote hits** (202 assemblies and 287 package extractions),
496 internal actions, **zero compiler worker actions**. Disk cache was disabled.
The recovered application served the setup Razor page and all three assets; their
hashes matched the raw MSBuild control. Cached compiler logs were replayed by
Bazel; the final process summary, rather than those logs, establishes cache hits.

This is 1.9× faster than the raw cold build, with startup, analysis and full output
download/materialization included. It is a loopback cache-mechanics result, not a
WAN estimate. Unrelated raw `bin/obj` files were absent from the relocated source.
Producer and consumer used the same SDK, platform and rules toolchain. The loopback
cache process survived; producer build/worker state did not.

Repeated trials initially exhausted the host's sparse container backing store.
Those failed runs are excluded. The final harness deletes producer outputs and
allows host block reclamation **outside timing** before recovery. The successful
run had sufficient free disk space throughout.

## Retained optimization and rejected experiment

Input validation used to scan the entire declared-input list for every mapped
source, reference, item and package. It now uses file and ancestor-directory hash
sets, preserving ordinal path semantics and rejection of similarly prefixed
siblings. In the exploratory pair, cumulative preparation fell from 14.79 to
7.62 seconds; other phase timings also varied, so the full wall-time difference
cannot be attributed solely to this lookup change.

An experimental content-based analyzer path and borrowed analyzer staging reduced
compiler memory and cumulative child time, but a four-worker run generated
malformed C# for valid Razor tag-helper attributes. The same server then failed a
different project; restarting it compiled the original view successfully. The
underlying SDK-versus-reuse cause was not isolated. **That experiment was removed**;
its 168.28-second two-worker result is not a shipped-performance claim. No retry or
suppression workaround was added to the production runner.

The final CMS actions each supplied 1.3–1.6 GB of inputs, exceeding the original
1 GiB snapshot-cache budget and causing repeated verification. Raising the bounded retention budget to 4 GiB per worker reduced cumulative
snapshot time
from 47.26 to 31.50 seconds and bytes verified from 7.57 to 3.33 GB in the measured
pair. The final CMS action went from verifying 1.64 GB to 3.75 MB. This is retained
disk data, not a 4 GiB RAM reservation. The 100,000-file bound remains.

Comparing all 202 reference hashes across those fresh executions found 114 equal
and 88 different. Of the differences, 87 were module/theme projects; the other
was `OrchardCore.Navigation.Core`. Original Orchard module targets embed physical
source paths in `ModuleAssetAttribute` string values, which ordinary C# `PathMap`
does not rewrite. These results do **not** establish byte-reproducible builds.
Cache recovery and public-reference stability for the sampled core-library body
edit are distinct properties. A module-resource edit is measured separately.

Follow-up: [stable worker paths](orchard-stable-worker-paths.md) removes random
broker paths and isolates an independent source-generator GUID in unchanged
Orchard. That report distinguishes fresh-output equality from cache recovery.

## Validation and limits

[Validation commands and results](evidence/orchard-explicit-performance/validation.md)
record the final retained-code checks. Host scaffold/Starlark and .NET checks pass
(116 tests passed, one skipped); final Linux worker acceptance, protocol and
package-lock controls pass. No GitHub CI was run.

The Linux worker acceptance covers compilation/test execution, implementation
edits, active/absent global-property removal, undeclared reads, source writes,
forged digests, similarly prefixed undeclared paths, and relocated cache recovery.
Generator checks cover helper implementation edits, compile-visibility isolation,
role mismatch, recovery, and a cached tool used by a new consumer action.
Package-lock analysis accepts a selected consumer version and rejects both an
unresolved inherited conflict and a direct-lock mismatch. Archive tests retain
hash/identity/traversal rejection and add separator/collision cases. Runtime tests
retain project/different-package collision rejection while accepting the selected
application package version.

Large package snapshots and repeated package/runtime output materialization remain
substantial costs. Framework-dependent package selection is explicit; RID-specific
publish, VSTest translation and universal remote execution are not established by
these results. HTTP-cache recovery uses loopback and full output downloads; it does
not estimate WAN or a production cache server's latency.
