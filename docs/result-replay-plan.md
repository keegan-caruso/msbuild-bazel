# Public-API MSBuild result replay

## Decision and status

This experiment captures and replays dependency target results through
public MSBuild project-cache APIs at a different workspace path. This precedes
the two-target Bazel rule and any investment in fixed absolute sandbox paths or
a custom MSBuild fork. Implemented and measured on macOS ARM64; see [findings](replay-findings.md)
and the finalized [experimental contract](replay-interface.md). The sections
below preserve the original experiment design.

Keep the existing v1 driver and raw-cache path probe as controls. Their
same-workspace restriction and measured relocation failure remain valid; see
[path findings](path-findings.md). Toolchain pins are unchanged. Start with the
pinned .NET SDK 10.0.100 and record the engine version in each experiment report.

## Why this is worth testing

Source research on 2026-09-05 compared MSBuild 17.0.0 with
[18.9.6](https://github.com/dotnet/msbuild/releases/tag/v18.9.6), the latest
published release checked that day. The repository's Nix SDK reported
MSBuild 18.0.2.52411 via `bash scripts/dotnet.sh msbuild -version -nologo` inside
the configured toolchain environment. The 18.9.6 findings below are source
inspection, not a build or relocation test on that version.

- Cache lookup and `PluginTargetResult` already existed in 17.0. MSBuild 17.8
  added the completed-build callback, `HandleProjectFinishedAsync`, which can
  capture results without accessing private engine caches. The 18.x API uses
  `Microsoft.Build.ProjectCache`; the experimental namespace is retained as
  obsolete. See the [plugin specification](https://github.com/dotnet/msbuild/blob/v18.9.6/documentation/specs/project-cache.md)
  and [plugin base class](https://github.com/dotnet/msbuild/blob/v18.9.6/src/Build/BackEnd/Components/ProjectCache/ProjectCachePluginBase.cs).
- Microsoft's MSBuildCache uses its own target-result representation and
  normalizes item paths and metadata before reconstructing `PluginTargetResult`
  objects. This is useful prior art, not proof of our cross-platform adapter:
  [target results](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/NodeTargetResult.cs),
  [item metadata](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/NodeTargetResultTaskItem.cs),
  [path normalization](https://github.com/microsoft/MSBuildCache/blob/54bcfb23a927bead6622eee0cd3f109ae66c9931/src/Common/PathNormalizer.cs).
- Raw cache serialization still includes absolute project paths. Upgrading the
  engine is not itself a relocation strategy. See
  [configuration serialization and equality](https://github.com/dotnet/msbuild/blob/v18.9.6/src/Build/BackEnd/Shared/BuildRequestConfiguration.cs).
- The latest engine still reports requested target results rather than every
  intermediate target result. Capture the explicit downstream target contract;
  do not assume a `Build` callback contains everything needed by publish or a
  later dependency query. See [TargetBuilder](https://github.com/dotnet/msbuild/blob/v18.9.6/src/Build/BackEnd/Components/RequestBuilder/TargetBuilder.cs).

## Proposed boundary

Use a separate experimental entry point and a versioned payload; finalize its
command and schema before implementation. Do not silently change v1 or teach it
to accept relocated opaque `results.cache` files.

The payload must describe:

- Project identity as a workspace-relative project path plus the complete
  global-property set, with explicit SDK/engine and payload versions.
- Requested targets and their successful output items, preserving item ordering,
  item specifications, and custom metadata needed for replay.
- Explicit root mappings for path-bearing values, including workspace, NuGet,
  toolchain and output roots where applicable. Unsupported external paths must
  be diagnosed, not silently retained or rewritten by guessing.
- A separate artifact manifest with paths relative to declared roots. Metadata
  is not artifact content; all required files must be staged before a hit is
  returned. Restore state and generated files need their own treatment.

Build Shared and collect the required target results through public APIs. In a
new process at the consumer workspace, reconstruct task items and return
`CacheResult.IndicateCacheHit(...)` for Shared. Initially use the fixture's
explicit target list; inspect `ProjectGraph.GetTargetLists(...)` to derive and
validate the graph-compatible requests without building a general exporter.

Plugins are queried for top-level submissions, not arbitrary recursive project
calls. Use graph-ordered submissions so dependency hits populate MSBuild's
in-memory results before App requests them. Prove how this interacts with strict
project isolation; do not silently turn off `-isolateProjects` or substitute
`BuildProjectReferences=false`. A missing dependency payload, target result, or
configuration match must fail instead of allowing MSBuild to compile Shared.

Bazel will ultimately own action scheduling and artifact caching. The plugin's
role is to replay the dependency bundles supplied to an action, not introduce
an independent cache that downloads or builds missing dependencies.

## Acceptance sequence

Write the experimental process contract and black-box tests before the runner.
Use copied fixtures, Release/net10.0, fresh processes, retained logs and the
existing `SPIKE_COMPILE` instrumentation.

| Case | Required evidence |
| --- | --- |
| Same-path replay control | Stage dependency artifacts after deleting bin/obj; App compiles, Shared does not, and output is `shared-v1/app-v1` |
| Relocated replay | Delete the producer workspace, restore consumer metadata in a new workspace with its own NuGet root, stage artifacts, replay Shared, and observe App-only compilation with baseline output |
| App-only edit | Reuse the same dependency payload at the consumer path; App alone compiles and prints `shared-v1/app-v2` |
| Missing payload or target result | Fail with a dependency/target diagnostic and no Shared compilation; do not return a partial cache hit |
| Missing artifact or identity mismatch | Reject missing files, mismatched global properties, toolchain versions, or unsupported payload versions before reporting a hit |
| Additional target request | Exercise a narrow fixture publish request after relocated replay; explicitly request/capture any additional results and verify the published app runs without rebuilding Shared |
| Raw-cache controls | Existing moved-bundle success, relocated raw-cache failure and fresh-cache success still run independently |

The report must record the exact commands, OS/architecture, SDK and engine
versions, requested targets, replay diagnostics, exit statuses, compilation
markers and application output. The producer path must be absent for the
relocation case. A successful cache lookup alone is insufficient evidence.

## Limits and exit criteria

The plugin callbacks do not discover a complete Bazel input set. MSBuild's
documented file-access observation uses Windows x64 MSBuild.exe and is not a
Linux/macOS `dotnet` solution. Keep restore separate and explicitly account for
imports, generated files, package assets, task inputs and environment state.

Normalizing target-result metadata does not normalize embedded paths in artifact
contents or guarantee arbitrary MSBuild side effects can be replayed. The narrow
publish case tests target-contract completeness; general publishing, custom
package targets and multi-targeting remain deferred.

If public-API replay passes, define the Bazel execution-log assertions and test
the same boundary across actual actions and sandboxes. Only then claim Bazel
disk-cache reuse; remote execution and remote-cache correctness require separate
evidence. If replay fails, record the specific API, target-state or path obstacle
before revisiting stable internal paths or an MSBuild fork.
