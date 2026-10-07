# Design

Build a selected project graph in one Bazel action. MSBuild retains SDK targets,
configuration and scheduling; sharing evaluation avoids a process per project.

## Ownership

| Component | Owns |
| --- | --- |
| Bazel | Declared inputs/toolchains, producer actions, action caching and tests |
| ProjectSync | Evaluating projects into committed declarations and contracts |
| MSBuild + cache plugin | SDK targets, compilation and reuse of configured projects |
| ArtifactTools | Package extraction, layout composition and app/test launch |

SDKs, runtimes, packages and task tools are artifacts. Downloaded and source-built
SDKs share a layout contract; compilation and execution toolchains are separate.

## Execution and caching

Sync records project paths plus global properties, inputs and output ownership.
Builds consume that contract and restore from declared packages. Definition,
source-list, package or configuration changes require sync. Custom task reads
need reviewed declarations; evaluation does not trace arbitrary file access.

Bazel can recover a whole unchanged Restore/build action. When the graph action
changes, the MSBuild plugin can recover individual projects from worker snapshots
or HTTP AC/CAS. A hit restores artifact bytes and target-result metadata.
Every request verifies declared bytes; MSBuild result metadata alone is not a cache.

Stable Linux workers can retain preparation and, for reviewed compiler-only edits,
pristine evaluation. Each request gets fresh project instances and build nodes.
Other input/configuration/membership changes, failures and retention limits reset
the engine. Prepared Restore can be a separate action reused across source edits.

## Invalidation

Keys include inputs, configuration, SDK/runner identity, outputs and dependency
roles. Dependencies are conservative unless a reference boundary is qualified.
For `A → B → C`, a changed C compiler DLL rebuilds B. A can reuse compilation if
B's compiler DLL stays unchanged and A does not directly read C. MSBuild may select
an authored reference assembly, an SDK reference assembly or an implementation DLL.
The selected bytes determine compiler invalidation; task/analyzer/tool reads keep
conservative dependency keys.

Opt-in sync qualification runs a private Build to capture complete compiler and
copy selections. New snapshots verify those selections against MSBuild's resolved
inputs. Runtime copies refresh even when compilation is reused, and app/test
layouts include their implementation dependencies. Hidden task reads and
Pack/Publish selection changes still require separate contracts.

[API](api.md) defines configuration; [support](support.md) records qualification
and isolation limits.
