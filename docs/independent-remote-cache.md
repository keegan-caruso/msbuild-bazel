# Real-service independent-worker acceptance

Related: #42 / RUL-61, after [worker identity](compatible-workers.md).

## Service and transport

The acceptance harness pins [bazel-remote 2.6.2](https://github.com/buchgr/bazel-remote/releases/tag/v2.6.2),
including its Darwin ARM64 release SHA-256, in
`tests/remote_workers/bazel-remote.json`. The native broker uses the service's
[HTTP CAS protocol](https://github.com/buchgr/bazel-remote#http11-rest-api):
GET/HEAD/PUT `/native/cas/<sha256>`. These are real stored objects and service
access/metrics records, not a simulated cache. This qualifies the inner native
project/preparation broker, not Bazel Action Cache hits or remote execution.

`report.remote.transport` records GET/HEAD/PUT attempts, successful GET payload
bytes, attempted PUT payload bytes, transport/server failures and summed request
durations. Headers, TLS framing and retransmissions are excluded; concurrent
request time can exceed elapsed wall time. Service logs/metrics independently
retain hit evidence. Redirects remain disabled and CAS digests are checked.

## Worker setup

Provision two native macOS ARM64 workers matching the explicit compatibility
record. Use the exact pinned Nix closure and identical prebuilt controller/runner
artifacts. Give each worker an independent controller checkout, CLI home, restored
source, state and Bazel output roots. Do not copy producer build/cache directories
to the consumer. Use matching directory depth for the current discovery policy.

Restore uses the source-owned NuGet configuration explicitly. The qualification
fixtures pass `RestoreConfigFile=<source>/NuGet.Config` (or `NuGet.config`) and use
separate CLI homes and the normal NuGet global cache. Unconstrained private NuGet
configuration paths legitimately change restore metadata and cause a miss; they
are not erased from production identity.

Run the pinned service on a reachable trusted endpoint. The included local
`CacheService` helper listens on loopback for rehearsal only. Service deployment,
authentication and network access must be provisioned for the actual worker pair.

On worker A, inside the pinned Nix environment:

```sh
python3 tests/remote_workers/worker.py produce --kind diamond \
  --output /private/tmp/wa/diamond --packages /absolute/nuget-cache \
  --endpoint https://cache.example/native
```

The producer compiles, executes the application, publishes its snapshot, shuts
Bazel down, deletes its source/state/Bazel outputs, and writes `handoff.json`.
Copy **only that handoff JSON** to worker B and run:

```sh
python3 tests/remote_workers/worker.py consume --kind diamond \
  --output /private/tmp/wb/diamond --packages /absolute/nuget-cache \
  --endpoint https://cache.example/native --handoff /absolute/handoff.json
```

Repeat with `--kind serilog --checkout <pinned-Serilog-checkout>` on both workers.
The worker helper refuses existing output/state, requires equal worker descriptors,
asserts zero consumer compiles, compares recovered managed artifact hashes and runs
the actual application or approval test. It records a one-way platform UUID digest
separately from compatibility identity. The default consumer rejects the same
machine; `--allow-same-host` labels a rehearsal and never marks independent-machine
acceptance. A differing platform UUID is supporting evidence, not a substitute for
provisioning genuinely separate workers without producer filesystem access.

## Local rehearsal

```sh
python3 tests/remote_workers/rehearse.py \
  --cache-binary /absolute/verified/bazel-remote \
  --packages /absolute/nuget-cache --checkout /absolute/pinned-serilog \
  --output /private/tmp/wr2
```

This exercises the real service, producer deletion, fresh restored consumers,
application/test oracles, and failed-test non-publication. Its report always says
`independentMachines: false`. A second physical host/isolated OS worker is still
required to close #42; a relocated checkout alone does not meet that gate.


Native macOS rehearsal (`/private/tmp/wr2/report.json`) passed the diamond and
Serilog fresh recovery cases with zero compiles, matching managed artifacts and
actual application/approval execution. Successful GET payloads were 182,004 and
4,638,874 bytes respectively. The failed approval control compiled zero and sent
zero PUTs. Both sides used separate source/state/Bazel/home directories; the
producer source and state were deleted. They still used one physical Mac and
shared installed tools/package acquisition cache, so #42 remains open pending the
second worker. Exact client counters, server access logs and metrics are retained.
