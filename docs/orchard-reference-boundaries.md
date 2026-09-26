# Orchard after reference-boundary inference

PR #92 is merged at `7d63ab98ac57ca70587d8e7c7686c45f58614dca`. The complete
202-project Orchard CMS graph still builds and passes its four HTTP smoke checks.
**The inference change does not improve this graph's broad API edit by itself.**
Orchard's generated declarations use transitive compiler references; regeneration
on merged main preserves their bytes. No direct-only opt-in is present.

## Incremental measurements

Orchard `04467a3438d4255627c1a478598a1585b3ff2947`, SDK 10.0.400, Bazel 9.2.0,
Linux ARM64. One 6-CPU/10-GiB build VM and two build slots; two Bazel workers with
a 4096-MB soft retained-worker budget. Release uses the graph's existing target
frameworks, including the netstandard2.0 source generator. Raw MSBuild builds the
same CMS entry project with `--no-restore`; downloads and warm-up are excluded.

Three samples alternate build-system order. Both systems retain their servers
between edits. A local Bazel disk cache is enabled to check reversion; HTTP caching
is disabled. Timers include client startup and log writing, but exclude subsequent
log compression and guest disk trimming. This differs from the earlier
[workflow protocol](project-sync-workflow-costs.md), which separated build-system
phases and disabled action caches. These results are not an isolated before/after
comparison with that report.

| Edit | Bazel samples (s) | Raw MSBuild samples (s) | Median comparison |
| --- | --- | --- | --- |
| No-op | 0.850, 0.719, 0.467 | 14.313, 12.752, 11.298 | 0.719 vs 12.752 s |
| Body | 2.409, 5.575, 2.686 | 10.644, 11.016, 11.402 | 2.686 vs 11.016 s |
| Public API addition | 142.214, 154.178, 156.434 | 29.798, 29.034, 31.401 | 154.178 vs 29.798 s |

The body edit changes `NotFoundManifestInfo.Description`; the API edit adds an
unused public property to the same type in `OrchardCore.Abstractions`. Every body
sample compiles one project and changes no reference DLLs. Every API sample
compiles 193 projects. API latency remains about **5.17× raw** in this protocol;
body latency is about **4.10× faster**. These are bounded samples, not a claim about
all Orchard edits. Sources are restored between samples, with cached Bazel
compilation results recovered on reversion.

The full generated build executes 202 compilations during setup. Both raw and
Bazel applications render the setup page and serve the three qualified embedded
assets, whose hashes match exactly. This is the CMS build/smoke slice, not the
whole Orchard unit-test suite. This follow-up measures Bazel 9.2.0 only.

## Two separate reasons the boundary does not stop propagation

### Compiler inputs remain transitive

`OrchardCore.Abstractions` has **31 direct and 192 transitive project consumers**
in the qualified graph. A compiler consuming C directly must invalidate when C's
reference changes, even if the intervening B reference stays unchanged. The
[synchronization fix](reference-invalidation.md) respects an explicit project
choice; it does not infer that transitive references are unnecessary.

The library opt-out probe uses the supported `transitiveCompileReferences=false`
mapping for all 201 libraries, retaining the executable's transitive runtime
manifest mode. Raw MSBuild probes the SDK property
`DisableTransitiveProjectReferences=true`. This is a compatibility probe, not a
performance candidate: the existing projects require additional direct references.
See the evidence for compiler diagnostics. For example, raw
`OrchardCore.Localization.Core` needs `OrchardCore.Abstractions` for
`DataLocalizedString`, and `OrchardCore.Data.YesSql` needs
`OrchardCore.Data.Abstractions` for `DatabaseTableOptions`.

### Asset paths change public metadata

The API samples change **89 Bazel reference DLLs**, not just C's reference. A
follow-up comparison around raw API reversion changes four; the two retained
repeat samples record each system's reference changes directly. Raw has additional
changes from Orchard's known random interceptor generation.

**87 changed Bazel module/theme references contain altered asset-path strings.**
For all 87, those asset-string lists are identical after normalizing only the
content-identity component of the worker path. For example, an unchanged Setup
view is embedded in assembly metadata as:

```text
Areas/OrchardCore.Setup/Views/Setup/Index.cshtml|/__rules_msbuild/in/<action-content-identity>/workspace/src/OrchardCore.Modules/OrchardCore.Setup/Views/Setup/Index.cshtml
```

A changed dependency changes the worker identity, so this string changes even
though the asset and its logical name are unchanged. This is a string comparison
for diagnosis; no binaries are rewritten, and it does not assert that every other
byte of those DLLs is identical.

The [stable-worker-path report](orchard-stable-worker-paths.md) already documents
the two underlying mechanisms: Orchard emits `ModuleAssetFiles.FullPath` into
public attributes, and `ArgumentsFromInterceptor` uses random GUIDs. Content-based
worker paths made identical actions stable while protecting against stale MSBuild
XML and Roslyn metadata. They do not make those attributes stable across changed
actions. This run measures the incremental consequence of that distinction.

## Reproduce and evidence

Prepare the disposable generated/raw workspaces as described in
[broader-graph qualification](project-sync-broader-graphs.md), then run in the pinned
Linux tool environment with enough host disk space:

```sh
python3 tests/project_sync/upstream/orchard_reference_boundaries.py \
  GENERATED_ORCHARD RAW_ORCHARD OUTPUT --repetitions 3
python3 tests/project_sync/upstream/orchard_reference_metadata.py \
  OUTPUT OUTPUT/warmup-bazel.execution.json.gz \
  OUTPUT/api-0-bazel.execution.json.gz OUTPUT/asset-paths.json
```

The driver backs up and restores source/mapping/generated inputs, records hashes
and execution logs, compresses large logs outside timing, trims deleted guest
blocks between commands, and stops the build servers. `--probe-only` runs only
the opt-out control. A completed output base/cache can be reused with `--state`;
use a fresh `--sample-offset` so measured edits cannot hit earlier cached results.

[Compact evidence](orchard-reference-boundaries-evidence.json) contains all nine
paired timings, action labels, reference-change records, smoke results and the
asset-string comparison. The retained sequence used targeted continuation:

- An initial setup hit host disk exhaustion and an overly broad hash assumption
  about the source generator. That setup is excluded. Completed synthetic state
  was reclaimed, inputs were recovered from retained source archives, and warm-up
  restarted. Raw's source generator emits no separate reference assembly, so the
  oracle compares the other 201 and requires the generator to stay unchanged.
- Sample 0's API build succeeded, but the initial exact reference-change-parity
  assertion exposed the metadata difference above. Its timings/action log remain
  valid. Raw reversion was inspected separately; samples 1–2 record the differing
  reference sets rather than claiming parity. Their warm-up recovers the unchanged
  Bazel baseline from cache. Raw reference baselines refresh after each revert to
  account for upstream generator randomness.
- The first opt-out attempt used the generic property map and hit the runner's
  reserved-property guard. It is excluded from compiler-compatibility evidence;
  the supported explicit library mapping was tested separately.

No production rules or upstream sources are changed by this follow-up, and no CI
workflow was dispatched. Runtime smoke parity does not establish reference-byte
parity, reproducibility of upstream random generators, or remote execution.

## Next work

Separate stable compiler-visible project/asset paths from content identity while
preserving digest verification and stale MSBuild/Roslyn cache protection. Prove
same-size/same-timestamp edits, runtime assets, workers and independent recovery
before applying that design to Orchard. In parallel, identify valid direct-reference
boundaries and explicitly declare genuinely required transitive types. Stabilizing
metadata alone will not remove the 193 compilations while C remains a declared
compiler input throughout this graph.
