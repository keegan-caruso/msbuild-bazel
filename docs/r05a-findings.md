# R05a generator delivery and reference roles

Implementation branch: `codex/r05a-expanded`, based on `9c549f3`.
Acceptance contract: [R05a plan](r05a-plan.md).

## Implemented boundary

The exporter retains all scheduling edges while validating NuGet snapshots only
against ordinary reference edges. NuGet excludes ReferenceOutputAssembly=false
producers from the consumer snapshot; each producer still needs its own successful
restore and recursively valid ordinary dependencies. Role mutations require fresh
restore. Conflicting duplicates, custom targets, disabled references, nondefault
asset filters and unqualified OutputItemType values remain rejected.

The action continues to use normal MSBuild project declarations and public result
replay. No dependency reference is rewritten to an ordinary assembly reference.
The acceptance probes compare actual compiler analyzer/reference arguments,
runtime DLL sets, generated behavior, diagnostics and Bazel execution sets.

Conventional `analyzers/dotnet/cs/*.dll` payloads now pass preparation and runner
validation for exact-version packages. Archive/restore agreement and per-file
size/hash checks remain required. Other analyzer layouts, executable tools, native
assets and arbitrary package build targets retain existing restrictions. Qualified
pilot archive pins still apply before this allowance.

## Fixtures and probes

`tests/fixtures/generator-roles` has an App, ordinary Shared library, classic and
incremental source generators, and a build-order producer. It covers independent
source/input/configuration changes, addition/removal, diagnostics, deliberate
generator failure and producer-free recovered compilation.

`probe_generator_combinations.py` adds a separately built package generator and a
diagnostic-only analyzer. The analyzer is tested once as a project reference and
once as a package. Its ROLE001 diagnostic is independent of source generation.
Local package versions 1.0.0/1.1.0 are acquired before graph preparation, archive
hashes are recorded, and package producer sources are deleted. Relocation reuses
those exact package bytes; reproducible package acquisition across independent
runs is not asserted.

The combined fixture retains a Shared declaration targeting net10.0 and
netstandard2.1. SDK negotiation selects net10.0 for the single net10.0 consumer.
Only that selected inner build executes. Native execution of netstandard2.1 or a
mixed netstandard/net10 graph is not qualified. Under the Nix SDK, restore downloads
the missing NETStandard.Library.Ref pack from NuGet even though that alternative
framework is not executed.

Both probes delete preparation sources before native actions. Recovery removes
the original generated workspace and output base, requires explicit disk-cache
hits and equal bundle inventories, then edits the consumer so its compilation must
execute with recovered generator/analyzer producers. App runtime DLLs must be
exactly App.dll and Shared.dll.

## Reproduction

Enter the pinned Nix shell or use setup, then acquire Buildifier:

```sh
python3 scripts/setup-starlark.py
bash scripts/check.sh
bash scripts/check-dotnet.sh
python3 -m unittest discover -s tests/generator_roles -v
python3 -m unittest discover -s tests/graph_packages -p test_analyzer_packages.py -v
```

Independent probes (output paths must not exist):

```sh
python3 tools/probe_generator_roles.py --output /tmp/r05a-roles
python3 tools/probe_generator_combinations.py --analyzer-delivery project --output /tmp/r05a-project
python3 tools/probe_generator_combinations.py --analyzer-delivery package --output /tmp/r05a-package
```

The manual `generator-roles.yml` workflow runs the same native macOS qualification.
Adding a workflow does not establish a hosted pass; it has not been dispatched.

## Validation record

Native macOS ARM64, Nix .NET SDK 10.0.100 and Bazel 8.4.2:

| Check | Observed result | Retained evidence |
| --- | --- | --- |
| Project generator roles | All 15 cases passed, including deliberate CS8785 failure and recovered consumer compilation | `/private/tmp/r05a-roles-final/report.json` |
| Package-delivered diagnostic analyzer with package/project generators | All 10 cases passed | `/private/tmp/r05a-combined-package-full/report.json` |
| Project-delivered diagnostic analyzer combinations | All 10 cases passed | `/private/tmp/r05a-combined-project-final/report.json` |
| Restore-role regressions | All 7 passed | `/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/generator-role-restore-pa6woa83` |
| Ordinary generator oracle | Passed | `/private/tmp/r05a-ordinary-tests.log` |
| Graph export regressions | All 20 passed | `/private/tmp/r05a-graph-tests.log` |
| Package regressions | 18 tests pass across the suite and native rerun; 2 existing Serilog prerequisites skipped. All 4 PrivateAssets modes pass after the bootstrap-environment fix. | `/private/tmp/r05a-package-tests.log`, `/private/tmp/r05a-private-assets-final.log` |
| Analyzer package missing/corrupt/layout guards | Both Python tests and direct action-runner controls passed | `tests/graph_packages/test_analyzer_packages.py`, `/private/tmp/r05a-runner-final.log` |
| Scaffold/Starlark and owned .NET style | Passed; added runner tests also build and format cleanly | `/private/tmp/r05a-check.log`, `/private/tmp/r05a-dotnet-check-2.log`, `/private/tmp/r05a-runner-format.log` |

Executed action compilation ownership was checked from the role/package reports:
each successful fresh action compiled only its own project. The first concurrent
project-combination attempt encountered an exporter runtimeconfig file rebuild
race; final probes coordinate shared exporter build/read operations with the
existing graph-preparation lock. Regression suites that rebuild shared tooling
should still run sequentially. The first native PrivateAssets rerun also exposed
inconsistent tool bootstrap environments: baseline ReplayPlugin/ActionRunner
assemblies included the Git revision, while the next preparation rebuilt them
without it. This invalidated producer actions despite an App-only source edit.
The test now passes the same explicit CLI home/package root and disabled MSBuild
node reuse to preparation as to its other commands; the original exact action-set
assertion remains unchanged.

An outer-sandbox attempt could not register darwin-sandbox; native runs use
the required sandbox outside that outer restriction. A discarded mixed-framework
attempt built with ordinary MSBuild but was rejected by the existing net10-only
exporter contract. The initial combined action exposed the matching runner package
category guard, which was extended together with preparation.

## Remaining acceptance

The pinned Spectre.Console revision is
`2dc90b90add956c2f6777cb659120900ac2eb740`. Its global.json requires SDK 10.0.400;
the repository pinned 10.0.100 at this checkpoint. The later [SDK upgrade](sdk-upgrade-findings.md) removes this SDK-selection blocker. A copied checkout failed `dotnet --version` with
exit 155 under the pinned SDK; evidence is at
`/private/tmp/r05a-spectre-prerequisites/report.json` and `sdk-selection.log`.
Its source generator targets netstandard2.0 and its
packages use central version management, with build-time tools/imports needing
qualification. Those prerequisites are not established by the synthetic fixture.
Spectre remains an outstanding real-project gate, not a passing R05a result.
Interceptors, full CommunityToolkit framework combinations, general generator
loader dependency closure, Linux R05 qualification, remote workers and full host
closure also remain outside the measured boundary.

## Coverage mapping

| Cells | Selected evidence |
| --- | --- |
| G01/G02/G06 | Classic and incremental project generators, ordinary/analyzer/build-order roles |
| G05 | Exact-version local package generator combined with project generators; version mutation |
| G07/G08 | Additional files, editor options, compiler-visible properties, removed values, generator errors and diagnostic controls |
| G09 | Pinned SDK/Roslyn only; no broader compiler compatibility claim |
| G11 | Diagnostic-only analyzer through project and package delivery; upgrade, suppression, severity and warnings-as-errors |
| G03/G04/G10 | Serializer-specific oracle, interceptors and SDK-generator behavior remain separate |

Reference framework evidence selects the supported net10.0 inner build from a
multi-targeted ordinary dependency. It does not establish arbitrary configured
edge properties, other runtime frameworks or the CommunityToolkit matrix.
