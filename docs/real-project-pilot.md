# Real-project pilot: Serilog discovery and MSBuild baseline

Milestone 4 preparation, measured 2026-09-06. Select the upstream
`test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj` entry point and its
`src/Serilog/Serilog.csproj` dependency. This provides a small public project
with real package, analyzer, signing, resource and shared-import requirements,
plus an executable public-API compatibility oracle. **This subtree is not yet
supported by the adapter, and milestone 4 is not complete.**

## Candidate comparison

Inspected project files and repository build configuration from Git checkouts
at these exact revisions; subsequent upstream changes do not change this study.

| Candidate | Pinned revision | Relevant requirements | Decision |
| --- | --- | --- | --- |
| [Serilog](https://github.com/serilog/serilog/tree/49b5339ce85385dc52d4d8e8f2b8308becf23506) | `49b5339ce85385dc52d4d8e8f2b8308becf23506` | SDK 10.0.100; net10 approval-test entry; multi-target library; PolySharp; signing; imported props/targets | First pilot: SDK matches this spike and a narrow behavior oracle needs no external service |
| [Dapper](https://github.com/DapperLib/Dapper/tree/6d48ef664acc7298c649e2d449d903b3360d5a90) | `6d48ef664acc7298c649e2d449d903b3360d5a90` | SDK 10.0.102 minimum; SqlBuilder references multi-target Dapper; central packages; Nerdbank.GitVersioning and SourceLink; database/native dependencies in broader tests | Defer: SDK and Git-derived build metadata add independent work before a faithful baseline |
| [Spectre.Console](https://github.com/spectreconsole/spectre.console/tree/2dc90b90add956c2f6777cb659120900ac2eb740) | `2dc90b90add956c2f6777cb659120900ac2eb740` | SDK 10.0.400; Console and Ansi share a netstandard2.0 source-generator project through analyzer references; JSON additional inputs; generated files outside obj; multiple TFMs | Strong later graph pilot, after analyzer-project handoff and SDK/framework contracts |

These are source inspections, not failed build claims for Dapper or Spectre.
Serilog's two source projects are smaller than the synthetic diamond, but
their configured graph and build inputs expose useful compatibility work.

## Requirements against the current contract

The [graph-export contract](graph-export-contract.md) accepts SDK-style C#
net10.0 and deliberately rejects multi-targeting. Source inspection of the
exporter confirms it rejects a nonempty `TargetFrameworks`, including an inner
build with a selected `TargetFramework`. No exporter rejection run or adapter
execution of this upstream source is claimed here.

| Upstream requirement | Evidence and adoption work |
| --- | --- |
| Multi-target dependency | [Serilog.csproj](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Serilog.csproj) builds net10.0/net9.0/net8.0/net6.0/netstandard2.0 on this host, with .NET Framework targets additionally on Windows. Define outer-build versus inner-build nodes and framework selection before relaxing rejection. A net10-only pilot must explicitly select an existing upstream inner build, not retarget source. |
| Signing key and shared imports | [Directory.Build.props](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/Directory.Build.props) imports Directory.Version.props and sets AssemblyOriginatorKeyFile to assets/Serilog.snk. Exported imports already have a declaration boundary; signing-key discovery needs explicit coverage or BazelExtraInput. Do not assume collecting Compile/Content/Analyzer also collects a property-based key path. |
| Source generator and analyzers | Serilog references PolySharp 1.15.0 and enables IsAotCompatible for compatible TFMs. Declare resolved analyzer/generator assemblies, dependencies, options and generated-output policy. Existing package payload coverage does not establish arbitrary generator correctness. |
| Resource and package inputs | ILLink.Substitutions.xml is an EmbeddedResource with a logical name. The approval project references Microsoft.NET.Test.Sdk 17.11.1, xunit.runner.visualstudio 2.8.2, xunit 2.9.2, Shouldly 4.2.1 and PublicApiGenerator 11.1.0. Validate the actual restore closure and execution assets; package pinning alone is insufficient. |
| Imported package-style behavior | [Serilog.targets](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/src/Serilog/Serilog.targets) contributes a conditional runtime configuration option when PublishTrimmed is true. This Build-only baseline does not exercise trimmed publishing; retain explicit rejection/scope boundaries. |
| Outputs beyond primary DLL | Collect reference/intermediate handoff, signed DLL, PDB, XML documentation, deps/runtimeconfig and test-runtime assets under a defined bundle contract. Primary TargetPath declaration alone does not prove downstream test execution. |
| Test oracle reads checkout data | [ApiApprovalTests.cs](https://github.com/serilog/serilog/blob/49b5339ce85385dc52d4d8e8f2b8308becf23506/test/Serilog.ApprovalTests/ApiApprovalTests.cs) generates the Serilog public API and compares Serilog.approved.txt. Declare that approval file for any future isolated test action. This oracle checks API shape, not all logging semantics. |

Do not remove signing, generators, analyzers or imported behavior to make an
adapter result appear compatible. Each required expansion needs its own
contract, failing acceptance case and measured result. Publishing, AOT,
Windows targets and the broader Serilog test suite are outside this pilot.

## Reproduce the ordinary baseline

Enter the pinned Nix shell, or install this repository's pinned tools, then run:

```sh
python3 tools/probe_real_project.py --output /tmp/serilog-baseline
```

The output directory must be new. The probe verifies SDK 10.0.100, clones the
public repository, checks out the pinned commit, restores into a fresh package
directory, performs a Release static-graph build, repeats it unchanged, and runs
the existing approval test with `--no-build --no-restore`. It retains command
arrays, timings, exit codes, logs, two binary logs, TRX and output SHA-256/size/
executable-bit records in `report.json`. No source is vendored into this repo.
Tool acquisition and restore use the network outside build measurement.

The important commands generated by the probe are equivalent to:

```sh
bash scripts/dotnet.sh restore "$project" -p:Configuration=Release -p:RestorePackagesPath="$packages"
bash scripts/dotnet.sh msbuild "$project" -graphBuild -t:Build -m -p:Configuration=Release -p:RestorePackagesPath="$packages"
# Repeat the preceding build unchanged, then:
bash scripts/dotnet.sh test "$project" --no-build --no-restore -p:Configuration=Release -p:RestorePackagesPath="$packages"
```

`project` is the absolute upstream approval-test csproj; `packages` is the
probe's output-local packages directory. The wrapper deliberately selects the
spike SDK. No upstream project, global.json, framework list or build property
file is edited.

## Measured evidence and limitations

On macOS 26.6.2 ARM64, using Nix .NET SDK 10.0.100 / MSBuild 18.0.2,
the unrestricted restore and static graph succeeded. MSBuild reported **7 nodes
and 11 edges**; output lines show five Serilog framework builds and one net10.0
approval-test build. The additional graph node is the multi-target outer build,
not an extra C# compilation. One public-API approval test passed, none failed
or skipped, and `git diff --stat` on upstream source was empty.

An initial control used `-p:TargetFramework=net10.0` for restore and graph build.
Restore succeeded, but the static graph still expanded the dependency's other
frameworks and failed with NETSDK1005 for their missing restore targets. This
demonstrates why a global TargetFramework flag is not by itself a contract for
pruning a multi-target graph. The successful probe uses unrestricted upstream
restore and does not pass that flag.

One successful preliminary sample recorded restore 2.181 s, fresh-output graph
build 2.362 s, unchanged graph build 0.588 s, and test invocation 0.912 s. These
are wall-clock subprocess times, **not a benchmark or a Bazel speedup**. Source
and package directories were fresh; SDK, OS and NuGet HTTP caches were warm,
and other work may share the host. Incremental MSBuild success is not proof that
each compiler target was skipped. Binary logs are retained for deeper analysis.

The final probe was rerun in another new directory after expanding the report
to inventory outputs from every built framework: restore 0.804 s, fresh-output
graph build 2.455 s, unchanged build 0.666 s, test invocation 0.912 s; every
step exited zero and the same 1/1 approval test passed. This repetition verifies
the delivered probe; it does not provide statistically meaningful timing data.

The net10.0 Serilog DLL in the library and test output directories had identical
SHA-256 `d2ec8b3f7ffcf92f4d980f2e0a2b3696779d2020c78f58535a5794619cbd8e5f`
in that sample. This verifies that ordinary MSBuild copied that dependency;
it does not establish deterministic cross-path bytes or Bazel output parity.

## Remaining milestone 4 acceptance

1. Define configured-inner-build selection and rejection of unsupported outer
   builds, then inventory evaluated inputs against the table above before
   adapter execution.
2. Run the same selected configuration with ordinary MSBuild and Bazel; compare
   observable API approval results, dependency identities and explicitly chosen
   consumer outputs. Add logging-behavior coverage before broader claims.
3. Prove signing-key, version/import, source and analyzer/package changes cause
   the required rebuilds; missing inputs must fail rather than use host state.
4. Measure repeated cold/fresh-output, unchanged, leaf-edit, shared-edit and
   cleared-output cache-recovery scenarios with documented cache/host state.
   Cache recovery and relocated producer deletion have not been measured here.
5. Run the supported pilot through Linux CI. Current measurements are native
   macOS only; no remote-cache or remote-execution conclusion follows.

Adoption currently requires multi-target graph policy, analyzer/signing input
coverage and test-output staging work. There is not yet evidence for estimating
implementation effort or end-user speedup.
