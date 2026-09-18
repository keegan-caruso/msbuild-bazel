# Identity and final verification profile

Measured 2026-09-18 on macOS ARM64 from main `8d5599c`, with opt-in
instrumentation in this worktree. No validation optimization is implemented.

## Protocol and correctness

Run diamond and pinned Serilog against a dedicated real loopback cache. For each,
produce/publish, delete the producer, recover a fresh consumer, then run three
paired profiling-off/on unchanged invocations using the same worker/server.
Alternate off/on order. Finally measure a profiled one-project edit and compare
its exact managed DLL/PDB set to an independent raw build. All 16 invocations
passed, with actual application/approval execution. Unchanged output hashes match
the accepted producer. Off/on worker identities and final verification request/
scan counts are identical; unchanged invocations compile zero projects, edits one.

The initial attempt was rejected before profiling because the request field had
not been registered. The corrected run is `/private/tmp/integrity-workflow-final`;
only that accepted run is included. Source and instrumentation hashes are in the
[evidence](integrity-workflow-profile-evidence.json).

`integrity-profile: true` adds per-root snapshot timers and file-open/read/hash/
manifest counters, runtime-manifest digest timers, closure-query timing and worker
capture timing. Profiling defaults off. Final verification uses the same scan
function and retains per-pass deduplication and exact comparisons. Source/package
files within the workspace are grouped together; this is not a per-file profile.

## Phase medians, three paired samples (seconds)

| Workload | Entry off | Entry on | Final off | Final on |
| --- | ---: | ---: | ---: | ---: |
| Diamond | 0.818 | 0.845 | 0.667 | 0.690 |
| Serilog | 0.840 | 0.853 | 0.816 | 0.816 |

The sums of phase medians are 1.485/1.535 seconds off/on for diamond and
1.657/1.669 seconds for Serilog. The observed difference is about 50/13 ms;
three paired samples cannot separate instrumentation overhead from all host noise.
Use unprofiled totals for baseline costs and profiled samples for attribution.

## Serilog attribution (sum of component medians, seconds)

| Component | Entry | Final | Combined |
| --- | ---: | ---: | ---: |
| Runtime closure scans | 0.627 | 0.593 | 1.220 |
| Controller/tool scans | 0.023 | 0.038 | 0.061 |
| Worker identity capture | 0.048 | 0.048 | 0.095 |
| Runtime manifest digests | 0.078 | — | 0.078 |
| Nix closure query | 0.069 | — | 0.069 |
| Workspace and package scan | — | 0.067 | 0.067 |
| Prepared plan scan | — | 0.066 | 0.066 |

Residual timing covers comparisons, policy hashes, other identity serialization,
and instrumentation/report bookkeeping. Component medians need not sum exactly
to the phase median. The runtime scans are approximately 73% of the profiled
identity-plus-final cost. Diamond runtime scans total 1.238 seconds.

### Largest runtime roots

| Root | Entry | Final | Actual bytes hashed per scan |
| --- | ---: | ---: | ---: |
| .NET SDK | 0.419 s | 0.388 s | 669,546,433 |
| LLVM | 0.144 s | 0.144 s | 397,363,144 |
| libiconv | 0.037 s | 0.034 s | 45,679,108 |
| ICU | 0.015 s | 0.015 s | 39,603,991 |

The complete runtime closure has 19 roots and physically hashes 1,177,165,764
bytes per scan after alias deduplication: approximately 2.35 GB across the two
passes of every invocation. Including controller/workspace/plan scans increases
that to 2.45 GB for diamond and 2.62 GB for Serilog. These are application-level
bytes hashed, not physical disk traffic: repeated runs benefit from OS caching.
Each pass avoids 385,462,969 repeated alias bytes. Final verification has
51 requests but only 31 scans, so overlapping discovery/controller requests
are already coalesced within that pass.

### Inside the scans

Across entry and final Serilog scans, medians sum to approximately:

- SHA-256 work: **0.778 s**.
- Opening files: **0.213 s**.
- Reading file streams: **0.140 s**.
- Constructing file manifest entries: **0.005 s**.

These times are nested within scan totals, not additional phases. Remaining scan
time includes enumeration, path/link resolution, metadata checks and bookkeeping.
Runtime manifest serialization/digesting is a separate 0.078-second entry cost.
The profile records elapsed time, not CPU samples; hash calls dominate measured
scan leaf time, but scheduler pauses cannot be ruled out.

## Implication

The largest opportunity is avoiding repeated full runtime scans under a proven
immutability boundary, especially the SDK and LLVM. The measured runtime-scan
component is about 1.22 seconds; that is an opportunity size, not a guaranteed
saving. Size/mtime receipts alone cannot safely replace current checks. Any next
implementation must establish which toolchain roots cannot change while reused,
invalidate on identity change, and preserve validation of mutable sources,
packages, plans and controller inputs. Do not remove LLVM merely because it is
large without proving the required runtime closure.

Worker capture, closure queries and manifest digesting total about 0.24 seconds
and are smaller secondary opportunities. Fresh-hit and edited diagnostics retain
the same broad runtime-dominated pattern; measurements here are macOS-only.
No remote-cache transport or test-runner optimization follows from this profile.

## Reproduce and validation

Build owned tools before measurement. In the pinned Nix environment:

```sh
python3 tests/remote_workers/integrity_workflow_profile.py \
  --output "$RESULTS" --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" \
  --bazel-install-cache "$INSTALL_CACHE" \
  --bazel-repository-cache "$REPOSITORY_CACHE"
python3 tests/remote_workers/integrity_workflow_summary.py \
  "$RESULTS/report.json" --output "$SUMMARY"
```

Owned .NET build/style, five style-policy tests, 32 preparation tests and 28 macOS
workflow tests passed (one Linux-only test skipped). After registering the profile
flag, Preparation rebuilt with zero warnings/errors and the accepted 16-invocation
experiment exercised both flag modes. No GitHub CI was dispatched.
