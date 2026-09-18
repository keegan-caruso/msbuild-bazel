# Bazel-owned preparation

## Boundary

The opt-in `scripts/bazel-build.sh --request REQUEST.json` lane places discovery
and native-plan preparation in a declared `MsbuildPrepare` action. Its output is
a tree artifact consumed directly by the native MSBuild build and test rules.
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
The built-in NuGet global cache supplies verified package payloads. Restore paths
and the path-dependent NuGet receipt hash are normalized before Bazel sees them.
Source contents, file membership, restore/package payloads, controller binaries,
policies, host identity, SDK files and native runtime files are declared inputs.
Cold preparation retains the existing qualification and full integrity checks.
Discovery uses exactly the declared runtime root list, without a second Nix
reference-closure query inside the action.

The returned worker identity has `inputOwnership: bazel-owned-preparation-v1`.
Its `controllerSdkClosure` field records controller content and the selected SDK
recipe/runtime root names; SDK content identity belongs to Bazel's action inputs.
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

Source body edits currently invalidate the preparation action as well as the
build action. The native project cache still limits compilation to the changed
project when its reference API is unchanged, but discovery runs again. This can
be slower than the legacy source-refresh path. Separating graph-discovery inputs
from source-content materialization is the next step before switching defaults.
