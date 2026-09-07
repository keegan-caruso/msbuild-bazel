# First milestone findings

## Evidence

`python3 -m unittest discover -s tests/e2e -v` passed all six scenarios locally using the pinned .NET SDK. The tests were written and run red before the driver was implemented. CI runs the same command after fresh tool installation and Bazel package loading.

- A normal traversal/static-graph build compiles Shared and App and prints `shared-v1/app-v1`.
- Shared can export an MSBuild results cache plus its bin/obj files. After deleting both projects' build outputs, the App build succeeds with App restore metadata and the exported Shared bundle staged back in place.
- The App build log contains `RULES_MSBUILD_COMPILE:App` and no `RULES_MSBUILD_COMPILE:Shared`; the output DLL runs independently and produces the expected value.
- An App-only source edit consumes the same Shared bundle and changes observable output to `shared-v1/app-v2`, with no Shared compilation marker.
- Missing listed artifacts and mismatched configuration are rejected.
- A bundle from another absolute workspace path is explicitly rejected. This tests the declared restriction, not whether MSBuild caches can be made relocatable.

## Implementation choices and limits

The runner uses real `-isolateProjects`, `-inputResultsCaches`, and `-outputResultsCache` switches. It does not replace ProjectReference with a DLL reference, disable dependency builds, or infer reuse from elapsed time.

Shared exports a fixed set of MSBuild target results: Build, GetTargetFrameworks, GetTargetPath, GetNativeManifest, GetCopyToOutputDirectoryItems, and GetTargetPathWithTargetPlatformMoniker. This list works for the fixture; it is not a general SDK contract. A graph-aware implementation must derive required target requests and global-property identities.

Exporting all project bin/obj files is deliberately conservative. It proves the handoff but does not establish a minimal artifact set. Restore uses workspace-local NuGet directories and is separate from compilation; downloading Traversal still requires network access during the test preparation phase.

The bundle manifest validates identity and file presence. It is not a content-addressed cache and does not implement input hashing, integrity validation, dependency invalidation, filesystem sandboxing, remote execution, or Bazel action scheduling.

## Subsequent experiments

The raw-cache path investigation is recorded in [path findings](path-findings.md):
bundle relocation succeeds, but workspace relocation fails MSBuild cache lookup.
The later [public-API replay experiment](replay-findings.md) measured successful
relocation with normalized target-result metadata and separately staged artifacts.
The [Bazel harness](bazel-findings.md) subsequently measured separate sandbox
actions and local disk-cache reuse. These later results do not change this v1
driver's same-workspace restriction. See the [current plan](implementation-plan.md).

## Scaffold check failure handling

`scripts/check.sh` now captures each tool version in a separate assignment so a failed wrapper exits the check before version comparison, and explicitly rejects version mismatches. On the macOS ARM64 review host without repository-installed tools, `bash scripts/check.sh` exited 1 with the setup instruction and no success message. Temporary copied-script probes with substitute wrappers verified matching versions, failures from either wrapper even with matching stdout, and mismatched versions from either tool. `bash -n scripts/check.sh` and `git diff --check` passed. These probes validate shell failure handling only; the pinned Linux toolchain and MSBuild e2e suite were not run on this host.

## Nix development environment

The flake targets Linux x86-64 and macOS ARM64 using Nixpkgs revision `74c7dbb8e8adc9fdd3e734d7fd85f36f5421a2f9`. Inspection of that revision confirmed binary SDK 10.0.100 sources for both platforms and Bazel 8.4.2. Nixpkgs patches the SDK for its runtime environment and additional MSBuild imports, and builds patched Bazel from source. These packages preserve the version baseline but are not byte-identical to the bootstrap downloads. The environment does not change the same-workspace cache restriction.

Local validation on the macOS review host: temporary executable probes passed for release and Nix Bazel version labels, mismatched SDK/Bazel versions, and either tool exiting nonzero despite printing the expected version. Driver and e2e executable selection honored `RULES_MSBUILD_DOTNET_ROOT`, including paths containing spaces, and retained the `.tools` default without it. Python syntax checks, shell syntax checks, and `git diff --check` passed. These probes are not MSBuild acceptance evidence.

After Nix installation, `nix --extra-experimental-features 'nix-command flakes' flake check path:. --all-systems --no-build --no-update-lock-file` passed evaluation for both platform definitions and validated the locked Nixpkgs source. The initial source hash had been computed from the GitHub archive using NAR serialization. On macOS ARM64, `nix --extra-experimental-features 'nix-command flakes' develop path:. --no-update-lock-file -c` successfully ran each of `bash scripts/check.sh`, `bash scripts/bazel.sh query //:repo_setup --noshow_progress`, and `python3 -m unittest discover -s tests/e2e -v`. All six real MSBuild scenarios passed in 21.144 seconds. Linux was evaluated but not executed locally. The added Nix CI workflow runs the tool checks, Bazel query, and e2e suite on Ubuntu only, without updating the lockfile; its results are pending execution.
