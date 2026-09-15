# MVP macOS action-path boundary

The initial Build/Test phase run stalled in the compiler during its first
unchanged-case warm-up. A one-second native process sample showed
`Debugger::Startup -> PAL_NotifyRuntimeStarted -> read`, before managed
compilation began. `lsof` showed debugger startup/continue FIFOs truncated to
the same `clr-debug-pipe-103` path. The action scratch path was 240 UTF-8 bytes.

The matching .NET 10.0.11 sources declare a `MAX_PATH` debugger transport
buffer in [pal.h](https://github.com/dotnet/runtime/blob/v10.0.11/src/coreclr/pal/inc/pal.h)
and construct the temporary-directory-prefixed pipe names and startup
handshake in [process.cpp](https://github.com/dotnet/runtime/blob/v10.0.11/src/coreclr/pal/src/thread/process.cpp).
The truncated FIFOs and blocked stack are local runtime evidence, not merely
an inference from source. The stuck compiler was terminated and the failed
run retained; it was not counted as a passing timing sample.

## Change

On macOS, `ActionRunner.Workspace` rejects a scratch path exceeding **208
UTF-8 bytes** before creating the output or diagnostics directories. This
reserves 52 bytes within the runtime's 260-byte buffer for the separator,
`clr-debug-pipe` prefix, process ID, 64-bit disambiguation key, direction suffix
and null terminator. The diagnostic tells the caller to use a shorter Bazel
`--output_base` and output directory. The scratch directory stays inside the
declared output; sandbox isolation and runtime diagnostics are preserved.

The performance harness uses compact sample-directory names; full repetition,
case and system identities remain in its JSON report. A short evidence root
such as `/private/tmp/mb2` also keeps the action paths within the supported
boundary. Longer outer paths remain rejected instead of hanging indefinitely.

## Validation

- Owned .NET build, formatter and warning checks pass, including all five
  policy-enforcement tests in `bash scripts/check-dotnet.sh`.
- `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release`
  passes. New ASCII and multibyte-path cases assert the actionable diagnostic
  and absence of output publication.
- The shorter-path Build/Test benchmark passed all 40 samples with actual
  native sandbox actions and approval tests. Timings and cache-state details
  are in the [calibration findings](local-mvp-calibration-findings.md).

Failed evidence: `/private/tmp/msbuild-mvp-e2e-calibration-1/report.json`.
Compiler stack: `/private/tmp/msbuild-mvp-csc-sample.txt`.
Build/style and runner tests: `/private/tmp/msbuild-mvp-path-tests.log`.

This qualifies an explicit macOS path boundary. It does not claim that every
runtime IPC path, SDK or operating-system version supports arbitrary depth.
