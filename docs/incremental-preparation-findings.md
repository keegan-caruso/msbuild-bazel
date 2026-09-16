# Removing repeated preparation work

This work is stacked on PR #67 (`3bdb903`). It keeps Python and the MSBuild/Bazel
execution boundary. The original MVP budget and qualification evidence are
unchanged. These are focused algorithm experiments, not a new release sign-off.

## Decision rule and protocol

The [plan](incremental-preparation-plan.md) declares five interleaved measured
baseline/candidate repetitions after warm-up. An improvement must save at least
10% and 0.1 seconds at the median on a declared workload. Output or correctness
failures reject the implementation regardless of timing. Native experiments run
serially on the same macOS ARM64 host with the pinned Nix SDK 10.0.400 and Bazel
8.4.2. Host load is uncontrolled. Tool build, restored-input setup and cold cache
seeding are reported separately. Native preparation timings include lease exit
and its final checks; they exclude compilation and untimed correctness oracles.

## 1. Deduplicate materialization

Normalize each configured node's restore files once, copy each source/import once,
and verify/extract each unique shared package once per preparation. Preserve each
consumer's package identity spelling and manifest. Check every unique package's
content again before publication, including archives and optional absent files.
A process-local staging session cannot be used after it closes or in another
workspace/output pair. Conflicting restore hashes still reject.

The initial matched experiment (`ma2`) reduces 1,000-project chain materialization
from 118.475s to 12.167s; the converging fan falls from 121.665s to 13.299s. The
100-project workloads fall from 1.110s/1.114s to 0.120s/0.129s. Every comparison
checks the entire output inventory: paths, bytes and modes. These fixtures include
one shared package and restored metadata; they do not execute native builds.

Review exposed two additional issues. A stat-only end check could miss mapped
writes, so the final implementation rehashes each unique package. Package ID case
must remain specific to each consumer even when payloads are shared. Dedicated
negative/compatibility tests cover both. The intermediate `ma2` implementation is
superseded; its timing is retained as an isolated experiment, not the final safety
claim.

Framework selection also rescanned every earlier project inside each dependency
closure. Tracking projects with multiple configured frameworks removes that
repeated scan. Unusual project names containing the delimiter retain the old
lookup semantics. The follow-up experiment includes the stronger package guard.
At 100 projects its saving is below the declared threshold; it is useful at 1,000.
The final matched follow-up (`ma4`, including both review fixes) records:

| Materialization | Deduplication baseline | Final lookup/guard | Reduction |
| --- | ---: | ---: | ---: |
| 1,000-project chain | 12.037s | 6.103s | 49.3% |
| 1,000-project converging fan | 13.124s | 7.107s | 45.8% |

Both are meaningful. These are sequential matched experiments; the original
118s/122s and final 6s/7s are not presented as one directly paired run.
An untimed 100-project chain verifies the work reduction independently:

| Instrumented work | Original | Final |
| --- | ---: | ---: |
| Text reads | 10,200 | 300 |
| Source/import copies | 5,250 | 201 |
| Package archive opens | 100 | 1 |
| Package bytes read through instrumented APIs | 12,302,400 | 246,048 |

The final package count includes the full content recheck. These counters do not
claim to measure all operating-system I/O. Complete output inventories match.
The materializer still emits transitive per-target declarations, so quadratic
output volume is not eliminated.

## 2. Reuse verified protected toolchains

`ProtectedStore` verifies 19 actual system-owned Nix roots on first use and keeps
only an in-process cache. It requires root ownership, no non-owner write access,
no extended ACLs, protected ancestry and protected symlink targets. A root change
or a new process prevents using the old record. Mutable/user-owned inputs always
retain full content hashing. Both native workloads pass untimed strict full-content
verification and exact per-mode payload equivalence to their seeded generation.

| Unchanged preparation | Strict baseline | Session reuse | Reduction |
| --- | ---: | ---: | ---: |
| Small fixture | 1.490s | 0.319s | 78.6% |
| Serilog library | 1.752s | 0.544s | 69.0% |

Both pass the meaningful-change threshold. One unchanged request avoids 38 tree
hashes, approximately 3.13 GB of repeated content hashing. There are no additional
full reads of protected roots after the initial 19 within either benchmark session.
Cold seeding is excluded from these medians and recorded separately (small:
3.725s strict / 1.892s session; Serilog: 3.840s / 2.178s, one sample each).

This is an **explicit trust choice**, not an equivalent corruption detector:
privileged Nix administration and storage integrity are trusted during the
session. Restart after privileged edits or store repair. A Nix pathname or disk
receipt alone never authorizes reuse. Default operation remains strict. The CLI
flag `--trust-system-nix-store` starts a new cache each process; persistent callers
can pass the same `ProtectedStore()` object across requests.

A separate five-pair probe reconstructs the verification cache before **every**
request, matching a one-shot CLI's cache lifetime. It includes that request's
initial verification but excludes interpreter startup on both sides:

| Fresh verification session per request | Strict baseline | Opt-in cache | Reduction |
| --- | ---: | ---: | ---: |
| Small fixture | 1.511s | 1.307s | 13.5% |
| Serilog library | 1.782s | 1.556s | 12.7% |

Both still meet the threshold, but the 0.319s/0.544s persistent-session medians
must not be advertised as one-shot CLI latency. Reproduce with
`tests/preparation_reuse/probe_fresh_store_session.py` using the same
`--source`, `--entries` and `--output` arguments.

## 3. Separate source content from graph discovery

With `--incremental-sources`, an existing C# file's content can change while the
qualified graph structure stays fixed. Update every matching manifest hash and
publish a new materialized generation with explicit certificate lineage. The
original observation digest identifies the original evaluation; a derived
certificate does not claim that evaluation ran again. Namespace membership,
modes, imports, restore, request, tools and all other roots must be unchanged.

| Preparation after a source edit | Reevaluate graph | Refresh hashes | Reduction |
| --- | ---: | ---: | ---: |
| Small fixture | 1.200s | 0.478s | 60.2% |
| Serilog library | 1.681s | 0.815s | 51.5% |

Both sides use the same protected-store policy, isolating the graph algorithm's
contribution. All six derived graphs per workload (warm-up plus five measurements)
match a fresh complete GraphExport at the identical sealed path, including every
metadata field. Normal compilation and materialization still run when required.

The first Serilog attempt correctly fell back because the initial guard rejected
all resources. Its unchanged XML resource has an explicit `LogicalName`, so the
final rule admits only `.xml` resources whose sole metadata is a literal name
matching the filename. RESX conventions, additional inputs and other resource
metadata still require discovery. The failed first attempt and final repeated
measurements are retained separately. The broader resource case is not qualified.

## 4. Mutable-checkout event tracking: rejected

A macOS `kqueue` reproduction opens a writable mapping, drains mapping-creation
events, then changes bytes without flushing. Reading the file observes changed
bytes while size/mtime/ctime remain unchanged and the event queue is empty. Thus
"no event plus same stat" cannot certify unchanged contents. The executable
`probe_file_event_gap.py` retains this evidence. The same regression is tested
against package staging and rejected by its final content check.

No watcher-only fast path is shipped. Full validation remains for ordinary mutable
checkouts and user-owned package trees. A separately supplied immutable input
generation could enable stronger change tracking, but that is a different input
contract and is outside this change. This candidate fails the correctness gate
before a speed comparison would be meaningful.

## Reproduction

Prebuild GraphExport, EvaluationProbe, ReplayPlugin and ActionRunner with the
pinned `nix develop` environment and `scripts/dotnet.sh`. Supply the restored small
fixture or pinned Serilog checkout and their existing entries JSON.

```sh
python3 tools/probe_materialization_scaling.py --output /tmp/scale \
  --baseline 3ff54ea --sizes 1000 --shapes chain fan --repetitions 5
python3 tools/probe_materialization_work.py --output /tmp/work-counts
python3 tools/probe_incremental_preparation.py --source SOURCE --entries ENTRIES \
  --output /tmp/store-probe --stage store
python3 tools/probe_incremental_preparation.py --source SOURCE --entries ENTRIES \
  --output /tmp/source-probe --stage source --edit App/Program.cs
python3 tools/probe_file_event_gap.py --output /tmp/file-event-gap.json
python3 tests/preparation_reuse/probe_mvp_invalidation.py --output /tmp/invalidation --incremental
python3 tests/preparation_reuse/probe_serilog_reuse.py --source UPSTREAM \
  --packages PACKAGES --output /tmp/serilog-incremental --incremental
```

Use short native output paths: the .NET debugger pipe limit also includes Bazel's
sandbox suffix. The package parity test now uses short generated paths after its
first native run reached the existing production path guard. No guard is disabled.

## Broader package limitation found during validation

The original package suite ran 29 tests: 26 passed, one test failed across four
PrivateAssets subcases, and two pinned-input tests were initially skipped. After
shortening its native paths, the remaining failure is MSB4252 for an implicitly
configured framework (`configuration=Release; IsGraphBuild=true`). The test
invocation does not supply the explicit `TargetFramework=net10.0` used by the MVP
slice. This broader replay case remains unresolved.

This is independently reproduced with the original `3bdb903` materializer. All
29 generated files in each of the four package modes are byte/mode-identical to
the candidate, and a native build of the original omitted-PrivateAssets case
reproduces the same global-property mismatch. The .NET runner/replay/exporter
sources are unchanged. `package-baseline-comparison.json` and the baseline native
log retain this control. The failure is not reported as a passing test or silently
excluded from a green suite. Both initially skipped tests pass when supplied with
the acquired pinned Serilog source/packages; the pilot-policy rerun passes all
three tests in that file.


## Final focused validation and applicability

- 67 preparation unit tests, 21 materializer rejection tests, six framework
  selection tests and seven dependency-closure tests pass (101 total).
- The 17 default reuse controls pass, including corruption, interrupted
  publication, concurrency, tool changes and producer-free native execution.
- Ten incremental invalidation/native action cases pass. Editing App's existing
  source executes App only; restoring its contents reuses the prior action;
  adding/removing files and optional imports still takes full discovery.
- Three Serilog cases pass: cold capture, source-content refresh, and native
  producer-free recovery. A new public property added to `Serilog.Log` is called
  from a separately built consumer, which prints `Serilog` and `incremental`.
- Twelve fresh-GraphExport equivalence checks pass across the two source-edit
  workloads. Sixty measured native preparation requests cover the persistent and
  fresh-session comparisons. All tests here run locally; no CI is dispatched.
- The broader implicit-framework package test remains a known baseline failure,
  as detailed above. The aggregate package suite is not claimed green.

Raw reports bind Python code hashes. `ma2` matches `3ff54ea`; the intermediate
`ma3` matches `7211998`; the final `ma4` materializer and all final native benchmark
Python hashes match the final source tree. Subsequent changes are test/document
updates. The evidence bundle includes applicability checks, source diff, reports,
certificates, logs, commands, failure controls and a SHA-256 inventory. It excludes
SDK/package binaries and build caches. Compilation speed, full Build/Test latency,
Linux behavior and thousand-project native execution are not inferred from these
preparation experiments.
