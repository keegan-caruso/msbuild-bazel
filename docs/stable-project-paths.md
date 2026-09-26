# Stable project paths: first synthetic qualification

An internal prototype fixes the path-driven reference churn in small SDK projects.
It is **off by default** and is not yet qualified for Orchard, package tasks,
analyzers, remote caching or remote execution. The broader
[design](stable-project-paths-design.md) remains the intended direction.

## What changed

The Linux worker keeps separate identities for:

- A project/configuration: stable source, asset and output paths.
- Its current inputs: existing SHA-256 verification and request diagnostics.
- Each compiler reference: a path containing the actual DLL digest.

The prototype clears staged inputs and intermediate/output files for every request.
MSBuild uses private XML caches for these mutable stable paths. SDK compiler-server
reuse remains enabled; SDK and runner inputs retain their existing worker lifetime.
Reference copies under the workspace remain for preparation/conflict checks, but
compiler HintPaths use the digest-qualified copies outside that workspace.
Removing this duplicate staging is later work.

No supported macro/rule attribute changed. The internal qualification flag is
`--define=rules_msbuild_stable_path_prototype=1` with `linux_worker=True`.
The request carries a logical target identity; the broker combines it with explicit
configuration, excluding source/reference contents and dependency membership.
The prototype rejects package/tool/project-analyzer inputs, custom SDKs, declared
`UsingTask` registrations, prepared restore and other unqualified input roles.
This narrow gate is not a general task-loading isolation guarantee.

## Small projects and observed results

The test creates six projects: `C`, `B`, two consumers `A` and `Fan`, an unrelated
library, and an executable test. `B` generates public assembly metadata from an
embedded resource's `FullPath`, reproducing Orchard's path problem without
Orchard-specific production code. `A` and `Fan` either consume only B's reference
or retain the normal transitive C reference. The executable test keeps the full
transitive dependency set.

For an unused public API addition to C:

| Mode | B reference DLL | A and Fan compilation | Executed compilations including test |
| --- | --- | --- | --- |
| Existing content-derived paths, direct references | Changes unnecessarily | Both rebuild | C, B, A, Fan, Test |
| Stable paths, direct references | Identical | Both skipped | C, B, Test |
| Stable paths, transitive references | Identical | Both rebuild, as required by their inputs | C, B, A, Fan, Test |

Bazel performed the scheduling; the harness does not simulate an action cache or
skip builds itself. Disk and remote action caches were disabled; normal local
incremental state was retained. The Test compilation remains
necessary on this API edit because its compiler input set includes C.

Additional passing controls:

- **Body edit:** only C compiles. The executable test reruns and deliberately
  fails on the changed implementation; reference DLLs remain identical.
- **Propagated constant:** C, B, both consumers and Test compile, with updated
  constants visible at runtime. Reference reuse does not hide a real API change.
- **Same-size/same-timestamp props edit:** only B compiles; the same worker sees
  the new conditional source behavior and the test reruns.
- **Resource content:** only B compiles and the test sees the new embedded bytes.
  The public path metadata and reference DLL remain unchanged.
- **Resource deletion, re-addition and rename:** metadata changes rebuild the
  consumers, runtime resources match current inputs, and the deleted path does
  not survive in metadata. Re-adding the same resource restores the reference hash.
- **Invalid XML followed by repair:** the worker rejects the bad import and
  successfully processes the repair without restarting.
- **Exposed transitive type:** a direct-only consumer fails with CS0012 when it
  inherits a type whose base lives in C. Adding C to both csproj and BUILD repairs
  the build. The transitive mode succeeds without that repair.
- **Custom task declaration:** the prototype explicitly rejects it; removing it
  lets the same worker continue.

All successful compilations in each full sequence used the same compiler-child
PID. Fresh workers in different workspace/output-base directories produced matching
reference DLLs, implementation DLLs and PDBs. The direct-reference sequence passed
on **Bazel 9.2.0 and 8.8.0**, including byte-for-byte baseline output agreement
between them. The existing-path reproduction and transitive control ran on 9.2.0.

## Reproduce

Inside the qualified Ubuntu 22.04 ARM64 worker image with SDK 10.0.400 and the
repository tool environment configured, use new disposable output directories:

```sh
python3 tests/explicit_msbuild/stable_worker_projects.py /tmp/stable-control --legacy
python3 tests/explicit_msbuild/stable_worker_projects.py /tmp/stable-direct
python3 tests/explicit_msbuild/stable_worker_projects.py /tmp/stable-transitive --transitive
USE_BAZEL_VERSION=8.8.0 python3 tests/explicit_msbuild/stable_worker_projects.py \
  /tmp/stable-direct-8 --expected-baseline /tmp/stable-direct/report.json
```

The driver enables the internal flag unless `--legacy` is selected. It records
actual compilation actions, reference hashes, process identity, test execution
and wall time. [Compact evidence](evidence/stable-project-paths/results.json)
includes source hashes and all completed sequences.

The environment used six CPUs, 10 GiB RAM, two build slots and one MSBuild worker.
Times are single diagnostic samples; some independent qualification runs overlapped.
They do **not** establish a speedup or predict Orchard timing. Earlier fixture-only
failures (target visibility, a missing csproj edge in the repair, and empty-glob
handling) were corrected before the complete passing sequences recorded here.

Validation also passed: ExplicitBuild Release build with warnings as errors,
.NET format verification, Buildifier, 5 code-style tests, 36 explicit-build unit
tests, forged-digest/undeclared-input worker checks, and the existing fresh-worker
path reproducibility check. GitHub CI was not run.

## Next boundaries

1. Version and qualify package/task/analyzer load groups, including replacement
   helpers and failure recovery. Define compiler-child recycling where isolation
   cannot be proven. Do not simply allow these inputs through the prototype gate.
2. Cover generated and prepared inputs, configuration switching and independent
   HTTP-cache recovery before making stable paths the normal Linux worker behavior.
3. Run the Orchard path-only experiment, then migrate selected dependency edges.
   Stable paths alone cannot remove work while C remains a declared compiler input.
   Measure XML parsing, staging and tool restart costs alongside compilation counts.
