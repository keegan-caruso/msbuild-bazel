# Performance versus raw MSBuild

Historical graph measurements at [revision 7e22cd6](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/performance.md):
runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Linux ARM64, four CPUs / 8 GiB, four MSBuild nodes, one graph worker with an
8192 MiB snapshot budget. Scope: 481 compilations / 543 configurations / 39 roots.
The graph-only cutover has not repeated this series.

Median wall seconds, three matched pairs, profiling off:

| Case | Bazel | Raw MSBuild | Difference |
| --- | ---: | ---: | --- |
| Cold Restore + Build | 1093.53 | 1048.89 | 4.3% slower |
| No-op | 0.41 | 17.62 | Bazel whole-action hit |
| Leaf body edit | 36.64 | 30.87 | 19% slower; six Csc calls each |
| Leaf API edit | 52.35 | 46.91 | 12% slower; 17 Csc calls each |
| Local project recovery | 20.58 | — | 481 hits; no compilation |
| Independent HTTP recovery | 34.35 | — | 481 hits; producer stopped |

Recovery starts with declared SDK/package inputs and prepared Restore available;
Bazel remote/disk action caches were disabled. Fresh-consumer Restore + recovery was
109.18 s, excluding acquisition. Native producers/tests are separate. Compiled and
recovered bytes matched. An unscored final restoration ran out of disk; a separate
restart verified restoration and suites. It is excluded from medians.

Body/API diagnostics spent about 5.7 s evaluating and 4.2 s copying ~680 MB.
Copies/publication and Restore invalidation remain optimization targets. Keep
profiling disabled for scores and match source, configurations, Restore/cache state,
native products and resources. Report actual compiler calls and project hits/misses.
Drivers: [cold](../tests/graph_build/upstream/runtime_cold.py),
[edits](../tests/graph_build/upstream/runtime_benchmark.py),
[recovery](../tests/graph_build/upstream/runtime_remote.py) (each accepts `--help`).
Keep detailed reports outside Git. See [support limits](support.md).
