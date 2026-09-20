# Evaluation: work to remove or share

Analysis based on `5c89f6f` plus opt-in evaluation profiling. The production
collection/cache behavior is unchanged. The XML reuse option below was enabled
only in a disposable Linux container using the checked-in experiment patch.

## Main finding: reuse parsed SDK XML and target bodies

Every evaluation currently constructs `new ProjectCollection()`. Its default is
not to reuse the process-wide ProjectRootElement cache. This repeats reading and
parsing the same SDK imports across projects, and discards another useful cache:
MSBuild stores an unexpanded `ProjectTargetInstance` on each parsed target element.

The public ProjectCollection constructor supports `reuseProjectRootElementCache`.
The experiment selects it while retaining a new ProjectCollection, ProjectInstance
and BuildManager per evaluation/build. It does not share evaluated properties,
items, target results or a previously built ProjectInstance.

The upstream implementation explains the two levels:

- [ProjectCollection construction](https://github.com/dotnet/msbuild/blob/main/src/Build/Definition/ProjectCollection.cs)
  selects a shared XML cache when requested.
- [Evaluator.ReadTargetElement](https://github.com/dotnet/msbuild/blob/main/src/Build/Evaluation/Evaluator.cs)
  reuses `targetElement.TargetInstance` when present. Its target body remains
  unexpanded until build execution. Per-project target selection and BeforeTargets/
  AfterTargets mappings are still constructed for each evaluation.
- [ProjectRootElementCache](https://github.com/dotnet/msbuild/blob/main/src/Build/Evaluation/ProjectRootElementCache.cs)
  manages retention and reload checks. This is a bounded strong-reference cache,
  not a promise that every SDK file is parsed exactly once forever; eviction can
  require another parse. Source links describe upstream implementation; the pinned
  SDK's public API was compiled and its performance/behavior tested directly.

### Measured cold builds

129 package-free projects, shared Bazel restore inputs, Linux ARM64, pinned
.NET 10.0.400/Bazel 8.4.2, four vCPUs, 6 GiB. Native Linux storage, preprovisioned
SDK/downloads, disabled action caches, fresh workers/outputs, unflushed OS caches.
Sequential cohorts rather than randomized pairs.

| Build-action elapsed time | Existing behavior | XML-cache reuse experiment |
| --- | ---: | ---: |
| Uninstrumented samples | 16.83 / 17.05 s | 12.90 / 12.50 s |
| Uninstrumented mean | **16.94 s** | **12.70 s** |
| Detailed profiler samples | 19.74 / 19.29 s | 15.56 / 15.84 s |

**25.0% less cold build-action time**, including fresh worker startup. The final
raw-MSBuild samples are 6.80 / 6.74 s (6.77 s mean), making the experiment **1.88x**
raw MSBuild. Initial workspace setup/analysis adds 4.69 s to its first run.
This is not an Orchard/package-heavy performance claim.

All **647 reference/runtime files**, including PDBs, are byte-identical between
the baseline and experiment. Detailed evaluation profiling is expensive (roughly
15–24% end-to-end overhead here); speed comparisons use uninstrumented controls.

### Evaluation attribution

The following are **summed worker durations under the detailed profiler**, not
portions of the 16.94/12.70-second elapsed builds. They should not be used to
project uninstrumented savings.

| Evaluator pass | Existing behavior | XML reuse |
| --- | ---: | ---: |
| Properties/import processing | 12.58 s | 4.06 s |
| Target definition processing | 9.54 s | 3.98 s |
| Items | 1.84 s | 1.41 s |
| Lazy items | 1.39 s | 1.12 s |
| Using tasks | 0.22 s | 0.13 s |
| Initial properties | 0.02 s | 0.02 s |
| Item definitions | 0.02 s | 0.02 s |
| Total evaluation, inclusive | 25.63 s | 10.76 s |

Pass values may be nested (notably lazy items); do not sum them. Collection setup
itself is only 0.09 summed seconds in the baseline, including profiler registration.
The cost is the lost reuse downstream, not allocating the collection object.
Import sites dominate the original hotspots. With XML reuse, bundled SDK framework
metadata and remaining property/target processing become more visible. This is
strong evidence for restoring MSBuild's existing caches before designing a second
SDK evaluator or skipping arbitrary targets.

## What can be shared, and what must remain project-specific

| Work | Proposed lifetime/removal | Evidence/constraint |
| --- | --- | --- |
| Parse immutable SDK props/targets | Reuse per worker through MSBuild's XML cache | Measured above; worker tool changes must replace the process |
| Construct unexpanded SDK target bodies | Reuse with their parsed XML | Already implemented by MSBuild; benefits are included above |
| SDK resolution and immutable SDK filesystem facts | Investigate per worker, keyed to SDK identity | Use a narrow cache; no measured incremental gain yet |
| Default source/item globs and ancestor configuration searches | Remove where explicit Bazel declarations fully replace them | Requires a qualified contract; do not bypass original-item validation or custom imports silently |
| SDK framework/reference-pack metadata tables | Potential Bazel preparation artifact per SDK/framework/configuration | Preserve SDK selection/metadata semantics; bundled-version file still costs 0.69 profiler worker-seconds after XML reuse |
| Project properties, conditions, item expansion, import selection | Evaluate for each configured project | Depend on project path, configuration, imports and declared inputs |
| Build results or mutable ProjectInstance state | Keep per action | Reusing a built instance can leak outputs/items and stale dependencies |

A blanket shared
[EvaluationContext](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.context.evaluationcontext)
is not the same as an XML cache. Its documented lifetime includes filesystem,
environment and SDK-resolution state; the worker changes request files and
HOME/temp paths between builds. Do not reuse that entire context without scoping
its caches. The SDK exposes a SharedSDKCache policy, which is a narrower candidate,
not a measured benefit in this experiment.

## Recommendation

First production change: adopt parsed-XML reuse for the persistent worker, keeping
fresh evaluated/build state and current tool invalidation. Qualify changed imports,
configuration/framework switches, generated restore imports and long-lived memory
behavior before broadening the supported scope. Retain the fresh-process fallback.
Then profile the remaining property/target work before moving another metadata
slice into Bazel. Removing all project evaluation is not justified by these results.

## Reproduction and evidence

Build ExplicitBuild and run `cold_profile.py` with
`RULES_MSBUILD_SHARED_RESTORE=1`. `profile_build=True` now adds MSBuild evaluation
pass/file/hotspot data and separates collection setup from evaluation. Run
`summarize_evaluation.py` on the evidence directory. Apply
`tests/explicit_msbuild/evaluation_xml_reuse.patch` only to a disposable checkout,
rebuild the runner, and repeat into a new output directory.

Checked-in [baseline](evidence/project-evaluation/baseline.json),
[experiment](evidence/project-evaluation/xml-reuse.json) and
[output comparison](evidence/project-evaluation/output-comparison.json) preserve
measurements. Full local profiles are under `artifacts/evaluation-baseline/` and
`artifacts/evaluation-reuse/`.

The experiment also passes the existing Linux worker acceptance controls: PID reuse
on source edits, PID replacement on tool changes, same-size/same-time source edits,
compiler failure/recovery, declaration rejection, sandbox negatives, producer-free
relocated cache recovery and actual compilation afterward. The real 16-package MTP
fixture passes, fails, and recovers, and rejects invalid package metadata/versions.
These are sampled correctness controls, not full qualification of arbitrary
project/import combinations or long-running cache memory behavior.
[Acceptance](evidence/project-evaluation/acceptance.json) and
[MTP](evidence/project-evaluation/mtp.json) reports are retained.

The profiling additions pass `scripts/check-dotnet.sh` (including its pre-existing
single environment-dependent skip), `git diff --check`, and experiment patch
applicability checks. The temporary container was removed after saving evidence.
No production cache default was enabled and no GitHub CI ran.
