# Bazel-owned preparation

## Boundary

The opt-in `scripts/bazel-build.sh --request REQUEST.json` lane places discovery
and native-plan preparation behind declared `MsbuildDiscover` and `MsbuildBindSources`
actions. Structural discovery is independent of compile-only source contents.
Their thin metadata outputs bind direct source/package inputs for build and test.
See [the four-step follow-up](bazel-direct-inputs.md) for current measurements
and the additional opt-in project-action mode.
A preparation cache hit therefore runs no project evaluation, graph preparation,
or custom SDK content scan in the outer controller. Bazel still tracks and
hashes its declared inputs according to its normal cache semantics.

This follows the ownership pattern in rules_go:

- [SDK repository rules](https://github.com/bazel-contrib/rules_go/blob/master/go/private/sdk.bzl)
  support downloaded and wrapped SDKs.
- [SDK file groups](https://github.com/bazel-contrib/rules_go/blob/master/go/private/BUILD.sdk.bazel)
  and [compile actions](https://github.com/bazel-contrib/rules_go/blob/master/go/private/actions/compilepkg.bzl)
  make toolchain files action inputs.

The existing build/test actions already declared SDK files. This change moves the
previously external preparation step behind Bazel's cache lookup and adds the
wrapped SDK's complete Nix runtime reference closure to the declared file group.
It is analogous to wrapping an installed SDK; it does not implement archive
fetching, toolchain resolution, or Go's package-compilation model.

The source checkout and restored metadata are staged without project evaluation.
Bazel repository rules acquire integrity-checked archives from the built-in NuGet
global cache or NuGet's public flat-container endpoint, then extract declared payloads. Restore paths
and the path-dependent NuGet receipt hash are normalized before Bazel sees them.
Source contents, file membership, restore/package payloads, controller binaries,
policies, host identity, SDK files and native runtime files are declared inputs.
Cold preparation retains the existing qualification and full integrity checks.
Discovery uses exactly the declared runtime root list, without a second Nix
reference-closure query inside the action.

The returned worker identity has `inputOwnership: bazel-owned-preparation-v1`.
Its `controllerSdkClosure` field records controller content and the selected SDK
recipe; the SDK repository resolves runtime roots and SDK content identity belongs
to Bazel's action inputs.
It cannot consume a legacy workflow snapshot as an equivalent worker identity.
Candidate project-cache bundles are fetched without requiring an upfront graph;
their seals are verified on download and actual input/toolchain keys are checked
by the native project-cache action.

## Execution and publication

Preparation's trusted staging wrapper uses Bazel's local execution strategy and
launches discovery under the existing restrictive `sandbox-exec` profile. macOS
forbids nesting that profile inside Bazel's own sandbox. The wrapper is cacheable
but is not itself sandboxed. Evaluated project/package behavior remains in the
strict discovery sandbox; build actions use `darwin-sandbox`. Remote execution is
disabled. This does not claim arbitrary project code is safely executable in the
wrapper or that Bazel's macOS sandbox denies every absolute-path read.

Bazel uploads for both preparation and build are staged by the publication gate.
Tests are forced to execute and consume the prepared manifest and sealed runtime
bundle without invoking build or restore. Final source/controller/staged-input
checks and output validation must pass before publication. Uploading producers
automatically prime the complete-seed action variant after successful tests;
priming must compile zero projects and preserve the accepted app and cache.
A priming failure rejects this opt-in invocation and publishes no staged actions.

## Usage

Build the owned tools first with `bash scripts/check-dotnet.sh`. Restore the
checkout explicitly, using the qualified SDK and a NuGet global cache. Then use:

```json
{
  "schemaVersion": 1,
  "repository": "/absolute/rules_msbuild",
  "workspace": "/absolute/restored-checkout",
  "state": "/absolute/owned-state",
  "output": "/absolute/new-result-directory",
  "sdkRoot": "/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet",
  "bazel": "/absolute/bazel-8.4.2",
  "entry": "App/App.csproj",
  "operation": "build",
  "nuget-packages": "/absolute/nuget-global-cache",
  "bazel-remote-cache": "http://127.0.0.1:9092",
  "bazel-remote-upload": true,
  "remote-endpoint": "http://127.0.0.1:9092/native"
}
```

Optional `remote-snapshot` supplies the producer's `publishedSnapshot` digest for
per-project reuse. `bazel-install-cache` and `bazel-repository-cache` share only
Bazel installation/downloads, not project state. For `operation: test`, provide
the existing `tests` declaration with `data` and `expectedTests`. Output must be
new on every request; state can be reused. Legacy state is deliberately rejected.

## Qualification

Run the focused harness in the pinned Nix environment:

```sh
python3 tests/remote_workers/owned_preparation_probe.py \
  --output /absolute/new-evidence \
  --cache-binary /absolute/bazel-remote \
  --packages /absolute/nuget-global-cache \
  --checkout /absolute/serilog \
  --bazel-install-cache /absolute/bazel-install-cache \
  --bazel-repository-cache /absolute/bazel-repository-cache
```

The harness deletes producers before fresh recovery, checks automatic priming,
forces tests, compares unchanged/edited DLL and PDB hashes with raw MSBuild,
exercises added source membership, and checks undeclared-read, failed-test and
live-input-mutation rejection with unchanged server PUT counts.

## Scope

This lane is opt-in; `scripts/build.sh` retains the existing supported workflow.
Qualification is limited to the pinned macOS ARM64 Nix SDK, Release/net10.0,
package-free diamond and Serilog approval-test graph. Restore remains explicit.
Linux support, SDK archive acquisition, physical-machine/WAN qualification and
removing the remaining mutable-input staging costs are separate work. Fresh
Bazel analysis/startup and forced test startup remain on the hit path.

Source body edits reuse structural discovery and bind only current source hashes.
Preparation outputs omit source/package payloads. SDK/tool wrapping and NuGet
archive acquisition belong to Bazel repositories. The default owned lane still
uses the native snapshot/seed protocol; `"project-actions": true` uses per-project
Bazel actions and a separate runtime composition action without native snapshots,
seed copies, or cache priming. It currently adds fresh-worker overhead and remains
opt-in. See [current evidence and usage](bazel-direct-inputs.md).

## Recorded result

Candidate `c59f420` passed all **17 workflow cases** and **five raw-MSBuild
DLL/PDB comparisons**. Both fresh consumers recovered one preparation action
and one build action after producer deletion. Body edits compiled one project.
Added-source membership invalidated preparation. Undeclared reads, failing tests,
and live source changes rejected the invocation with no new server PUTs.
All owned .NET/style and pinned Starlark checks passed (one Linux-only test skipped).
See [compact evidence](bazel-owned-preparation-evidence.json).

| Workload | Cold producer + priming | Fresh remote hit | Warm median (3) | Fresh body edit |
|---|---:|---:|---:|---:|
| diamond | 10.726 s | 3.327 s | 1.131 s | 7.911 s |
| serilog | 19.230 s | 6.136 s | 2.779 s | 13.123 s |

These are direct controller wall times with tools already built and restore
completed. Fresh consumers have new project/Bazel state but share the binary-keyed
Bazel installation, repository downloads and NuGet cache. Warm samples retain the
Bazel server/state. Serilog always runs its approval test. Only warm values are
medians; other columns are individual qualification observations. They do not
establish raw-MSBuild parity, a before/after speedup, or WAN performance.
