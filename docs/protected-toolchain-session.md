# Protected toolchain reuse in a native controller session

## Behavior

`trust-system-nix-store: true` enables an in-memory cache of fully verified
macOS system Nix runtime manifests. The first request hashes content and audits
protection. Final validation and subsequent requests may reuse eligible manifests.
Default requests still hash all content. Linux and non-Nix runtimes use full scans.

Only root-owned directory generations directly inside `/nix/store` qualify.
Parents and entries must satisfy the root ownership, write-permission and no-ACL
policy; the store's root-owned sticky parent is handled explicitly. Symlink chains
and their resolved ancestors must stay within protected store content. Root
replacement/protection changes invalidate reuse. Caller-visible manifests are
clones, so callers cannot modify the cached identity. Ordinary/user-writable trees
always take the full-scan path. Two small standalone Nix import files remain
uncached; a warm qualified run has 34 hits across 17 directory roots and four
full fallback scans totaling 3,244 bytes of those standalone files.

This opt-in policy trusts privileged Nix administration and storage integrity for
the process lifetime. It does not detect privileged in-place edits or storage
corruption within an already trusted generation. Restart after store repairs,
privileged changes or SDK updates. A root path or timestamp alone never authorizes
initial reuse: the protection audit and complete content scan are required first.
No on-disk receipt grants trust, and restarting drops all verified manifests.

Mutable workspace/package/plan/controller checks remain. Failed tests and final
lease violations retain their existing publication gates. The returned artifact
and worker identities do not change when the same content is verified under this
opt-in policy.

## Session interface

```sh
bash scripts/build-session.sh < requests.jsonl > reports.jsonl
```

Each input line is one complete JSON workflow request, using the existing schema
and an explicit `"trust-system-nix-store": true`. Each output line is one JSON
result. Requests run serially; EOF exits. Each invocation needs a new output path,
while source/state paths may be reused. The session does not start a listening
service or write persistent trust metadata. The wrapper builds Preparation before
starting; other owned tools must already be built or bootstrapped by a request.
Specify NuGet packages as in an ordinary workflow request.

The loaded controller directory is snapshotted at startup and checked before each
request. Changed controller files require restart, even if their size and mtime
are restored. A request cannot substitute another repository/controller or SDK
for the one loaded by the session. Invalid requests return an error result and
the session can read the next request; failure never creates a verification bypass.

One-shot `scripts/build.sh --trust-system-nix-store ...` can save the final runtime
scan within that invocation. A session additionally amortizes the entry scan and
controller startup across requests. Existing Bazel state/server reuse is separate
and remains enabled in all steady-state benchmark variants.

## Benchmark protocol

Use the same built binary for default, one-shot trust and warm-session trust.
For each of diamond and Serilog, run three repetitions in alternating mode order
against the same warm Bazel worker and real loopback cache. The producer and first
fresh consumer establish remote recovery; unchanged measured invocations reuse
local Bazel state and force application/approval execution. They are not repeated
remote downloads. Sessions start before fixture setup; session process startup,
fixture restore and tool compilation are outside per-request timings. First-use
content verification is included in the recorded cold producer's identity phase.

Check identical worker identities, exact unchanged producer artifacts, zero
compilations on hits, and one compilation for body edits. Compare edited DLL/PDB
outputs to independent raw builds. Reject a forced Serilog failure and a live
input mutation with zero outer publication, zero inner PUTs and no change in the
real cache server's PUT count. Unit controls cover actual protected Nix reuse,
restart revalidation, returned-manifest isolation, same-size/restored-mtime mutable
changes, loaded-controller mutation and repository/SDK substitution.

## What rules_go suggests

The inspected `rules_go` SDK repository code downloads/extracts using SHA-256,
then exposes SDK file targets. Its compile action declares SDK tools, headers and
standard-library inputs through Bazel dependency sets. See [SDK acquisition](https://github.com/bazel-contrib/rules_go/blob/master/go/private/sdk.bzl),
[SDK targets](https://github.com/bazel-contrib/rules_go/blob/master/go/private/BUILD.sdk.bazel)
and [compile action inputs](https://github.com/bazel-contrib/rules_go/blob/master/go/private/actions/compilepkg.bzl)
(inspected 2026-09-18). This does not imply that Bazel never hashes SDK files.

We already declare SDK files as Bazel inputs for build/test through
`@dotnet//:files`. The architectural gap is the outer controller: discovery runs
before Bazel, and its runtime identity includes the broader native closure. The
inference is to move that discovery/runtime boundary under Bazel and use a pinned
SDK repository, letting normal input tracking replace more outer-controller work.
Simply deleting the existing identity/lease checks would leave discovery uncovered. This session implementation is a bounded
opt-in improvement; avoid expanding it into a separate general build daemon.
Bazel-owned SDK/discovery is the next larger design to explore while retaining
MSBuild's SDK and NuGet behavior.

## Accepted results, 2026-09-18

Candidate `4d025a0` passed 18 measured unchanged invocations, two fresh consumer
checks, two body edits, two cold producer builds and both rejected-publication
controls. Three-repetition unprofiled medians, seconds:

| Mode | Diamond total | Serilog total | Diamond identity + final | Serilog identity + final |
| --- | ---: | ---: | ---: | ---: |
| Default, new controller process | 2.055 | 4.944 | 1.508 | 1.660 |
| One-shot protected trust | 1.543 | 4.378 | 0.981 | 1.120 |
| Warm protected session | 0.680 | 3.338 | 0.245 | 0.349 |

Total reductions versus default are 25%/11% for one-shot trust and 67%/32% for
the session. Session results include both verified-manifest reuse and a warm
controller process; they do not isolate the benefit of hashing removal alone.
These are same-host steady-state comparisons, not fresh remote-worker or WAN
results. Cold producers retained the initial full runtime scans and audit; their
complete timings and counters are in the [evidence](protected-toolchain-session-evidence.json).
The final pass keeps all mutable-input checks and conservative file-root scans.

Owned .NET build/style checks, five style-policy tests, 32 preparation tests and
32 macOS workflow tests passed (one Linux-only test skipped). Shell syntax,
Python harness compilation and diff checks passed. No GitHub CI ran. The benchmark
uses the completed candidate after adding repository/SDK identity guards. An
earlier harness incorrectly expected zero fallback scans; that rejected attempt
is excluded. The corrected expectation preserves both tiny standalone import
files' full verification.
