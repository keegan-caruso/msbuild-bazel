# Run an app on a source-built runtime

Bazel builds an ordinary SDK-style app and runs it on a selected runtime built
from dotnet/runtime source. `bazel run //app:app` exercises JSON, gzip,
asynchronous streams and SHA-256. The app uses the existing `runtime_host`
attribute; it needs no special rule.

The qualification uses Linux ARM64, runtime v10.0.0
(`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400 and Bazel 9.2.0.
The composed framework directory is `10.0.0`; the source build identifies itself
as `.NET 10.0.0-dev`.

## Verified behavior

- All **130 host binaries** match their declared source producers: 121 managed
  framework assemblies, eight native binaries and the qualification probe.
- The app loads **28 source-built components**, including CoreLib, CoreCLR, JIT,
  dotnet, hostfxr, hostpolicy and native compression/cryptography support.
- Direct execution succeeds with only the host, app and OS directories mounted.
  The installed SDK, build checkout and package cache are inaccessible.
- Removing CoreCLR fails with exit code **135**, even when an installed SDK
  runtime is advertised. It does not silently fall back.

Incremental controls retain upstream semantics:

| Edit | Recompiled | Result |
| --- | --- | --- |
| None | Nothing | No executed actions |
| `Console.WriteLine` body | `System.Console` and its `mscorlib` implementation-reference consumer | App behavior changes; `App.dll` and the Console contract remain unchanged |
| App greeting | App only | Every host binary remains unchanged |
| Revert either edit | Affected targets | Original binary hashes restored |

An independent container at a different workspace path, with the producer
stopped, recovered **270 managed actions, five native actions and 120 layouts**
from HTTP cache. Disk caching and consumer uploads were disabled. All **2,834
assembly, native and layout output hashes** matched. Both app launch modes and
the missing-CoreCLR control passed again on the recovered outputs.

See [compact evidence](runtime-application-evidence.json). Recorded incremental
times are single build/verification samples, not a performance benchmark.

## Reproduce

Use a Linux ARM64 environment with the pinned SDK/Bazel tools. Native preparation
also needs clang, CMake, make, Python headers, bubblewrap and development packages
for ICU, unwind, LTTng, NUMA, OpenSSL, zlib and Kerberos. User namespaces must work.
The native preparer captures compiler tools/headers as explicit archives; native
build actions run upstream scripts in a filesystem and network namespace.

From this repository, with a clean checkout of the pinned runtime revision:

```sh
export RULES_MSBUILD_DOTNET_ROOT=/path/to/pinned/dotnet
export RULES_MSBUILD_BAZEL="$PWD/scripts/bazel-launcher.sh"
bash scripts/dotnet.sh build tools/ExplicitBuild/ExplicitBuild.csproj -c Release
python3 tests/explicit_msbuild/runtime/application_prepare.py \
  /path/to/runtime /path/to/new-output
```

Preparation restores and builds upstream prerequisites, evaluates the configured
graph, and emits explicit declarations. Raw build outputs are excluded from the
Bazel workspace. Project references with `PrivateAssets="all"` become
`implementation_deps`. A temporary installed-host inventory selects framework
components; `source_host.py` then removes every installed runtime binary.

In the resulting `workspace` directory:

```sh
"$RULES_MSBUILD_BAZEL" --output_base=/path/to/base run //app:app \
  --jobs=2 --strategy=MSBuildAssembly=worker \
  --worker_max_instances=MSBuildAssembly=1
```

The example's [BUILD file](../examples/source-runtime-app/BUILD.bazel) sets
`runtime_host = "//runtime:app_host"`. That target exposes an `msbuild_layout`
through `msbuild_runtime`, using the source-built `dotnet` entry point.

The scripts beside `application_prepare.py` provide the remaining checks:
`application_verify.py` verifies binary identities and isolation;
`application_incremental.py` exercises edits and restores sources;
`application_cache.py` seeds or recovers an HTTP cache using an empty output base.
Each accepts `--help` and retains reports/logs in the requested output directory.

## Scope

This is a reproducible qualification workflow for a selected runtime, not a
complete redistributable framework or source-built SDK. Build tools, the rules'
launcher and targeting packs still use the bootstrap SDK. Direct execution of
the built app needs only the composed runtime and OS libraries. Other framework
components require additional declared producers and qualification; this does
not establish support for every app, runtime project or platform.
