# Performance versus raw MSBuild

The graph workflow runs one MSBuild graph action and reuses project snapshots
through the cache plugin. Bazel whole-action hits and MSBuild project-cache hits
measure different work. All times below are wall seconds, profiling off.

## Runtime scorecard

Historical measured graph baseline at [revision `7e22cd6`](history.md):
runtime v10.0.0 `60629d14374c56f1cb51819049ad1fa529307f8d`, SDK 10.0.400,
Linux ARM64 VM, four CPU / 8 GiB, four MSBuild nodes, one graph worker,
8192 MiB logical snapshot budget. Scope: 260 paths, 543 configured nodes,
481 compilations and 39 selected roots. Runner SHA-256:
`670dcb55f6b1b12132c2b19793f6e8f8b381f8db77b4220dd3e6348d788df2ca`.
The graph-only cutover has not repeated this large timing series.

Three matched pairs per scored case:

| Case | Bazel median (range) | Raw median (range) | Interpretation |
| --- | ---: | ---: | --- |
| Cold Restore + Build | 1093.530 (1090.422–1187.811) | 1048.885 (1022.047–1086.768) | 4.3% workflow overhead |
| Cold Build only | Same full Bazel invocation | 967.741 (945.796–1007.308) | 13.0% versus raw Build alone |
| No-op | 0.407 (0.403–0.756) | 17.624 (17.623–18.870) | Bazel whole-action hit |
| Leaf body edit | 36.640 (35.976–37.844) | 30.869 (29.232–31.770) | 19% overhead; six Csc calls both |
| Leaf API edit | 52.348 (49.912–52.724) | 46.910 (44.351–51.154) | 12% overhead; 17 Csc calls both |
| Local project recovery | 20.581 (17.863–25.606) | — | 481 hits, no compiler calls |
| Independent HTTP recovery | 34.348 (34.271–38.194) | — | 481 hits; producer stopped |

Cold raw Restore median was 79.460 s. Bazel Restore action median was 87.954 s;
graph action median was 995.484 s, including staging, verification and export.
These action durations are not compiler-only time. The independent recovery scores
start with declared SDK/package/repository inputs and prepared Restore available;
Bazel action remote/disk caches were disabled. First fresh-consumer invocation was
109.184 s including Restore, with SDK/package/bootstrap acquisition preceding it.
Native producer/test time is separate from these managed scores.

Compiled DLL/PDB/resource bytes match complete-source raw MSBuild for all 3,622
compared files. All 10,780 snapshot files match bytes/modes on recovery. The final
original restoration hit a full disk and exited unsuccessfully after scoring;
a separate unscored restart/restoration verified artifacts and all suites. It is
excluded from timing medians.

## Where the time remains

Separate diagnostic body/API requests spent about 5.66/5.76 s evaluating projects.
Materialization copied 10,621/10,465 files, 688.5/677.2 MB, in 4.28/4.13 s; the Linux
filesystem used fallback copies, not copy-on-write clones. Hashing tasks overlap,
so summed task durations must not be added as wall time.

Independent HTTP diagnostics downloaded 5,680 CAS blobs and 263,018,617 logical
bytes (250.83 MiB), including manifests. This excludes pointers and wire overhead.
Cold graph VM usage peaked at 4.940–5.894 GiB; raw at 3.399–4.127 GiB. These are
whole-VM MemAvailable samples, not process RSS; raw warm observations can include
an idle retained graph worker.

## Decisions from profiling

- Retained a request-local ownership index: validation fell from 1.804 s to
  0.006/0.003 s in the measured control. No cross-request evaluated-project cache.
- Did not retain node-key caching or reordered traversal: no established wall win.
- Kept SDK/package byte verification: isolated warm costs were about 0.312/0.929 s;
  mutation checks cannot be replaced by an unchecked path/timestamp.
- Kept ordinary copies by default. A macOS COW fixture improved 7.03 to 6.74 s;
  it does not establish Linux savings.
- Compact retained outputs remain experimental: 128 MB to 1.86 MB did not improve
  body wall time (4.15 versus 4.14 s) and are not the public graph default.
- Detailed evaluation profiling nearly doubled a diagnostic run (7.55 to 15.19 s).
  Scores must have profiling disabled.

## Reproduce

Prepare pinned inputs using [runtime qualification](runtime-qualification.md),
then inspect each driver's help and use fresh disposable output directories:

```sh
python3 tests/graph_build/upstream/runtime_cold.py --help
python3 tests/graph_build/upstream/runtime_benchmark.py --help
python3 tests/graph_build/upstream/runtime_remote.py --help
```

Match source, configuration/frameworks, native products, Restore state, resource
limits and cache state. Report source edits, graph misses and actual Csc counts
separately. A project-cache miss need not invoke the compiler. Include preparation
and acquisition when reporting complete developer workflows.

[History](history.md) preserves earlier Orchard/Avalonia, source SDK and retired
per-project benchmarks. They are separate experiments, not comparable replacements
for this scorecard. No matched full native build, x86-64 or remote-execution timing
is claimed.
