# First milestone findings

## Evidence

`python3 -m unittest discover -s tests/e2e -v` passed all six scenarios locally using the pinned .NET SDK. The tests were written and run red before the driver was implemented. CI runs the same command after fresh tool installation and Bazel package loading.

- A normal traversal/static-graph build compiles Shared and App and prints `shared-v1/app-v1`.
- Shared can export an MSBuild results cache plus its bin/obj files. After deleting both projects' build outputs, the App build succeeds with App restore metadata and the exported Shared bundle staged back in place.
- The App build log contains `SPIKE_COMPILE:App` and no `SPIKE_COMPILE:Shared`; the output DLL runs independently and produces the expected value.
- An App-only source edit consumes the same Shared bundle and changes observable output to `shared-v1/app-v2`, with no Shared compilation marker.
- Missing listed artifacts and mismatched configuration are rejected.
- A bundle from another absolute workspace path is explicitly rejected. This tests the declared restriction, not whether MSBuild caches can be made relocatable.

## Implementation choices and limits

The runner uses real `-isolateProjects`, `-inputResultsCaches`, and `-outputResultsCache` switches. It does not replace ProjectReference with a DLL reference, disable dependency builds, or infer reuse from elapsed time.

Shared exports a fixed set of MSBuild target results: Build, GetTargetFrameworks, GetTargetPath, GetNativeManifest, GetCopyToOutputDirectoryItems, and GetTargetPathWithTargetPlatformMoniker. This list works for the fixture; it is not a general SDK contract. A graph-aware implementation must derive required target requests and global-property identities.

Exporting all project bin/obj files is deliberately conservative. It proves the handoff but does not establish a minimal artifact set. Restore uses workspace-local NuGet directories and is separate from compilation; downloading Traversal still requires network access during the test preparation phase.

The bundle manifest validates identity and file presence. It is not a content-addressed cache and does not implement input hashing, integrity validation, dependency invalidation, filesystem sandboxing, remote execution, or Bazel action scheduling.

## Next experiment

Define the concrete Bazel e2e harness before writing the Starlark rule. It must assert actual executed actions for cold, unchanged, App-edit and Shared-edit builds, then clear outputs while preserving disk cache. First investigate whether result metadata and artifacts can be rehydrated across differing action paths. Do not advertise portable caching while the runner requires one absolute workspace path.
