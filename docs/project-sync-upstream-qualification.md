# Generated upstream qualification

Production `msbuild_sync` now emits buildable ObjectPool and Pipelines entry
projects at the revisions in the [original inventory](project-sync-upstream.md).
These are bounded slices, not whole-repository compatibility.

## Measured results

SDK 10.0.400, runtime host 10.0.11, Bazel 9.2.0, Release/net10.0:

| Slice | Generated projects | Platform | Raw/Bazel test parity |
| --- | ---: | --- | ---: |
| ObjectPool, ObjectPool.Tests, InternalTesting | 3 | macOS ARM64 and Linux ARM64 | 18 exact names/outcomes |
| Pipelines library and tests | 2, with 25 authored source dependency producers | Linux ARM64 | 577 exact names/outcomes |

Both slices pass warm local test-cache reuse, library body-edit test invalidation,
unchanged public reference assembly, restoration, and rejection of an edited
custom-target contract. Pipelines checks its separately built public contract;
its implementation output deliberately changes after the edit. A startup hook
proves raw and Bazel testhosts load their respective source-built Pipelines DLLs.
The Bazel proof also matches the generated producer's output hash after each edit.
See [recorded controls](project-sync-upstream-qualification-evidence.json).

`bash scripts/check-dotnet.sh` passes on both platforms: 5 style, 7 tooling,
35 runner and 29 generator tests. `bash scripts/check.sh` passes toolchain and
Starlark validation on macOS ARM64.

ObjectPool runs its original `GenerateDirectoryBuildFiles` bootstrap as a declared
Bazel producer. The generated props keep a symbolic `$(RepoRoot)` for the shipping
package directory, avoiding an embedded temporary action path. NuGet SDKs, signing
keys, targeting packs, analyzers and test tooling come from declared package inputs.
The root NuGet configuration copied as test content has a separate staging path;
the build's restore configuration remains closed.

Pipelines retains existing explicit task, resource-generation, reference-pack and
dependency producers. Only its two entry declarations are replaced by generated
ones. The runtime layout uses the pinned **installed native/runtime host**, with
Pipelines replaced by its source-built implementation. This is not another
qualification of the earlier complete source-only runtime host.

## Reproduce

Use disposable Linux ARM64 checkouts at the pinned revisions, with all referenced
sources present. Full checkouts work; sparse checkouts must include shared sources,
build tasks and generation inputs. Raw setup restores packages and writes ignored
upstream build artifacts. It does not edit upstream source/project files.

```sh
source scripts/env.sh
python3 tests/project_sync/upstream/qualify.py \
  /checkout/aspnetcore /checkout/runtime /tmp/fresh-sync-qualification
```

The driver records per-step logs and `commands.json`. `controls.py` records parity,
cache, edit and drift checks. The checked-in document snapshots freeze exact hashes
and target/task names; preparation rejects changed or newly discovered custom
contracts instead of approving them automatically. Package document lookup tolerates
filesystem casing differences; content hashes and target/task lists must still match.

The recorded Linux run resumed at Pipelines preparation after fixing package-path
casing in the fixture snapshot lookup; subsequent sync/build/controls all passed.
Acquisition, evaluation inventory and authored dependency preparation are fixture
setup. Generated `.bzl` output is never hand-edited. These runs are correctness
qualification, not cold-build benchmarks.

## Remaining limits

- macOS Pipelines raw tests pass (577); generated sync succeeds, but the sandboxed
  build fails to start an out-of-process MSBuild task host. Linux qualification
  preserves task behavior and sandboxing. macOS generated build/test is unqualified.
- Linux evidence is ARM64, not x86-64. No GitHub CI was dispatched.
- Only net10.0/Release and these selected graphs are covered. Http.Abstractions and
  Immutable are covered by the subsequent [expanded qualification](project-sync-expanded.md);
  wider graphs remain follow-ups.
- Complex repositories still author package, bootstrap, custom-target and tool
  contracts. The generator does not infer task side effects or execute targets.
- Warm local caching and declared inputs do not establish remote-cache portability
  or relocation correctness. Those need separate cache/path perturbation runs.
