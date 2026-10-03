# Performance versus raw MSBuild

Main **8d83f0f**, runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
SDK 10.0.400, Bazel 9.2.0, Linux ARM64: four CPUs / 8 GiB, four MSBuild nodes,
one graph worker with an 8192 MiB snapshot budget. Scope: 481 compilations /
543 configurations / 39 roots. Refreshed after the graph-only cutover.

Median wall seconds, three matched pairs, profiling off:

| Case | Bazel | Raw MSBuild | Difference |
| --- | ---: | ---: | --- |
| No-op | 0.39 | 17.43 | Bazel whole-action hit |
| Leaf body edit | 32.66 | 30.24 | 8.0% slower; six Csc calls each |
| Leaf API edit | 47.80 | 46.68 | 2.4% slower; 17 Csc calls each |
| Local project recovery | 20.07 | — | 481 hits; no compilation |

All 3,622 compiled files matched raw bytes on every row. Body/API edits reused
prepared Restore and had 475/464 project hits. Acquisition, the all-miss seed,
source restoration and filesystem trimming were outside scored observations.
Only one build VM ran during scoring. The incomplete series from a disk-damaged
VM was excluded; these rows came from a fresh filesystem and verified inputs.
Cold and independent HTTP recovery refreshes remain pending.

Separate body/API diagnostics measured evaluation **5.36/5.59 s**, input hashing
**2.74/2.75 s**, and replay copies **3.82/3.08 s** (689/677 MB). Worker staging was
1.00/1.08 s. These scopes can overlap; do not add operation totals as wall time.
The owned-product publication and package-input reductions on the qualification
branch passed small controls; their large-graph effect is not yet measured.

[Historical series at 7e22cd6](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/performance.md)
measured cold Restore + Build at 1093.53 s versus 1048.89 s raw, and independent
HTTP recovery at 34.35 s. Those measurements predate the graph-only cutover.

Match source, configurations, Restore/cache state, native products and resources.
Keep profiling off for scores and report compiler calls and project hits/misses.
Drivers: [cold](../tests/graph_build/upstream/runtime_cold.py),
[edits](../tests/graph_build/upstream/runtime_benchmark.py),
[recovery](../tests/graph_build/upstream/runtime_remote.py) (each accepts `--help`).
Use `--trim-between-rows` when thin VM disks need unscored reclamation. Keep
reports outside Git. See [support limits](support.md).
