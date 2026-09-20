# Evaluation: work to remove or share

Original analysis based on `5c89f6f` plus opt-in evaluation profiling. The initial
experiment below ran in a disposable Linux container. Parsed-XML reuse is now
enabled for persistent workers; see the production validation below.

## Main finding: reuse parsed SDK XML and target bodies

Before this change, every evaluation constructed `new ProjectCollection()`. Its default is
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

Parsed-XML reuse is now enabled for the persistent worker, keeping fresh
evaluated/build state and current tool invalidation. Changed imports, Release/Debug
switches and generated restore inputs pass the controls below. Framework switches
and long-lived memory behavior need further qualification before broadening scope. Retain the fresh-process fallback.
Then profile the remaining property/target work before moving another metadata
slice into Bazel. Removing all project evaluation is not justified by these results.

## Reproduction and evidence

Build ExplicitBuild and run `cold_profile.py` with
`RULES_MSBUILD_SHARED_RESTORE=1`. `profile_build=True` now adds MSBuild evaluation
pass/file/hotspot data and separates collection setup from evaluation. Run
`summarize_evaluation.py` on the evidence directory. The current runner needs no
patch. The historical prototype patch is available at commit `0d90ff3` under
`tests/explicit_msbuild/evaluation_xml_reuse.patch`.

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
That experiment did not enable production reuse. No GitHub CI ran.


## Production enablement and validation

`BuildProject` now enables `reuseProjectRootElementCache` only when running in the
isolated persistent worker. Fresh-process execution retains the default. Each
request still creates fresh collections, evaluated instances and build managers.
The shared cache retains parsed XML and unexpanded target bodies, not build results
or evaluated properties/items. Declared SDK/runner changes replace the worker;
dynamic XML uses content-identified request paths. MSBuild controls eviction, so
this avoids repeated work when entries remain cached rather than promising one
parse forever.

A new four-CPU Linux run of the same 129-project graph measured **13.58 / 12.47 s**
uninstrumented, **13.02 s mean**: **23.1% less** than the earlier 16.94 s baseline.
These are separate sequential cohorts, not randomized pairs. Raw MSBuild measured
6.54 / 6.39 s, **6.46 s mean**, making the worker build **2.01x raw**. Initial
startup/analysis adds 4.67 s; the first complete run takes **18.25 s**. Downloads
and SDK provisioning remain excluded. Instrumented samples are kept separately
because profiling adds overhead. This remains a package-free graph measurement.

The new `xml_reuse.py` fixture runs after worker acceptance and covers an explicit
custom import in the general per-project restore lane. It checks a same-size import
edit with restored timestamp in the same worker, Release/Debug output, another
import edit in the Debug worker, malformed XML rejection, and recovery in that
same worker. Existing acceptance passes tool-key replacement, source edits,
declaration rejection, sandbox negatives, deleted-producer relocated cache recovery
and compilation afterward. The real 16-package MTP fixture passes/fails/recovers;
protocol tests reject forged digests and arbitrary tool roots.

```sh
RULES_MSBUILD_SHARED_RESTORE=1 RULES_MSBUILD_EXPLICIT_WORKER=1 \
  RULES_MSBUILD_CHECK_TOOL_RESTART=1 \
  python3 tests/explicit_msbuild/acceptance.py /tmp/acceptance
python3 tests/explicit_msbuild/xml_reuse.py /tmp/acceptance
```

[Timing/evaluation summary](evidence/project-evaluation/enabled.json),
[import/configuration controls](evidence/project-evaluation/enabled-imports.json),
[acceptance](evidence/project-evaluation/enabled-acceptance.json) and
[MTP](evidence/project-evaluation/enabled-mtp.json) retain compact evidence.
Full local logs are under `artifacts/worker-xml/`. These checks do not establish
arbitrary import/plugin compatibility or package-heavy performance.

Production enablement passes `scripts/check-dotnet.sh` (one existing
environment-dependent skip) and `git diff --check`. No GitHub CI was run.
