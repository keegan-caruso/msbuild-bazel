# Linux persistent MSBuild and Roslyn worker

`msbuild_compile_project(linux_worker = True)` opts into the sequential JSON
Bazel worker in `NativeProjectCache`. It retains per-project actions and declared
outputs. The default fresh-process path is unchanged. Use the worker execution
strategy; this opt-in currently requires the pinned Ubuntu 22.04 ARM64 image,
.NET 10.0.400 and bubblewrap. The macOS owned-workflow controller is not enabled
for Linux by this change.

## Execution boundary

A trusted C# broker verifies SHA-256 identities from Bazel's WorkRequest, stages
verified snapshots, and maps only the current request's inputs read-only into a
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

## Cross-action input identities

The broker now retains a private content-addressed store capped at 1 GiB and
100,000 files per worker. It copies and hashes the first occurrence of each
Bazel SHA-256 identity, then hardlinks that verified inode into subsequent
requests' read-only input mounts. Executable and non-executable inputs have
separate entries. LRU eviction is constant-time and removes only the broker's
link; an active request keeps its snapshot. EOF and graceful worker shutdown
remove the private store. Abrupt host/process termination can still require
normal temporary-directory cleanup.

The child receives a broker-generated index for exactly that read-only mount.
Package and dependency validation retains expected-hash/size comparisons but
can use verified identities for these immutable files. Files outside the index,
including mutable action workspaces and outputs, continue to be byte-hashed.
A changed Bazel identity selects new bytes; an unchanged identity selects the
previous verified snapshot, even if the original producer path later changes.
This deliberately relies on Bazel's input identity contract, not timestamps as
proof of immutability. The store itself is never mounted in the compiler child.

Bazel 8.4.2 expands tree artifacts and supplies hex digest text as a protobuf
bytes field (base64 in JSON): see its pinned
[WorkerSpawnRunner](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/worker/WorkerSpawnRunner.java#L261-L288).
Empty/non-SHA-256 identities are rejected in this qualified lane.

## Measured results

[Step 1 evidence](linux-persistent-compiler-step1.json) measured the small real
SDK project at 0.814s fresh versus 0.118s warm with MSBuild/Roslyn reuse: 6.9x.

[Step 2 evidence](linux-worker-input-identities-evidence.json) compares the
same compiler worker with its input store/index disabled and enabled. The
package stress case adds four distinct 64 MiB package payload files to the
prepared input contract. They exercise actual staging, borrowing and validation;
they are synthetic data, not an Orchard workload or NuGet download benchmark.

| 256 MiB declared package payload | Warm action median |
|---|---:|
| Fresh isolated action process | 0.984s |
| Persistent MSBuild/Roslyn, full input copying/hashing | 0.490s |
| Persistent MSBuild/Roslyn plus verified input reuse | 0.127s |

Input reuse saves 74% of warm worker action time in this case (3.9x);
both changes give 7.8x versus fresh isolated actions. These are sequential
single-project action timings, **not a raw MSBuild or full Orchard comparison**.
Bazel's own input digest computation is outside these direct-protocol timings.
The four-request batches exclude their first request from the warm medians.
First-use worker staging still copies/hashes new inputs; its benefit comes as
other actions reuse those identities. On the small package-free project,
0.114s without input reuse versus 0.115s with it shows no meaningful extra gain.

For one unchanged package request, broker staging fell from 0.158s to about
0.002s. Broker verification fell from 256 MiB to zero bytes; child byte hashing
fell from about 512 MiB to roughly 99 KiB. Both still perform output validation.

Additional controls pass: stale package payload expectations, corrupted sealed
API artifacts, dependency API changes (the stale consumer fails), corrected
consumer/fresh-build byte parity, previous-input removal, digest mismatch,
store eviction, executable-mode preservation, and mutable-file validation.
Actual Bazel actions reuse one worker. After worker shutdown and deletion of
the producer output base, a fresh Bazel server recovers the identical output
bundle from the HTTP action cache with a remote cache hit.

Owned tooling builds/style checks, ActionRunner contract tests and 105 Python
checks passed in Linux; three macOS-specific checks were skipped. No GitHub CI
ran. Raw logs for the measured run are under
`artifacts/apple-container/run.2l8ktk`; checked-in evidence contains the results.
The next performance qualification is a large graph on this Linux worker path.

Graceful Bazel shutdown also passed the assertion that no private broker stores
remained before recovery (`artifacts/apple-container/run.j6dshD`).
