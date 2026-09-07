# Run .NET tests with Apple container

Use this runbook to build and run the Shared -> App fixture in a disposable
Linux container on an Apple silicon Mac. Start with the MSBuild smoke test;
use the optional Bazel probe to check sandboxed actions and local cache reuse.
Run host commands from the repository root.

## 1. Prepare the host

Requirements:

- An Apple silicon Mac running macOS 26.
- Homebrew for the installation command below.
- Internet access for container images, Ubuntu packages, pinned tools and NuGet.
- At least 2 GB of guest memory for the smoke test; 4 GB for the Bazel probe.

Install Apple container if needed, then start and check its service:

```sh
brew install container
container system start
container system status
```

If startup requests a Linux kernel, accept the recommended kernel. For a
noninteractive installation, run:

```sh
container system kernel set --recommended
container system start
```

The service status should be `running`. Check basic guest execution:

```sh
container run --rm alpine uname -sm
```

Expected output: `Linux aarch64`. The project scripts default to native ARM64
and select architecture-specific downloads at the same .NET/Bazel versions.
To reproduce the Rosetta x86-64 baseline, set `SPIKE_CONTAINER_ARCH=amd64`:

```sh
SPIKE_CONTAINER_ARCH=amd64 bash scripts/test-apple-container.sh
```

This workflow does not run a macOS guest. Nix support remains limited to the
platforms already declared in `flake.nix`; this ARM64 path uses `setup.sh`.

## 2. Run the Shared -> App smoke test

```sh
bash scripts/test-apple-container.sh
```

The script prints the absolute path of its log at startup. A successful run
exits 0 and ends with:

```text
PASS: Shared -> App produced shared-v1/app-v1
```

The build log should also contain `SPIKE_COMPILE:Shared` and
`SPIKE_COMPILE:App`. Any setup, restore, build or output assertion failure
returns a nonzero exit code.

The script:

1. Starts a digest-pinned Ubuntu 22.04 ARM64 guest with 2 CPUs and 2 GB RAM.
2. Mounts the checkout read-only and copies the fixture into the guest.
3. Installs and verifies the repository's checksum-pinned .NET SDK 10.0.100 and
   Bazel 8.4.2 through `scripts/setup.sh`.
4. Restores the fixture, builds Release with MSBuild graph isolation, and runs App.
5. Checks the output and removes the container on exit.

No build runs directly in the source fixture. The smoke test retains default
guest path protections and uses MSBuild for compilation; it does not exercise
Bazel actions or dependency-result replay.

## 3. Inspect logs and rerun

Logs remain under `artifacts/apple-container/smoke.*/run.log`. Use the exact
path printed by the script to inspect a particular run. Each invocation gets
a new log directory, so rerun the same command after correcting a failure.

Tool downloads, NuGet packages and build outputs live inside the disposable
guest and are removed with it. Without a prebuilt image, each run installs them afresh. The Ubuntu image
is cached on the host. Ubuntu package installation uses live package
repositories; the complete guest environment is not reproducibly pinned.

## 4. Optional: run the Bazel sandbox/cache probe

Bazel's nested Linux sandbox needs `--masked-path NONE --read-only-path NONE`
on the validated Apple container version. These relax guest system-path
protections so the helper can mount `/proc`, while retaining Bazel's actual
`linux-sandbox`. Neither flag alone passed. Apple marks these options
[experimental](https://github.com/apple/container/blob/1.3.1/docs/runtime-configuration.md).
The launcher supplies both flags, a read-only source mount, a writable evidence
mount, and `--init` to reap Bazel server processes during shutdown.

```sh
bash scripts/run-apple-container.sh python3 tools/probe_bazel.py --output /evidence
```

Check the command's exit status and `report.json` in the printed evidence
directory. Expected positive cases:

| Case | Projects executed | Disk cache hits |
| --- | --- | --- |
| Cold | Shared, App | None |
| Unchanged | None | None; existing outputs reused |
| App edit | App | None |
| Shared edit | Shared, App | None |
| Outputs cleared | None | Shared, App |
| New Bazel output base | None | Shared, App |

Executed MSBuild actions should report `linux-sandbox`. The negative
`undeclaredInput` case must fail with `FileNotFoundException` naming
`undeclared.txt`; that expected rejection does not make the overall probe fail.
An overall exit status of 0 means all probe assertions completed.

## 5. Run broader scenario suites

To run graph export, generated-graph execution, and the end-to-end suite in one
fresh guest:

```sh
bash scripts/test-apple-container-scenarios.sh
```

To select only particular suites, name them explicitly:

```sh
bash scripts/test-apple-container-scenarios.sh graph graph-execution
bash scripts/test-apple-container-scenarios.sh e2e
```

The guest uses 4 CPUs, 6 GB RAM and both protected-path flags from step 4.
The script excludes host caches, downloaded tools and generated build outputs
when copying the checkout. Setup runs once, then suites run sequentially;
failures in one suite do not prevent later suites from running.

| Suite | Coverage |
| --- | --- |
| `graph` | Diamond edges, configured identities, relocated export, explicit inputs, and rejection of unsupported or escaping paths |
| `graph-execution` | Sandboxed diamond and root-project builds; stale inputs, unsupported configuration, missing dependencies and cycle rejection |
| `e2e` | MSBuild baseline/handoff, relocation controls, public-API replay, runner process contracts, action identity, package inputs/assets, staging and disk-cache recovery |

For an architecture comparison, retain the default 4 CPUs and 6 GB RAM and run
the same suites with `SPIKE_CONTAINER_ARCH=amd64`. Results include the guest
architecture in `summary.json`. Do not mix an architecture change with CPU or
Bazel execution-mode changes when measuring its effect.

The printed `run.*` evidence directory contains `run.log`, one log per
suite, and `summary.json` with counts, durations, failures, errors and explicit
skip reasons. Inspect skips separately from passes: the Nix native runtime
test requires `SPIKE_NATIVE_RUNTIME_TEST=1` and a Nix environment and is not
enabled in this setup-based guest. A suite with no discovered tests fails.
Overall exit status is nonzero if any suite fails. Small logs and reports from
retained failed workspaces are copied under `failures/` before guest removal.

## 6. Reuse the Bazel server and profile no-op builds

Server mode is the default. Probes reuse servers within each output base and
explicitly shut them down before deleting their workspaces. Idle timeout is
120 seconds. For a batch-mode comparison:

```sh
SPIKE_BAZEL_MODE=batch bash scripts/test-apple-container-scenarios.sh e2e
```

Run the benchmark with three no-op samples per mode:

```sh
bash scripts/run-apple-container.sh python3 tools/benchmark_bazel.py --output /evidence
```

Inspect `performance.json`, mode-specific build logs, execution logs and
`.profile.json.gz` traces in the printed evidence directory. Each mode gets a
separate output base and cache, a cold warmup, then three unchanged builds.
The benchmark asserts two MSBuild actions in each warmup and zero in every
no-op. Timings exclude tool installation and server shutdown. Trace durations
can overlap; do not sum nested events.

The measured batch median was 1.792 seconds, versus 0.074 seconds for the
server (about 24 times lower). Cold warmups were 8.84 and 8.35 seconds.
Batch builds spent roughly 0.80–0.88 seconds in analysis/execution;
the last two server no-ops spent about 0.038–0.042 seconds checking file
changes and 0.011–0.014 seconds in `buildTargets`.

To evaluate more CPUs independently, keep memory and mode fixed:

```sh
SPIKE_CONTAINER_CPUS=6 SPIKE_CONTAINER_MEMORY=6G bash scripts/test-apple-container-scenarios.sh
```

The default remains 4 CPUs and 6 GB. A 6-CPU improvement has not been measured.

## 7. Build and use a pinned toolchain image

Build once, then select the exact local image digest for subsequent runs:

```sh
bash scripts/build-apple-container-image.sh
export SPIKE_CONTAINER_IMAGE="$(cat .cache/apple-container/arm64/image.ref)"
bash scripts/test-apple-container.sh
bash scripts/test-apple-container-scenarios.sh
```

The image contains Ubuntu packages and the checksum-verified SDK and Bazel.
Runs copy current source into the guest and check the repository's versions
and archive checksum stamps against the installed toolchain. A mismatch fails
with a rebuild instruction. This avoids repeated apt and tool downloads;
NuGet restore and workspace builds still happen inside each disposable guest.

Rebuild after changing pins or image inputs and reload `SPIKE_CONTAINER_IMAGE`.
Build logs, image metadata and input hashes live in `.cache/apple-container/arm64`.
The builder registers the digest reference in the local image store; nothing
is published to a registry. Ubuntu package repositories are live at image
build time: the resulting digest pins that artifact, but rebuilds are not
guaranteed to produce identical bytes. The ARM64 image path is validated.
Unset `SPIKE_CONTAINER_IMAGE` to return to installation in a fresh Ubuntu guest.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Container service unavailable | Run `container system start`, then check `container system status`. |
| No default kernel configured | Run `container system kernel set --recommended`, then start the service again. |
| Bootstrap rejects the architecture | Use Linux `arm64` or `amd64`; other architectures are rejected rather than receiving an incompatible download. |
| Restore or download failure | Inspect the run log for the failing host or checksum. Resolve connectivity and rerun; a fresh guest has no warm NuGet cache. |
| Bazel says `linux-sandbox` is not registered, or helper reports `mount /proc: Operation not permitted` | Use both protected-path flags in step 4. Do not substitute standalone execution and call it a sandbox pass. |
| Bazel shutdown times out | Use the launcher with `--init`; without a reaping init process, exited server processes caused 60-second shutdown failures. |
| `container copy` rejects a stopped container | Retain logs through the evidence mount before exit. For a retained stopped container, `container export` can recover its filesystem as a tar archive. |

## Cleanup

All procedures use `--rm` to remove the guest on exit. After an interrupted
run, inspect for any remaining container:

```sh
container list -a
```

If this test left a container behind, replace `TEST_CONTAINER_ID` below with
its ID, then stop and delete only that container:

```sh
container stop TEST_CONTAINER_ID
container delete TEST_CONTAINER_ID
```

Retain host logs while diagnosing a failure. Downloaded images remain cached.
When finished using Apple container, stop its service with
`container system stop`.

## Validation and limits

Validated on 2026-09-06, with an M3 Pro, macOS 26.6.2, Apple container 1.3.1,
and repository baseline `6a14e1f`. The smoke script exited 0 and printed the
expected PASS line. The focused Bazel probe passed all six positive cases and
the undeclared-input rejection with both protected-path flags enabled.

Each measured scenario run passed 41 tests, with one explicit Nix-only skip:

| Suite | x86-64 / batch | ARM64 / batch | ARM64 / server |
| --- | --- | --- | --- |
| Graph export (12 passed) | 65.49 s | 14.77 s | 15.63 s |
| Graph execution (15 passed) | 106.64 s | 27.15 s | 27.34 s |
| End-to-end (14 passed, 1 skipped) | 2011.78 s | 290.17 s | 212.90 s |

All used 4 CPUs and 6 GB RAM against baseline `6a14e1f` plus the staged
container changes. These are single-run observations, not a controlled
hardware benchmark. The skipped test is `test_native_runtime_closure`, which
requires `SPIKE_NATIVE_RUNTIME_TEST=1` inside `nix develop`.

Retained evidence directories are `baseline-amd64`, `scenarios.BXxxfD`
(native batch), `scenarios.jmH9Vc` (native server), and `run.MD6PXR`
(no-op benchmark) under `artifacts/apple-container/`. These generated files
are deliberately ignored by Git.

The final prebuilt-image integration run also passed 41 tests with the same
one skip (`run.T96fZG`): graph 17.12 s, graph execution 30.53 s, and end-to-end
228.62 s. The image avoids setup downloads; this run does not establish an
additional improvement in test execution time. Its Shared -> App smoke test
passed (`smoke.b4o4zQ`). Eight bootstrap/server-lifecycle unit tests passed. A deliberately changed
ARM64 SDK archive pin was rejected with the expected rebuild instruction
(`run.OdWhU5`).

Validated local image digest:

```text
msbuild-bazel-toolchain@sha256:758f615972683a582ad312154a7d76225ed31ef17fff575d88a991c0cf5bcb58
```

Keep native Linux CI for x86-64 acceptance; it was not rerun for these changes.
Nix runtime closure, remote caching and cross-platform artifact reuse remain
outside the validated scope.
