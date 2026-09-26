# Complete Http.Abstractions graph generation

Stage 1 of the [roadmap](roadmap.md) migrates the previously hybrid HTTP
qualification to production `msbuild_sync`. The self-contained combined driver
completed end to end from pinned disposable source checkouts with a fresh output
workspace, including the existing Immutable regression slice.

## Scope and design

The selected graph contains 44 configured assembly producers: 43 `net10.0`
projects and the `netstandard2.0` validation generator. The acquisition fixture
records the selected project/framework pairs and supplies package locks and
reviewed task bindings. Production sync evaluates sources and emits every
compilation declaration. Existing names remain aliases for explicit tool/output
and dependency bindings. Generated `.bzl` files are never patched.

Package acquisition, the GenerateFiles bootstrap action, non-copy task inputs,
project-output wrappers and test hosts remain authored. In particular,
`NativeMethods.txt` is a CsWin32 generator input despite having no copy-to-output
metadata. The SDK host remains necessary for the HTTP test's T4 compilation.

The expanded document contract includes the IIS project. Its native components
are conditional on `UseIisNativeAssets`/`PackNativeAssets`; this Linux managed
slice does not build or claim IIS native components. The mappings identify
upstream baseline-reference bookkeeping, platform attributes and conditional
IIS asset lists explicitly. Unknown item types still fail in production sync.

## Production corrections

- Preserve resource `Language` metadata. HTTP's shared form-mapping resource uses
  `Language="CSharp"` with its reviewed resx generator.
- Preserve evaluated source order. Alphabetizing HTTP.sys's partial-class sources
  produced CA1844 on `RequestStream.Log.cs`; retaining MSBuild's order eliminated
  that discrepancy without suppressing diagnostics. A small synthetic verifies
  that an explicit `Second.cs;First.cs` order survives synchronization.

## Validation workflow

Use the pinned Linux toolchain and clean checkouts at the revisions in
[expanded qualification](project-sync-expanded.md). With sparse checkouts, include
root files and `eng`/`src` (initialize cone mode before selecting directories):

```sh
python3 tests/project_sync/upstream/expanded.py \
  ASPNET_CHECKOUT RUNTIME_CHECKOUT - FRESH_OUTPUT
```

The `-` argument downloads and verifies the pinned VSTest archive, runs the
upstream GenerateFiles bootstrap, and prepares its evaluation inventory. An
existing base qualification directory remains accepted for repeated local work.
Bootstrap archives are staged separately from graph archives so packages with
the same filename cannot overwrite different pinned bytes.

The HTTP preparation uses `RULES_MSBUILD_SYNC_INPUTS_ONLY=1`, which exports
acquisition/binding metadata instead of emitting assembly compilation rules.
The driver evaluates all selected HTTP projects, synchronizes, runs existing
parity/body/contract controls, then runs `http_graph_controls.py` for repeat-sync,
`--check`, producer count, API invalidation, missing-source rejection and repair.

Raw comparison uses the same pinned source, Linux ARM64, SDK 10.0.400,
Release/net10.0 and Bazel 9.2.0. Acquisition, generated-graph qualification and
independent remote-cache recovery are separate claims. The latter remains stage 3.

## Recorded controls

[Compact evidence](project-sync-http-full-evidence.json) records:

- 44 generated HTTP producers; repeated sync is byte-stable and `--check` passes.
- 714 raw/Bazel HTTP outcomes match exactly; warm test results are cached.
- Body edits rerun tests with unchanged public references. A public API edit
  changes the reference and reruns tests; restoration recovers the baseline.
- Missing source and changed custom-document contracts fail; repair restores sync.
- The existing Immutable slice still passes 22,544 normalized outcomes and its
  source-assembly load probe before/after an edit. Its dependencies remain authored
  until stage 2.
- Small application bootstrap, execution, props changes, stale source detection
  and regeneration pass on both Bazel 8.8.0 and 9.2.0.
- Linux owned-code validation passes 5 style, 7 tooling, 35 runner and 33 sync/name
  normalization tests. Toolchain/Starlark checks and `git diff --check` pass.

These are correctness runs. They do not establish new performance numbers,
independent remote-cache recovery, additional platforms or whole-repository builds.
