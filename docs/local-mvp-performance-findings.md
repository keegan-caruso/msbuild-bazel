# MVP preparation performance qualification (#7)

## Result and scope

The unchanged [predeclared budget](local-mvp-preparation-budget.json) passes
on native macOS ARM64 with the locked default Nix toolchain. This qualifies
preparation latency for the two frozen workloads. The adapter still costs more
than ordinary MSBuild for this small Build/Test workload; no scale or other
platform benefit is claimed.

Measured candidate: `efb4baf3c367390ecde8679f4894192a86e54f95`.
The [release evidence index](local-mvp-release-evidence.json) contains report
hashes, every measured sample, work sets and the recomputed qualification result.
The [clean-candidate findings](local-mvp-release-qualification.md) describe
acquisition, correctness, failed attempts and evidence applicability.

## Change and preserved boundaries

Profiling the initial candidate found that repeated `Path.is_relative_to` calls
constructed more than a million temporary parent-path objects while checking
entries against the declared runtime closure. Canonical allowed-root names and
separator-terminated prefixes now perform the same containment check. Every
entry is still resolved strictly; sibling prefixes, undeclared symlinks and
cycles remain rejected.

Independent declared roots are hashed with at most four worker threads. Every
byte and namespace entry still participates. Per-file before/after descriptor
checks, directory membership checks, final traversal checks and the enclosing
consumption lease remain intact. Hashing can overlap because its native work
releases the Python GIL. Result order and persisted snapshot schema are unchanged;
controller identity changes still invalidate old preparation requests.

Unit controls cover sibling-prefix escapes, filesystem-root containment, exact
serial/parallel identity equality and existing mutation/symlink cases. Running
the original and optimized capture algorithms over identical inputs produced
exactly equal snapshots and keys: 22 roots, 7,126 entries and 1,594,326,951 hashed
bytes. This is a direct algorithm comparison, separate from the old-cache
upgrade control, whose generated tool inputs also changed during rebuild.

## Frozen preparation gate

Five measured fresh/reuse pairs per workload, with one warm-up per mode and an
initial cache seed excluded from the measured pairs. Pair order alternates.
Full preparation context wall time includes lease teardown/final verification,
not just time until a consumer becomes available. Source and tool fingerprints
remain unchanged after warm-up. Runs were serial, with no concurrent agent
builds/probes; interactive Mac load remained uncontrolled.

| Workload | Fresh median (range), s | Reuse median (range), s | Reuse/fresh | Budget |
| --- | ---: | ---: | ---: | --- |
| Small App → Shared | 2.271 (2.246–2.331) | 1.544 (1.484–1.651) | 0.680 | Pass |
| Pinned Serilog library | 2.184 (2.182–2.450) | 1.866 (1.791–1.911) | 0.854 | Pass |

Both limits are unchanged: median reuse/fresh ≤ 1.0 and median full reuse ≤ 5s.
The budget SHA-256 remains
`c89f378450e1d7196ce30931e7c45990d7a5511c63bf431d39b6299cec0f84c1`.
Median reuse is approximately 32% faster for the small fixture and 15% faster
for Serilog. Each reuse sample skips discovery, materialization and tool builds;
each fresh control executes all three. These savings replace the initial #5
calibration's 62%/79% regressions without relaxing validation.

- Small: cold seed 3.555s; fresh/reuse warm-up 2.272s/1.517s.
- Serilog: cold seed 3.924s; fresh/reuse warm-up 2.432s/1.771s.

The qualifier verifies the original budget hash, complete unique samples, exact
requests/work flags, finite timings, stable source/tool identities and a
same-candidate 40-sample ordinary-MSBuild/adapter Build/Test comparison. It
recomputes preparation medians instead of trusting summary fields and exits
nonzero on missing evidence or exceeded limits. The raw calibration reports
remain descriptive (`performanceQualified: false`); the separate qualification
report evaluates them against the frozen budget.

## End-to-end Build/Test comparison

Five repetitions of each case/system produce 40 passing samples. Ordinary
MSBuild is unchanged. Every sample executes exactly one
`ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally` test. Explicit test
preparation remains fresh; the preparation-reuse gain above must not be applied
to these Build/Test numbers.

Median seconds below exclude acquisition, restore, baseline warm-up, assertions,
evidence copying and Bazel shutdown. Raw reports also retain complete workflow
times and every setup phase. Phase medians need not sum to the median total.

| State | System | Export | Prepare | Build | Test | Comparison total |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Fresh | MSBuild | — | — | 0.862 | 0.683 | 1.538 |
| Fresh | Adapter | 0.480 | 2.926 | 7.484 | 1.620 | 12.532 |
| Unchanged | MSBuild | — | — | 0.635 | 0.666 | 1.297 |
| Unchanged | Adapter | 0.473 | 2.559 | 0.539 | 1.561 | 5.121 |
| Test source edited | MSBuild | — | — | 0.684 | 0.682 | 1.365 |
| Test source edited | Adapter | 0.473 | 2.560 | 2.069 | 1.594 | 6.721 |
| Recovery* | MSBuild | — | — | 0.826 | 0.683 | 1.516 |
| Recovery* | Adapter | 0.481 | 2.919 | 4.245 | 1.627 | 9.319 |

*Recovery is not a speed-ratio comparison: ordinary MSBuild rebuilds two projects
after output deletion at the same path. The adapter deletes the producer,
relocates the consumer, recovers both build bundles from local disk cache and
forces the actual test. Fresh executes both projects; unchanged executes none;
the observable test-source edit executes only the approval-test project. No
hidden dependency recompilation is accepted.

Bazel trace profiles are retained separately. This pinned Bazel build reports
an integrated `runAnalysisAndExecutionPhase`; it does not give an isolated
analysis wall-time measurement. Its median durations are below, nested within
the Build/Test commands above. They overlap other events and must not be added
to command wall times or presented as isolated analysis cost.

| State | Build analysis + execution, s | Test analysis + execution, s |
| --- | ---: | ---: |
| fresh | 3.950 | 1.355 |
| unchanged | 0.274 | 1.294 |
| sourceEdited | 1.797 | 1.328 |
| recovered | 0.867 | 1.348 |

## Reproduction and limitations

Use the clean setup and restored fixture recipes in the
[release qualification](local-mvp-release-qualification.md). Give each probe a
new short output directory:

```sh
python3 tools/probe_preparation_performance.py --source <small-fixture> \
  --entries <small-entries.json> --output /private/tmp/qps --repetitions 5
python3 tools/probe_preparation_performance.py --source <restored-serilog-library> \
  --entries <serilog-entries.json> --output /private/tmp/qpl --repetitions 5
python3 tools/probe_serilog_performance.py --source <pinned-serilog-checkout> \
  --packages <package-cache> --output /private/tmp/qbt --repetitions 5
python3 tools/qualify_preparation_performance.py \
  --budget docs/local-mvp-preparation-budget.json \
  --small /private/tmp/qps/report.json --serilog /private/tmp/qpl/report.json \
  --end-to-end /private/tmp/qbt/report.json --output /private/tmp/qgate.json
```

The first containment-only experiment left Serilog above its ratio budget
(1.029); that failed intermediate result is retained. Later exploratory results
are labeled separately from this final run. No budget was changed. Nix store,
filesystem caches and possible SDK compiler-server reuse are not cold per sample.
Bazel server/cache policies and host snapshots are recorded. Aggregate process
tree memory and broad scale remain unmeasured. Only the supported local macOS
combination is qualified; no CI workflow was dispatched.
