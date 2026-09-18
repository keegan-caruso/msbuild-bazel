# Pinned Bazel dependency-cache reuse

The native workflow stages a checked-in Bazel 8.4.2 module lockfile and optionally
reuses verified repository downloads across fresh consumers. Project build
outputs, action caches, analysis and servers remain isolated. The pinned template
is identical for the diamond and Serilog native workspaces; it contains 132
registry-file SHA-256 identities and no machine paths or extension results.

## Measured results

Three-repetition medians in seconds, compared with the previous
[cache-hit overhead candidate](cache-hit-overhead.md). Both new stages use
production candidate `817dcfd` and a reused Bazel installation.

| Workload / case | Previous | Lockfile only | Lock + shared downloads | Reduction from previous |
|---|---:|---:|---:|---:|
| Diamond unchanged | 7.029 | 6.832 | 5.444 | 22.5% |
| Serilog unchanged | 11.199 | 10.988 | 9.445 | 15.7% |
| Diamond body edit | 7.531 | Not measured | 5.884 | 21.9% |
| Serilog body edit | 11.434 | Not measured | 9.844 | 13.9% |

All 18 new raw/adapter comparisons passed exact managed DLL/PDB equality and
actual application/approval-test execution. Unchanged consumers compiled zero
projects, body edits one. Raw MSBuild medians in the final run were 0.580/1.088 s
for unchanged diamond/Serilog and 0.997/1.202 s for body edits. Every comparison
still misses the retained diagnostic target of 1.25 * raw + 0.250 seconds.

The lockfile alone helps modestly; sharing verified downloads supplies most of
the improvement. Module-mapping medians fall from 1.442/1.376 s with isolated
downloads to 0.110/0.114 s with the shared cache. Bazel's complete phase falls
from 3.855/5.705 s to 2.327/4.215 s. Initial/final integrity checking still costs
about 2.67/2.86 s combined; it and the remaining Bazel/action work now dominate.
Individual phase medians overlap or need not sum to the median wall time.

The trace still has 132 events named download per invocation, but their union is
only 21–23 ms on unchanged warm-cache consumers. These events include local
cache reads, so they must not be described as 132 external requests. The shared
repository cache contains 133 objects totaling 169,719 payload bytes; this is
stored payload size, not wire traffic.

The shared repository cache started empty. Producer wall times were 10.917 s
for diamond (including initial repository population) and 13.861 s for Serilog
(with that dependency cache already populated). These are single producer
samples with fresh compilation/preparation, not a repeated cold-build benchmark.
Producer source, server and project state were removed before measured consumers.

[Timing evidence](bazel-repository-cache-evidence.json) retains samples, phase
measurements, compiler counts, producer timings, source-report hashes and harness
provenance. [Profile evidence](bazel-repository-cache-profiles.json) retains the
trace summaries and hashes. Runs were sequential on the same interactive macOS
ARM64 host, so small differences include run-to-run variation; the trace change
supports attribution of the large improvement to dependency reuse. Initial
Restore and tool acquisition remain excluded for both paths. No cold/API timing
matrix or independent-worker acceptance is claimed by this follow-up.

## Behavior and qualification

- `bazel/native.MODULE.bazel.lock` is staged as `MODULE.bazel.lock` on every
  generation, including retained workspaces. Bazel runs with `--lockfile_mode=error`.
  Missing required lock data fails; the build cannot silently update the pin.
- The template belongs to the controller's already-hashed `bazel` tree. Changes
  affect worker/native cache identities and final input validation.
- `--bazel-repository-cache` supplies a separate worker-owned download cache.
  Bazel reads objects by their expected digest; corrupted objects are not accepted.
  A cold online producer can populate this cache. No producer source or build
  state is required by consumers.
- `--bazel-disable-repository-downloads` passes Bazel's repository-rule download
  disable flag. Bazel 8.4.2 can still fetch a registry file on a registry-cache
  miss; this option is not an external-network sandbox. This distinction was
  established by the missing-object controls and is documented in CLI usage.
- Native build/test actions retain the required Darwin sandbox. Remote execution
  remains disabled. NuGet continues to use its ordinary global package cache.

See [workflow options](native-workflow.md#pinned-bazel-dependencies-and-reusable-downloads).
The lockfile is qualified for this pinned Bazel/native MODULE definition; tool or
dependency changes require a reviewed regeneration and acceptance run.

## Correctness controls

[Control evidence](bazel-repository-controls.json) records five passing cases:

1. Producer source/state removed, fresh native recovery with repository-rule
   downloads disabled: zero compiles, exact managed output equality and actual
   application output equality. Action sandboxing remains enabled.
2. Fresh `@platforms//cpu:arm64` query succeeds with external networking denied
   and only the warm repository cache. Local sockets/loopback are allowed.
   A separate public curl fetch fails under the same process policy.
3. Missing required registry object fails with external networking denied.
4. Corrupt registry object fails under that same policy; its bytes are not trusted.
5. Removing a required registry hash from the lockfile fails in error mode even
   with a warm cache. Every query leaves its input lockfile unchanged.

The two network-negative cache tests allow Bazel to attempt fallback fetching;
external process policy blocks it. They establish rejection, not that the
repository-rule download flag covers registry lookups.

Preflight corrected the control design: an outer macOS sandbox prevents nested
Darwin action-sandbox creation, so external-network blocking is applied to the
query controls, not the full native build. `mod graph` fetches unrelated extension
repositories; the accepted query exercises the platforms dependency actually
used by the native build. Lowering the direct platforms request to 0.0.10 was
still compatible because resolution selected 0.0.11, so the invalid-lock control
instead removes a hash required by that selected version. Failed preflight runs
are excluded from acceptance and timing evidence.

## Reproduction

Use the pinned Nix environment, SDK, Serilog checkout and real bazel-remote from
the [measurement protocol](bazel-repository-cache-protocol.md). The shared Bazel
installation must be separate from the repository-download cache.

```sh
# Isolate the lockfile improvement, with fresh repository downloads.
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" --output "$LOCK_RESULTS" \
  --repetitions 3 --cases unchanged --bazel-install-cache "$INSTALL_CACHE" \
  --protocol docs/bazel-repository-cache-protocol.md

# Add shared downloads. Start REPOSITORY_CACHE empty; producer fills it.
python3 tests/remote_workers/measure.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" --output "$CACHE_RESULTS" \
  --repetitions 3 --cases unchanged body --bazel-install-cache "$INSTALL_CACHE" \
  --bazel-repository-cache "$REPOSITORY_CACHE" \
  --protocol docs/bazel-repository-cache-protocol.md

python3 tests/remote_workers/repository_controls.py --cache-binary "$CACHE_BINARY" \
  --packages "$PACKAGES" --checkout "$SERILOG_CHECKOUT" \
  --output "$CONTROL_RESULTS" --install-cache "$INSTALL_CACHE"
```

The control runner uses a process-scoped macOS network policy, explicit local
socket permissions and reserved-address host mapping for the negative queries;
it does not change machine networking. No global caches are corrupted: negative
cases use private copies. Retained evidence is same-host, not independent-worker
qualification.

Bazel's [lockfile documentation](https://bazel.build/external/lockfile) describes
error mode and registry hashes. [JSON traces](https://bazel.build/advanced/performance/json-trace-profile)
provide the profiling fields used here; a span named download may be a local
cache read and is not an HTTP request count.

## Final validation

`scripts/check-dotnet.sh` passed owned .NET build/warnings/style checks plus
5 style-policy, 32 preparation and 21 workflow tests. All five focused cache
controls passed. `scripts/check.sh`, Python harness compilation and
`git diff --check` passed. No GitHub CI was run.
