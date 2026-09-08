# Bazel output layout and selected-version acceptance

## Change and scope

This follows the [original four-version matrix](nix-bazel-matrix-findings.md).
That run found an in-workspace repository-content cache rejection in Bazel 9.2.0,
and a hardcoded 8.4.2 version guard blocking all other build probes. The user
subsequently authorized fixing those harness boundaries, while recording any
new adapter or Bazel compatibility failures without repairing them.

The normal `scripts/bazel.sh` wrapper now leaves the output root to Bazel.
It retains persistent server/batch selection and forwards explicit startup
options, including `--output_base` and `--output_user_root`. No version-specific
namespace or cache-disabling flag is added. Version-switching in a single
worktree can replace the server; separate workspaces in the matrix avoid that.

`tests/starlark/test_repositories.py` and
`tests/sdk_repository/test_sdk_repository.py` now put the main workspace in a
`workspace` subdirectory, beside their output base and output user root. They
retain their real repository evaluation and exact negative diagnostics.
The SDK suite's non-Nix executable fallback was corrected to `.tools/bin/bazel`.

The audit of explicit output roots found one further in-checkout invocation:
the host-version query in `tools/probe_serilog_performance.py` ran from the
caller directory with state under the requested output directory. It now uses
Bazel's default for this batch metadata query. The performance experiment was
not rerun; no performance claim follows from this adjustment.

The remaining explicit roots in graph/configuration/package/test-action,
multilanguage, synthetic-scale and Serilog build probes, benchmark cases,
graph-handoff/package tests and Starlark extension support are outside their
invoked generated workspace. They retain that layout. `BazelSession` lifecycle
behavior is unchanged; its success/failure cleanup tests remain in acceptance.

The build probe checks the exact shell-selected version, falling back to
`.bazelversion` outside a selection. Only the exact release label and the known
Nixpkgs `- (@non-git)` suffix are accepted. Its report records the selected pin,
reported version and executable. RCs, other releases and arbitrary suffixes
remain rejected.

## Comparison with other rules

The inspected TypeScript rules leave the normal output root alone and put
explicit test caches in temporary directories. Scala's nested test helper uses
external `/tmp` output bases and optionally reuses the parent's download cache.
These are source/configuration comparisons, not execution evidence:

- [rules_ts configuration at bfbf401](https://github.com/aspect-build/rules_ts/blob/bfbf40157a65e5bd3a0b708c179bbd7e843d3f33/.bazelrc)
- [rules_scala nested helper at 2634bc3](https://github.com/bazel-contrib/rules_scala/blob/2634bc357e6ccb93571d153c2c5eee43837bc746/test/expect_build_failure/nested_bazel.sh)

The acceptance matrix keeps fresh, independent state rather than adopting
Scala's shared-output-base optimization.

## Reproduction and evidence layout

On macOS ARM64 with Nix installed, from a Git worktree:

```sh
python3 scripts/test-nix-bazel-matrix.py --output /tmp/rules-msbuild-bazel-matrix
```

Use a new output directory outside the checkout. The runner rejects output
inside the checkout: MSBuild discovers ancestor `.editorconfig` files even for
fixtures with their own project directory. The runner snapshots tracked and unignored untracked
files, including pending changes, once; ignored tool downloads and build outputs
are excluded. Each version receives an identical copy without Git metadata.
`source-hashes.json` records the starting file hashes. No per-version lockfile
changes are written back to the developer worktree. Each wrapper workspace has
a fresh output base; native user-level repository/download caches may still be
shared. The boundary probe uses its own initially empty disk cache and separate
output bases. This is not a cold-download or performance benchmark.

```text
matrix-output/
  source-snapshot/
  source-hashes.json
  results.json
  <version>.log
  <version>/
    workspace/
    evidence/
      environment.json
      results.json
      tmp/              # retained repository-test fixtures and diagnostics
      boundary/         # probe workspace, caches, logs and execution records
```

Nix acquires the exact official release binary with its pinned checksum. The
locked SDK remains 10.0.400 for all four entries. Each shell runs independent
gates, retaining failures and continuing:

```sh
python3 scripts/setup-starlark.py
bash scripts/check.sh
bash scripts/bazel.sh query //:repo_setup --noshow_progress
bash scripts/bazel.sh info output_base
python3 -m unittest discover -s tests/bootstrap -v
python3 -m unittest discover -s tests/starlark -v
python3 -m unittest discover -s tests/sdk_repository -v
python3 tools/probe_bazel.py --output <entry-evidence>/boundary
bash scripts/bazel.sh shutdown
```

Gates have 900-second timeouts; an entire entry, including shell acquisition,
has a 5400-second limit. Ordinary wrapper shutdown runs in a `finally` block
and its result is recorded. Probe sessions also log shutdown on success/failure.
The former 9.2-only cache-disable cleanup workaround is removed. No acceptance
command disables repository-content caching or sandboxing.

## Measured results

Run completed on 2026-09-07 local time (2026-09-08 UTC), macOS 26.6.2 ARM64,
with SDK 10.0.400 and the exact official Bazel releases packaged by Nix.
The matrix exited 0. All four entries passed all nine gates with no skips.

| Bazel | Checks/query/info | Bootstrap | Starlark | SDK repository | Build/cache | Shutdown |
| --- | --- | --- | --- | --- | --- | --- |
| 7.7.1 | Pass | 12 passed | 13 passed | 3 passed | Pass | Pass |
| 8.4.2 | Pass | 12 passed | 13 passed | 3 passed | Pass | Pass |
| 8.8.0 | Pass | 12 passed | 13 passed | 3 passed | Pass | Pass |
| 9.2.0 | Pass | 12 passed | 13 passed | 3 passed | Pass | Pass |

Evidence is retained at `/private/tmp/rules-msbuild-bazel-layout-acceptance`.
The complete source hash manifest and each entry's environment/results JSON are
there. All four recorded initial module lock hashes equal
`91391299173df3e40b818a0424a2ca6de9855f8b2d7a779fd5ed8e95382c48b9`.
Final code/config files match the tested source hashes. The developer worktree's
`MODULE.bazel.lock` and `flake.lock` remain unchanged.

All four build probes measured the same action sets:

| Case | Executed projects | Disk-cache hits |
| --- | --- | --- |
| Cold | Shared, App | None |
| Unchanged | None | None |
| App edit | App | None |
| Shared edit | Shared, App | None |
| Outputs removed | None | Shared, App |
| Fresh output base | None | Shared, App |

Every probe recorded `darwin-sandbox`, verified application output, passed the
undeclared-input negative control, and retained two successful session-shutdown
logs. Ordinary wrapper shutdown also succeeded in every entry, including 9.2.0,
without disabling the repository-content cache. The intermediate run also
recorded successful wrapper cleanup after a failed Starlark gate. Bootstrap
coverage verifies probe cleanup on exceptions and rejection of shutdown failures.

The observed normal-wrapper output bases were under
`/private/var/tmp/_bazel_<user>/...` for 7.7.1/8.4.2/8.8.0, and
`~/Library/Caches/bazel/_bazel_<user>/...` for 9.2.0. Test/probe state remained
explicit and outside the workspace it built.

The default Nixpkgs shell separately passed
`bash scripts/check.sh --toolchain-only`. The runner's in-checkout output
rejection was exercised before it created a directory. Changed Python files
parse, and `git diff --check` passes. No additional adapter compatibility failure
was exposed by this focused matrix; that does not qualify untested scenarios.


An initial follow-up attempt used `artifacts/nix-bazel-matrix-layout` inside the
checkout. Its core suite setup failed because the retained temporary fixture
inherited the original checkout's `.editorconfig`, producing `path-escape: input
escapes workspace`. This was a matrix layout error; no adapter behavior was
changed. The runner now requires external output. Those intermediate results
remain in the worktree artifacts and are not the final acceptance evidence.

## Main integration validation

Before publishing, main had advanced to `c17027e` with Spectre and framework
handling changes. These merged cleanly at `857c220`. A focused post-merge run
on Bazel 9.2.0 passed all nine gates: toolchain/setup/query/info, 12 bootstrap
checks, 13 Starlark tests, 3 SDK repository tests, the sandbox/cache probe and
ordinary shutdown. Evidence is at `/private/tmp/rules-msbuild-bazel-postmerge-9`.
The other three versions retain the earlier pre-merge matrix evidence; they
were not rerun on the integrated code. The generated module lock change from
the post-merge run was discarded before publishing.

## Qualification limits

This is focused native macOS ARM64 evidence using official release binaries
packaged by Nix. The default Nixpkgs 8.4.2 shell remains a separate distribution.
The additional named shells are not exposed on Linux. GitHub CI was not
requested or dispatched. Full R17 package/graph scenarios, independent workers,
remote caching and cross-version artifact reuse remain unqualified.
