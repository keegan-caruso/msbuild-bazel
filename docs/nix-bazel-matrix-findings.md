# Nix Bazel version matrix

This is the historical initial run, before the authorized layout and version-guard
changes. Its commands describe the runner at that checkpoint. For the current
runner and subsequent acceptance, see [layout findings](nix-bazel-layout-findings.md).

## Scope and environment

Requested versions: 7.7.1, 8.4.2, 8.8 and 9.2. The latter two select exact
upstream releases 8.8.0 and 9.2.0. This experiment records failures without
changing adapter, Starlark or probe compatibility behavior.

The run on 2026-09-07 (2026-09-08 UTC) starts from `fd455b9`, on native
macOS 26.6.2 ARM64, with the locked Nix
.NET SDK 10.0.400. All four named shells package upstream release executables,
including their bundled JDK, using the SHA-256 pins in
`nix/bazel-versions.json`. Nix verifies the downloads. Release URLs and hashes
were obtained from `https://releases.bazel.build/<version>/release/`.

The default shell retains Nixpkgs' patched/source-built Bazel 8.4.2. It is a
different distribution from the named `bazel-8_4_2` entry. The exact requested
versions were not all present in the existing Nixpkgs inputs: the older input
provided 7.6.0/8.4.2, and the SDK input provided 7.6.0/8.7.0/9.1.1.
The additional release packages are deliberately exposed only on
`aarch64-darwin`. Linux keeps its existing default shell; no Linux matrix,
remote-worker or cross-version cache qualification is claimed.

## Reproduction

With Nix installed, from the repository root:

```sh
python3 scripts/test-nix-bazel-matrix.py --output artifacts/nix-bazel-matrix
```

Use a new output directory for each run. The runner enters each named shell
sequentially, records commands, durations and exit codes, and continues after
failures. It returns nonzero if any shell or gate fails. Each shell runs:

```sh
python3 scripts/setup-starlark.py
bash scripts/check.sh
bash scripts/bazel.sh query //:repo_setup --noshow_progress
python3 -m unittest discover -s tests/starlark -v
python3 tools/probe_bazel.py --output <entry-output>/boundary
```

Each gate has a 900-second timeout. Shell acquisition plus all gates has a
5400-second timeout per version. Wrapper servers are shut down after the gates;
the boundary probe manages its own server. Test workspaces are disposable copies.
The Starlark tests may update the root `MODULE.bazel.lock`; run in a dedicated
worktree and review/discard that generated lock change after testing.

Interactive selection:

```sh
nix develop .#bazel-7_7_1
nix develop .#bazel-8_4_2
nix develop .#bazel-8_8_0
nix develop .#bazel-9_2_0
```

Use `--extra-experimental-features 'nix-command flakes'` if needed; the matrix
runner supplies this explicitly. Nix sets `RULES_MSBUILD_BAZEL_VERSION` alongside
`RULES_MSBUILD_BAZEL`. The check script verifies the selected version while
retaining consistency checks between `.bazelversion` and the baseline JSON pin.
The shell wrapper uses `.cache/bazel/<version>`; probes/tests already allocate
separate output bases. This does not assert cache compatibility across versions.

## Results

| Bazel | Shell acquisition | Checks | Scaffold query | Starlark suite | Build/cache probe |
| --- | --- | --- | --- | --- | --- |
| 7.7.1 | Pass | Pass | Pass | 13 passed | Blocked by 8.4.2-only guard |
| 8.4.2 | Pass | Pass | Pass | 13 passed | Pass |
| 8.8.0 | Pass | Pass | Pass | 13 passed | Blocked by 8.4.2-only guard |
| 9.2.0 | Pass | Fail (exit 2) | Fail (exit 2) | 9 passed, 4 failed | Blocked by 8.4.2-only guard |

Pinned Buildifier acquisition passed in every shell. The matrix process exited
1 as expected because some gates failed. Raw logs and JSON results are retained
under `artifacts/nix-bazel-matrix/<version>/` in the experiment worktree.

The 8.4.2 build probe measured cold execution of Shared and App, no execution
on unchanged rebuild, App-only execution after an App edit, both projects after
a Shared edit, and both outputs recovered from disk cache after output removal
and again with a fresh output base. Execution records identify `darwin-sandbox`.
The undeclared-input negative control passed. This is the package-free explicit
two-project boundary, not broad graph/package qualification.

### Bazel 9.2.0 failure

The wrapper puts its output user root inside the checkout. Bazel 9.2.0 rejects
its automatically chosen repository-content cache there:

```text
ERROR: The repo contents cache [.../.cache/bazel/9.2.0/cache/repos/v1/contents]
is inside the main repo [.../msbuild-nix-bazel-matrix].
```

The four failures in `test_repositories.RepositoryContracts` have the same cause:
these fixtures also place the output user root inside their workspace. They are
`test_installed_sdk_exports_real_tool_files`,
`test_runtime_manifest_schema_and_override_rejections`,
`test_runtime_payload_override_and_manifest_refresh`, and
`test_sdk_redeclaration_refetch_and_invalid_import`. The schema negative control
failed because it saw the cache-location error instead of the intended diagnostic.
All nine `test_core.CoreValidation` tests passed; they use output roots outside
their main workspace. No cache-location workaround was applied to acceptance.

Ordinary wrapper shutdown hit the same 9.2.0 restriction. For cleanup only,
`bash scripts/bazel.sh shutdown --repo_contents_cache=` stopped that server.
The runner now uses this argument only for 9.2.0 shutdown and records cleanup
status; check, query, Starlark and boundary commands remain unchanged. The
recorded acceptance run predates this cleanup-only runner adjustment. No gates
were rerun with the cache disabled.

The Starlark tests updated `MODULE.bazel.lock` during the sequential matrix;
the generated diff was discarded after completion. Each version used its own
wrapper output root and freshly allocated test/probe output bases, but this run
did not reset the root module lock between versions. This is a limitation of
comparison reproducibility, not an isolated dependency-resolution matrix.

## Additional controls and limits

The Linux default shell still evaluates and exports expected version 8.4.2.
This is evaluation evidence only, not a Linux execution test.
The native macOS default Nixpkgs shell also passes
`bash scripts/check.sh --toolchain-only`.
A deliberate mismatch in the 7.7.1 shell, using
`env RULES_MSBUILD_BAZEL_VERSION=9.2.0 bash scripts/check.sh --toolchain-only`,
fails with `Expected bazel 9.2.0, got bazel 7.7.1.`

The existing `tools/probe_bazel.py` explicitly accepts only 8.4.2. A failure at
that guard is a harness limitation before build acceptance, not evidence that
another Bazel version cannot build the adapter. The guard is left unchanged
as requested. No failed compatibility gates are repaired in this change.
GitHub CI was not dispatched. Full R17 release qualification remains open.
