# Sequential MSBuild host reuse

`NativeProjectCache --worker-probe` is a sequential process-reuse experiment, not
a production Bazel worker or a sandbox. It consumes one JSON line per request
with `RequestPath` and `WorkingDirectory`, then returns `exitCode` and captured
output. Each request gets a new project collection and build manager; environment,
working directory and console state are restored after execution. Profile counters
are reset per build. MSBuild assemblies/JIT remain loaded across requests.

Eight representative Orchard projects, including the CMS entry, were run in
fresh/worker/worker/fresh batches. All 32 project invocations produced identical
entry/API/runtime output files at matching paths.

| Mode | Batch action seconds | Median |
|---|---|---:|
| Fresh processes | 39.579, 35.020 | 37.300 |
| Reused host | 32.831, 32.646 | 32.738 |

The observed reduction is 12.2%; the warmer fresh batch versus the second worker
batch reduces the difference to 6.8%. These are isolated actions with prebuilt
dependencies and retained filesystem caches, not full-graph Bazel timings.
Compiler child processes remain isolated; this does not yet reuse Roslyn servers.
A failed request followed by a valid request passes and retains output parity.

## Disposition

Retain the prototype; do not enable it in the production macOS workflow.
Bazel 8.4.2's [sandboxed worker implementation](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/worker/SandboxedWorker.java)
uses `linux-sandbox` for hardened workers. A worker execution root alone does not
establish the existing macOS action read/write/network isolation. Linux hardened
worker qualification and a broader failure/mutation matrix are prerequisites for
production integration. Per-project cache keys must remain independent.

Reproduce with `tests/remote_workers/worker_session_probe.py`, supplying the retained
Orchard execroot, a new output directory, the pinned dotnet path and the runner DLL.
Raw evidence: `/private/tmp/worker-session-measure` and
`/private/tmp/worker-recovery-control`. See [timings](worker-session-evidence.json).
