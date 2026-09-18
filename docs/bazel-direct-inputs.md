# Moving remaining work into Bazel

## Step 1: structural discovery and source binding

Discovery now receives source membership with empty C# placeholders. Actual
source contents are declared by a separate binding action. Only compile-only
C# inputs qualify; using one as an additional/resource/import input rejects the
split. Existing restrictive XML/import policies remain. Project/import/package
content and file membership still invalidate discovery. The binder resolves
Bazel input-tree symlinks and writes only its own output copies.

All 18 qualification cases and five raw-MSBuild DLL/PDB comparisons passed.
Body edits recovered discovery remotely and compiled one project. Adding a source
invalidated discovery; additional-file roles, undeclared reads, failed tests and
live source mutation rejected publication. The owned code checks passed before
the final input-tree copying adjustment; full final checks are recorded below.

| Workload | Previous fresh body edit | Split discovery | Change |
|---|---:|---:|---:|
| Diamond | 7.911 s | 5.139 s | 35% lower |
| Serilog | 13.123 s | 9.276 s | 29% lower |

These are separate qualification runs, not an interleaved A/B speedup claim.
Tools were already built and restore completed; Serilog includes a forced test.
Source/package payloads are still in preparation outputs at this step.

## Step 2: direct source and package inputs

Preparation outputs contain metadata and expected payload hashes, not copies of
source/package payloads. Build actions consume the declared input files and reject
hash mismatches before MSBuild. NuGet's known ZIP packaging metadata omissions are
recovered from declared `.nupkg` files and checked against the expected hash.
macOS case aliases resolve consistently; ambiguous source names are rejected.

The diamond controls pass; Serilog additionally passes with the archive-metadata
fallback. Five raw-MSBuild output comparisons and all rejection controls pass.
Dedicated tests cover read-only/symlinked discovery inputs, immutable templates,
metadata-only binding, and a mismatched payload rejected before MSBuild.

Serilog's two preparation trees total **1,758,148 bytes**. Fresh action-cache
transfer is **22,512,866 bytes**, down from 192,010,790 immediately after the split
and 106,670,973 in the original single-preparation-action qualification. This is
an 88% reduction versus step 1, or 79% versus the original lane. It is measured
loopback transfer, not a WAN latency result. Fresh body-edit wall time is 8.248 s
versus 9.276 after step 1 and 13.123 originally. Timing observations are separate
runs with tools built and restore completed. Serilog's warm median is 2.749 s.

See the step [one](bazel-direct-inputs-step1-evidence.json) and
[two](bazel-direct-inputs-step2-evidence.json) evidence. Full checks and the final
combined qualification will be repeated after repository/project-action work.

## Step 3: repository-owned setup

Bazel now wraps the qualified Nix SDK/runtime closure and built tools as local repositories. NuGet archives come from the built-in NuGet cache or the public flat-container endpoint and are acquired through Bazel's repository cache. Reviewed signed-archive SHA256 pins are checked separately from NuGet restore content hashes. Extracted payloads and metadata are declared action inputs. The outer workflow no longer copies tool binaries or package payloads or queries the Nix closure each invocation. Restore remains explicit.

Measured loopback results (seconds; three warm runs):

| Workload | Cold + prime | Fresh hit | Warm median | Body edit |
|---|---:|---:|---:|---:|
| Diamond | 11.336 | 3.315 | 0.830 | 5.016 |
| Serilog | 16.763 | 5.771 | 1.887 | 8.057 |

Serilog warm median fell from step 2's 2.749 s to 1.887 s (31%). Body-edit change was small (8.248 to 8.057 s). These are sequential loopback measurements, not controlled A/B or WAN results. Both workloads retain raw DLL/PDB parity, source-role and undeclared-read rejection, and zero publication for failed tests or live source mutation. Owned code checks pass: 5 style, 32 preparation and 35 workflow tests (one Linux-only skip). Evidence: `bazel-direct-inputs-step3-evidence.json`.

## Step 4: individual project actions (opt-in)

Set `"project-actions": true` in the owned-workflow JSON request. Use
`bazel-remote-cache` and `bazel-remote-upload`; omit `remote-endpoint` and
`remote-snapshot`. This mode uses Bazel's action cache for every project and
runtime composition. It does not fetch native catalogs, copy/save seed bundles,
or prime a second cache variant.

The first invocation recovers/runs structural discovery, reads the validated
layout, and generates one Bazel rule per configured project. A structural
fingerprint retains that layout across warm invocations. Each binding action
checks its project edges and source membership against discovery, so stale
layout metadata cannot silently change the build. Shared structural and package
inputs remain conservative; source body content is scoped to its owning project.

Each compile action receives only its own C# bodies and stable dependency API
trees, and must compile exactly one project. The project-cache plugin validates
and replays dependency results; it cannot fall back to compiling a dependency.
API trees retain genuine reference assemblies, SDK/package contracts, target
results, and deterministic implementation-metadata stubs. Those stubs preserve
assembly references, platform, framework and version metadata used by MSBuild's
runtime selection. They contain no methods. Method-body bytes, PDBs and XML
implementation output are excluded from this contract. A separate action combines
real current project DLL/PDB/XML outputs into sealed runtime bundles without
running MSBuild. This preserves transitive runtime selection even when a
reference assembly omits an implementation-only assembly dependency.

The optimization target is large project graphs, especially remote-cache hits
and body edits. Some small-graph overhead is an accepted tradeoff. Fresh workers
currently need two Bazel invocations, with a validated layout handoff between
discovery and project analysis. The mode is explicitly selected while platform,
configuration and scaling qualification progresses; small-graph timing alone is
not a reason to retain the whole-graph architecture.

Runtime composition validates each producer once, indexes its artifacts, and
assembles only the requested entry. It does not rebuild a composed cache bundle
for every intermediate project: those compile outputs already belong to Bazel.
This removes the all-projects-by-all-projects refresh loop. Project mode uses
selective top-level remote downloads, so a cache hit does not materialize unused
intermediate plans, API trees or compile outputs.

Restore remains explicit. Qualification covers the macOS ARM64 Nix SDK,
Release/net10.0 diamond, Serilog and synthetic fan graphs. It does not establish
Linux, remote execution, WAN or large real-monorepo performance.

## Large-graph measurement and decision

The target is large-graph cache reuse, accepting small-graph overhead. A dedicated
`tests/remote_workers/project_scale_probe.py` compares the two modes on 16- and
64-project synthetic fan graphs (a binary dependency tree joined by an entry
project). All 40 final cases pass: exact raw MSBuild DLL/PDB parity, runtime
output oracle, zero compiles on hits, and exactly one compile for a body edit.
Fresh project-mode edits recover the other 15/63 compiles remotely. Warm edits
reuse a worker and its validated layout. Restore is excluded; both modes use
Bazel jobs=2, a local HTTP cache, the same SDK, and built tools. Timing samples are
sequential, with one sample per edit/cold/fresh case and three warm no-ops;
these are observations, not a statistical or WAN speedup claim.

| Projects | Mode | Cold producer | Fresh hit | Warm median | Warm shared edit | Warm leaf edit | Fresh shared edit | Fresh leaf edit |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 16 | whole | 17.75 | 3.64 | 1.07 | 3.42 | 2.47 | 5.71 | 5.65 |
| 16 | projects | 25.93 | 6.88 | 0.88 | 3.49 | 2.41 | 8.09 | 8.24 |
| 64 | whole | 43.25 | 4.69 | 1.95 | 6.49 | 4.82 | 8.24 | 7.53 |
| 64 | projects | 84.89 | 12.14 | 1.51 | 4.55 | 3.44 | 12.74 | 13.29 |

All timings are seconds. Cold producer includes cache publication; whole mode
also primes its seeded action variant. A shared edit changes the foundational
library's method body; a leaf edit changes one terminal branch's method body.

Profiling the first project-action implementation found the runtime composer
validating and refreshing every project's copy-local outputs against every
other producer. Its action time grew from 0.517 s at 16 projects to 6.775 s at
64. Entry-only composition with indexed artifacts reduced the 64-project action
to 0.272 s (96% lower, about 25x faster). Fresh shared-edit wall time fell from
19.304 to 12.738 s (34% lower), and fresh leaf-edit time from 20.126 to 13.290 s
(34% lower). Fresh-hit download bytes fell from 15,188,947 to 9,635,846 (37%).
Fresh-hit wall time was effectively unchanged (12.223 to 12.143 s).

At 64 projects the final per-project mode improves warm shared/leaf edits by
30%/29% and warm no-ops by 23% versus the whole-graph mode. The 16-project warm
edit results are effectively level. This supports continuing the per-project
architecture for large graphs. It does **not** establish an overall fresh-worker
win: fresh hits and edits remain slower at 64 projects, and cold production is
about twice as expensive. Keep the explicit mode selection while removing the
fresh-worker bootstrap/analysis/cache overhead; do not make small-graph parity
the optimization gate.

For the final 64-project fresh shared edit, executed binding/compilation/
composition take 0.176/0.894/0.272 s. The layout phase takes 2.834 s, and the main
Bazel invocation 8.046 s. The remaining time therefore primarily lies outside
those three executed actions. Next profiling should distinguish Bazel analysis,
cache lookup/materialization and controller integrity work, then remove the
second analysis/bootstrap handoff where possible. Cold scheduling/publication,
conservative structural inputs and repeated dependency replay also remain.

Evidence: [baseline](bazel-project-scale-baseline.json),
[final scale run](bazel-project-scale-evidence.json), and the
[full small-graph qualification](bazel-direct-inputs-step4-evidence.json).
The baseline contains 28 cases before warm-edit cases were added. The raw-build
records are output oracles; only the initial raw build is cold, and the remaining
raw timings are not valid independent incremental-performance baselines.

Reproduce inside the pinned `nix develop` environment, supplying existing cache
and package directories:

```sh
python3 tests/remote_workers/project_scale_probe.py \
  --output /private/tmp/project-scale-new \
  --cache-binary /private/tmp/worker-tools/bazel-remote \
  --packages /private/tmp/mr/p \
  --bazel-install-cache /private/tmp/oh-bazel-install \
  --bazel-repository-cache /private/tmp/br-final-repositories \
  --nodes 16 64
```

Owned checks pass: 5 style, 32 preparation and 38 workflow tests (one Linux-only
skip). The composer test verifies entry-only output, current dependency bytes,
immutable producer bundles, and rejection of a corrupt unselected producer before
output creation. The earlier full qualification also checks API/source membership
changes, undeclared reads and source roles, and zero external PUTs for failed
tests/live mutation. Final post-optimization Serilog qualification is recorded
separately below.

Final post-optimization Serilog qualification passes all nine cases and three
raw DLL/PDB plus runtime-metadata comparisons. Fresh hits compile zero projects;
body edits compile one and recover the other remotely; the API change compiles
both. Failed tests and live mutation publish zero external objects. Timings:
cold producer 18.835 s, fresh hit 6.727 s, warm median 1.712 s, body edit 9.989 s.
See [final Serilog evidence](bazel-direct-inputs-step4-serilog-evidence.json).
C# action-runner contract/process tests and pinned Starlark validation pass.
