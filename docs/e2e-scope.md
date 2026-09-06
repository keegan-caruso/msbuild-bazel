# End-to-end scope

## Milestone 1: prove the MSBuild boundary before writing a Bazel adapter

Initial target: Linux x86-64; local MSBuild acceptance was also measured on macOS
ARM64 (see [findings](findings.md)). .NET 10.0.100, net10.0, Release; two projects (App -> Shared) and Microsoft.Build.Traversal 4.1.82. Standard SDK projects; no application NuGet dependencies. Traversal is restored during preparation.

| Scenario | Required observation |
| --- | --- |
| Traversal baseline | Both project compilation markers occur and App prints `shared-v1/app-v1` |
| Isolated dependency handoff | Shared action runs first; delete bin/obj; restore App's restore metadata; App consumes Shared bundle, compiles App only, and prints the baseline value |
| App-only edit | Reuse the same Shared bundle, change App's suffix, build App; no Shared marker and output changes to `shared-v1/app-v2` |
| Missing dependency artifact | Delete a listed bundle artifact; consumer exits nonzero with a dependency diagnostic |
| Configuration mismatch | Supply a bundle with different configuration; consumer rejects it |
| Workspace relocation | Supply a bundle from a different absolute workspace path; consumer explicitly rejects this unsupported case |

Tests use fresh copied workspaces, isolated NuGet package directories, subprocess timeouts and retained logs on failure. They test the public process contract, not private helper functions. No mocks, sleeps, timing assertions, unconditional skips or expected failures may substitute for running the build.

The original tests were run before `tools/spike.py` existed; see the historical
red-run evidence below. The driver is now implemented and these tests must pass.

## Path-probe evidence

The prerequisite path experiment is implemented in `tools/probe_paths.py` and
`test_msbuild_paths.py`. It moves a completed bundle while preserving the project
path, then tries an unchanged cache at a new workspace path after removing the
producer workspace and restoring the consumer afresh. Finally it builds a fresh
dependency cache at the consumer path as a positive control. The seventh e2e
test asserts successful App-only compilation for both controls and raw MSBuild
`MSB4252` for relocation. See [path findings](path-findings.md).

## Milestone 2: public-API result replay (implemented)

The separate [experimental contract](replay-interface.md) and black-box test
were written before the runner. `test_msbuild_replay.py` invokes the probe and
asserts same-path and relocated replay, App-only edits, missing payloads/target
results, missing artifacts, identity mismatches, unsupported paths, and narrow
publish. The original seven tests retain their v1 expectations as controls.
See [replay findings](replay-findings.md) for measured results.

Use graph-ordered dependency submissions and verify strict isolation. Require
the producer workspace to be absent in the relocation case, fresh consumer
restore metadata, staged artifacts, and no Shared compilation. Record commands,
engine versions, target requests and actual application output.

## Milestone 3: explicit Bazel integration (implemented)

`test_bazel_boundary.py` runs the two-target harness with a mandatory native OS
sandbox. It checks cold Shared+App execution, unchanged reuse, App-only and
Shared edits, disk-cache recovery after clearing outputs, and reuse in a fresh
Bazel output base. It compares runtime output, checks compile markers and declared
inputs, and rejects an undeclared relative input. Restore and plugin preparation
run before compile actions. See [Bazel findings](bazel-findings.md) for the
measured macOS evidence, passing Ubuntu 22.04 Linux CI results, and host/runtime limits.

## Milestone 4: action identity (implemented)

The identity probe tests imports, generated-source data, declared versus ambient
build environment, restore metadata and host identity. Python runtime inputs are
explicit. See [identity findings](action-identity-findings.md).

## Milestone 5: pinned build-package inputs (implemented)

The package probe checks exact-version NuGet build assets, data/target upgrades,
and rejection of missing, corrupt or stale inputs. It retains the scheduling and
cache matrix. Coverage is build-only; ordinary package DLL/runtime assets remain
unproven. See [package findings](package-input-findings.md), including the precise
full-suite and focused-rerun validation record.

## Deferred

General graph generation, multi-targeting, Native AOT, general publishing beyond
the replay fixture check, Razor/WPF, arbitrary package build tasks, remote
execution and distributed caches. Linux x86-64 remains the initial Bazel target;
native macOS ARM64 replay, Bazel sandbox/cache, identity and package tests have
been measured. The earlier nine-test suite also passed in Ubuntu 22.04 Linux CI;
Linux validation of the newer identity/package tests is handled separately.
Cross-platform artifact reuse is not established. A failed prerequisite experiment is a useful finding
and blocks expanding into these areas.

## Red-run evidence

Before implementation: `python3 -m unittest discover -s tests/e2e -v` ran six tests; all six failed because the public `tools/spike.py` entry point did not exist. No skips or expected-failure annotations were used.
