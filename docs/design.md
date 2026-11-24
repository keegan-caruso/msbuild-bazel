# Design

Builds a selected project graph in one Bazel action using the MSBuild project-cache plugin (sole compilation backend). MSBuild retains SDK targets, configuration, and scheduling; shared evaluation avoids a process per project.

## Ownership

| Component | Owns |
| --- | --- |
| Bazel | Declared inputs/toolchains, producer actions, action caching, tests |
| ProjectSync | Evaluating projects into committed declarations and contracts |
| MSBuild + cache plugin | SDK targets, compilation, reuse of configured projects |
| ArtifactTools | Package extraction, layout composition, MTP/VSTest protocols |

SDKs, runtimes, packages, and task tools are artifacts. NuGet resolves only in the explicit update job; committed locks and archive manifests become Bazel inputs for offline Restore. Downloaded and source-built SDKs share a layout contract; compilation and execution toolchains are separate. Downloaded SDK pins (`global.json` or `dotnet.sdk(version = ...)`) resolve release metadata once per SDK/platform, writing immutable archive facts to `MODULE.bazel.lock` (hashes verified on download; download availability does not imply MSBuild compatibility). Separate runtime declarations use the same metadata/lockfile flow; app `runtimeconfig` controls framework compatibility and roll-forward.

## Execution and caching

Sync records project paths, global properties, inputs, and output ownership. Builds consume that contract and restore from declared packages; definition, package, configuration, or explicit source-list changes require sync. Reviewed Compile globs expand Bazel-declared members per request (membership changes update project keys and reset evaluation without changing prepared Restore). Custom task reads need reviewed declarations (evaluation does not trace arbitrary file access).

With a complete `msbuild_sync(srcs = ...)` snapshot, evaluation and private compiler qualification run as a cacheable Bazel action (Bazel owns reuse/invalidation) and a local publisher writes/checks declarations; without `srcs`, sync evaluates locally each run. Opt-in Linux qualification caching adds per-project reuse inside a changed preparation action: early evaluated inputs key verified SDK artifacts and compiler/copy metadata in HTTP AC/CAS using a fixed private namespace and conservative dependency closure keys. Verified Restore products have a separate key over source layout/content, SDK, packages, tools, properties, and mappings; explicit `restoreReuseInputs` can exempt reviewed compiler-only contents while post-Restore evaluation and compiler keys still read current files. Qualification transfers full evaluated instances to build nodes (sharing targets/task registrations without re-evaluating), shares read-only SDK/package identities within the invocation, stages privately via CoW clones where available (ordinary copies otherwise), verifies materialized bytes on replay, and keeps pre/post-Build byte checks on mutable inputs. The final graph contract remains the build interface. Opt-in `seed_build_cache` qualifies in the ordinary Linux namespace, retains intermediate products, and hands an input/output proof to the ordinary runner—which reuses verified Restore products, evaluates with generated products temporarily set aside, verifies SDK bytes, pristine properties/items, compiler selections, requested targets, and complete owned products, then publishes normal snapshots. Qualification and ordinary keys stay separate; only validated products cross, and changed inputs or incompatible context reject the handoff.

Bazel recovers whole unchanged Restore/build actions. When the graph action changes, the MSBuild plugin recovers individual projects from worker snapshots or HTTP AC/CAS (restoring artifact bytes + target-result metadata). Every request verifies declared bytes; MSBuild result metadata alone is not a cache.

Stable Linux workers retain preparation and (for reviewed compiler-only edits) pristine evaluation; each request gets fresh project instances and build nodes. Other input/configuration/membership changes, failures, and retention limits reset the engine. Prepared Restore can run as a separate action reused across source edits.

## Invalidation

Keys include inputs, configuration, SDK/runner identity, outputs, and dependency roles. Dependencies are conservative unless a reference boundary is qualified. For `A → B → C`, a changed C compiler DLL rebuilds B; A reuses compilation if B's compiler DLL is unchanged and A does not directly read C. MSBuild may select an authored reference assembly, SDK reference assembly, or implementation DLL; selected bytes govern compiler invalidation, while task/analyzer/tool reads keep conservative dependency keys.

Opt-in sync qualification runs a private Build to capture compiler and copy selections; new snapshots verify those selections against MSBuild's resolved inputs. Runtime copies refresh even on compilation hits, and app/test layouts include implementation dependencies. Hidden task reads and Pack/Publish selection changes require separate contracts.

See [API](api.md) for configuration and [support](support.md) for qualification/isolation limits.
