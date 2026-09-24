# Stable physical paths in isolated Linux workers

## Cause

Orchard's unchanged `OrchardCore.Module.Targets.targets` constructs module asset
attributes from `%(ModuleAssetFiles.FullPath)`. These strings become public
assembly metadata. Compiler `PathMap` rewrites supported debug/source paths, not
arbitrary attribute values. The worker previously mounted its randomly named
`/tmp/explicit-worker-<guid>` directory at the same physical path inside the child.
Thus identical actions could generate different module DLLs and reference DLLs.

The earlier full-graph comparison found 88 different reference assemblies across
fresh executions; 87 were modules/themes. Remote-cache recovery still worked by
returning the producer's bytes, which is a different property from reproducibility.

## Change

The broker retains private randomly named storage. Bubblewrap mounts its inputs,
outputs, compiler scratch and runner at fixed paths beneath `/__rules_msbuild` in
the isolated compiler process. Each worker has its own mount namespace. Input and
tool mounts remain read-only; outputs and compiler scratch remain writable.

Preparation emits compiler-visible paths for generated source/reference/analyzer
items, package links and installed shared-restore metadata. Session paths use the
same mapping. Original source files, imported targets and compiled binaries are
not rewritten. This is generic worker behavior; no Orchard-specific rule or target
override is introduced. Non-worker preparation retains its previous path behavior.

Content identity remains part of input/output paths. Identical inputs receive
identical physical paths, while changed requests receive distinct paths. This
preserves the existing protection against stale MSBuild XML and Roslyn metadata
when contents change but sizes/timestamps match. SDK paths remain pinned.

## Validation

The focused regression invokes two fresh workers in different temporary roots
with identical request bytes. Its SDK-style project emits an assembly attribute
containing `$(MSBuildProjectDirectory)`. On the previous runner (`fdc9214`) the
reference DLL, implementation DLL and PDB all differ. With stable child paths,
all three match and the attribute contains the fixed namespace path.

Two fresh full-graph builds used Bazel 9.2.0, SDK 10.0.400 and Orchard
`04467a3438d4255627c1a478598a1585b3ff2947` in the qualified 4-CPU/8-GiB container.
The second source checkout was relocated; producer output/worker state was
removed between builds. Local and remote action caches were disabled, and both
runs executed 202 compiler actions plus 287 package extractions. Of 13,904
published reference/runtime files, 13,644 matched. Reference matches improved to
137/202 in this pair, but unchanged upstream Orchard is still not reproducible.
Both applications rendered the setup page and served three embedded assets with
matching hashes.

### Remaining upstream generator randomness

`OrchardCore.SourceGenerators/ArgumentsFromInterceptor.cs:171` calls
`Guid.NewGuid()` when naming generated interceptor classes. Metadata inspection
of `OrchardCore.Navigation.Core` confirms different `Interceptor_<guid>` types
with identical worker input identity and physical paths. That reference changes
consumer input identities, propagating path differences into module metadata.
Other implementation-only outputs also vary where this generator runs.

A separate diagnostic pair replaces that GUID with SHA-256 of the interceptor
location data, matching the stable-ID approach already used by Orchard's
`ShapeFactoryGenerator`. The exact patch is retained as evidence; it is applied
only to disposable test checkouts, not Orchard's upstream source or production
rules. The unmodified and diagnostic results must not be conflated.

The diagnostic pair executed all 202 compiler actions independently at different
checkout paths and fresh output bases, with no action-cache reuse. **All 13,904
published files matched byte-for-byte, including all 202 reference assemblies.**
Setup-page and three embedded-asset checks passed on both builds. Times were
138.1 and 142.5 seconds (rounded); these are qualification samples, not a measured
performance improvement. This demonstrates that stable worker paths remove the
observed path variance once the separate generator randomness is controlled.

[Compact evidence](evidence/orchard-stable-worker-paths/) includes reference
hashes, comparison summaries, runtime checks, the failing old-runner regression,
and decoded navigation metadata. Full per-file manifests and compiler logs are
retained in the local experiment directory, outside Git.

Reproduce the worker regression with
`python3 tests/explicit_msbuild/worker_path_stability.py`. The full comparison uses
`reproducibility.py SOURCE EVIDENCE NEW_OUTPUT_BASE` under
`tests/explicit_msbuild/orchard_compatibility/`; see its README for setup. The
diagnostic generator patch is a zero-context patch, applied explicitly with
`git apply --unidiff-zero` only in a disposable Orchard checkout.

### Regression checks

- Host tooling/Starlark checks and owned .NET builds/style checks passed.
- Host suites: 116 passed, one existing Linux-only environment skip.
- Linux worker protocol: forged digest, undeclared request and tool-root controls
  passed.
- Linux worker acceptance on Bazel 8.4.2: compile/test, body-edit reference
  stability, compiler reuse, same-timestamp edit recovery, read/write isolation
  and producer-deleted relocated cache recovery passed.
- Shared-restore worker acceptance passed, including a real compilation using
  recovered restore metadata at the relocated path.
- `git diff --check` and Python harness syntax checks passed. No CI was run.

The two original full builds took 180.1 and 158.4 seconds. Other regression checks
ran concurrently, so these are correctness runs, not a controlled performance
comparison.

## Scope

The fix addresses random worker/host paths for the qualified Ubuntu 22.04 ARM64
persistent-worker lane. It does not establish non-worker or cross-platform
reproducibility. Paths are still embedded, but are stable for identical action
inputs. A content edit can still change that action's physical path and therefore
its generated public metadata; removing that extra reference churn would require
separate work on compiler cache invalidation or target semantics.

Diagnostics intentionally contain timings, process IDs and other execution data;
byte comparisons cover published reference/runtime outputs, not diagnostics.
These stable paths are build-time paths, not promises that original source files
exist when a cached application runs. Runtime checks exercise Orchard's embedded
asset fallback, not development-time source watching or tenant setup.
