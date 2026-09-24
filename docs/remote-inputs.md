# Remote generation and package inputs

These bounded controls use SDK 10.0.400 and an SDK-free Ubuntu 22.04 ARM64
Buildbarn worker. Local fallback is disabled. They extend the
[remote graph qualification](remote-execution.md); they do not qualify a complete
Avalonia build, cross-compilation, or other worker platforms.

## Standalone source generation

`tests/explicit_msbuild/remote_generation.py` compiles a declared MSBuild task,
executes `msbuild_generate` remotely, and compiles/tests its generated source.
Both Bazel 8.8 and 9.2 pass these controls:

- Input changes rerun generation and downstream compilation/tests.
- Tool changes rebuild the tool, generation and consumer.
- Consumer-only edits leave generation cached; no-op builds execute nothing.
- Omitting the declared generator input fails the remote action.
- Restoring inputs recovers the successful action.

An independent Bazel 9.2 consumer at different paths recovers generation,
compilation and tests from remote cache and verifies the generated-source hash.

## Binary and RID-specific packages

`tests/explicit_msbuild/remote_package_assets.py` creates an explicit synthetic
NuGet archive on the client. The archive supplies a reference DLL, distinct
fallback and Linux ARM64 managed implementations, and an ARM64 native library
called through P/Invoke. Linux x64 entries are deliberately invalid sentinels.
No compiler or package source is required on the executor.

Bazel 8.8 and 9.2 pass remote extraction, compilation and execution. Changing the
native library invalidates compilation/tests; removing it fails with
`DllNotFoundException`. Restoration recovers the successful results. An
independent Bazel 9.2 consumer recovers the package and tests from remote cache.
This qualifies the selected ARM64 assets, not the full RID fallback graph.

This exposed a one-shot compilation bug: runtime package export resolved the
request's relative package directory from the compiler workspace. Export now
uses the declared package location in that workspace to derive the asset's
relative path. The existing rejection of paths outside the package remains.

## Avalonia generation slice

`tests/explicit_msbuild/remote_avalonia_idl.py` downloads five hash-checked IDLs
from Avalonia commit `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`: Native, Win32 COM,
WinRT, DirectX and DComposition. MicroCom.CodeGenerator.MSBuild 0.11.0 is acquired
with a pinned archive hash.

All five generate remotely on Bazel 8.8 and 9.2 and match raw MSBuild-generated
C# byte-for-byte. An independent Bazel 9.2 consumer recovers the final generated
output and verifies its hash. The Windows IDLs are generator inputs on Linux;
this does not establish Windows compilation or execution support. No claim is
made about the entire Avalonia graph or compilation of these interop assemblies.

## Reproduce

Start the [qualified executor](remote-execution.md#reproduce-with-buildbarn).
Set `RULES_MSBUILD_BAZEL` to the Bazel launcher. For client-side fixture acquisition,
the package test additionally needs `gcc` and `RULES_MSBUILD_DOTNET_ROOT`; the
Avalonia parity test needs that SDK environment variable and network access.

```sh
python3 tests/explicit_msbuild/remote_generation.py /tmp/generation \
  --executor grpc://WORKER_IP:8980
python3 tests/explicit_msbuild/remote_package_assets.py /tmp/assets \
  --executor grpc://WORKER_IP:8980
python3 tests/explicit_msbuild/remote_avalonia_idl.py /tmp/avalonia-idl \
  --executor grpc://WORKER_IP:8980
```

Use new output directories. Each script emits command logs, execution logs and
`report.json`; Avalonia also emits `parity.json`. To check independent recovery,
copy only the completed fixture's `source` directory (excluding `bazel-*`) to a
fresh consumer, then run the same script with a new output directory and
`--recover-workspace /path/to/copied/source`. The script rewrites the local rules
repository override for the consumer; uploads and disk cache stay disabled.

See [compact evidence](remote-inputs-evidence.json). These are correctness checks,
not comparable performance benchmarks.
