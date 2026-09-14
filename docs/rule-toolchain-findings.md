# Explicit build SDK input

Projects retain their authored `TargetFramework` and `TargetFrameworks`. Both
`graph_project` and `msbuild_project` accept `sdk_version`, the exact directory
version under the declared `sdk` payload. The default remains `10.0.400`.
The existing `sdk` and `dotnet` labels must describe the same complete installation.

```starlark
# Alongside the rule's project, source, restore and runner inputs:
sdk = "@dotnet//:files",
dotnet = "@dotnet//:sdk/dotnet",
sdk_version = "11.0.100-preview.7.26381.103",
```

Preparation accepts `--sdk-root` and `--sdk-version` (or the equivalent Python
keyword arguments). The selected version must match discovery's toolchain record;
preparation re-evaluates the graph with that installation before publication.
Generated rules carry that exact version. SDK payload files and the request that
contains the version are action inputs, so both participate in Bazel's action key.

The runner invokes `dotnet exec <sdk-root>/sdk/<sdk-version>/MSBuild.dll` and binds
SDK resolution and compiler subprocesses to that installation. Project `global.json`
files remain inputs, but cannot silently select a different execution SDK. Missing
or unsafe SDK directory selections are rejected. Replay payload SDK identity now
comes from evaluated `NETCoreSdkVersion`, and SDK/engine mismatches remain rejected.

Adapter tool target frameworks are separate preparation inputs, described in
[tool input findings](tool-input-findings.md). MSBuild 18.10 tooling requires the
compatible net11 tool framework. The declared installation must include runtimes
needed by the adapter executables and targeting packs needed by the projects.
This change selects the engine included in that SDK layout; it does not download
or assemble independent MSBuild distributions, or qualify every matrix cell.

## Validation

On macOS ARM64:

- `bash scripts/check-dotnet.sh`: passed builds, formatting and five policy tests
  including the final replay SDK-identity follow-up.
- `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release`:
  passed, including exact engine selection and invalid/missing SDK rejection.
- `python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -q`:
  20 passed, including alternate SDK discovery matching and mismatch rejection.
- `bash scripts/bazel.sh test //tests/starlark:core --noshow_progress`: ten passed;
  both rules serialize a nondefault SDK version into the action's declared request.
- `python3 scripts/check-starlark.py`: passed all nine owned Starlark files.
- Default root-project native sandbox build passed at `/tmp/msbuild-rule-default-2`.

The alternate SDK probe initially found inherited `DOTNET_HOST_PATH` selecting
an older compiler host; preparation, probes and actions now bind this explicitly.
A second run exposed an absent net10 targeting pack during isolated execution.
The qualification installation therefore includes the SDK-requested 10.0.10
reference pack as a declared SDK file input, plus runtime 10.0.11 for ActionRunner
and the sample application. General downloaded framework-pack staging is unchanged.

The alternate native sandbox run passed at `/tmp/msbuild-rule-alternate-4`:

```sh
python3 tools/probe_graph_execution.py --root-project \
  --sdk-root /tmp/msbuild-rule-sdk11 \
  --sdk-version 11.0.100-preview.7.26381.103 \
  --tool-target-framework net11.0 \
  --output /tmp/msbuild-rule-alternate-4
```

The project still targets `net10.0`; both ordinary and isolated builds print
`root-project`, and preparation's source workspace is deleted before Bazel runs.
The captured bundle records SDK `11.0.100-preview.7.26381.103`, engine
`18.10.0.38203` (the engine bundled with that SDK), and target `net10.0`.
This establishes the alternate SDK input path, not qualification of MSBuild
18.10.1, all project targets, or multi-project cache reuse under SDK 11.

Final default replay regression passed at `/tmp/msbuild-rule-replay/report.json`
using `python3 tools/probe_replay.py --output /tmp/msbuild-rule-replay`:
same-path and relocated replay, application edit and Publish succeeded; eleven
negative controls rejected mismatched or missing inputs. Final `git diff --check`
and Starlark formatting/lint also passed. No Linux or remote-cache claim is made.

## Recovery and rebase validation, 2026-09-14

Temporary-file cleanup removed the worktree metadata and most source files.
The implementation was reconstructed from this task's recorded file edits and
rebased onto main `6de1a30`. Surviving source files were backed up before recovery;
the surviving findings file matched the reconstructed version exactly.

After rebase, owned .NET build/style checks (including five policy tests), runner
contract tests, 20 preparation tests, two tool-output tests, and all ten Bazel
rule-analysis tests passed (the latter reused valid cached test results).
A fresh native root-project sandbox build also passed at
`/tmp/msbuild-rule-rebased-native/report.json`, with SDK 10.0.400 and the
preparation workspace deleted before execution. Starlark formatting/lint and
`git diff --check` passed. The cleaned-up SDK 11 installation was not reacquired;
its earlier qualification above was not rerun during recovery.

## Integration with preparation reuse

The rebase onto RUL-6 (`c5934ce`) preserves the leased materialization path:
it uses the prebuilt, identity-checked default plugin and skips tool builds and
rediscovery. Fresh preparation retains explicit SDK selection and reported tool
output paths. The private leased entry point rejects explicit toolchain overrides;
qualification of reusable preparations for alternate toolchains remains separate.
Shared tool `.props` files now participate in the preparation controller identity.

Targeted integration validation: 43 preparation-reuse tests, 21 preparation tests
(including override rejection during leased materialization), and two tool-output
tests pass. Starlark formatting/lint and `git diff --check` pass.

Native integration passed all 17 reuse cases, including corruption and interrupted
publication recovery, concurrent-consumer serialization, tool-change invalidation,
and two producer-free native sandbox actions. Evidence:
`/tmp/msbuild-toolchain-reuse-integration/report.json`.

Fresh fallback passed for unsupported authored XML and explicit test requests:
`/tmp/msbuild-toolchain-fallback-integration-4/report.json`. Initial fixture setup
attempts lacked the empty package directory and used inconsistent `/tmp` versus
`/private/tmp` restore paths. Regenerating restore with canonical paths fixed the
probe setup; no product behavior was relaxed.

Commands (inside the pinned Nix environment):

```sh
python3 tools/probe_preparation_reuse.py --output /tmp/msbuild-toolchain-reuse-integration
python3 tests/preparation_reuse/probe_fresh_fallback.py \
  --workspace /private/tmp/msbuild-toolchain-fallback-source \
  --output /private/tmp/msbuild-toolchain-fallback-integration-4
```
