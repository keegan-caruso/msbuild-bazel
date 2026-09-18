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

The architectural inference for this project is to give Bazel ownership of the
.NET SDK/runtime and discovery actions, letting its normal input tracking handle
more of the work currently performed by the outer controller. Our discovery
currently runs before the Bazel action, so deleting its identity/lease checks now
would leave that boundary uncovered. This session implementation is a bounded
opt-in improvement; avoid expanding it into a separate general build daemon.
Bazel-owned SDK/discovery is the next larger design to explore while retaining
MSBuild's SDK and NuGet behavior.
