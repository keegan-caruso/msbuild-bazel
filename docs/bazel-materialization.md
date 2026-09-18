# Bazel analysis and runtime materialization

## Scope and decision

This follow-up profiles the remaining Bazel phase, checks for repeated SDK
analysis and removes redundant runtime export copies. It uses native macOS ARM64,
pinned SDK 10.0.400/Bazel 8.4.2 and same-host bazel-remote 2.6.2. The
[protocol](bazel-analysis-protocol.md) retains fresh consumer state, deleted
producers, raw MSBuild comparison and exact execution/artifact acceptance.
No independent-worker or broader platform qualification is implied.

## Baseline breakdown

Three unchanged repetitions, candidate `55d23bc`; seconds are medians:

| Span | Diamond | Serilog |
| --- | ---: | ---: |
| Bazel process launch | 0.480 | 0.479 |
| Module mapping | 0.115 | 0.108 |
| SDK package load | 0.049 | 0.059 |
| Analysis/execution start to first build action | 0.747 | 0.914 |
| Sandbox filesystem creation | 0.197 | 0.487 |
| Test runfiles tree | 0 | 0.296 |
| Native runner MSBuild subprocess | 0.235 | 0.408 |
| Native runner runtime replacement | 0.004 | 0.051 |
| Native runner final app copy | 0.001 | 0.021 |
| Test runtime verification/copy | — | 0.025 |
| VSTest subprocess | — | 0.429 |

These are nested spans, not additive wall-time buckets. In particular, the
interval before the first action includes more than target analysis; sandbox
creation is inside action processing, and runner phases are inside subprocess
execution. Bazel's merged analysis/execution trace does not expose a clean
standalone analysis wall time. We do not infer one by subtracting overlapping
spans. The native runner's phase diagnostics add a handful of stopwatch reads;
no per-file profiling is enabled.

## SDK investigation

All 12 samples loaded the SDK package once. Each action declares 4,906 distinct
SDK/import paths, with the same canonical payload-digest inventory across both
fixtures and build/test actions. No repeated enumeration or duplicate SDK input
within an action was found. The shared filegroup/depset is retained: replacing
thousands of source-file targets with an extra SDK staging action is not supported
by the measured 49–59 ms package-load cost. See [SDK analysis](bazel-sdk-analysis.md)
for rejected alternatives and contract boundaries.

## Runtime export change

Previously the runner copied the complete entry bundle, deleted its historical
runtime, copied the newly composed runtime into that location, sealed it and
copied it to `app`. The new path validates the complete entry bundle, copies only
its reference/intermediate artifacts and replay results, then moves the finished
private runtime directory into the output. It seals that output and retains the
public `app` copy. Cache bundles remain independent and unchanged.

The moved directory is under the same action output as its destination. MSBuild
has exited, the plugin has completed input verification and cache publication,
and no further consumer needs the private workspace. This avoids cross-device
moves and mutable sharing with cache bundles or test scratch. Final sealing still
hashes and normalizes all runtime files. There is no fallback that silently drops
validation if a move fails; the action fails.

For the unchanged fixtures, each avoided runtime copy covers 10 files/60,960 bytes
for diamond and 142 files/6,679,511 bytes for Serilog. Two runtime copies are
removed, along with deletion of the discarded historical runtime and final
scratch-runtime cleanup. Metadata is regenerated through the existing seal.

## Measurement and validation

Candidate `318918b`, three repetitions per case. Full workflow medians:

| Workload | Before | After | Change |
| --- | ---: | ---: | ---: |
| Diamond unchanged | 4.514 s | 4.516 s | +0.04% |
| Diamond body edit | 5.007 s | 5.068 s | +1.21% |
| Serilog unchanged | 8.346 s | 8.517 s | +2.04% |
| Serilog body edit | 8.830 s | 8.688 s | -1.62% |

**No reliable end-to-end speedup is established.** The small export savings are
visible in the instrumented phase but are smaller than variation elsewhere.
The unchanged Serilog test action spans ranged 0.867–0.885 s before and
0.893–1.430 s after, while VSTest itself remained about 0.43 s. The slowest
sample's Bazel test subprocess span rose from 0.622 to 1.182 s; the extra time
is outside the instrumented VSTest portion and is not attributed to SDK analysis
or output copying. Sequential three-sample runs cannot establish its cause.
The unchanged diamond median is effectively flat. Raw comparison medians after
are 0.587/0.995 s for diamond unchanged/body and 1.076/1.214 s for Serilog;
all four still miss the diagnostic raw-MSBuild performance target.

The local phase improvement is consistent across all six samples per fixture:

| Runtime replacement | Before, unchanged | After, unchanged | Reduction |
| --- | ---: | ---: | ---: |
| Diamond | 4.229 ms | 0.702 ms | 83.4% |
| Serilog | 51.404 ms | 0.795 ms | 98.5% |

Body-edit medians are 4.271 → 0.693 ms and 52.469 → 0.885 ms respectively.
Serilog cleanup also drops from about 60 to 54 ms. The bounded change is retained
because it removes two provably redundant copies without changing declarations,
validation, seals or the output contract. It is not presented as a solution to
the remaining seconds of workflow overhead.

Both 12-pair runs passed exact managed DLL/PDB comparison against raw MSBuild,
actual app/approval-test execution, and the expected zero/one compilation sets.
An additional cross-candidate comparison passed all 12 samples for **all** app,
cache and current-runtime file bytes and modes, complete artifact manifests,
seal digests and replay target metadata. Controller/toolchain keys necessarily
change with the runner binary and are excluded from cross-candidate metadata
identity comparison; artifact paths, digests and replay targets are included.
Local .NET checks passed all 5 style-policy, 32 preparation and 23 workflow tests,
including mutation/restored-metadata and special-file rejection controls.
Repository/toolchain/Starlark checks passed. No CI was dispatched.

All 14 cases in the existing production-controller probe passed with Python
blocked in child PATH: local unchanged/body reuse, malformed-proof fallback,
producer-deleted unchanged/body recovery, API-change test rejection, package
upgrade, corrupt preparation/project recovery, namespace invalidation, missing
and tampered NuGet rejection, lease-mutation rejection and failed-test rejection.
Failure cases published no remote objects and left no committed local project
cache, as asserted by the probe. This test uses the harness's fault-injecting
HTTP service; timing comparisons use the pinned real bazel-remote service.

The exact control command was:

```sh
python3 tests/dotnet_workflow/probe.py --checkout /private/tmp/mr/upstream --packages /private/tmp/mr/p --output /private/tmp/ba-controls
```

It ran inside the same pinned Nix development shell after timing finished.
[Control outcomes and transport evidence](bazel-materialization-controls.json)
record the expected rejections separately from successful builds.

## Reproduction and evidence

```sh
python3 tests/remote_workers/analysis_profile.py BEFORE/report.json AFTER/report.json --output profiles.json
python3 tests/remote_workers/overhead_summary.py BEFORE/report.json AFTER/report.json --output timing.json
python3 tests/remote_workers/materialization_parity.py BEFORE/report.json AFTER/report.json --output parity.json
```

Run `tests/remote_workers/measure.py` inside the pinned Nix environment with
`--repetitions 3 --cases unchanged body`, the pinned bazel-remote binary, acquired
Serilog source/NuGet cache, SHA-keyed install cache and repository-download cache;
pass `--protocol docs/bazel-analysis-protocol.md`. Exact flags are unchanged from
the [integrity streaming protocol](integrity-streaming-protocol.md).
Retained raw runs are `/private/tmp/ba-profile` and `/private/tmp/ba-export`.
The first summary attempt rejected test SDK equality because it incorrectly
filtered only build-action paths; test inputs carry a runfiles prefix. The fixed
summary compares the normalized repository-relative paths and payload digests,
including all 4,906 files for both actions. No measured build was rerun or
excluded for this reporting-only correction.

- [Workflow timing and raw comparisons](bazel-materialization-evidence.json)
- [Nested trace spans and runner phases](bazel-materialization-profiles.json)
- [Full export parity](bazel-materialization-parity.json)

