# Linux persistent MSBuild and Roslyn worker

`msbuild_compile_project(linux_worker = True)` opts into the sequential JSON
Bazel worker in `NativeProjectCache`. It retains per-project actions and declared
outputs. The default fresh-process path is unchanged. Use the worker execution
strategy; this opt-in currently requires the pinned Ubuntu 22.04 ARM64 image,
.NET 10.0.400 and bubblewrap. The macOS owned-workflow controller is not enabled
for Linux by this change.

## Execution boundary

A trusted C# broker verifies SHA-256 identities from Bazel's WorkRequest, stages
regular copies, and maps only the current request's inputs read-only into a
long-lived bubblewrap child. The child has the pinned SDK/runtime, read-only
Linux loader/user records, writable action outputs and a private compiler IPC
directory. It has no host checkout mount and no host network. The broker remains
outside that sandbox and exports only validated outputs, rejecting links.
Bazel tool declarations include the runner and SDK so tool changes invalidate
the worker key.

The child retains loaded MSBuild assemblies and Roslyn's compiler server. Each
request gets a fresh ProjectCollection and BuildManager, empty action outputs,
and a workspace path derived from the complete request input identities. The
last point avoids reusing compiler metadata at the same path for different
contents with coincidentally equal timestamps/sizes. Environment and current
working directory are restored after every build. Only this isolated child
turns shared compilation on; ordinary actions retain the prior setting.

This supports trusted project tasks, as other persistent compiler workers do.
It is not isolation between mutually hostile in-process MSBuild tasks: arbitrary
managed tasks can retain state in the worker process. No multiplexing or worker
cancellation is advertised. A timed-out child is killed and the worker exits.
The worker's private staging directory is outside the execroot because Bazel
cleans unrecognized execroot entries between separate build commands.

## Qualification

Run in the pinned native Linux Apple container:

```sh
RULES_MSBUILD_CONTAINER_IMAGE=rules_msbuild-toolchain:arm64 \
  bash scripts/run-apple-container.sh \
  python3 tests/remote_workers/linux_compiler_worker.py /evidence
```

The fixture uses a real SDK library, captured offline restore metadata and sealed
project outputs. It checks byte equality of every bundle/API/runtime file,
failed compilation followed by a valid request, same-size/same-mtime source
changes, mismatched input digests, denied absolute undeclared reads, denied input
writes and denied host loopback connections (with a positive outside control).
Two separate actual Bazel builds must reuse the same compiler worker process.
Compiler diagnostics must report server-served compilation.

These small-project results are a worker startup measurement, not a new Orchard
end-to-end result. Package-heavy and large graph timing must be reported
separately. Independent Razor builds retain the previously documented path
normalization limitation; this change does not establish Razor byte equality.
