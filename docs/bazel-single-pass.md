# Moving the remaining controller work into Bazel

Implementation order: portable project layout, direct checkout inputs, single-project
MSBuild execution, then cacheable locked restore. Each step is measured and
committed before the next. Large-graph cache hits and edits are the priority;
small-graph overhead is an accepted tradeoff.

## 1. Portable layout and one Bazel invocation

A versioned `project-layout.json` describes the qualified Release/net10.0 entry,
project edges and C# source membership. It contains no source hashes or absolute
workspace paths. A bootstrap project-action build exports it in the workflow
output directory; it can also be exported from a qualified discovery graph with
`Preparation owned-export-layout --request FILE`, where the request contains
`graph` and `output` paths. Keep the layout with the project configuration and
supply its path using `"project-layout": "/path/to/project-layout.json"` together
with `"project-actions": true`.

Workers with the declared layout generate stable project targets before starting
Bazel and use one invocation. The bootstrap path remains available to generate or
refresh the layout. A source-body edit does not require a refresh. Changed edges,
source membership or configuration require a new layout; changes to other
structural contents can still reuse a layout when its declarations remain valid.

`MsbuildValidateLayout` checks the entire declared layout against current strict
MSBuild discovery. All project binding actions depend on its validation output.
Thus omitting a node/edge or using stale membership cannot bypass discovery,
even when the declared graph itself can be analyzed successfully. The check is
cacheable; it does not duplicate full-graph validation inside every project
binder. The controller also checks that the supplied layout did not change during
the invocation before publishing cache objects.

Validation: 20 diamond/Serilog qualification cases and seven raw-output comparisons
pass, including DLL/PDB and semantic runtime metadata parity. The separate stale
layout probe rejects a removed dependency with zero external PUTs. The focused
unit covers body-insensitive portable layout export, stale edges, source membership,
configuration and extra projects. The owned suite passes (5 style, 32 preparation,
38 existing workflow tests, one Linux-only skip) plus the new layout test. Changed
Starlark files pass pinned buildifier checks.

Reproduce with `tests/remote_workers/owned_preparation_probe.py --project-actions
--declared-layout`, `tests/remote_workers/project_scale_probe.py --nodes 64 --modes
projects --declared-layout`, and `tests/remote_workers/layout_guard_probe.py` in
the pinned Nix environment. Cache binary/package/install/repository-cache paths
are the same arguments documented in `bazel-direct-inputs.md`.

### Measured result

The 64-project run passes all ten cases and three raw-output oracles. Every
supplied-layout invocation uses exactly one Bazel invocation; fresh body edits
recover 63 project compiles remotely and compile one. Compared with the preceding
project-action run, fresh hits are 11.476 versus 12.143 s, fresh shared edits
12.910 versus 12.738 s, and fresh leaf edits 13.204 versus 13.290 s. Warm median
is 1.602 s; warm shared/leaf edits are 4.812/3.407 s. Cold bootstrap is 86.009 s
and still uses two invocations to generate the initial layout.

This is a structural improvement with only a modest observed fresh-hit change,
not a material edit-time speedup. The first invocation previously performed
loading/analysis work that the second could reuse; removing the boundary does
not remove that work. Measurements are sequential loopback samples, not a
controlled statistical comparison. See `bazel-single-pass-step1-evidence.json`.

## 2. Direct checkout ownership

Set `"direct-checkout": true` with project actions. A local Bazel repository
exposes the declared regular checkout files as symlinks. The controller no longer
copies a source tree into `state/g/inputs`, and test data is consumed directly.
It reads existing assets to declare pinned package archives; package acquisition
remains repository-owned. The original checkout snapshot and independent final
verification still enforce the zero-publication rule for live mutation.

`MsbuildNormalizeRestore` consumes raw restore metadata and emits normalized
individual files as Bazel outputs. Discovery and project compilation consume
those declared outputs. The action excludes C# bodies, so warm body edits reuse
it. Inputs and repository files are never rewritten: when MSBuild/discovery needs
writable metadata, the runner changes permissions only on its private copies.

Fresh workers still execute normalization because raw restore files and the
normalization request contain checkout-specific paths. Their normalized outputs
are identical across locations, allowing downstream discovery and compilation to
hit remotely. Moving locked restore itself into a cacheable action is a later
step; this change alone does not eliminate the restore prerequisite.

All 20 diamond/Serilog qualification cases and seven raw-output comparisons pass.
The harness verifies that the copied source tree does not exist. Failed tests and
live mutation retain zero external publication. The owned checks pass: 5 style,
32 preparation, 40 workflow tests (one Linux-only skip), plus changed Starlark
validation. A focused test covers relocated normalization, path-prefix boundaries,
failed restore receipts, and identical canonical metadata. The initial acceptance
run caught read-only Bazel outputs being rewritten after copying; private-copy
permissions were fixed before the passing run.

The 64-project fan run also passed (10 cases, three raw output oracles). Against
step 1, observed wall times were:

| Case | Step 1 | Direct checkout |
| --- | ---: | ---: |
| Cold bootstrap | 86.009s | 85.366s |
| Fresh cache hit | 11.476s | 10.546s |
| Warm no-op median (3) | 1.602s | 1.198s |
| Warm shared edit | 4.812s | 4.132s |
| Warm leaf edit | 3.407s | 2.975s |
| Fresh shared edit | 12.910s | 12.661s |
| Fresh leaf edit | 13.204s | 12.709s |

These are individual local loopback runs, not confidence intervals. The useful
observed gain is in warm controller overhead; fresh workers still execute the
normalization action. Both fresh edits compiled one project and reused 63 remote
compile results. Restore remains excluded from these timings.
See `bazel-single-pass-step2-evidence.json` for compact evidence.

## 3. Single-entry MSBuild execution

Project actions now evaluate the real entry project through MSBuild's public
`BuildManager` API, with one MSBuild node. Bazel supplies the complete dependency
API set. Each private dependency project copy is replaced with a project containing
only the producer's recorded target outputs; it has no SDK imports, compiler, or
nested project references. MSBuild can request those outputs without evaluating
the dependency SDK or scheduling its build graph again. Unknown targets fail with
MSBuild's missing-target error.

The normal command-line non-graph build did not initialize the cache plugin in
our first prototype. The public API host supplies an already evaluated entry
`ProjectInstance`, allowing the existing plugin to validate the entry and capture
real SDK target results. The whole-graph mode retains its original command line.

Before compilation, the plugin checks the complete dependency set, seals,
toolchain, transitive API identities, and artifact ownership. It validates the
entry's evaluated configuration, references and supported copy-local behavior.
The runner checks original payload hashes before replacing private project
copies, and publication still requires final original-checkout validation.
The native filesystem sandbox remains enabled. This lane no longer uses MSBuild
static-graph isolation: Bazel schedules the project builds; MSBuild still executes
small recorded-result targets when its SDK asks for dependency metadata.

Validation: owned builds/style/format checks, 5 style tests, 32 preparation tests,
40 workflow tests (one Linux-only skip), and the C# contract suite pass. A focused
contract test executes recorded values through real MSBuild, verifies escaped
semicolons and literal property expressions survive, and checks unknown targets
fail with MSB4057. The complete 20-case qualification passes seven raw DLL/PDB
and runtime metadata comparisons, fresh recovery, source/API invalidation, and
zero publication for failed tests/live mutation. An attempted custom-target
workflow probe was rejected even earlier by the existing discovery XML policy.

The 64-project run passed all 10 cases and three raw oracles:

| Case | Step 2 | Single entry |
| --- | ---: | ---: |
| Cold bootstrap | 85.366s | 83.322s |
| Fresh cache hit | 10.546s | 10.887s |
| Warm no-op median (3) | 1.198s | 1.122s |
| Warm shared edit | 4.132s | 4.120s |
| Warm leaf edit | 2.975s | 2.844s |
| Fresh shared edit | 12.661s | 12.644s |
| Fresh leaf edit | 12.709s | 12.739s |

Total compile-action execution fell from 68.481s to 64.215s (6.2%); cold wall time
improved 2.4%. Fresh/edit improvements are small or absent in this run. The change
removes repeated SDK evaluation but does not eliminate per-action MSBuild startup,
private input materialization or metadata composition. This is not evidence of a
large overall speedup. Both fresh edits still execute one compile and recover 63
remote compile results. See `bazel-single-pass-step3-evidence.json`.
