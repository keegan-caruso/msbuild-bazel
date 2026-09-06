# Loading a declared JIT inside the Bazel action

This experiment extends the [runtime integrity controls](native-runtime-integrity-findings.md)
to a library that the build actually loads. It keeps the explicit two-project
graph, SDK 10.0.100, framework 10.0.0, Release configuration and local-cache-only
policy.

## Mechanism

The .NET 10 runtime [loads the JIT from beside CoreCLR](https://github.com/dotnet/runtime/blob/v10.0.0/src/coreclr/vm/codeman.cpp#L1657).
The runner therefore copies the host and Microsoft.NETCore.App runtime into its
action scratch directory, replaces `libclrjit` with a declared payload, and
launches `dotnet exec <original-sdk>/sdk/10.0.100/MSBuild.dll` through that private
host. SDK and pack directories remain
symlinks to declared SDK inputs. External Nix dependencies and host OS libraries
remain absolute-path dependencies. The initial action runner still uses the
original SDK host.

`loader_jit` and `loader_manifest` are optional Bazel rule inputs. The manifest
contains the expected library filename, byte length and SHA-256. Both labels and
a native closure declaration are required together. The runner verifies the
payload before starting MSBuild. `loader-runtime.json` records the private host,
staged JIT path, original JIT path and staged hash in diagnostic outputs.

The harness checks loader records for **both** project builds: the private JIT
must appear, its staged digest must match, and the original JIT path must be
absent. Logs survive scratch cleanup in retained diagnostic files. Fresh
execution uses a different output base and empty disk cache to verify loading
again at a different action path.

## Byte variants and rejection controls

Both valid payloads come from the pinned SDK's JIT. The second macOS payload has
a changed Mach-O UUID and a new ad-hoc signature from the closure's pinned Nix
sigtool; the Linux payload has an appended marker outside ELF load segments.
These change file identity without changing executable instructions or the JIT
interface. This is not a test of a new JIT implementation or SDK version.

The matrix covers original copied bytes, changed valid bytes, unchanged reuse,
disk-cache recovery, and fresh execution. A missing payload declaration and
stale payload hash must fail before compilation. A deliberately invalid native
image with a matching manifest must reach the runtime loader and fail before
compilation, even while the original installed JIT is available. Installed SDK
files are never modified, and the original JIT hash is checked after the controls.

## Run

Inside the pinned Nix development shell:

```sh
python3 tools/probe_bazel.py --native-runtime-probe --output artifacts/loader-runtime-1
SPIKE_NATIVE_RUNTIME_TEST=1 python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -k native_runtime -v
```

The existing Nix CI workflow runs the extended test on Linux. Both setup and
Nix workflows also run the .NET runner contract tests. Set
`SPIKE_NATIVE_EVIDENCE_DIR` to retain the successful native test's top-level
reports and logs; the Nix workflow uploads these as `native-runtime-evidence`.
Absolute log paths in reports identify the original run directories; the
archive retains log files by basename.

## Local implementation findings

The initial private copy kept Nix's read-only file modes, so replacing the JIT
in place failed. The runner now unlinks only its private JIT copy before writing
the replacement. A subsequent build using `dotnet msbuild` succeeded but loaded
the original runtime through SDK discovery. Direct `dotnet exec MSBuild.dll`
invocation loaded the private JIT in both MSBuild and compiler processes.

Focused macOS sandbox retries loaded both valid payloads without the original
JIT appearing in the traces. The invalid-image control reached the loader and
failed with `Failed to load JIT compiler`, before any compilation marker.
These retries are retained under `artifacts/loader-runtime-1`; its original
report records the failed first attempt, not a passing full matrix.

## Scope of the conclusion

This is one enforced runtime-library boundary. It does not make the remaining
SDK, native dependency closure or operating system hermetic. It does not prove
remote-cache correctness, ordinary NuGet binary/runtime assets, cross-platform
artifact reuse, or general input discovery. General graph export must not turn
those unproven properties into implicit promises.
