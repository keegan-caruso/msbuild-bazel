# Native runtime payload integrity and loader evidence

This extends the Nix reference-closure experiment with content validation,
a copied-library identity control, and loader diagnostics from a separate
sandbox build. It retains the host identity salt and `no-remote` policy.

## Contract and experiment

Preparation writes schema version 2 of `runtime-closure.json`. Every file has a
relative store path, size and SHA-256 digest. Before starting MSBuild, the runner
requires an exact, duplicate-free declaration and verifies every payload.
Older manifests must be regenerated. These checks run after the .NET host has
already started; they cannot validate the runtime before its own loading.

The probe selects an external native library and substitutes a workspace copy
through a Bazel repository label. It first builds with identical bytes, then
flips one byte while preserving size. The stale manifest must reject the copy
before compilation. Updating the expected digest must execute both projects;
an unchanged rebuild must execute neither. The installed Nix file's original
hash is checked again at the end of this control.

This is intentionally a declared-input experiment. The override does not patch
absolute Nix loader paths. A build accepting the changed copy therefore does
**not** demonstrate that it loaded those changed bytes, nor a working library
upgrade. It exposes the distinction between hashing a declaration and forcing
the loader to use it.

`trace_runtime = True` marks a separate action with `SPIKE_TRACE_RUNTIME=1`.
The runner sets `DYLD_PRINT_LIBRARIES=1` and `LD_DEBUG=libs` directly on its
MSBuild child process and redirects loader output into the declared diagnostics
directory (`DYLD_PRINT_TO_FILE` / `LD_DEBUG_OUTPUT`). The harness extracts dyld
loaded-image records on macOS or glibc initialization records on Linux from
those files. Search candidates in glibc diagnostics are not treated as loaded
libraries. The report
lists paths outside the declared Nix file inventory. This is a loader sample,
not a syscall audit: ordinary file reads, child processes that suppress loader
diagnostics, and libraries not exercised by the fixture remain outside it.

## Commands

Inside the pinned Nix development shell:

```sh
python3 tools/probe_bazel.py --native-runtime-probe --output artifacts/native-integrity-3
SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -k native_runtime -v
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
```

## Measured macOS ARM64 result

`artifacts/native-integrity-3/report.json` is a complete passing run with SDK
10.0.100 and native `darwin-sandbox` actions. Its manifest contains 6,009 files
across 19 Nix store paths. Cold, unchanged, App-only edit, Shared edit, cleared
outputs with disk-cache reuse, and a new output base all retain their expected
execution matrix and runnable DLL/apphost outputs.

| Additional case | Observed result |
| --- | --- |
| Missing closure declaration | Rejected before compilation |
| Identical library copy | No compilation; Shared restored from disk cache |
| One-byte change, stale manifest | Payload mismatch rejected before compilation |
| Updated expected hash | Shared and App execute; both app entry points print `shared-v2/app-v2` |
| Unchanged changed-payload build | Neither project executes |
| Loader trace | Both projects execute successfully with separate loader logs |

The copied payload is zlib's `libz.1.3.1.dylib` (106,224 bytes). Its installed
store hash remains unchanged. This library was not among the recorded loaded
paths; the control measures declared-input identity and integrity only.

Each project's trace records 609 distinct loaded paths: eight within the
declared Nix inventory and 601 outside it. The latter comprise 438 `/System`
framework/library paths and 163 `/usr/lib` paths, including
`/usr/lib/libSystem.B.dylib`. Raw logs are retained as
`artifacts/native-integrity-3/native-loader-shared.log` and
`artifacts/native-integrity-3/native-loader-app.log`.

The native-runtime e2e acceptance test passed in 94.392 seconds. The runner
contract tests passed, including same-size corruption, symlink payloads,
duplicate paths, invalid paths and mismatched manifest versions/declarations.
`bash scripts/check.sh`, Python syntax checks and `git diff --check` passed.
The full e2e suite was not rerun for this extension.

## Diagnostic implementation findings

The first trace attempt set loader variables directly on the Bazel action and
produced no loader records. Setting them at the runner's MSBuild child boundary
produced records, but compiler tasks treated inherited stderr diagnostics as
errors. Redirecting loader output to files in the declared diagnostics directory
preserves the normal compilation success checks. No compiler errors are ignored
or downgraded. These failed attempts are retained under
`artifacts/native-integrity-2`; that directory's original report is not a passing
run.

## Remaining boundary

Absolute store and host loader paths remain in use. The next experiment should
force an actual loaded-library substitution or deny an observed host dependency,
then measure behavior under the sandbox. Host OS libraries/frameworks, complete
filesystem-read discovery, remote-cache correctness and ordinary NuGet runtime
assets remain unproven. Linux validation of this extension belongs to the
existing Nix CI workflow; no new Linux result is claimed here.
