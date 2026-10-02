# Design

Keep MSBuild's SDK behavior while giving Bazel explicit, cacheable work. Build a
selected project graph in one action to share evaluation and scheduling within a
build and avoid starting MSBuild separately for every project.

## Ownership

| Component | Owns |
| --- | --- |
| Bazel | Declared inputs/toolchains, producer actions, whole-action caching and tests |
| ProjectSync | Evaluating projects into committed Bazel declarations and JSON contracts |
| MSBuild + cache plugin | Configured project edges, SDK targets, compilation and project reuse |
| ArtifactTools | Package extraction, layout composition and app/test launch |

SDKs, runtimes, packages and task tools are declared artifacts. Downloaded and
source-built SDKs use the same layout contract; compilation SDK and execution
runtime are separate selections.

## Execution

Sync records input files, configured projects and output ownership. Builds consume
that contract, restore from declared packages, evaluate the MSBuild graph afresh,
then build or recover each project. Definition changes require sync; custom task
reads require reviewed declarations. Evaluation does not trace arbitrary file access.

MSBuild composes project outputs. Bazel extracts the selected runtime layout for
an app or test, making runtime dependencies part of that target's cache inputs.

## Two cache levels

Bazel can skip an unchanged graph action entirely. When an input changes, the
MSBuild plugin reuses matching projects inside the action. A hit restores both
artifact bytes and target-result metadata; MSBuild's result cache alone is insufficient.

Project snapshots persist through a Linux worker or HTTP AC/CAS service. The worker
retains caches and preparation, but starts fresh isolated MSBuild per request.
Prepared Restore can be a separate action so body edits reuse it. Stable paths
support relocation; declared-byte checks remain required on project-cache hits.

## Invalidation

Keys include declared inputs, evaluated configuration, SDK/runner identity,
output contracts and dependency roles. Dependencies are conservative by default.
With reviewed reference boundaries, in `A → B → C`, a changed C reference assembly
rebuilds B; A can reuse compilation if B's reference stays unchanged. Explicit copy
contracts refresh runtime implementations. Task/analyzer edges use implementation bytes.

[API](api.md) covers configuration; [support](support.md) separates these contracts
from platform qualification and filesystem hermeticity.
