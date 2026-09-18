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
