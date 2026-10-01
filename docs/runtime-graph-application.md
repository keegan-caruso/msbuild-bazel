# Source-runtime app through the graph cache

This is the graph backend's ordinary-app checkpoint. The earlier
[per-project runtime app](runtime-application.md) remains separate evidence.

## Scope

The pinned runtime v10.0.0 revision is
`60629d14374c56f1cb51819049ad1fa529307f8d`. Linux ARM64 uses SDK 10.0.400,
four MSBuild nodes and declared offline packages. The combined loaded-common and
loaded-platform selection contains **130 projects, 298 configurations and 263
compilations**. Authored older frameworks remain in the graph.

Preparation combines reviewed slices and preserves each root's framework.
`removeRoots` replaces a redundant top-level root as declared by the inventory;
its project remains reachable through dependencies. Conflicting frameworks and
an override that would flatten the selection fail before preparation.

The app host contains **58 managed assemblies and eight native binaries**, all
from declared source producers. They include CoreLib, CoreCLR, RyuJIT, the dotnet
muxer, hostfxr, hostpolicy, System.Native, compression and OpenSSL support.
Composition uses evaluated output selectors and the shared runtime provider,
with framework identity 10.0.0. No installed framework template supplies binaries.
Native actions retain upstream CMake/Ninja behavior, four jobs, explicit version
headers and the archived Ubuntu ARM64 toolchain/sysroot.

## Evidence

Bazel 8.8 and 9.2 pass app startup, JSON serialization, gzip round-trip and SHA-256.
Verification compares every composed binary to its producer, checks hashes of
loaded source components, and executes the app in a namespace with neither the
SDK nor build checkout mounted. Removing CoreCLR fails even when an installed
SDK is advertised. All 66 producer hashes and isolated loaded-component names
match across both Bazel baselines. A fresh raw MSBuild graph from the complete
pinned source has the same 298 configurations/263 compilations and matches all
**2,031 compiled DLL/PDB/resource files** byte for byte. Graph artifact modes
are 0555; raw files are 0644. This is a correctness control, not paired timing.

On Bazel 8.8, a unique Pipelines body edit gets 258 hits/five misses and reruns
the app test while preserving App.dll. Restoration gets 263 hits/zero misses and
restores every host hash. A unique app edit recompiles only the app, deliberately
fails its test and preserves the host; reverting it recovers the original app
snapshot and passes. Unchanged tests are cached. Reverted inputs rerun tests;
older local test results are not assumed to remain cached. CLI guards reject
missing primary slices, duplicate selections and framework-flattening overrides
before staging. Python syntax and diff checks pass; CI was not run.

The first 8.8 build was interrupted when the host disk filled and Linux marked
its filesystem read-only. Completed reports were preserved, retired caches
removed and the owned container restarted. The retry passed; the interrupted run
is excluded. Fixture assertions were corrected to hash the actual test layout,
use unique app edits and allow test execution on restoration. Failed attempts
remain in private reports.

All five additional native products match an independent raw-native build byte
for byte. CoreCLR, JIT, corerun and System.Native already have raw parity in the
[bounded source-host checkpoint](graph-cache-plan.md#graph-backed-source-host-checkpoint).

Construction observations are unscored. This scope has no paired incremental
performance claim yet. The 163-compilation scorecard in the
[graph plan](graph-cache-plan.md) remains the current paired timing baseline.

## Reproduce

Use the pinned source archive, declared 163-package feed, qualified native
acquisition inputs, and new disposable directories. Native acquisition requires
the qualified Ubuntu ARM64 image and pinned package inputs.

```sh
python3 tests/graph_build/upstream/runtime_prepare.py "$source_archive" "$feed" "$prepared" --slice loaded-common --also-slice loaded-platform --prepared-restore
mkdir "$native_workspace"
python3 tests/explicit_msbuild/runtime/native_prepare.py "$source_archive" "$native_workspace" --jobs 4 --ninja
python3 tests/explicit_msbuild/runtime/native_component_prepare.py "$native_workspace/native" "$native_workspace/native_support" support --jobs 4 --ninja
python3 tests/explicit_msbuild/runtime/native_component_prepare.py "$native_workspace/native" "$native_workspace/host" host --jobs 4 --ninja
python3 tests/explicit_msbuild/runtime/native_component_prepare.py "$native_workspace/native" "$native_workspace/crypto" crypto --jobs 4 --ninja
python3 tests/explicit_msbuild/runtime/native_component_prepare.py "$native_workspace/native" "$native_workspace/compression" compression --jobs 4 --ninja
python3 tests/graph_build/upstream/runtime_application.py "$prepared/workspace" "$native_workspace"
```

From the generated workspace, invoke the repository's Bazel wrapper with
`USE_BAZEL_VERSION=9.2.0` or `8.8.0` and a separate output base per version:

```sh
bash "$rules_repo/scripts/bazel-launcher.sh" --output_base="$base" test //:app //:app_test --jobs=1 --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache= --test_output=errors
python3 "$rules_repo/tests/graph_build/upstream/runtime_application_verify.py" "$prepared/workspace" "$report"
```

Verification needs the selected SDK environment only for the negative fallback
control. The successful isolated app execution deliberately does not mount it.
Run the edit control immediately after a successful app/test build, retaining
the warm graph worker:

```sh
python3 "$rules_repo/tests/graph_build/upstream/runtime_application_controls.py" "$prepared/workspace" "$controls" --output-base "$base" --version 8.8.0
```

After restoring original sources and stopping the graph worker, compare against
a fresh full-source raw build:

```sh
python3 "$rules_repo/tests/graph_build/upstream/runtime_full_source.py" "$source_archive" "$prepared/workspace" "$raw_control"
```

Private reports retain producer/loaded hashes and logs; large reports stay out
of Git.

## Limits

This selected framework supports the app smoke test. It is not a complete,
redistributable runtime or qualification of all upstream tests. Execution still
uses the guest OS libraries. Native construction has a declared inner namespace;
the qualification action runs locally, so it does not qualify remote execution.
ARM64 evidence does not cover x86-64.

Remaining gates: broader edit controls, graph-backed
upstream suites, native source/header/tool mutations, independent runnable-runtime
recovery, fault tests and larger paired timings. Keep graph mode opt-in.
