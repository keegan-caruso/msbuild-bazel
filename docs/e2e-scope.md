# End-to-end scope

## Milestone 1: prove the MSBuild boundary before writing a Bazel adapter

Linux x86-64, .NET 10.0.100, net10.0, Release; two projects (App -> Shared) and Microsoft.Build.Traversal 4.1.82. Standard SDK projects; no application NuGet dependencies. Traversal is restored during preparation.

| Scenario | Required observation |
| --- | --- |
| Traversal baseline | Both project compilation markers occur and App prints `shared-v1/app-v1` |
| Isolated dependency handoff | Shared action runs first; delete bin/obj; restore App's restore metadata; App consumes Shared bundle, compiles App only, and prints the baseline value |
| App-only edit | Reuse the same Shared bundle, change App's suffix, build App; no Shared marker and output changes to `shared-v1/app-v2` |
| Missing dependency artifact | Delete a listed bundle artifact; consumer exits nonzero with a dependency diagnostic |
| Configuration mismatch | Supply a bundle with different configuration; consumer rejects it |
| Workspace relocation | Supply a bundle from a different absolute workspace path; consumer explicitly rejects this unsupported case |

Tests use fresh copied workspaces, isolated NuGet package directories, subprocess timeouts and retained logs on failure. They test the public process contract, not private helper functions. No mocks, sleeps, timing assertions, unconditional skips or expected failures may substitute for running the build.

Before implementation, the test command is expected to fail because `tools/spike.py` does not exist. Record that red run, then implement. The workflow should run the tests after the implementation commit rather than hide failures behind file-existence guards.

## Path-probe evidence

The prerequisite path experiment is implemented in `tools/probe_paths.py` and
`test_msbuild_paths.py`. It moves a completed bundle while preserving the project
path, then tries an unchanged cache at a new workspace path after removing the
producer workspace and restoring the consumer afresh. Finally it builds a fresh
dependency cache at the consumer path as a positive control. The seventh e2e
test asserts successful App-only compilation for both controls and raw MSBuild
`MSB4252` for relocation. See [path findings](path-findings.md).

## Milestone 2: public-API result replay (next, not implemented)

Define a separate experimental process contract and black-box tests before
implementation. The [replay plan](result-replay-plan.md) specifies same-path and
relocated replay, App-only edits, missing dependency payloads/target results,
missing artifacts, identity mismatches, and a narrow publish request. Preserve
the existing seven tests and their v1 expectations as controls. No new replay
tests have been run or counted as passing.

Use graph-ordered dependency submissions and verify strict isolation. Require
the producer workspace to be absent in the relocation case, fresh consumer
restore metadata, staged artifacts, and no Shared compilation. Record commands,
engine versions, target requests and actual application output.

## Milestone 3: Bazel integration (gated by replay)

The following Bazel scenarios remain planned:

- Build the same outputs with a real custom Bazel action per project.
- Compare normal build output with the Bazel result.
- Read execution logs to assert cold (Shared + App), unchanged (neither), App edit (App only), Shared edit (Shared + App).
- Clear local outputs while retaining disk cache and verify artifact reuse and execution.
- Exercise changed output/sandbox paths before claiming portability.

## Deferred

General graph generation, multi-targeting, Native AOT, general publishing beyond
the replay fixture check, Razor/WPF, arbitrary package build tasks, remote
execution and distributed caches. Linux x86-64 remains the initial Bazel target;
native macOS ARM64 MSBuild controls have been measured, but cross-platform Bazel
support is not established. A failed prerequisite experiment is a useful finding
and blocks expanding into these areas.

## Red-run evidence

Before implementation: `python3 -m unittest discover -s tests/e2e -v` ran six tests; all six failed because the public `tools/spike.py` entry point did not exist. No skips or expected-failure annotations were used.
