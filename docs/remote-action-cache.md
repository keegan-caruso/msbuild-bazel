# Whole-action HTTP cache integration

Current behavior: [automatic producer priming and current runtime seeds](canonical-seeds.md) supersede the manual priming procedure in the historical measurements below.

## What is implemented

The native controller accepts `--bazel-remote-cache URL` for read-only whole-action
reuse and `--bazel-remote-upload` for trusted producers. It requires
`--independent-workers` and qualified discovery, preserving the existing worker,
SDK, controller, source and project identity checks. The endpoint is separate
from the inner preparation/project snapshot endpoint. No remote executor is used.

This is compatible with the bazel-remote container being set up independently.
The integration uses HTTP/HTTPS. gRPC, authentication headers/credential helpers,
container deployment acceptance and actual independent-machine acceptance remain
outside this slice. Embedded URL credentials, queries and fragments are rejected.
No GitHub CI or infrastructure deployment was performed.

## Keys and seed history

Sources, tool bytes, manifest/worker identity, restore inputs and project seeds
remain declared Bazel inputs. Different workspace roots do not change the action
key for the qualified fixture. Different source bytes or seed sets do.

A seed-free producer does not populate the same key as a fully seeded consumer.
The probe records and deletes that producer, then records and deletes one seeded
primer. Every measured hit starts with fresh consumer source/preparation/Bazel
state and uses the explicit original inner snapshot. The primer's cost is not
included in the later hit latency, and is not claimed to disappear. This avoids
pretending that incidental seed history can be excluded from the action key.

A first body edit misses the outer cache and uses the native per-project cache,
compiling one project. Repeated read-only edited consumers remain misses because
that action is not uploaded. After an explicit successful publication, another
consumer of the same source/seed combination can recover the edited action.

## Publication gate

Bazel may normally upload a successful build before a later test or controller
validation fails. The controller therefore gives Bazel a per-invocation random
loopback endpoint. GET/HEAD requests read through to the configured service;
PUTs are bounded and staged locally. CAS upload content is checked against its
digest. The gate publishes only after successful tests, lease validation and
output bundle validation, uploading all content before action metadata.

Read-only is the default. A failed workflow discards staging without remote
publication. Cache publication errors are reported separately from a successful
local build. The gate caps uploads at 256 MiB/object and 2 GiB/invocation, bounds
HTTP requests and does not follow upstream redirects. Test actions retain their
existing no-remote policy and are forced in qualification. Cached diagnostics
belong to the producer; current executed-work counts come from Bazel's execution
log (`buildActions`, `remoteBuildHits`, `compiles`).

## Validation and measurements

The [protocol](remote-action-cache-protocol.md) defines the paired comparison and
negative controls. The timed run at `/private/tmp/ac-qualified`, candidate `7614e90`, passed all
28 workflow cases and all six paired raw-MSBuild comparisons (each checks both
unchanged and body-edited artifacts). Three repetitions per fixture:

| Complete workflow median | Diamond | Serilog |
| --- | ---: | ---: |
| Inner cache only, unchanged | 4.730 s | 8.992 s |
| Outer action hit, unchanged | 4.363 s | 8.171 s |
| Reduction of median elapsed time | 7.8% | 9.1% |
| Outer miss, body edit | 5.485 s | 9.486 s |
| Raw MSBuild, unchanged | 0.603 s | 1.232 s |
| Raw MSBuild, body edit | 1.067 s | 1.372 s |

Every unchanged outer consumer had exactly one remote build hit and zero build
actions/compiles. Inner-only unchanged consumers ran one action and zero compiles.
All six read-only body misses compiled exactly one project. The two edited-action
recovery cases also hit without executing MSBuild. Every successful Serilog test
invocation executed its approval test; no remote test-result reuse was used.
All managed DLL/PDB bytes matched the raw builds.

These are loopback measurements on an interactive host. The third Serilog outer
sample took 11.540 s versus 9.803 s for its inner-only pair; it remains included.
The other two pairs favored the outer cache. The medians establish the observed
cost in this run, not a guaranteed speedup or a realistic WAN-cache estimate.
All cases still miss adapter <= 1.25 * raw + 0.250 s. Full preparation and final
integrity validation remain, and all bundle outputs are still downloaded.

The failed-test and live-lease-mutation cases each staged action objects and
executed one compile, but published zero action-cache objects and zero inner
objects. The real server's PUT counter was unchanged across each rejected run;
no committed project cache or pending staging directory remained.

After this timed run, `d66b2fa` broadened timeout handling from
`TaskCanceledException` to its `OperationCanceledException` base and added a
partial-publication regression. This changes only the error path; the timed
numbers above identify the earlier binary explicitly. The separate final-binary
run at `/private/tmp/ac-final` passed all 16 cases: both producer/primer sequences,
fresh unchanged outer hits and inner-only controls, body-edit misses and edited
hits, raw artifact parity, forced approval tests and both publication-rejection
controls. This single-repetition confirmation is not pooled with the earlier
three-repetition timing data. The final unit suite passed all 27 workflow tests
and the Preparation formatter check passed after the timeout change.

[Compact qualification and timing evidence](remote-action-cache-evidence.json)
retains both revisions, complete case outcomes, action keys, transfer counters,
raw comparisons, source report hashes and harness hashes.

Local validation includes full .NET style/build checks, five style-policy tests,
32 preparation tests and 27 workflow tests. New gate tests cover write deferral,
CAS-before-AC publication, discarded staging, read-only writes, malformed paths,
wrong CAS digests, partial-upload publication rejection, HTTP read-through and endpoint validation. The first test
bridge build needed a nullable annotation fix; the initial mock-service tests
needed its required `/bazel` URL prefix. Both were corrected before qualification.
Repository/toolchain/Starlark checks passed.

The initial diamond-only smoke probe at `/private/tmp/ac-smoke` demonstrated the
protocol before the full qualification; it is excluded from the final timing
comparison. Production uses .NET; Python remains test harness only.

## Usage

Append these options to the usual `scripts/build.sh` arguments:

```sh
--independent-workers --bazel-remote-cache http://127.0.0.1:9090
```

For a trusted producer, additionally pass `--bazel-remote-upload`. Continue to
provide the existing `--remote-endpoint` and explicit `--remote-snapshot` when
reusing preparation/project seeds. Keep `--force-tests` while qualifying a cache.
The server can be supplied later without changing the implementation.

## Hosting status

The native executable is sufficient: its AC/CAS protocol is the same one exposed
by the container image. Qualification starts and stops isolated native servers;
these are not an always-on service. Apple container 1.4.1 became available during
this task, and the pinned image was pulled, but no container was created or
started after the user chose to continue with the native server. There is no
container startup/persistence acceptance claim. An always-on native instance
can be selected through the same endpoint option without another implementation
change.
