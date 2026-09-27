# Run an app on a source-built runtime

## Goal

Build a pinned dotnet/runtime revision with Bazel and run an ordinary SDK-style
application on the resulting runtime. Preserve upstream MSBuild semantics and
make the runtime an explicit application execution dependency.

The first platform is Linux ARM64, using runtime v10.0.0
(`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400 and Bazel 9.2.0.
The SDK remains a bootstrap compiler and targeting-pack input. Operating-system
libraries remain platform inputs. Neither may substitute installed .NET runtime
binaries into the application's selected host.

## Acceptance

1. Build CoreLib, the required managed libraries, CoreCLR, JIT, dotnet host and
   required native support libraries from declared source/tool inputs.
2. Compose these products with `msbuild_layout` and expose `msbuild_runtime`.
3. `bazel run //app:app` successfully exercises JSON, gzip and cryptography.
4. Compare every host binary with its source producer and verify the actual
   process loads the selected runtime. Include a rejected fallback control.
5. Verify that runtime edits invalidate execution inputs while preserving an
   unchanged app compilation; app edits preserve runtime build results.
6. Recover the outputs in an independent cache consumer and run the app again.

This is a usable selected runtime, not a claim that all dotnet/runtime projects,
platforms or framework components are supported.

## Work in progress

`tests/explicit_msbuild/runtime/application_prepare.py` prepares a standalone
workspace from the pinned checkout. It reuses the qualification inventory and
source-host composition without bringing along the runtime test projects.
Preparation acquires packages and evaluates upstream projects; Bazel owns the
resulting declared managed and native builds. Temporary installed-host metadata
is used for component selection and then removed by `source_host.py`.

The initial preparation attempt incorrectly propagated platform-specific target
frameworks into build-tool restore. Restore now evaluates the outer projects
before the selected framework builds, as in the existing raw runtime benchmark.
The managed prerequisite build and configured inventory now pass. Removing a
redundant CoreLib root preserves the configuration already reached through
upstream references. Generated declarations contain 262 managed nodes and 90
package inputs; the source-only host selects 121 managed and eight native
products, with no runtime test projects. The fresh Bazel build is in progress.
The fresh app workflow has not yet passed acceptance; existing source-host test
results in [runtime-source-host.md](runtime-source-host.md) are separate evidence.

Preparation command, in a provisioned Linux ARM64 environment:

```sh
export RULES_MSBUILD_DOTNET_ROOT=/path/to/pinned/dotnet
python3 tests/explicit_msbuild/runtime/application_prepare.py \
  /path/to/runtime /path/to/new-output
```

The output retains per-stage logs. Its `workspace/app/BUILD.bazel` selects
`//runtime:app_host`, whose entry point is the source-built `dotnet` executable.

Validation so far: Python syntax checks and BUILD formatting pass; the sample
executes successfully on the installed SDK runtime as a smoke control. The fresh
Bazel build was interrupted by host disk exhaustion. Its outputs were discarded,
completed audit containers were reclaimed, and the build restarted with
`--jobs=1`. Source-host application execution, incremental controls and independent
cache recovery remain unverified.
