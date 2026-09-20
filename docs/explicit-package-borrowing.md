# Package borrowing in the explicit model

Keep read-only borrowing in the new explicit rules. It is already their behavior;
the older generated-workflow `borrow-package-inputs` switch does not control them.
No production implementation or default changed in this experiment.

## Controlled comparison

Base: `84d1d2c`. Linux ARM64 / Ubuntu 22.04, SDK 10.0.400, Bazel 8.4.2,
four CPUs, 6 GiB, four persistent compiler workers. Synthetic 33-project graph:
32 libraries using Microsoft.CodeAnalysis.CSharp 5.9.0 and one executable that
consumes them all. Three resolved package archives (CSharp, Common, Analyzers),
with their exact archive/content hashes declared as Bazel inputs.

The baseline creates per-project symlinks to the verified read-only package trees.
A temporary runner variant replaces only that symlink with recursive byte copies.
Both modes keep worker input digest verification, snapshot reuse, read-only compiler
mounts, NuGet restore, compilation, and output publication. The copy variant lives
in a disposable checkout; it is not a new production option.

Three pairs alternate execution order: borrow/copy, copy/borrow, borrow/copy.
Each mode gets a new Bazel output base and compiler workers. Package acquisition,
extraction, repository initialization and tool builds occur before timing. SDK and
OS caches are warm: **cold means fresh project build actions/workers**, not an
empty machine. Local action disk caching is disabled; no remote cache is used.
Each cold build executes 33 project actions, each body edit executes one, and
no-op builds execute none.

| Scenario | Copy median | Borrow median | Interpretation |
| --- | ---: | ---: | --- |
| Cold project build | 10.447 s | 8.678 s | 16.9% lower median wall time |
| One library body edit | 0.900 s | 0.801 s | Too noisy for a reliable end-to-end claim |
| No-op | 1.006 s | 1.081 s | No package preparation executes; timing noise |

Paired cold-build savings are **9.0%, 11.4%, and 19.2%**. Raw cold times:

| Pair | Copy | Borrow |
| --- | ---: | ---: |
| 1 | 10.447 s | 9.512 s |
| 2 | 9.745 s | 8.639 s |
| 3 | 10.741 s | 8.678 s |

Median summed preparation time across the 33 actions falls from **2.756 s to
0.438 s (84.1%)**. This is cumulative worker work, not additive wall time across
four concurrent workers. Snapshot work remains present (1.34 s copy / 1.41 s
borrow median), as intended; borrowing does not bypass verification. Other phase
and filesystem effects also contribute to the wall-clock difference.

## Correctness and scope

- All project implementation and reference assembly hashes match between modes
  and repetitions, separately for cold and edited states.
- Every edited application run returns the expected aggregate value, 225.
- The experiment validates borrowing performance in the **explicit** model. It
  does not qualify arbitrary packages that require writable package directories,
  measure the full Orchard application, or independently settle defaults in the
  older generated workflow. Package payload size and graph shape affect savings.
- The offline setup resolves the Roslyn analyzer prerequisite to stable 5.9.0;
  NuGet reports NU1603 because the requested prerelease minimum is absent from
  the local feed. Both modes use the same resulting exact lock; setup is untimed.

Reproduce inside a disposable qualified Linux container with the repository and
SDK available, a flat local feed of the required package archives, and the seeded
Bazel repository cache:

```sh
export RULES_MSBUILD_REPOSITORY_CACHE=/tmp/repository-cache
python3 tests/explicit_msbuild/package_borrow_benchmark.py \
  --output /evidence --feed /tmp/feed --projects 32 --pairs 3
```

The harness requires a fresh `/tmp/explicit-borrow-experiment` directory. It saves
logs and measurements, removes each completed Bazel output base, and leaves
remaining fixture/tool files for container cleanup. Compact results are in
[evidence/explicit-package-borrowing](evidence/explicit-package-borrowing/summary.json).

The integration worktree remains paused at its earlier conflict. This benchmark
does not modify its files or resolve that merge.
