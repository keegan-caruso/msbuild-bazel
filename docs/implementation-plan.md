# Current support

The sole build path is `msbuild/graph.bzl`, exported by `msbuild/defs.bzl`, with
`tools/GraphBuild` and the MSBuild project-cache plugin. `tools/ProjectSync`
generates its explicit contracts. `tools/ArtifactTools` extracts packages,
composes artifacts and launches apps/tests; it does not compile projects.

Baselines: SDK **10.0.400**, Bazel **8.8.0 / 9.2.0** (default).
The API is experimental. There is no published runner package or BCR release.

## Supported contracts

- Configured SDK project graphs, explicit sources/imports/generated files and output ownership.
- Build/Publish target-result caching, reviewed compiler reference boundaries,
  implementation edges and runtime-copy refresh.
- Offline locked NuGet/package SDK inputs and separately prepared Restore.
- Complete task/analyzer tool layouts, reviewed generators and native producer bindings.
- Executable/MTP/VSTest tests, downloaded/source-built execution hosts.
- Verified downloaded or declared Bazel-produced SDKs; no host-path SDK repositories.
- Stable Linux paths and sandboxed graph workers on the qualified Ubuntu ARM64 VM.

These are contracts, not blanket compatibility claims. Review custom target reads,
shared output ownership, SDK/package imports and configured references explicitly.
The graph runner validates declarations, not arbitrary filesystem accesses.

## Measured upstream scope

The pre-cutover graph qualification built **481 configured compilation nodes** from
runtime v10.0.0 and ran eight suites: **118,952 passes / 64 skips / zero failures**.
Raw compiled bytes, restored snapshots, SDK-absent source-host execution,
body/API/native input controls and independent HTTP recovery passed. Both Bazel
baselines have bounded Linux ARM64 worker controls. See
[runtime qualification](runtime-qualification.md) and [performance](performance.md).

Orchard's full 202-project graph and selected Avalonia graphs also have graph-cache
build/replay evidence at the [pre-cutover revision](history.md). Their old per-project
benchmarks do not measure this backend. The 22-component source SDK build remains a
separate qualified producer; its consumer declarations now use graph rules.

## Cutover validation

See [cutover checks](graph-cutover.md) for commands, observed results and remaining
qualification limits. Current small-fixture checks verify the new entrypoint and
artifact utilities. Previous full-runtime timings refer to the recorded engine,
SDK and environment; this migration does not claim a fresh large-graph benchmark.

## Remaining work

1. Re-run larger source SDK and NativeAOT consumers with the graph-only interface;
   preserve their native tool, package and output contracts before claiming parity.
2. Reduce graph artifact publication size after auditing outputs outside declared
   products and preserving replay, app/test layouts and independent recovery.
3. Investigate unnecessary private Restore invalidation and measured body/API
   materialization costs. Keep verification unless a complete byte contract replaces it.
4. Expand runtime slices and project-sync contracts with small controls first.
5. Qualify Linux x86-64, macOS workers, RBE, arbitrary SDKs/workloads and full runtime
   repository builds separately; none follows from Linux ARM64 evidence.

GitHub CI is manual-only and requires an explicit request.
