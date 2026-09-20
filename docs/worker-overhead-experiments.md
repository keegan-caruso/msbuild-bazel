# MSBuild execution, evaluation and prepared-reference experiments

## Outcome

Worked through all three priorities after `015682c`. **None of the tested runtime
changes established a meaningful end-to-end speedup.** Retain the finer lifecycle
profiling and reproducible evidence; discard the speculative manager/node cache,
SDK-resolution sharing, ancestor-search suppression, reference metadata changes
and logging change. Production build/cache behavior stays unchanged.

129 package-free projects, shared restore, .NET 10.0.400/Bazel 8.4.2, Ubuntu 22.04
ARM64, four vCPUs/6 GiB, native Linux storage. Each cohort alternates two controls
and two detailed profiles, then measures two raw MSBuild builds. Workers/outputs
restart each time; OS caches are not flushed. SDK/repository provisioning and
initial analysis are excluded from build time. Sequential cohorts are not randomized
pairs; observed differences of 1–2% do not establish a win given sample variation.

| Experiment | Uninstrumented build samples, seconds | Mean seconds |
| --- | ---: | ---: |
| lifecycle | 13.45 / 12.21 | 12.83 |
| manager-reuse | 13.52 / 11.88 | 12.70 |
| engine-reuse | 12.78 / 12.67 | 12.73 |
| evaluation-reuse | 13.37 / 12.63 | 13.00 |
| prepared-references | 12.93 / 12.16 | 12.54 |
| minimal-logging | 12.78 / 12.68 | 12.73 |

Baseline raw MSBuild: **6.75 / 6.31 s**, mean **6.53 s**. Later cohort raw means
range **6.82–7.11 s**, further evidence of run-to-run/environment variation.
The baseline worker/raw ratio is **1.96x**, consistent with the previous refresh's
1.84x. Do not claim that these small differences are production improvements.

## 1. MSBuild execution lifecycle

Profiling now separates manager setup, BeginBuild, BuildRequest, EndBuild and
manager disposal. Normal uninstrumented execution still calls `BuildManager.Build`.
The successful profiled path follows its public BeginBuild/BuildRequest/EndBuild
sequence; EndBuild is protected by finally, and manager disposal is protected by
using. Per-action ProjectCollection/ProjectInstance/BuildManager state remains fresh.
The final disposal marker was added after the timing cohorts; earlier reports
include disposal in the remaining child/protocol residual, not a separate phase.

Baseline summed worker wall-seconds (not elapsed-time slices):

| Phase | Seconds |
| --- | ---: |
| Project evaluation | 10.94 |
| Manager and request setup | 0.025 |
| BeginBuild | 1.07 |
| BuildRequest | 20.91 |
| EndBuild | 3.13 |
| Csc task, nested inside BuildRequest | 8.83 |

Keeping the manager while resetting project/result caches gave **12.70 s**, versus
**12.83 s** baseline. Also retaining the execution node gave **12.73 s**. BeginBuild
and EndBuild still total about **3.94 worker-seconds**, versus **4.19** baseline.
Allocation is negligible and retaining the manager does not remove the build-session
lifecycle. Added retained state is not justified by this result.

An additional output experiment reduced each control build log from about **7.3 MB
to 28 KB** using Minimal console verbosity, while keeping warnings/errors. It
measured **12.73 s** and is also discarded as a performance change. Csc/task time
and target execution remain more substantial than log output transport here.

A process-long build session would be a different change. It must solve request
logger/environment lifetimes and safe cache eviction. MSBuild's
[ClearCachesAfterBuild flag](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.execution.buildrequestdataflags)
also clears parsed XML caches; it is not a free way to keep only engine infrastructure.
The [BuildManager implementation](https://github.com/dotnet/msbuild/blob/main/src/Build/BackEnd/BuildManager/BuildManager.cs)
explains BeginBuild/EndBuild and node/cache lifecycle. These links describe upstream
APIs; measurements used the pinned SDK directly.

## 2. Remaining evaluation

Tested an SDK-resolution-only shared EvaluationContext for the qualified plain-SDK
worker lane, plus disabling Directory.Build.props/targets and Directory.Packages.props
ancestor searches. Shared-restore qualification rejects those inputs already.
Fresh filesystem/glob caches and evaluated instances were retained. General
projects/imports kept their existing behavior.

The experiment averaged **13.00 s** versus **12.83 s** baseline. Profiled evaluation
was **11.36** versus **10.94 summed worker-seconds**. It does not establish a benefit;
all of these runtime changes are discarded. SDK resolution and ancestor searches
are not the next large saving in this fixture. Repeated property expansion and
configured-target processing remain. The SDK metadata expansion itself is not
replaced with a second evaluator.

[SharedSDKCache documentation](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.context.evaluationcontext.sharingpolicy)
confirms that this policy shares SDK resolution, not filesystem caches.

## 3. Prepared references

Bazel already supplies the transitive project-reference closure and reference
assembly files. The experiment marks those Reference items ExternallyResolved and
sets their ReferenceAssembly paths in the qualified shared-restore lane. It keeps
RAR and SDK conflict handling, framework references, and normal package behavior.

ResolveAssemblyReference dropped from **1.53 to 1.35 summed worker-seconds (12%)**.
Elapsed time averaged **12.54 s**, about **2.2% lower**, inside this cohort's timing
variation. The saving in the targeted task is only **0.18 worker-seconds**. This
small result does not justify claiming a cold-build win; runtime metadata changes
are discarded too. Skipping the entire RAR/SDK target graph would require preparing
and validating all of its output metadata, not merely forwarding DLL paths.

## Correctness, reproduction and evidence

All five variants produced **647 byte-identical reference/runtime output files**
against the profiled baseline, including PDBs. See
[output comparison](evidence/worker-overhead/output-comparison.json).
Compact timing, lifecycle and task reports for every cohort are in
[the evidence directory](evidence/worker-overhead/). Full profiles, traces and logs
remain locally in `artifacts/` under each cohort name.

Reproduce each measured source in a disposable checkout by applying its patch from
`tests/explicit_msbuild/experiments/`, rebuilding ExplicitBuild, then running:

```sh
RULES_MSBUILD_SHARED_RESTORE=1 \
  python3 tests/explicit_msbuild/cold_profile.py /tmp/CASE /evidence/CASE
python3 tests/explicit_msbuild/summarize_cold_profile.py /evidence/CASE
```

Patches are experiments only; do not apply multiple patches together. They target
the final profiling source and reproduce each measured variant, including the earlier
phase layout. Set RULES_MSBUILD_DOTNET_ROOT, RULES_MSBUILD_BAZEL and
RULES_MSBUILD_REPOSITORY_CACHE to the pinned tools/cache in the Linux container.
The acceptance harness now accepts `RULES_MSBUILD_PROFILE_BUILD=1` to test the
profiled lifecycle under compilation failure/recovery and cache controls.

## Next investment

These results narrow the problem: retained manager objects, SDK resolution, and
reference dependency discovery are not large enough to close the gap. The larger
remaining categories are configured SDK evaluation and actual target execution.
Before introducing a process-long build session or replacing SDK target outputs,
measure the real large application workload. This synthetic graph deliberately
amplifies per-project overhead and cannot establish Orchard/package-heavy gains.


## Final validation

`RULES_MSBUILD_PROFILE_BUILD=1 RULES_MSBUILD_SHARED_RESTORE=1
RULES_MSBUILD_EXPLICIT_WORKER=1 RULES_MSBUILD_CHECK_TOOL_RESTART=1` acceptance passes
with assertions for all five lifecycle phases and exactly one Csc task per build.
This includes compilation failure/recovery, tool replacement, source edits,
negative declaration/sandbox checks, deleted-producer cache recovery and compilation
after relocation. Changed-import/configuration checks, actual 16-package MTP
pass/fail/recovery and protocol rejection controls also pass. Their reports and a
[final phase record](evidence/worker-overhead/final-profile-check.json) are retained.

`scripts/check-dotnet.sh` passes, with its one existing environment-dependent skip.
The initial invocation had an incorrect local Bazel path; rerunning with the correct
path passed. `git diff --check` and applicability checks for all six experiment
patches pass. No GitHub CI was run. The task container was removed after preserving
all evidence.
