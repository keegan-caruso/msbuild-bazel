# R01 Starlark baseline validation

This change implements the added `starlark_core` gate on top of source checkpoint
`bdbc060`. The original scope is the explicit Shared/App rules and package-free configured
diamond on native macOS ARM64, Bazel 8.4.2 and .NET SDK 10.0.100. Package,
configuration and test-rule extensions remain separately owned gates. The later Linux ARM64 container integration is recorded below; Linux x86-64 CI
remains deferred.

## Implemented contracts

- **S01:** Buildifier 8.2.1 is checksum-pinned for macOS ARM64, Linux x86-64 and Linux ARM64 in
  `scripts/starlark-tools.json`. `python3 scripts/setup-starlark.py` verifies the
  installed binary or atomically installs a verified download. `scripts/check.sh`
  invokes the read-only formatting/lint gate. The warning policy is the pinned
  release's default warning set, with only two local provider-name compatibility
  suppressions. Malformed formatting and an unused load both fail without rewriting
  the file. Tracked/unignored source candidates and explicitly supplied generated
  workspace root files are checked; dependency downloads and Bazel output trees
  are excluded.
- **S02:** No substantial pure Starlark helper was added. Action registration is
  tested through S03. The Python declaration renderer is covered by actual
  generated-workspace loading and Buildifier, including typed values and escaping.
- **S03:** Skylib 1.8.2 is a pinned development dependency with a checked-in module
  lock. Ten analysis tests inspect the explicit rules and every diamond node plus
  an unrelated project. They require one compile action, declared SDK/executable,
  runner/support, request, restore, host and policy inputs; separate bundle and
  diagnostics outputs; exact environment; and the public bundle providers.
  Dependency diagnostics and unrelated compiler sources must not enter consumers.
  Bad environment keys and missing providers fail with expected diagnostics.
  Actual `aquery` checks require `block-network` and `no-remote` on every build
  action; analysis tests alone cannot expose all execution-policy fields.
- **S04:** A real restore/export/prepare pipeline emits a diamond containing a source
  filename with spaces and quotes. Bazel loads it and `cquery` verifies direct
  edges against an independent fixture expectation. `aquery` verifies four actions
  and transitive replay bundles: App has direct Left/Right edges and consumes
  Left/Right/Shared bundles. Reordering already validated nodes, dependencies and
  inputs produces identical BUILD bytes; the discovery freshness guard remains
  unchanged. Colon, backslash, CR and LF in project paths fail explicitly before
  plan publication. The explicit generator is checked after its native probe.
- **S05:** Real repository evaluation checks the installed Nix SDK's tool exports,
  exact empty-SDK and invalid-import failures, changed SDK declarations in reused
  and fresh output bases, unsupported runtime manifest schemas, overrides absent
  from manifests, valid replacement payloads, changed replacement bytes and changed
  manifest membership without stale repository files. Synthetic text payloads
  isolate repository semantics; they are never executed as native libraries.

The generators now emit consistently formatted declarations through a shared
Python renderer. Buildifier is not a preparation or action dependency. Explicit
source lists and graph dependency labels have deterministic order. The package
negative control now replaces the whole package-list assignment so multiline
formatting cannot turn a missing-input experiment into a Starlark parse failure.
No MSBuild compilation/replay or action execution policy was changed.

## Commands and evidence

Use the repository wrappers inside the pinned Nix environment. Acquire Buildifier
once before the checks. The two binary checksums match the asset digests published
in the [Buildifier 8.2.1 release](https://github.com/bazel-contrib/buildtools/releases/tag/v8.2.1).
Skylib assertions use its [analysis-test API](https://github.com/bazelbuild/bazel-skylib/blob/1.8.2/lib/unittest.bzl):

```sh
python3 scripts/setup-starlark.py
bash scripts/check.sh
python3 -m unittest discover -s tests/starlark -v
python3 -m unittest discover -s tests/sdk_repository -v
python3 -m unittest discover -s tests/starlark_native -v
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
python3 -m unittest discover -s tests/graph_cache -v
python3 -m unittest discover -s tests/graph_handoff -v
```

The ten Skylib tests can also be run independently:

```sh
bash scripts/bazel.sh test //tests/starlark:core --test_output=errors
```

The new `.github/workflows/starlark.yml` uses the documented
[macos-15 ARM64 runner label](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) and wires the baseline checks and native
behavioral controls to a macOS runner, with retained logs. The workflow is configured;
a passing hosted run is not claimed by a local result. Existing Linux setup/Nix
workflows acquire Buildifier before their scaffold check when those workflows run.

Local acceptance uses the installed Nix SDK `/nix/store/mfpfzwpi79ac7yvm50lnq235vzy7knw6-dotnet-sdk-10.0.100/share/dotnet`,
Bazel `/nix/store/9mzvqbfsvcg98n64jrvfjqrdkkr9s530-bazel-8.4.2/bin/bazel`, and
Nix Python 3.13.9. Set `RULES_MSBUILD_DOTNET_ROOT` and `RULES_MSBUILD_BAZEL` to those paths when
replaying outside `nix develop`; use the Nix Python interpreter. Native probes
ran outside the agent sandbox so Bazel could register `darwin-sandbox`; the
initial nested-sandbox failure was a tooling restriction, not passing evidence.

| Check | Observed result | Retained evidence |
| --- | --- | --- |
| Buildifier acquisition and repeat verification; scaffold, formatting/lint | Passed; eight owned Starlark files | `scripts/check.sh` and verified release asset hashes |
| `tests/starlark` | 11 tests passed, including ten real Skylib analysis tests | `/private/tmp/starlark-final-regressions/core.log`; generated workspace and query logs at `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/starlark-core-ec4rrxqy` |
| `tests/sdk_repository` | Three tests passed, including the real pinned Nix import | `/private/tmp/starlark-final-regressions/sdk.log` |
| `tests/starlark_native` | One native explicit generator/build/cache test passed | `/private/tmp/starlark-explicit-final.log`; report at `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/starlark-explicit-zvpif_p6/probe/report.json` |
| `tests/graph_execution` | 34 passed, one optional Serilog signing-fixture test skipped | `/private/tmp/starlark-final-regressions/graph-execution.log` |
| `tests/graph_cache` | Nine tests passed, including producer-free relocated recovery | `/private/tmp/starlark-graph-cache.log`; report at `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-fhoadrdd/probe/report.json` |
| `tests/graph_handoff` | 12 tests passed, including forced replay and discovery/publication controls | `/private/tmp/starlark-final-regressions/handoff.log`; detailed reports under `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/graph-handoff-1fhzqucu` |
| Explicit build-package regression | One test passed, including missing/corrupt/stale package controls with multiline BUILD declarations | `/private/tmp/starlark-final-regressions/build-package.log` |
| Explicit binary-package regression | One test passed on a fresh-workspace retry, including direct/transitive upgrades and rejection controls | `/private/tmp/starlark-binary-retry.log`; report at `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-e2e-binary-1wkxydph/probe/report.json` |
| Test-data preparation regression | Three tests passed | `python3 -m unittest discover -s tests/test_action -p test_preparation.py -v` |

The skipped case requires an acquired pinned Serilog signing key; it does not
qualify the separate signing extension. Test durations are validation runtimes,
not comparative performance measurements. The first binary-package regression timed out after 300 seconds in the direct
package-upgrade Bazel invocation, after initial build/edit/cache cases completed.
Its failure is retained in `/private/tmp/starlark-final-regressions/binary-package.log`;
the fresh-workspace retry passed in 71.4 seconds without a source change.
The first timeout remains a recorded unsuccessful attempt; its cause was not
established. The retry supplies the binary-package regression evidence.

## Boundaries

Analysis and repository checks do not establish runtime file-read closure,
remote execution/cache correctness or arbitrary project-name support. The native
runtime payload/loader/JIT experiment retains its earlier independent evidence;
text-payload repository controls do not extend it. Generated package/configuration/
test-rule assertions belong to `starlark_packages`, `starlark_configured` and
`starlark_tests`. Other Bazel versions and platforms require their own runs.

## Integration with main and Linux ARM64

On 2026-09-07 the worktree was fast-forwarded to main `1247e3d`, including the
Apple container launcher, architecture-specific tool acquisition and Bazel
server lifecycle changes. All Starlark edits reapplied without conflicts. A
backup stash preserves the pre-integration work. These results are separate from
the earlier macOS evidence above.

Buildifier now has the release-verified Linux ARM64 binary pin. Source validation
handles the guest's checkout without Git metadata while excluding tools, caches,
outputs and directory symlinks. A regression deliberately places malformed
Starlark in excluded directories and confirms malformed owned sources still fail.
The container launcher acquires the validation tool before checking source when
using a prebuilt SDK image. Minimal image-build and MSBuild smoke contexts select
an explicit toolchain-only check; ordinary checkout validation remains strict.

The existing scenario runner now exposes `starlark`, `starlark-native`,
`sdk-repository`, `graph-cache`, `graph-handoff` and `bootstrap` alongside its
original suites. No protected-path flags were removed, and native tests still
require actual `linux-sandbox`; standalone execution is not substituted.

```sh
RULES_MSBUILD_CONTAINER_IMAGE=msbuild-bazel-toolchain@sha256:758f615972683a582ad312154a7d76225ed31ef17fff575d88a991c0cf5bcb58 \
  bash scripts/test-apple-container-scenarios.sh bootstrap starlark sdk-repository \
  starlark-native graph-execution graph-cache graph-handoff e2e
```

The selected guest has 4 CPUs and 6 GB RAM, Linux 6.18.35/aarch64 with glibc 2.35,
SDK 10.0.100, Bazel 8.4.2 and server mode for probes that use the shared session
helper. Analysis tests continue to use their explicit batch invocations. The
read-only checkout is copied into the guest; sources are not built on the host.
Evidence is retained under `artifacts/apple-container/run.CfJCuN/` in this worktree.
All eight suites completed without failures: 91 tests passed and four were
skipped, with ten additional Skylib analysis tests nested in the Starlark suite.

| Suite | Passed | Skipped | Seconds |
| --- | ---: | ---: | ---: |
| Bootstrap | 8 | 0 | 0.02 |
| Starlark | 12 | 0 | 54.76 |
| SDK repository | 2 | 1 | 10.27 |
| Explicit native Starlark | 1 | 0 | 23.99 |
| Graph execution | 33 | 2 | 47.63 |
| Graph cache | 9 | 0 | 150.94 |
| Graph handoff/discovery | 12 | 0 | 147.95 |
| End to end | 14 | 1 | 207.94 |

The four skips are the Nix SDK repository import, the Nix import
filegroup test, the acquired Serilog signing-key fixture and the opt-in Nix
native-runtime closure test. They are not passes.
The Starlark suite includes its ten Skylib analysis tests. Actual native actions,
cache recovery and forced replay are asserted by the separate native suites;
passing analysis alone is not used to claim `linux-sandbox` acceptance.

The updated toolchain image recipe also built successfully, verifying all archive
pins and the explicit toolchain-only check. Its local digest is
`msbuild-bazel-toolchain@sha256:93209b1af7de53ba86ed3b5787f5047983d69d8c7a7f3774c9ce64f0a1025e5a`;
recipe input hashes, build log and image reference are in
`.cache/apple-container/arm64/`. Nothing was published to a registry. The cached
older image's smoke test passed at `artifacts/apple-container/smoke.9vDI6D/run.log`.

The rebuilt image smoke also passed at `artifacts/apple-container/smoke.8h2udp/run.log`,
with both compile markers and the expected `shared-v1/app-v1` output.

Review follow-up: failure collection now includes `starlark-*` temporary
directories. A focused host-side `python3 -` probe invoked the production suite
runner with a deliberately failing unittest and temporary `starlark-core-`,
`starlark-repository-` and `starlark-explicit-` directories. It verified a failed
summary and exit status, retained `.log` and `report.json` files for all three
prefixes, and exclusion of binaries and Bazel caches. This checks collection
behavior; the Linux suites were not rerun for this prefix-only fix.
