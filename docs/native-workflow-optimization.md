# Native workflow overhead reduction

These changes retain the opt-in native backend and its local macOS ARM64 scope.
They do not qualify remote workers or claim raw-MSBuild parity.

## Step 1: retain prepared and generated inputs

Native staging reads a validated preparation generation while holding its lease,
then checks the payload again before completing consumption. The legacy mutable
consumer-copy API retains its existing behavior. Generated files are compared by
content, written atomically only when different, and removed when no longer
selected. No persisted timestamp receipt authorizes reuse. In particular, changed
seeds and test data cannot survive from a previous graph. Unchanged files retain
inodes/mtimes, reducing both copying and Bazel input processing.

A same-host before/after experiment used the pinned Serilog approval graph with a
retained Python controller, explicit protected-Nix-store policy, guarded source
refresh, actual VSTest on every run, and three unchanged and three private-library
edits. Cold and seeded runs warmed each fresh state first; acquisition and Restore
are outside the measured workflow. This profile is not the default one-shot CLI.

| Median seconds | Baseline | Step 1 |
| --- | ---: | ---: |
| unchanged total | 2.629 | 2.167 |
| unchanged preparation | 1.012 | 0.787 |
| unchanged staging | 0.296 | 0.245 |
| unchanged final validation | 0.165 | 0.246 |
| source edit total | 5.750 | 5.392 |

Unchanged total improved 17.6%; source edits improved 6.2%. Final validation costs
more because borrowed payloads are rehashed at exit. All expected compiler/test
counts passed. These sequential three-sample comparisons are diagnostic, not
statistical guarantees or isolated attribution of every subphase.

Validation: 75 preparation unit tests pass, including linked-destination refusal,
corrupt generated-file replacement, stale-input pruning, stable unchanged inodes,
and mutation of a borrowed payload. All 11 real workflow controls pass: actual
Build/Test, bad golden data, body edit, corrupt plan, new source, unchanged reuse,
lease mutation with no publication, package tampering and missing test data.
Generated Starlark passes pinned Buildifier. No GitHub CI was run.

Reproduce the phase-focused protocol inside the pinned Nix shell:

```sh
python3 tests/preparation_reuse/measure_native_overhead.py \
  --source /path/to/serilog --packages /path/to/packages --output /private/tmp/overhead
```

## Step 2: reuse verified packages on source edits

A qualified C# content-only derivation now copies the verified native payload and
updates its changed sources and project identity records directly. It avoids
rebuilding the intermediate evaluated plan and re-extracting/revalidating package
archives whose entire discovery domain is unchanged. The previous payload is
verified before reuse and after copying; the derivation is independently checked
against the previous graph and discovery certificate. Namespace, mode, restore,
package, import, additional-input or other unsupported changes cannot enter this
path. This optimization retains the explicit `incremental_sources` opt-in.

The same three-sample protocol gave unchanged **2.163 s** (essentially unchanged
from 2.167 s) and source edits **4.992 s**, 7.4% faster than step 1. Source-edit
preparation fell from **1.841 s to 1.436 s**. All three edits reported package
payload reuse and no discovery execution. Native refresh unit checks compare the
entire payload with full materialization and reject corrupt prior inputs, late
source changes, changed graph structure and package namespace changes.

Validation: 80 preparation unit tests pass. All 11 real workflow controls pass
with incremental sources enabled, including package tampering, corrupt cached
plans, new sources, final lease mutation and unchanged cache publication on
failure. No GitHub CI was run.

## Step 3: share invocation identities with fresh final checks

SDK and controller roots now share content snapshots within one workflow run.
Sharing a broad SDK snapshot with a narrower discovery domain checks every
resolved symlink traversal boundary against the narrower allowed roots. Mutable
source and discovery workspaces still receive full reads. Before committing the
project-cache pointer, all memoized roots are rehashed, including membership and
modes, with independent roots checked concurrently. No on-disk stat receipt or
cross-run mutable-root cache is introduced. Optional protected-Nix-store trust
continues to use its existing explicit administrator/storage policy.

The initial implementation serialized final verification and regressed unchanged
CLI time; it was corrected before committing. Matched default-CLI measurements
(including Python startup, three unchanged and three library edits) are:

| Median seconds | Step 2 | Step 3 |
| --- | ---: | ---: |
| unchanged total | 3.633 | 3.427 |
| source edit total | 11.026 | 8.725 |
| source edit preparation | 6.515 | 4.159 |

This is a 5.7% unchanged improvement and 20.9% source-edit improvement. These CLI
source edits use conservative full rediscovery; the faster optional retained
profile remains separate. Use `--profile cli` with the phase-focused measurement
command to select the one-shot CLI protocol.

A real controller-namespace mutation after staging leaves a passing test result
but rejects final success and leaves the project-cache pointer unchanged. Unit
controls include mmap content changes with restored mtime, new namespace members,
closed invocation reuse and broader-to-narrower symlink-domain rejection.

## Complete Serilog comparison after all three changes

All 36 paired samples and three fresh-preparation controls pass: 75 actual
Build/Test executions with matching runtime bytes, expected compiler counts and
one passing approval test each. The original protocol, exclusions and target
remain those in [the baseline report](native-workflow-performance.md). Neither
profile meets the predeclared steady-state target. Medians are three samples,
seconds; paired raw columns use their respective runs.

| Case | Native CLI | Raw paired with CLI | Optional retained | Raw paired with retained |
| --- | ---: | ---: | ---: | ---: |
| cold | 11.332 | 1.316 | 11.576 | 1.321 |
| seeded | 4.751 | 1.057 | 3.491 | 1.042 |
| unchanged | 3.530 | 1.051 | 2.166 | 1.070 |
| body | 8.076 | 1.261 | 4.451 | 1.201 |
| test-edit | 7.840 | 1.051 | 3.991 | 1.073 |
| recovery | 11.172 | 1.314 | 10.743 | 1.304 |

Relative to the earlier complete-workflow baseline, unchanged CLI time improves
15.7% (4.187 to 3.530 s), and the optional retained profile improves 20.4%
(2.721 to 2.166 s). Library edits improve 25.2% on the CLI and 13.2% on the
optional retained profile. The final unchanged paths remain roughly 3.36x and
2.02x their paired raw times. These are combined improvements, not isolated
attribution to individual optimizations.

## Larger graphs: local-state context

All 30 paired Build-only samples pass on owned 10- and 100-project fan graphs,
with three repetitions, matching runtime bytes and executable behavior. These
use a retained controller and explicit protected-Nix-store policy. The fixture
uses `TargetFrameworks=net10.0` to retain explicit configured nodes during SDK
reference negotiation; implicit framework-global nodes remain outside this native
qualification. Restore/acquisition and post-run oracles are excluded on both
paths. Recovery clears preparation, Bazel and compiler outputs but retains local
project bundles and the same source path; it is not remote-cache evidence.

| Projects | Case | Native seconds | Raw seconds |
| ---: | --- | ---: | ---: |
| 10 | cold | 11.213 | 3.633 |
| 10 | seeded | 1.302 | 0.736 |
| 10 | unchanged | 0.600 | 0.721 |
| 10 | leaf | 2.361 | 1.144 |
| 10 | recovery | 7.907 | 3.641 |
| 100 | cold | 45.176 | 26.120 |
| 100 | seeded | 4.659 | 3.193 |
| 100 | unchanged | 1.992 | 3.184 |
| 100 | leaf | 5.708 | 3.509 |
| 100 | recovery | 21.174 | 26.097 |

Unchanged reuse beats raw at both sizes. Leaf edits still compile two native
projects versus one raw project because evaluated dependency keys include full
artifact identities. Cold overhead remains substantial. These local numbers
provide context; changed fresh consumers with a remote cache are the next focus.

Reproduce:

```sh
python3 tests/preparation_reuse/measure_native_scale.py \
  --output /private/tmp/native-scale --counts 10 100 --repetitions 3
```

Final checks: 84 preparation tests, 23 native-cache tests, all 11 final real
workflow controls and the additional post-staging controller-mutation control
pass. Pinned environment/Starlark checks pass. No GitHub CI was run.

The [changed remote-consumer follow-up](native-changed-remote.md) focuses on
cross-revision cache reuse and counts actual compilation hits separately from
successful bundle downloads.
