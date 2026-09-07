# Managed binary package findings

**Status:** Focused Linux x86-64 native-sandbox acceptance passed on commit
`3771e5b`. The broader setup and Nix regression runs remain in progress at this
checkpoint. New macOS binary-package acceptance has not been measured.

The [contract](binary-package-plan.md) and black-box e2e test were committed
before implementation. The initial run failed with `unrecognized arguments:
--binary-package-probe` (one test, 0.077 seconds).

## Implementation

`binary_inputs.py` builds repository-authored RulesMsbuild.Binary and RulesMsbuild.Leaf packages
outside actions with SDK 10.0.100. Each archive includes a reference assembly and
an executable assembly. Shared references RulesMsbuild.Binary, which depends on
RulesMsbuild.Leaf. App calls through Shared and executes both package implementations.

The existing package staging verifier now accepts a prepared archive inventory
in addition to the original checked-in build-package pins. Restore manifests
still enumerate and hash-check every resolved package payload. The runner,
replay plugin, action request and bundle schemas are unchanged.

The probe exercises the scheduling/cache matrix, fresh execution at new paths,
direct and transitive upgrades, DLL hash/deps.json evidence and rejection controls.
The generated package archives are hashed during preparation; they are not
independently pinned external artifacts. Repeated preparation of the unchanged
Leaf package at separate paths must produce identical archive bytes.

## Local validation

Pinned tool checks passed. All three package variants built, including the
unchanged Leaf archive comparison. Restore and ordinary traversal Build passed;
the baseline printed `shared-v1/binary-v1/leaf-v1/app-v1`.

Command (with RULES_MSBUILD_DOTNET_ROOT/RULES_MSBUILD_BAZEL pointing at the existing pinned tools):

```sh
python3 -m unittest discover -s tests/e2e -p test_binary_packages.py -v
```

The first local integration run stopped before any Bazel action because the
Java trust store could not validate bcr.bazel.build's TLS certificate. Retrying
the same prepared cold build with the system Java trust store resolved registry
access, but this container does not register Bazel's required `linux-sandbox`
strategy. No fallback strategy was used. This is not a passing sandbox/cache
result. CI validation is tracked on PR #2.

## Binary resolver finding

The first Linux setup CI run passed all 13 existing non-native tests but failed
the new binary test at Shared's `ResolvePackageAssets` with `NETSDK1064`.
NuGet's package resolver requires a `.nupkg.sha512` or `.nupkg.metadata` marker
to recognize an installed package; extracted DLLs alone are insufficient.
See [SDK resolver](https://github.com/dotnet/sdk/blob/v10.0.100/src/Tasks/Microsoft.NET.Build.Tasks/NuGetPackageResolver.cs)
and [NuGet resolver](https://github.com/NuGet/NuGet.Client/blob/dev/src/NuGet.Core/NuGet.Packaging/FallbackPackagePathResolver.cs).

Preparation now derives the `.nupkg.sha512` sidecar from the already verified
archive, checks it against the restore library hash and declares/hashes it with
the payloads. A negative control removes its declaration. No ambient metadata
or package archive is copied into an action. This extends preparation, without
changing the runner's manifest validation or replay schemas.

A focused local runner check then succeeded: Shared compiled only Shared, App
compiled only App and recorded a Shared replay hit, and the application printed
`shared-v1/binary-v1/leaf-v1/app-v1`. A second pair of direct runner invocations
at fresh workspace paths produced identical complete consumer bundles. Both
staged DLLs matched their runtime payload hashes and differed from their
reference assembly hashes. These direct invocations were debugging evidence
outside Bazel, not a substitute for native sandbox/cache acceptance.

## Linux acceptance

The [focused CI job](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34011816923/job/101428853796)
passed the complete binary-package test in 154.609 seconds. Its
[retained evidence](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34011816923/artifacts/9982728603)
contains reports and logs.

Measured results:

- Cold and fresh executions build Shared and App; unchanged builds execute
  neither. App-only edits execute App alone; Shared edits execute both.
- Clearing outputs and using a new output base restore both bundles from the
  disk cache. Fresh execution with an empty cache at new action paths produces
  identical bundle bytes and executable bits.
- Direct and transitive package upgrades rebuild both actions and execute the
  changed implementation. Each upgrade leaves the other package DLL unchanged.
- App's deps.json contains both packages. Its DLLs match runtime payload hashes
  and differ from reference assembly hashes. No consumer compilation of Shared
  occurs, and preparation workspaces/feeds are absent before action execution.
- Missing payload declarations or installation markers, corrupt transitive DLLs,
  stale direct restore and an incomplete transitive manifest fail before
  compilation. Removing RulesMsbuild.Leaf.dll from a private copied App output makes
  application execution fail.

The marker-fix run had already completed the positive matrix but failed when
the negative control tried to remove a DLL from a copy of Bazel's read-only
output directory. The harness now makes only that private copy writable. The
full setup run approached its 15-minute limit (856.168 seconds for tests), so
its limit is now 25 minutes; the focused job has a separate 10-minute limit.
All 13 existing non-native tests passed in that earlier run. The later focused
job establishes the complete new package matrix; it is not a claim that the
latest full setup/Nix jobs have finished.

## Limits

This slice covers managed net10.0 ref/lib assets and an exact transitive package
dependency on the explicit two-project graph. It does not establish RID-specific
or native package selection, analyzers, arbitrary feeds/build targets, central
package management, version conflict behavior, full runtime closure, remote
caching or cross-platform artifact reuse. This closes the deliberately narrow
managed-package gate for a local-only graph exporter; it does not establish
general NuGet compatibility or remote-cache correctness.
