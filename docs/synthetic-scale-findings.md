# R09 synthetic scale protocol: initial correctness slice

The deterministic fixture generator and runnable comparison protocol are implemented.
R09 remains open. Construction at 10, 100 and 1,000 nodes is tested; construction
is not build acceptance at those sizes. No performance qualification is claimed.

`tools/synthetic_graph.py` defines two topologies with indices in topological
order: a chain and a binary fan-out tree whose terminal consumer joins every
leaf. Both contain exactly the requested number of compilation nodes and every
node is reachable from the entry. Each project contains one fixed-format C#
source; its output is a deterministic modular sum of direct dependencies. The
fixture has no external packages, fixes SDK 10.0.100, and disables compiler/server
reuse. The manifest records all edges. Repeated generation is byte-identical.

Run construction checks and the bounded native smoke with pinned tools:

```sh
python3 -m unittest discover -s tests/scale_synthetic -v
# Native smoke, separate from construction-only tests:
python3 -m unittest discover -s tests/scale_synthetic_native -v
python3 tools/probe_synthetic_scale.py --nodes 10 --shape fan \
  --cases fresh warm --output /tmp/synthetic-10-fan
```

The full runnable state protocol is:

```sh
python3 tools/probe_synthetic_scale.py --nodes 10 --shape chain \
  --output /tmp/synthetic-10-chain-all
python3 tools/probe_synthetic_scale.py --nodes 10 --shape fan \
  --output /tmp/synthetic-10-fan-all
```

Use `--nodes 100` or `--nodes 1000` only as explicit larger experiments; these
levels have not been qualified. Timeouts are errors, not successful skips.

Each state owns separate ordinary/preparation/generated directories, output base
and disk cache. A state never inherits another state's mutation or cache. Warm,
leaf, shared and recovery cases independently build the unmodified baseline
before the measured invocation. SDK/bootstrap and restore work are labeled
separately. Both systems use two workers and identical sources. Ordinary builds
retain diagnostic logs and MSBuild binary logs; the probe counts executed `Csc`
task-start records, excluding skipped targets. Generated builds retain Bazel
execution logs, profiles, native-action compilation logs and complete bundle
hash/mode inventories. Every node is explicitly requested so recovery materializes
all bundles. Preparation sources are deleted before final generated execution.

| State | Ordinary expected compiler invocations | Generated expected action executions |
| --- | --- | --- |
| Fresh | Every node | Every node, empty cache/output base |
| Warm | Zero | Zero |
| Leaf edit (entry consumer body) | One | Entry consumer only |
| Shared edit (root dependency body) | One, unchanged public API | Root and complete consumer closure |
| Recovery | Every node after deleting bin and configuration obj | Zero, every node restored from disk cache after deleting output base and generated workspace |

Both mutations add seven to the selected method body and must change the executed
entry output. Each system is checked against the same computed output oracle,
not against the other's compiler counts. Ordinary mutations expect only the edited
project to compile because their public API is unchanged; violations fail the
work-set check and need investigation. Recovery also requires identical generated
bundle bytes and executable bits to its own unmodified warmup.

The report includes one descriptive elapsed wall time per subprocess and aggregate
preparation call. It does **not** infer separate evaluation, analysis or execution
costs from these totals. Bazel profiles are retained for later phase attribution.
`processTreePeakBytes` is null with an explicit missing-sampler reason: neither
parent RSS nor the largest child's RSS measures simultaneous process-tree RSS.
Five interleaved repetitions, dedicated worker calibration, SDK acquisition costs,
aggregate descendant memory sampling and predeclared numeric budgets remain
unimplemented/unmeasured. Correctness runs can overlap other work; their wall times
must not be used as performance comparisons. No-op latency or memory budget passes
are reported.

## Measured evidence

The ten-node fan fresh/warm smoke passed on macOS ARM64 with pinned Nix SDK
10.0.100 and Bazel 8.4.2. The graph has 13 edges and both ordinary and generated
outputs were exactly `70`. Fresh ordinary compiler/generated action counts were
10/10; independent warm counts were 0/0. Every generated execution used
`darwin-sandbox`, with preparation sources deleted before the final invocation.
Evidence: `/private/tmp/msbuild-scale-smoke-10/report.json`.

The independently warmed ten-node fan mutation/recovery controls also passed:

| Case | Ordinary Csc tasks | Generated executions | Generated disk hits | Both output oracles |
| --- | --- | --- | --- | --- |
| Entry leaf edit | 1 | 1 | 0 | `77` |
| Shared root edit | 1 | 10 | 0 | `105` |
| Output/cache recovery | 10 | 0 | 10 | `70` |

Recovery bundle bytes/modes matched its baseline warmup exactly. Evidence:
`/private/tmp/msbuild-scale-mutations-10/report.json`. These differences in
ordinary and generated shared-edit work are expected under the current
conservative artifact handoff policy.

Construction checks pass both topologies at all three specified sizes. Larger
scale execution and chain native execution remain unmeasured. The native runs overlapped other correctness work,
so the recorded wall times are not performance comparisons.

The dedicated native unittest entrypoint also passed on the final topology-checking
probe (one test, 57.5 seconds overall; not a benchmark). Evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/synthetic-scale-q9rhan22/probe/report.json`.

## Confirmed larger-chain preparation blocker

A bounded non-native reproduction with a 1,000-node chain manifest called the
real `prepare_graph._prepare` while mocking only package-plan validation. Its
recursive dependency-closure traversal raised `RecursionError: maximum recursion
depth exceeded` at Python's default recursion limit of 1,000, before graph
re-evaluation or a native build. Evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/synthetic-closure-review-d594ifj1/result.json`.
This was a confirmed preparation-scale blocker, not 1,000-node build acceptance
or a native timeout. The iterative fix below addresses that failure without
raising Python's recursion limit.
## Dependency-closure recursion fix

Preparation formerly recomputed each inclusive dependency closure through recursive
DFS. A synthetic 1,000-node chain raised Python `RecursionError` before discovery
revalidation; repeated convergence also revisited the same subgraphs. The focused
regression reproduced that failure with only package inspection mocked, before
any SDK/Bazel subprocess or plan publication.

`prepare_graph.dependency_closures` now processes nodes in dependency-first DAG
order using an iterative ready queue and memoizes each node's inclusive closure.
Missing dependencies and cycles retain their existing ValueError diagnostics;
self-loops fail as cycles. The change does not increase Python's recursion limit.
Closure storage still scales with total reachable node pairs (quadratic for a
chain), and merging many dense dependency sets can remain expensive. This removes
one bounded correctness blocker, not all scale costs.

Seven focused tests pass: exact 1,000-node chain closures, a 1,000-node layered
converging fan, known diamond/disconnected closures, duplicate edges, cycle and
self-loop controls, missing dependencies, and the 1,000-node preparation path
reaching the discovery-request guard. The seven test methods completed in 0.111
seconds locally; the existing 16 preparation rejection tests passed in 0.021
seconds. These are Python-only validation times, not graph build benchmarks.

```sh
python3 -m unittest discover -s tests/graph_execution -p test_dependency_closures.py -v
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
```

No 1,000-project restore, export, native build, cache or Linux qualification is
claimed by this fix. Native scale acceptance remains a separate bounded run.
