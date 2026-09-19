# Action-local validation and direct-cache experiment

Status: small-graph build/recovery and failed-publication controls passed;
measurements did not justify changing the default. Workflow-gated publication
remains the default. `experimental-direct-action-cache` is an explicit experiment,
not a qualified replacement for the existing cache trust boundary.

## Design

Rules_go's useful pattern is to make an action's successful exit mean its outputs
are suitable for caching. A separate validation action does not prevent the
producer's earlier success from being cached. Therefore bundle integrity checks
must run in the producing compile/composition process before exit zero.

`tools/BundleIntegrity.cs` is shared by the controller and native action runner.
It verifies the seal, result identity, safe artifact paths, exact file inventory,
artifact lengths and content hashes. Compile actions check their entry, API and
runtime projections; composition checks the final app and metadata. Existing
input and borrowed-package mutation guards stay in place. Controller validation
continues to run; the experiment does not remove it.

| Concern | Action responsibility | Remaining boundary |
| --- | --- | --- |
| Package payload | Pinned archive verification and extraction; compile payload hashes | Repository/toolchain identity and acquisition |
| Compile inputs | Initial payload validation, plugin input checks, dependency verification, borrowed-input final checks | Host changes outside the sandbox and original checkout mutation |
| Compile/API/runtime outputs | Shared bundle validation before producer success | Qualification of every supported SDK/target behavior |
| Final application | Composition validation before success | Runtime/application tests |
| Cache transport | Bazel verifies/downloads and publishes successful actions directly in experiment | Cache writer authentication, trust and eviction are deployment concerns |
| Whole workflow/test result | Controller leases and tests still fail the command | Successful earlier actions may already be cached |

## Explicit semantic difference

Direct caching publishes successful actions independently. A later source-lease
failure, unrelated failed action or failing test does not retract those entries.
This is normal Bazel action-cache behavior but differs from this repository's
current whole-workflow publication barrier. Cacheable artifact correctness and
whole-workflow acceptance are separate requirements.

Action-local checks are opt-in with `action-local-validation`; direct mode
automatically enables them. Both measured paths enable the same checks.
The default workflow keeps its existing checks and avoids this additional pass.

The experiment uses synchronous uploads, Bazel's concurrent-input-change guard,
and verified downloads. It retains the qualified macOS Nix SDK restriction and
requires project actions plus an explicit HTTP cache. It does not establish
that the concurrent-change guard replaces our original-source/worker leases, or
that arbitrary mutable SDKs/custom targets are safe. Do not enable direct mode
by default on small-fixture evidence.

## Qualification plan

`tests/remote_workers/direct_cache_probe.py` builds a real four-project graph
with Newtonsoft.Json and PolySharp, recovers it after deleting the producer,
and verifies a changed implementation with a single compile. Separate empty
cache services provide gated/direct cold measurements and three alternating
changed-source pairs. Runtime values and output hashes are checked.

`action_publication_control.py` then runs the real composition action against a
controlled sealed fixture. A valid bundle must recover from the direct cache.
A bundle with a correctly sealed but invalid toolchain identity must fail inside
the producer and fail again in fresh Bazel state, never becoming a cache hit.
This control validates cache publication ordering, not executable semantics of
the synthetic payload. The real MSBuild graph supplies runtime coverage.

The broader graph and production rollout require further qualification of
lease-failure semantics and mutable-input races. The measured effect of removing
the gate must be separated from disabling validation; this experiment retains
validation on both paths and adds the same producing-action checks to both.

## Completed results (2026-09-19)

| Case | Workflow gate | Direct cache |
| --- | ---: | ---: |
| Cold (one sample per mode) | 14.840 s | 15.571 s |
| Changed 1 | 1.993 s | 2.101 s |
| Changed 2 | 1.808 s | 1.867 s |
| Changed 3 | 1.793 s | 1.907 s |
| Changed median | 1.808 s | 1.907 s |

Both compared modes enable the same action-local checks, use separate empty
caches for cold builds, and alternate order for changed builds. Every cold
measurement compiles four projects; every changed measurement compiles one
project without discovery execution. Direct mode is about 0.73 s slower cold
and 0.10 s slower at the changed median in this small loopback sample. This
is not evidence for enabling it, nor a prediction of large-graph/WAN behavior.

The direct producer's application matches the gated bootstrap bytes. After
deleting the producer, fresh recovery executes zero compiles and recovers both
package extractions, with identical DLL/PDB hashes and the expected runtime
value. A changed implementation compiles once and updates the runtime value.

The controlled composition action produced these results:

| Input | Action exit | Remote hit |
| --- | ---: | --- |
| Valid seal and identity | 0 | No |
| Same input, fresh worker | 0 | Yes |
| Valid seal but invalid toolchain identity | 1 | No |
| Same invalid input, fresh worker | 1 | No |

The invalid case writes its candidate app/metadata but fails the shared validator
before action success. It never becomes a successful cache result. Successful
unrelated actions may still publish, as described above.

Validation: all owned tools and test executables built with warnings as errors;
action-runner tests cover changed/missing bytes, extra members, invalid identity,
unsafe paths and duplicate artifacts. The focused controller/cache suite ran
38 tests (37 passed, one Linux-only skip). C# formatting, pinned Buildifier,
Python syntax and diff whitespace checks passed. No GitHub CI was requested.

Evidence: `action-local-cache-evidence.json`; raw traces and logs remain under
`/private/tmp/direct-validation-run`. Reproduce with the qualified SDK/Bazel
environment and `tests/remote_workers/direct_cache_probe.py --output <new-dir>
--repositories <repository-cache> --cache-binary <pinned-bazel-remote>`.

Keep both new options off by default. Large-graph timings, source/worker mutation
controls and a deliberate decision about per-action versus whole-workflow cache
acceptance are required before a production rollout.
