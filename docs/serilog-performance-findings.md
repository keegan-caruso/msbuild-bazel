# R04 Serilog comparative measurement findings

The bounded measurement harness passed three repetitions of ordinary MSBuild
and the Bazel adapter for the pinned `Serilog.ApprovalTests` project and its
Serilog dependency at Release/net10.0. All 24 system/case samples passed their
output, work-set and actual-test checks. Numeric latency and memory budgets were
unset before the run, so these are descriptive measurements, not a performance
pass or speedup claim.

The recorded command was:

```sh
/nix/var/nix/profiles/default/bin/nix \
  --extra-experimental-features 'nix-command flakes' \
  develop -c python3 tools/probe_serilog_performance.py \
  --source /private/tmp/msbuild-serilog-baseline-3/source \
  --packages /private/tmp/msbuild-serilog-baseline-3/packages \
  --output /private/tmp/serilog-performance-qualification-1 \
  --repetitions 3 \
  --bazel-mode server \
  --host-note 'No concurrent adapter validation during measurement; normal desktop activity and shared compiler/OS caches are uncontrolled.'
```

The retained report is
`/private/tmp/serilog-performance-qualification-1/report.json`; its source
archive SHA-256 is
`bc289bfa238dd5c3f244027feade1b5cf9b0ae72ad33a3763f44583734bd4e98`.
The adapter checkout was at `5e784879a723e5bafffc3643fd8b9217759033c4`
with the complete dirty-worktree inventory captured in the report.

The default is five repetitions and the harness refuses fewer than three. Bazel
uses the repository's default persistent-server mode, with one server scoped to
each independent case/system sample and an explicit shutdown afterward. Pass
`--bazel-mode batch` only for a separately labeled batch-mode experiment; its
startup-heavy results do not represent the repository default. The harness
interleaves ordinary MSBuild and Bazel order for each repetition. Every system
and case receives a separate source copy, outputs and caches. Edited and
recovered cases first warm their own unchanged baseline, so no mutation or warm
state flows from another case.

The pinned Nix Bazel system rc is retained because it supplies Bazel's pinned
JDK. Home and workspace rc files are disabled and the effective policy is
recorded in the report.

Both paths preserve the SDK's default shared C# compiler-server behavior. The
harness disables MSBuild node reuse but does not kill or disable VBCSCompiler;
it records matching compiler-server process snapshots before and after every
sample. Any reuse across systems or repetitions is therefore disclosed host
state, and these measurements do not isolate compiler-server startup cost.

The host was macOS 26.6.2 (`Darwin 25.6.0`) on ARM64 with 11 logical CPUs and
19,327,352,832 bytes of physical memory. The selected tools were .NET SDK
10.0.100 and Nix Bazel 8.4.2. The pinned package directory contained 2,969 files
and 316,361,102 bytes. One VBCSCompiler process was present with the same PID and
start time in every before/after snapshot. No other adapter validation ran, but
normal desktop activity and shared compiler/OS caches were uncontrolled.

## Observed timings

Times are seconds, shown as median `[minimum, maximum]` across three
repetitions. “Comparison” excludes acquisition, Restore, independent warm-up,
assertions, evidence copying and server shutdown. “Full workflow” adds recorded
source/package setup, Restore and required independent warm-up; final server
shutdown remains cleanup rather than workload time.

| Case | Ordinary comparison | Bazel comparison | Ordinary full workflow | Bazel full workflow |
| --- | ---: | ---: | ---: | ---: |
| Fresh | 1.901 `[1.881, 2.023]` | 14.915 `[14.641, 15.538]` | 3.530 `[3.412, 4.015]` | 16.361 `[16.275, 17.005]` |
| Unchanged | 1.581 `[1.547, 1.939]` | 6.270 `[6.253, 6.401]` | 4.690 `[4.619, 4.803]` | 21.039 `[20.659, 21.594]` |
| Source edited | 1.572 `[1.571, 1.574]` | 7.864 `[7.823, 7.866]` | 4.175 `[4.133, 4.670]` | 22.413 `[21.780, 22.520]` |
| Recovered | 1.799 `[1.741, 1.819]` | 11.300 `[10.739, 11.491]` | 4.346 `[4.316, 5.027]` | 27.340 `[26.772, 28.381]` |

The measured comparison phases were:

| Case | System | Export | Preparation | Build | Actual test |
| --- | --- | ---: | ---: | ---: | ---: |
| Fresh | Ordinary | n/a | n/a | 1.108 `[1.072, 1.234]` | 0.793 `[0.789, 0.810]` |
| Fresh | Bazel | 0.564 `[0.556, 0.566]` | 3.654 `[3.515, 3.722]` | 8.471 `[8.329, 9.111]` | 2.156 `[2.094, 2.355]` |
| Unchanged | Ordinary | n/a | n/a | 0.787 `[0.771, 1.102]` | 0.793 `[0.777, 0.837]` |
| Unchanged | Bazel | 0.573 `[0.570, 0.623]` | 3.091 `[3.079, 3.128]` | 0.564 `[0.559, 0.569]` | 2.045 `[2.033, 2.091]` |
| Source edited | Ordinary | n/a | n/a | 0.784 `[0.782, 0.787]` | 0.788 `[0.786, 0.792]` |
| Source edited | Bazel | 0.565 `[0.564, 0.569]` | 3.142 `[3.087, 3.178]` | 2.078 `[2.031, 2.084]` | 2.074 `[2.046, 2.137]` |
| Recovered | Ordinary | n/a | n/a | 1.006 `[0.955, 1.036]` | 0.786 `[0.782, 0.793]` |
| Recovered | Bazel | 0.568 `[0.565, 0.570]` | 3.670 `[3.633, 3.676]` | 4.863 `[4.410, 5.086]` | 2.195 `[2.092, 2.202]` |

Setup remained separate. Across all 12 samples per system, ordinary source
extraction was 0.046 `[0.043, 0.060]`, package copy 0.637
`[0.511, 1.065]`, and Restore 0.896 `[0.844, 0.953]`. Bazel source
extraction was 0.045 `[0.043, 0.051]`, package copy 0.559
`[0.527, 1.253]`, and Restore 0.946 `[0.836, 1.114]`. The Bazel recovery's
additional relocated extraction, package copy and Restore were respectively
0.044 `[0.043, 0.044]`, 0.909 `[0.532, 1.078]`, and 0.515
`[0.514, 0.517]`. One-time repository acquisition was also retained separately:
source extraction 0.040, package copy 1.062, Restore 1.008, export 0.516,
preparation 3.448 and Bazel no-build repository acquisition 5.516 seconds.

## Observed work sets and tests

Every row repeated exactly three times with the same result:

| Case | Ordinary actual Csc tasks | Bazel Build evidence | Actual test evidence |
| --- | ---: | --- | --- |
| Fresh | 2 | Serilog and Serilog.ApprovalTests executed in `darwin-sandbox`; no omitted records. | One passing expected Fact per system; Bazel TestRunner executed in `darwin-sandbox`. |
| Unchanged | 0 | Both bundles materialized; neither node had an execution-log record. The report does not infer a cache-hit type. | One passing expected Fact per system; Bazel TestRunner was forced and uncached. |
| Source edited | 1 | Serilog.ApprovalTests executed in `darwin-sandbox`; Serilog materialized without an execution-log record. | One passing expected Fact per system; the test assembly hash changed from its independent baseline. |
| Recovered | 2 | Serilog and Serilog.ApprovalTests each reported `disk cache hit`; both recovered bundle inventories matched their independent cold baseline byte-for-byte including executable modes. | One passing expected Fact after ordinary's same-path output-deleted rebuild and after Bazel's producer-free relocation; Bazel TestRunner was forced and uncached. |

All Bazel test phases had zero noncached MSBuild project actions. Every runner
report confirmed direct SDK VSTest invocation with no hidden Build or Restore.
Across the run, 12 ordinary and 12 Bazel invocations each executed exactly the
named approval Fact once and passed it.

## Method and retained evidence

The four cases are:

| Case | Ordinary MSBuild state | Bazel state |
| --- | --- | --- |
| Fresh | Restored source with no Build outputs; expect two real Csc tasks. | Empty output base and action disk cache; expect Serilog and Serilog.ApprovalTests actions to execute. |
| Unchanged | Independently build the unchanged baseline, then build again; expect zero Csc tasks. | Independently build the unchanged baseline, regenerate the same plan with its output base/cache retained, then expect zero MSBuild action executions. |
| Source edited | Independently build the unchanged baseline, add a private constant to `ApiApprovalTests.cs`, and require the test assembly hash to change; expect one Csc task. | Apply the identical edit after an independent warm-up; expect only Serilog.ApprovalTests to execute. |
| Recovered | Independently build the unchanged baseline, delete both projects' `bin` and configuration-specific `obj` outputs, and rebuild; this is an output-deleted rebuild, not a cache hit. | Independently build the unchanged baseline, delete its source, generated workspace and output base, prepare a relocated consumer, delete that preparation source, then require two disk-cache hits and byte/mode-identical recovered bundles. |

Every Bazel Build explicitly requests both configured node targets. This keeps
the recovery oracle from passing merely because the approval-test target was
materialized while its library bundle was absent.

Every measured sample runs the selected approval Fact once. Ordinary MSBuild
uses direct `dotnet vstest` after Build. Bazel uses
`--nocache_test_results`, requires one native TestRunner action and checks the
runner report says that neither Build nor Restore was invoked. A cached Bazel
test shortcut is intentionally excluded from the comparison.

`report.json` retains every command, working directory, exit code, raw log,
MSBuild binary log, Bazel execution log, Bazel JSON trace profile, TRX and test
runner report. It records executed Csc task counts, MSBuild project visits,
Bazel execution/cache-hit worksets, runner identities, exact cache/process
policy and host/toolchain identity. Failures are written incrementally with the
active stage and all evidence produced before the error.

Bazel execution logs omit some local action-cache reuse. The report therefore
keeps recorded executions and cache hits separate from
`materializedWithoutExecutionRecord`; it does not relabel an omitted record as a
hit. Both requested node targets and both materialized bundle inventories are
required in every Build. The recovery case additionally requires explicit disk
cache records for both nodes. Machine-readable comparability metadata marks the
ordinary recovered rebuild and Bazel relocated recovery as non-comparable, so a
downstream report cannot turn them into a speedup ratio.

Source extraction, package copying and Restore are timed separately as
acquisition/setup. Export and preparation are separate adapter phases. The
comparison total is ordinary Build plus actual VSTest versus adapter Export,
Preparation, Bazel Build and actual Bazel VSTest execution. Independent warm-up,
assertions, hashing and evidence copying are excluded from that total. Bazel
profile events are retained and named events are reported, but nested trace
durations can overlap and are not summed.

The report presents median and range for each case/system plus every raw sample.
It does not calculate a speedup ratio because ordinary MSBuild and the adapter
expose different phase boundaries. The recovered operations are explicitly
non-comparable, and normal desktop activity plus shared compiler/OS caches were
uncontrolled. Aggregate process-tree and persistent-server memory was
intentionally unmeasured because periodic process enumeration would distort the
small no-op timings. That memory gate remains part of R09/C16 scale
qualification.
