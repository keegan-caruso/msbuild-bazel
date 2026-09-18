# Reuse alias content digests within one integrity scan

The SDK closure has multiple symlink names for large native libraries. The initial
19-root inventory visits 6,002 files and logically covers 1,562,628,733 bytes.
Most redundant bytes come from LLVM and ICU aliases.

`FileTree.Snapshot` now retains a regular file's digest within that one snapshot
when following symlinks. Every alias still produces its full manifest record;
file metadata and directory-namespace checks remain. Metadata changes between
aliases reject the scan. The cache is discarded when the snapshot returns.
Initial identity, discovery and final lease validation do not share content
cache entries. There is no metadata-only trust across invocations.

The test bridge can disable the optimization to compare the old and new scans
using the same binary. The SDK profile requires exact equality for every snapshot
and canonical root digest. New controls cover multiple aliases and changed bytes
with restored size/mtime on a subsequent verification pass.

## Scan measurement

Five profiled scans per variant on the resolved macOS Nix SDK closure:

| Metric | Without reuse | With reuse |
| --- | ---: | ---: |
| Median scan time | 0.692 s | 0.563 s |
| Bytes physically hashed | 1,562,628,733 | 1,177,165,764 |
| Alias file reads avoided | 0 | 32 |
| Median allocated bytes | 24,475,696 | 25,447,856 |

All 19 root digests match. The optimization avoids 385,462,969 bytes of hashing
per scan (24.7%) and reduced median profiled scan time by 18.6%. It adds about
0.97 MB of cumulative managed allocation for digest lookup records. These are
warm-process micro-measurements, not an end-to-end speedup claim.

## Workflow protocol

Run the immediate parent and candidate sequentially with three unprofiled
repetitions per diamond/Serilog fixture using `action_cache_probe.py`. Each run
has deleted producers/primers, fresh consumer state, exact raw DLL/PDB parity,
actual app/tests, body misses and failed-test/lease non-publication controls.
Keep the same pinned SDK, cache service, Bazel install cache and repository cache.
No other build or test runs concurrently with the timed workflows.

## Complete workflow results

The immediate baseline (`e791999`, `/private/tmp/alias-workflow-before`) and
candidate (`5e5763b`, `/private/tmp/alias-workflow-after`) each passed all 28 cases
and six paired raw comparisons, including unchanged/edited managed artifacts,
actual application/approval execution, and rejected-test/lease publication guards.
Three repetitions per fixture, sequential runs on the same interactive host:

| Median complete workflow | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Diamond remote hit | 4.072 s | 3.857 s | 5.3% |
| Serilog remote hit | 7.431 s | 7.220 s | 2.8% |
| Diamond body miss | 5.089 s | 4.825 s | 5.2% |
| Serilog body miss | 8.804 s | 8.385 s | 4.8% |

This is a modest measured improvement, not raw-MSBuild parity. Raw unchanged
medians were 0.575/0.579 s for diamond and 1.074/1.094 s for Serilog, before/after.
Sequential-run noise remains possible; the independent byte-count and scan
measurements establish the removed work. [Evidence](integrity-alias-evidence.json)
retains report hashes, revisions, medians and exact root digests.

Final validation: 28 workflow tests passed on macOS with the Linux-only control
skipped, 32 preparation tests passed, and both changed .NET projects passed
formatter checks. The complete workflow measurements exercised actual sandboxed
builds, cache hits and failure controls. No CI was dispatched.
