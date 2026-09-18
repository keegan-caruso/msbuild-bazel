# Streaming integrity checks

Integrity scans now hash regular files through a pooled 64 KiB buffer instead of
copying each entire file through a growing MemoryStream and a second byte array.
The change applies to tree snapshots and worker executable/system-tool hashes.
Callers that need actual file contents retain the existing byte-array reader.

## End-to-end results

Three unprofiled repetitions per case, compared with the preceding
[repository-cache candidate](bazel-repository-cache.md). Shared Bazel installation
and dependency-download caches are enabled in both variants.

| Workload / case | Before | Streaming | Reduction | Raw MSBuild |
|---|---:|---:|---:|---:|
| Diamond unchanged | 5.444 s | 4.487 s | 17.6% | 0.573 s |
| Diamond body edit | 5.884 s | 4.983 s | 15.3% | 0.994 s |
| Serilog unchanged | 9.445 s | 8.287 s | 12.3% | 1.076 s |
| Serilog body edit | 9.844 s | 8.677 s | 11.9% | 1.202 s |

All 12 comparisons passed exact managed DLL/PDB equality and actual
application/approval-test execution. Unchanged consumers compiled zero projects;
body edits compiled one. All four medians still miss the retained diagnostic
performance target of adapter <= 1.25 * raw + 0.250 seconds.

Combined entry/exit integrity phase medians drop from approximately 2.67 to
1.77 s for unchanged diamond and 2.86 to 1.93 s for Serilog. Their Bazel phases
remain approximately 2.32 and 4.25 s. Phase medians do not necessarily sum to the
median wall time. The large allocation/scan improvement is directly measured;
small changes in other phases include sequential-run noise and possible effects
of reduced GC pressure. Serilog's unchanged samples range from 8.276 to 8.779 s.

[Workflow evidence](integrity-workflow-evidence.json) retains all samples,
phase/transport data, compiler counts, scan counts, source-report hashes and
harness provenance. This is one implementation change followed by its repeated
workflow measurements; profiling itself is recorded separately.

## Profile findings

The resolved production SDK has 19 Nix runtime roots. A full scan makes 6,002
file visits and hashes 1,562,628,733 bytes, including followed symlink targets.
This is bytes processed per scan, not the unique on-disk SDK size.

Five-scan medians after an initial reference snapshot:

| Measurement | Buffered | Streaming |
|---|---:|---:|
| Full SDK snapshot | 1.089 s | 0.700 s |
| Cumulative managed allocation per snapshot | 6,082.8 MB | 24.5 MB |
| File read/buffering, including open | 0.521 s | 0.147 s |
| SHA-256 computation | 0.483 s | 0.464 s |
| File manifest construction | 0.0018 s | 0.0014 s |
| Manifest comparison | 0.0012 s | 0.0010 s |
| Canonical manifest digesting | 0.0234 s | 0.0219 s |

The snapshot is 35.8% faster with 99.6% less cumulative managed allocation.
Allocation is measured on the calling thread and is not peak resident memory.
Reading/buffering includes allocation and GC costs incurred during that operation;
it is not a cold-disk I/O measurement. The reference scan warms the filesystem
cache. Gen-2 collection counts fall from a median 79 to 1 per profiled cycle;
those cycles also include comparison and canonical digesting.

The remaining snapshot time includes traversal, metadata checks, directory
manifests and profiling overhead. Manifest comparison costs about one millisecond;
whole-file buffering is the useful optimization target in these results.

[Profile evidence](integrity-profile-evidence.json) retains all samples, allocation
counts, GC counts, assembly hashes and per-root canonical digests. Every SDK root
digest is identical between buffered and streaming variants. The profiler resolves
the development-shell SDK wrapper exactly as the workflow does; an initial probe
of the broader unresolved wrapper closure is excluded from this evidence.

## Preserved validation

- Both byte-array and streaming readers use the same descriptor-opening helper.
  No-follow/nonblocking opens and descriptor-level regular-file checks remain.
- Every file is read and hashed on every validation pass. The pooled object is a
  byte buffer, not cached file contents, digests or metadata-based approval.
- Snapshot size, mtime and mode checks remain before/after reading. The snapshot
  additionally requires the byte count actually read to match its initial size.
- Directory namespace checks, explicit symlink-following policy, per-caller
  expected manifests and final workflow verification remain in place.
- Buffer return and descriptor/hash disposal run on failure as well as success.
  This retains the existing before/after integrity model, not an atomic snapshot
  or protection against all possible concurrent filesystem races.

Tests cover empty inputs, 64 KiB boundaries, a 17 MiB multi-buffer file, SHA-256
parity, symlink/FIFO/directory rejection, same-length edits with restored mtime,
conflicting expected manifests and mutation between passes. Existing archive,
NuGet staging and worker-identity rejection controls also pass.

## Reproduction

The profile helper is a test bridge; normal workflow calls do not collect
per-file clocks or allocation counters. Buffered instrumentation is commit
`b637d6e`; streaming is `24b9329`. Build the test bridge in the pinned Nix environment
at the corresponding revision, then run:

```sh
bash scripts/dotnet.sh build tests/Preparation.Tests -c Release -warnaserror
python3 tests/remote_workers/integrity_profile.py \
  --output "$PROFILE_RESULTS" --label "$VARIANT"
```

The [declared protocol](integrity-streaming-protocol.md) separates these warm
instrumented microbenchmarks from one-shot unprofiled workflow timings. To repeat
the latter with the same pinned SDK, Serilog checkout, real cache server and
provisioned tool caches:

```sh
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" --output "$RESULTS" \
  --repetitions 3 --cases unchanged body --bazel-install-cache "$INSTALL_CACHE" \
  --bazel-repository-cache "$REPOSITORY_CACHE" \
  --protocol docs/integrity-streaming-protocol.md
```

Consumer source, preparation, Bazel server and action caches remain fresh;
producer source/state is removed before consumption. Both paths execute the
application/approval test and require exact managed DLL/PDB equality. Initial
Restore and tool acquisition are outside both clocks. These remain sequential,
same-host macOS ARM64 measurements, not independent-worker acceptance. Cold/API
cases are outside this focused follow-up.

## Validation

`scripts/check-dotnet.sh` passed owned .NET builds, warnings/style checks,
5 style-policy tests, 32 preparation tests and 23 workflow tests. All 19 SDK
manifest digests match the buffered reference across the two profiling variants.
`scripts/check.sh`, profiler/harness Python compilation and `git diff --check`
also passed. No GitHub CI was run.
