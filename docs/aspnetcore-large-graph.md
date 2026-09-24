# ASP.NET Core large managed graph qualification

The full selected graph compiles with explicit Bazel rules and recovers from an
HTTP action cache in an independent Linux container. This qualifies the selected
managed graph, not the entire ASP.NET Core repository build.

## Upstream workload

Pinned ASP.NET Core v10.0.0, revision
`7387de91234d3ef751fa50b3d1bfede4130213ff`, on Ubuntu 22.04 ARM64,
4 CPUs / 8 GiB, SDK 10.0.400 and Bazel 9.2.0.

`tests/explicit_msbuild/aspnetcore/baseline.py` selects 185 original product/test
entry projects across Http, Middleware, Mvc, SignalR, Servers, Security, Hosting,
Caching, DataProtection and Identity. Sources, root imports, Arcade targets,
resource generators and analyzers are retained. This builds tests; it does not
execute the test suites or qualify packaging/native/Java/Node builds.

MSBuild's static graph has 331 nodes, including 39 outer multi-targeting nodes and
292 inner framework nodes. Following the selected compatible dependency frameworks
from the entry projects yields **220 project files / 275 framework builds**.
All 275 selected nodes have raw assembly outputs. The additional 17 inner graph
nodes are unselected dependency variants; they must not inflate the comparison.

The raw checkout's SDK version is changed to 10.0.400 so both paths use the qualified
worker SDK. SDKs such as Arcade retain their original global.json versions.
`WarningsNotAsErrors=CS8629;IDE0031` keeps two diagnostics introduced by the newer
SDK visible without failing the unchanged upstream sources. No analyzer is disabled.
The raw `.dotnet` symlink points at the same SDK used by Bazel.

## Serial local measurements

| Case | Raw MSBuild | Bazel |
| --- | ---: | ---: |
| Clean outputs | 44.55 s | 136.63 s |
| No-op, median of three | 11.85 s | 0.21 s |
| ObjectPool body edit | 13.31 s | 0.97 s |

Both builds use two build slots on equivalent 4 CPU / 8 GiB Linux VMs. Tools and
package downloads are warm. Bazel's clean-output case also extracts its locked
NuGet archives. Clean and edit rows are single successful observations; no-op
samples are raw 12.18/11.85/10.98 s and Bazel 1.20/0.21/0.15 s.

The body edit changes ObjectPool's default capacity multiplier from two to three.
Only its selected **net10.0 target** recompiles under Bazel. Reference
bytes stay unchanged, so no consumer assembly action executes. Both source trees
are restored afterward. These runs compile upstream tests but do not execute them.

Cold compilation is **3.07 times slower** than raw MSBuild. Warm no-op and body-edit
latency improve substantially; those results do not imply cold parity.

The successful Bazel cold run disables execution logging. An earlier sorted JSON
execution log exhausted the 1 GiB JVM heap; another run exhausted host disk space
and correctly rejected a corrupted worker input. Neither failed run is a timing
result. Small edit logs use `--noexecution_log_sort` and are read incrementally.
Disposable VM disk trimming is performed outside measured builds.

## Parity and validation

All **275 selected implementation assemblies** have matching embedded resources.
Of the 99 available raw reference assemblies, **95 are byte-identical**. The other
four differ in generated file-local type-name path hashes; their inspected type,
method and field metadata matches after normalizing only those hashes. This is
not a claim that every implementation DLL is byte-identical or that the upstream
test suites have run.

The repository .NET/unit/format checks and toolchain/Starlark checks pass. The
focused compatibility suites contain **39 passing cases**, including expected
rejections, runtime checks, project-package version changes and SDK cache recovery.

## Independent HTTP-cache recovery

A producer seeded a fresh, checksum-verified bazel-remote 2.6.2 service on the
private container bridge. The producer VM was then removed. A separate consumer
used a different workspace (`/consumer/project` instead of `/work/bazel`), a fresh
Bazel output base, no disk cache and disabled uploads.

- Consumer wall time: **29.43 s**, including client/server startup and analysis.
  Bazel itself reports 23.01 s.
- **278/278 assembly actions hit the HTTP cache**, including three execution-
  configuration tool builds in addition to the 275 selected targets.
- **578 total remote hits**, including 300 package-extraction actions.
- **Zero assembly compilations** in the consumer.
- **15,733 declared output files match** the producer byte-for-byte: selected
  runtime files, reference DLLs and restore-identity JSON artifacts.

The producer also had 275 Bazel-generated parameter files adjacent to reference
DLLs. Those are execution inputs, not declared outputs, and are excluded from the
artifact comparison. The harness hashes the exact reference DLL and runtime tree.

The JSON-log reader was corrected to stream Bazel's adjacent `}{` record boundaries;
three regression tests cover that format and incomplete logs. The producer's
completed log and artifacts were inspected after restarting its VM; no producer
wall-time claim is made. This is a private-bridge cache experiment, not a WAN or
remote-execution benchmark.

## Explicit declarations

The test-only inventory and preparation scripts emit ordinary per-project BUILD
rules and checksum-locked package archives. They are not a production discovery
entry point. The selected closure locks **274 package archives**. Extraction actions may appear
in both target and execution configurations.

`layout.targets` is an upstream adapter, outside the generic runner. It points
framework-pack lookup at the declared SDK and holds already-resolved project and
framework references while the upstream bare-reference-to-package target executes.
Resource-generation metadata must be preserved, including GenerateSource,
Namespace, ClassName and ExcludeFromManifest.

For initial compatibility qualification, generated bootstrap props/targets are
captured as explicit files. They are **not yet generated by a Bazel action in this
large workload**. The earlier independent GenerateFiles integration remains separate.

## Generic contract additions

- NuGet SDK resolution reads the same declared, read-only package tree as restore.
  SDK packages belong in `package_lock`; global.json remains an explicit import.
  Missing SDK versions fail with no network fallback inside the sandbox.
- `framework_assemblies` declares bare framework Reference names. Names are checked
  against the selected SDK/locked reference pack. Unknown names and path/alias
  overrides fail. SDK-injected full paths within those reference packs are accepted.
- `msbuild_project_output` with `project_outputs` supplies an implementation assembly
  as Content/None without adding it to compiler references. Original project role
  and copy metadata must agree. Producers remain in the target configuration.

The SDK fixture covers worker reuse across versions, undeclared-version rejection,
and fresh-path cache recovery. The project-output fixture covers body edits with
unchanged consumer reference bytes, framework-name rejection, missing edges and
role/copy-metadata mismatches. The focused restore-identity fixture checks a custom package ID, a package-version
change, runtime execution and generated dependency-file project classification.
The final repository checks and all 39 focused cases pass.

The HttpSys CsWin32 generator was already running correctly. Promoting every
transitive archive to a direct PackageReference introduced an unwanted Win32Docs
compile reference and changed C# namespace resolution. Retaining package roots
fixed this without disabling or modifying the generator.

## Evidence and remaining gates

The first broad qualification built 29/292 top-level targets. After resource and
reference adapter corrections, 74/292 passed. Those exploratory passes included
the 17 unselected framework variants and cannot be compared to the raw timing.
Subsequent runs use the corrected selected closure. The package-root correction
reached **269/275**, with all remaining failures involving the in-repository
ObjectPool project replacing a NuGet dependency. Explicit restore identities
preserve that behavior without dependency-project evaluation. The corrected
selected graph now builds **275/275** successfully.

A space-heavy disposable VM was replaced after it became unresponsive. Evidence,
prepared inputs and raw assemblies were saved under
`/private/tmp/aspnet-scale-evidence/`; replacing the VM recovered host free space
from about 8 GiB to 34 GiB. Do not interpret interrupted or failed qualification
runs as performance results.

Bootstrap generation is still captured during setup; moving it into this large
Bazel workload is a separate integration step. Cold compilation remains the main
performance gap. Full upstream test execution, packaging and native/Java/Node
workloads are outside this qualification.

## Reproduction

Use the qualified Ubuntu 22.04 ARM64 image, SDK 10.0.400, Bazel 9.2.0, and the
pinned upstream checkout. Export `RULES_MSBUILD_DOTNET_ROOT` and
`RULES_MSBUILD_BAZEL`, then run:

```sh
python3 tests/explicit_msbuild/aspnetcore/setup.py <checkout> <new-output-directory>
python3 tests/explicit_msbuild/aspnetcore/benchmark.py \
  <output>/source <output>/bazel <bazel-output-base> <output>/baseline <measurements>
```

Setup preserves original root imports and builds the original GenerateFiles and
RepoTasks projects. Inventory is a test-only setup step. `prepare.py` emits explicit
BUILD declarations, package locks and the upstream layout adapter. The individual
setup stages retain logs. The measured builds do not rerun inventory/discovery.

`remote.py` seeds or consumes the HTTP cache and hashes all selected runtime,
reference and restore-identity outputs. Give the consumer a separate VM, workspace
path and output base, with no local action cache. Consumer uploads are disabled.
See [the machine-readable evidence](aspnetcore-large-graph-evidence.json).
