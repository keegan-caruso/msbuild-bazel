# Linux ARM64 cache-worker qualification

The first Linux workflow lane targets Ubuntu 22.04 ARM64 with the checksum-pinned
SDK 10.0.400 installed at `/opt/rules_msbuild-toolchain/.tools/dotnet`, Bazel 8.4.2,
and bubblewrap. It retains qualified discovery, source/input leases and gated
cache publication. Other distributions, architectures, SDK locations and arbitrary
packages remain outside this lane.

## Platform implementation

Discovery uses bubblewrap with a private mount/process/network namespace. It
binds only declared SDK, system libraries, tools, input roots and scratch output;
input mounts are read-only. Builds require Bazel's actual `linux-sandbox` runner.
No standalone or process-wrapper fallback is accepted.

Worker identities have a separate `linux-arm64-worker-v1` policy. They include
OS release, kernel release/build, CPU features, CPU count, Bazel/bubblewrap/shell
bytes, system configuration and the controller/SDK/system-library tree digests.
The same full final input validation remains required before publication. This
is a conservative selected-image contract, not general Linux hermeticity or
cross-platform artifact reuse.

Common Linux SDK imports must exactly match already-reviewed SDK-relative bytes.
Two Linux-specific hashes are added after reviewing differences: bundled runtime
identifiers change from osx-arm64 to linux-arm64; Microsoft.NET.Sdk.targets omits
the Nix-specific extra.targets import. No new executable XML behavior is admitted.

Linux ARM64's O_NOFOLLOW constant differs from x86-64. The file integrity reader
now selects the architecture-specific value; symlink/FIFO/directory rejection
and regular-file hashing are covered by the actual Linux tests.

## Reproduction

```sh
bash scripts/build-apple-container-image.sh
python3 tests/remote_workers/apple_workers.py \
  --image "$(cat .cache/apple-container/arm64/image.ref)" \
  --output /absolute/new-evidence-directory
```

Apple container 1.4.1 omitted nested files in the tested directory build context.
The builder packages the minimal inputs into one archive before transfer. SDK and
Bazel downloads remain SHA-256-verified; each completed image is recorded by its
immutable digest. Ubuntu package acquisition is not a reproducible apt snapshot.

The orchestrator starts a dedicated digest-pinned bazel-remote container and
separate producer/consumer VMs using the same immutable toolchain image. Each
worker copies only source inputs, builds its own controller, restores its own
packages and starts with fresh project/Bazel state. No producer outputs or package
cache are mounted into the consumer. Only the handoff JSON crosses workers.

The producer runs cold and seeded-primer builds for the diamond and Serilog test
graphs. Seed history still affects outer action keys. The producer VM is stopped
and deleted before the consumer is created; the harness checks its absence and
distinct Linux boot IDs. Reports and logs are retained outside the guests, but
producer build state is not exported. The cache VM is the only surviving build
artifact store between workers.

Acceptance requires zero outer-hit build actions/compiles, inner-only recovery,
one compile for a body edit, exact managed DLL/PDB parity with raw MSBuild, actual
Serilog approval-test execution, and zero server PUTs after an intentionally
failed test. Unit controls additionally verify that discovery denies undeclared
reads, writes to inputs, and access to the parent network namespace.

Separate Linux VMs on one Mac establish isolated-worker evidence. They do not
establish physical-machine independence, WAN performance or macOS-to-Linux reuse.

## Accepted run, 2026-09-18

Candidate `90f4e24`, with source archive and image digests recorded in the
[compact evidence](linux-cache-workers-evidence.json), passed all eleven workflow
cases in `/private/tmp/linux-workers-qualified/report.json`:

| Case | Diamond compiles | Serilog compiles | Remote build hits |
| --- | ---: | ---: | ---: |
| Producer cold | 4 | 2 | 0 |
| Producer seeded primer | 0 | 0 | 0 |
| Fresh consumer outer cache | 0 | 0 | 1 each |
| Fresh consumer inner cache only | 0 | 0 | 0 |
| Consumer body edit | 1 | 1 | 0 |
| Failed approval test | — | 1 | 0 |

The consumer was created only after successful producer stop/deletion and an
absence check. Boot ID hashes differ. Both unchanged and edited managed DLL/PDB
sets exactly matched the consumer's independent raw builds. Serilog's actual
approval test ran on recovered outputs. The intentionally failed test staged
action-cache uploads but published zero objects; the real server PUT counter was
unchanged and inner publication sent zero PUTs.

Each Linux worker passed 28 workflow and 32 preparation tests, including the
namespace isolation and ARM64 file-type guards. Host macOS owned .NET build/style,
five style-policy tests, 32 preparation tests, and 27 workflow tests passed
(the additional Linux-only test was explicitly skipped). Repository pins and
Starlark checks passed. No GitHub CI was dispatched.

The temporary producer, consumer and qualification cache containers were deleted.
The persistent native macOS cache remains running. These measurements are
correctness qualification, not a controlled Linux-versus-macOS speed comparison.
