# MSBuild-native project-cache exploration

## Decision

The general project-cache API works on our pinned macOS ARM64 SDK, but the
published Microsoft.MSBuildCache.Local package is not a usable drop-in backend.
Do not replace the existing build path or claim a plugin performance improvement
from this experiment. This is a compatibility investigation, not a cache benchmark.

## Pinned inputs

- SDK: repository-pinned .NET 10.0.400, macOS ARM64, locked Nix environment.
- Package: Microsoft.MSBuildCache.Local **0.1.340-preview**.
- Package SHA-256: `f5b19cc753c38cb1dff5644e5da8efdd4b473cc13f943772e8f813a1c5672fac`.
- Package repository revision: `54bcfb23a927bead6622eee0cd3f109ae66c9931`.
- MSBuild source feature-gate inspection: `22771eff1f722f5e7c2dbb45fefe9d87a7406a15`.

The NuGet package's repository metadata matches the inspected upstream revision.
The probe verifies its archive hash before extraction. No production dependency
was added. Direct props/targets imports exercise the actual downloaded package;
its binary was not modified or rebuilt for a different architecture.

## Observed results

| Check | Result |
| --- | --- |
| Ordinary ten-project build, package disabled | Succeeds; ten compiler invocations; correct app output |
| `-reportFileAccesses`, package disabled | Fails with MSB1001, unknown switch |
| Package enabled with required reporting switch | Same unsupported-switch failure |
| Package enabled without reporting switch | Build fails; no cache success inferred |
| Explicit package assembly-load diagnostic | FileLoadException: assembly architecture incompatible with process |
| Plugin compiled against our SDK, cold build | Ten cache queries, ten project completions, ten compilations, correct app output |
| SDK-native plugin, unchanged build | Ten queries/completions, zero compilations, correct app output |
| SDK-native file-access callbacks | Zero on both runs |

The diagnostic plugin deliberately returns **CacheMiss for every query** and
reports zero cache hits. Its warm zero-compilation result comes from ordinary
MSBuild incrementality. It never restores or publishes artifacts. The report's
`accepted` flag means the diagnostic/control checks completed, not that upstream
caching is supported; `cacheReuseQualified` is always false.

## Why the upstream package cannot provide our current build path

There are independent constraints:

1. **Architecture:** upstream explicitly builds the Local/Common projects for
   x64 because of RocksDB. The downloaded managed assembly's PE machine is
   AMD64 (`0x8664`), and package inventory includes Windows `rocksdb.dll` payloads.
   The ARM64 loader rejects the assembly before storage functionality is tested.
   See the pinned [Local project](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Local/Microsoft.MSBuildCache.Local.csproj).
2. **Input observation:** the documented invocation requires file-access reporting.
   The inspected MSBuild source defines `FEATURE_REPORTFILEACCESSES` only for its
   full .NET Framework target. Our `dotnet msbuild` rejects the switch. Upstream
   returns without caching a completed project when no file-access report has
   arrived. Omitting the switch is not a caching fix. See the pinned
   [feature gate](https://github.com/dotnet/msbuild/blob/22771eff1f722f5e7c2dbb45fefe9d87a7406a15/src/Directory.BeforeCommon.targets#L114)
   and [publication guard](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/MSBuildCachePluginBase.cs#L618).

Changing only the storage library or running an x64 process would not address the
missing file observation. This experiment did not test a Windows/full-framework
host, Linux, Rosetta, a remote cache, or a newer/different SDK. No CI was run.

## What remains viable

The SDK-native project-cache interface can receive the already evaluated graph,
answer project queries, and observe project completion within one MSBuild build.
The existing repository ReplayPlugin already uses that API for dependency replay;
this independent control confirms the callback lifecycle on the current SDK.

A bounded next experiment could implement a local content cache behind this API,
using our existing qualified input contracts rather than unavailable file-access
tracing. Keep SDK compilation and MSBuild graph scheduling, and handle:

- Keys covering configured properties, SDK/tool/plugin identity, declared sources,
  imports, restore inputs and the correct dependency inputs.
- Input additions/removals, directory globs, missing-file probes and mutations.
  Hashing only `Compile` items is insufficient for general MSBuild.
- Verified artifact materialization and the target results consumers require.
- Cache miss publication only after successful builds; corruption and partial
  entries must reject or miss safely.
- Cold builds, body/API edits, changed imports, deleted outputs, relocation and
  clean consumer builds against ordinary MSBuild oracles.

Reusing the already evaluated graph may avoid a second evaluation, but doing so
without weakening discovery is work still to prove. The existing API/runtime
split may also help edit invalidation; this probe makes no claim about that.
Input identity and sandbox enforcement are separate: a plugin cache alone does
not retain Bazel's filesystem isolation or remote-execution guarantees.

**Recommendation:** if macOS/Linux remain required, retain the current path and
prototype a narrow MSBuild-native cache with explicit inputs before changing the
architecture. Evaluate Microsoft's existing implementation on a supported
Windows/full-framework host if that platform is relevant. Do not begin a broad
upstream port merely to obtain a timing comparison.

## Reproduce

Inside the locked Nix shell, with a new short output path:

```sh
python3 tools/probe_msbuild_cache.py --output /private/tmp/plugin-cache-probe
```

The probe downloads and verifies the pinned package, creates an isolated synthetic
Git fixture, runs baseline/reporting/load controls, builds the diagnostic plugin,
and checks cold/warm outputs and compiler/callback counts. `--package PATH` uses
an already downloaded archive with the same mandatory hash verification.

Owned .NET build/style checks pass, including the new diagnostic plugin. The
experiment does not alter the default adapter, existing replay, or cache rules.
