# MVP preparation calibration (issue #5 / RUL-7)

## Result

Five paired measurements per workload show that unchanged reuse skips exporter,
materializer and tool-build work, but **increases full preparation latency** on
this host. Full-tree input verification and copying are included in the metric.
This is calibration, not issue #7 performance qualification.

| Workload | Fresh median | Reuse median | Reuse/fresh | Fresh range | Reuse range |
| --- | ---: | ---: | ---: | ---: | ---: |
| App -> Shared fixture | 2.272s | 3.691s | 1.625 | 2.257–2.278s | 3.667–3.720s |
| Pinned Serilog library | 2.203s | 3.945s | 1.791 | 2.198–2.210s | 3.923–3.982s |

Every measured reuse sample reports `reused=true`, `discoveryExecuted=false`,
`materializationExecuted=false`, and `toolBuildsExecuted=false`. There are five
successful fresh and five successful reuse samples for each workload. Source
identity is unchanged across each measured sequence after the reported warm-up.

## Predeclared budget

[The numeric budget](local-mvp-preparation-budget.json) requires, independently
for both workloads, median reuse/fresh preparation ratio **at most 1.0** and
median full reuse preparation **at most 5.0 seconds**, with five measured
repetitions per mode, correct work sets and no failed or missing samples.

The ratio gate requires the current regression to be fixed; calibration is not
being relabeled as a performance pass. The absolute guardrail bounds interactive
cost while the ratio prevents an apparently acceptable absolute duration from
hiding a regression against ordinary fresh preparation. Freeze the budget hash
before #7, and investigate failures without changing thresholds retrospectively.

Declared budget SHA-256:
`c89f378450e1d7196ce30931e7c45990d7a5511c63bf431d39b6299cec0f84c1`.

## Environment and protocol

Native macOS ARM64 27.0 (26A428), Nix 2.35.2, locked SDK 10.0.400,
MSBuild 18.9.6.38015, runtime 10.0.11, Python 3.13.9 and Nixpkgs Bazel
8.4.2. The source base is `498114a4b67ba56682b93fb6a6f98d82d1b2acaf`,
with the calibration harness, package-free fixture correction and macOS path guard in this change.
The exact SDK/closure and limitations are in the [contract](local-mvp-contract.md).

Runs were serial on an interactive Mac. Background desktop load was not
controlled; no other agent build or native probe ran during measurement. These
are local observations, not a hardware-independent latency promise. Source and
cache lived on unsynchronized local storage after File Provider interference
was observed under Documents.

`tools/probe_preparation_performance.py` retains warm-up, cache seed, individual
samples, controller/tool identities, source hashes, work flags and timings. It
measures through context teardown, including the final lease/input checks.
Warm-up is explicit: fresh MSBuild discovery creates assets caches under `obj`.
The first small-fixture warm-up also refreshes generated tool-tree content;
its pre-warm-up tool inventory differs from the measured inventory. For both
workloads, the seed generation's exact tool identity equals the final identity;
every measured reuse request validates that identity under its lease. The seed
manifests are retained alongside the timing reports.
The initial small run incorrectly compared its final source to the pre-warm-up
identity and failed the harness assertion. It was retained as an unsuccessful
attempt, and the corrected complete run was measured independently.

```sh
python3 tools/probe_preparation_performance.py \
  --source <restored-workload> --entries <entries.json> \
  --output <new-evidence-directory> --repetitions 5 \
  --host-note "Serial interactive-Mac calibration; desktop load uncontrolled; no concurrent agent builds/probes."
```

Retained calibration reports:

- `/private/tmp/mcs3/report.json`
- `/private/tmp/mcl2/report.json`
- Rejected initial harness run: `/private/tmp/msbuild-mvp-small-calibration-1/report.json`

## Ordinary MSBuild and adapter Build/Test phases

All **40 samples** passed correctness and expected work sets: five repetitions
of each of four cache/input cases in each system. Each sample executes exactly
one passing approval Fact. The measured adapter uses native `darwin-sandbox`
actions, a per-case local disk cache, no remote cache/execution and a retained
Bazel server within each case. Setup and warm-up are outside the comparison;
full workflow includes setup, warm-up and server shutdown. Recovered consumers
have independent output bases and producer state removed.

Median seconds (individual values and min/max retained in the report):

| Case | Ordinary build | Ordinary test | Adapter export | Adapter preparation | Adapter build | Adapter test | Ordinary comparison | Adapter comparison |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fresh | 0.844 | 0.685 | 0.484 | 2.883 | 7.355 | 1.637 | 1.533 | 12.325 |
| unchanged | 0.666 | 0.653 | 0.492 | 2.557 | 0.506 | 1.587 | 1.319 | 5.117 |
| sourceEdited | 0.680 | 0.672 | 0.485 | 2.558 | 2.077 | 1.565 | 1.350 | 6.682 |
| recovered | 0.851 | 0.695 | 0.480 | 2.903 | 4.101 | 1.660 | 1.545 | 9.175 |

Medians of separate phases need not sum to the median of their totals.
Bazel's retained trace reports overlapping analysis/execution events, not an
exclusive analysis stopwatch. The build `runAnalysisAndExecutionPhase` medians
are 3.820s fresh, 0.270s unchanged, 1.799s source-edited and 0.879s recovered;
these are contained in build time and must not be added to it. Raw profiles and
named-event summaries are retained for every build and test invocation.

Full workflow medians (ordinary / adapter) are 2.598 / 13.284s fresh,
3.054 / 17.199s unchanged, 3.134 / 18.790s source-edited and
3.243 / 22.712s recovered. Restoration and acquisition remain explicit phases.
The recovered comparison is **not a like-for-like cross-system speed test**:
ordinary MSBuild compiles both projects while Bazel retrieves both build bundles
from disk cache and then executes the approval test. No project action executes
on unchanged Bazel builds; source-edited runs execute only the approval-test
project; fresh runs execute both projects. Every test is forced to execute.

Retained report: `/private/tmp/mb2/report.json`. The failed long-path attempt at
`/private/tmp/msbuild-mvp-e2e-calibration-1/report.json` remains unsuccessful;
see the [diagnosis and path guard](local-mvp-path-findings.md). All reported
successful phase timings above come from the independent complete rerun.

Preparation seed/acquisition costs are separate from steady-state comparisons.
Explicit test requests use fresh preparation; library reuse timing does not
establish test-preparation reuse or end-to-end speedup. These observations
complete calibration and expose work for #7; they do not pass its ratio gate.
