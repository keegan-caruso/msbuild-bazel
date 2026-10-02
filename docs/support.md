# Support and limits

The graph workflow is the sole backend. Baselines: SDK 10.0.400, Bazel 8.8.0/9.2.0.
Inputs, package inventories, generated products, tool layouts and output ownership
must be declared. MSBuild retains SDK/project semantics; custom task reads require
reviewed contracts. Sync does not trace arbitrary file access or acquire missing packages.

The cutover passed small graph build/replay, dependency invalidation, output ownership,
signing, package SDK, tool, MTP/VSTest and generated-package controls on Linux ARM64.
Both Bazel baselines passed sandboxed worker Build/Publish parity and failure recovery.
Prepared Restore and HTTP cache fault/recovery controls passed.
Contributor commands are in [CONTRIBUTING](../CONTRIBUTING.md).

Earlier graph qualification built **481 runtime v10.0.0 compilation nodes**:
3,622 compiled files matched raw MSBuild, 10,780 snapshots matched bytes/modes,
and eight suites passed **118,952 tests / 64 skips / zero failures**. A source-built
runtime ran apps/tests with the installed SDK absent; stopped-producer/relocated-consumer
HTTP recovery passed. This large series predates the graph-only cutover.
[Detailed evidence and retired workflows](https://github.com/keegan-caruso/msbuild-bazel/tree/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs)
remain at the recorded revision. [Performance](performance.md) uses that same baseline.

Remaining priorities:

1. Requalify full source-SDK, NoTargets and NativeAOT consumers on the sole graph interface.
2. Reduce large-graph publication/staging and unnecessary Restore invalidation, with matched body/API controls.
3. Expand reviewed runtime slices and qualify platforms independently.

This is not whole-repository runtime support. Linux x86-64, macOS persistent workers,
RBE, arbitrary SDKs/workloads and full native build parity are unqualified.
Linux workers require Bubblewrap and nested user/mount/PID namespaces; ordinary
container defaults may block them. Project-graph isolation alone does not establish
filesystem hermeticity. Build trusted targets; keep reports outside Git and summarize
commands, outcomes and remaining limits when extending support.
