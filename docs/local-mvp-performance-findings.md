# MVP preparation performance qualification (#7)

## Change and preserved boundaries

Profiling the initial candidate found that repeated `Path.is_relative_to` calls
constructed more than a million temporary parent-path objects while checking
entries against the declared runtime closure. Canonical allowed-root names and
separator-terminated prefixes now perform the same containment check. Every
entry is still resolved strictly; sibling prefixes, undeclared symlinks and
cycles remain rejected.

Independent declared roots are hashed with at most four worker threads. Every
byte and namespace entry still participates. Per-file before/after descriptor
checks, directory membership checks, final traversal checks and the enclosing
consumption lease remain intact. Hashing can overlap because its native work
releases the Python GIL. Result order and persisted snapshot schema are unchanged;
controller identity changes still invalidate old preparation requests.

Unit controls cover sibling-prefix escapes, filesystem-root containment, exact
serial/parallel identity equality and the existing mutation/symlink cases.

## Frozen gate

The unchanged [budget](local-mvp-preparation-budget.json) requires five measured
pairs per workload, median reuse/fresh at most 1.0 and median full reuse at most
5.0 seconds. The new `tools/qualify_preparation_performance.py` verifies the
original budget SHA-256, complete unique samples, exact requests and work flags,
finite timings, stable source/tool identities and a same-candidate 40-sample
ordinary-MSBuild/adapter Build/Test comparison. It recomputes medians rather than
trusting summary fields. An exceeded limit or missing evidence fails the gate.

Initial optimization measurements (not the final qualification run) reduced
small-fixture preparation from 2.270s fresh to 1.486s reuse and Serilog from
2.200s fresh to 1.737s reuse. The first containment-only experiment left Serilog
above its ratio budget; it is retained as an unsuccessful intermediate result.
No budget threshold was changed. Final clean-candidate qualification is pending.

The benefit is bounded preparation-work reduction. End-to-end adapter overhead,
recovery differences, broad application scale and other platforms must not be
inferred from these two small workloads.
