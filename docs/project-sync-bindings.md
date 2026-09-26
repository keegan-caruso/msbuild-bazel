# Explicit sync contracts: qualification

The five generator blocker areas now have explicit inputs/mappings and small
end-to-end controls. This qualifies the primitives, **not generated builds of
ASP.NET Core or dotnet/runtime**. The authored upstream adapters retain their
separate qualification. The later [upstream qualification](project-sync-upstream-qualification.md)
applies these contracts to ObjectPool and Pipelines. See [API and limits](project-sync.md).

## Changes and evidence

| Area | Implemented behavior | Control |
| --- | --- | --- |
| Bootstrap and SDKs | Producer labels map to logical evaluation/build paths; closed NuGet SDK package set | Generated props/source/resource consumed without source-tree writes; producer edit reflected; missing SDK rejected |
| Reference roles | Exact bare assembly-to-project/package/framework bindings; explicit project compile/private/analyzer/tool/output roles | Bare project reference compiles; role mismatch rejected; no assembly-name discovery |
| Custom targets/tasks | SHA-256 plus exact target/task names and authored inputs; declared managed task properties | Real project-built task executes; task/input edits change output; contract drift rejected |
| Package flow | IncludeAssets/ExcludeAssets, partial PrivateAssets, central VersionOverride; package metadata retained in dependency restore records | Eight cases match raw MSBuild build/run success or rejection |
| Friend/signing/implementation | SDK friend items and tracked keys; explicit implementation-reference selection | Friend body edit reflected; signed friend runs; wrong key/nonfriend rejected; implementation-only API runs and contract-only selection fails |

NuGet needed a runner correction: inherited package references previously became
direct references. That erased edge-specific asset masks. Dependencies now publish
their evaluated package references and masks, and consumers supply them to NuGet's
`GetRestorePackageReferencesTask` as dependency graph entries. The consumer keeps
only its own directly declared package references.

The eight package controls cover compile privacy (including downstream rejection),
runtime privacy, compile/runtime exclusion, compile-only inclusion, private tooling
assets, and a central version override. They compare actual compiler/runtime
outcomes, not only emitted declarations. They do not exhaust all NuGet asset types,
central transitive pinning combinations or arbitrary package build logic.

The custom-document contracts require reviewed input completeness. A hash makes
that review stale when the document changes; it does not establish hermeticity by
itself. Sync still runs no MSBuild targets. Explicit user Analyzer/FrameworkReference
items, merged evaluation tool layouts and external repository label aliases remain
unqualified or rejected as described in the API guide.

## Validation

SDK 10.0.400, macOS ARM64 and Linux ARM64 Apple containers. The owned-tool checks
pass (5 style, 7 tooling, 35 runner, 25 generator tests), as do 10 SDK extension
checks and 41 Bazel analysis tests on macOS. The Linux runs also pass the owned-tool
checks. [Recorded cases](project-sync-bindings-evidence.json) distinguish platforms
and Bazel versions; an expected rejection has a nonzero exit code.

```sh
bash scripts/check-dotnet.sh
bash scripts/check.sh
bash scripts/bazel.sh test //tests/analysis:all
python3 -m unittest discover -s tests/sdk_repository -p test_sdk_extension.py -v
python3 tests/project_sync/bootstrap.py /tmp/fresh-sync-bootstrap
python3 tests/project_sync/roles.py /tmp/fresh-sync-roles
python3 tests/project_sync/implementation.py /tmp/fresh-sync-implementation
python3 tests/project_sync/assets.py /tmp/fresh-sync-assets
```

Each fixture requires a fresh destination. `bootstrap.py` uses `msbuild_generate`
for props/resource production and a separate source producer. `roles.py` generates
disposable signing keys; no keys are committed. No timing, remote execution, or
independent remote-cache recovery claim is made for these new contracts. GitHub
CI was not dispatched.

Linux harness notes: the prebuilt image needs an explicit
`RULES_MSBUILD_BAZELISK=/opt/rules_msbuild-toolchain/.tools/bin/bazelisk` when
repository wrappers export tool paths. Bazel 8.8 build state belongs on the guest's
native filesystem: placing its sandbox on the host-mounted evidence directory
failed with `inaccessibleHelperDir (Permission denied)`. Keep logs/results on the
host mount and copy them after the native-filesystem run.

## Historical upstream checkpoint

Pinned revisions are unchanged from the [initial inventory](project-sync-upstream.md).
ASP.NET's real `GenerateDirectoryBuildFiles` target now succeeds in a disposable
checkout using the pinned SDK's targeting packs:

```sh
bash scripts/dotnet.sh msbuild /checkout/aspnetcore/eng/tools/GenerateFiles/GenerateFiles.csproj \
  -restore -t:GenerateDirectoryBuildFiles -p:Configuration=Release \
  -p:NetCoreTargetingPackRoot=/absolute/pinned-dotnet/packs/ -v:minimal
```

This setup run is raw MSBuild; its upstream bootstrap has not yet been wrapped in
Bazel. The default sync probes now reject `CreateDirectory` for ObjectPool and
Http.Abstractions, `Service` for ObjectPool.Tests, and `WorkloadSdkBandVersions` for
all three runtime entries. None was silently allowed.

A separate evaluation-only inspector enumerates **all imported documents and item
kinds**, bypassing neither build validation nor task execution. For net10.0:

| Entry | Non-SDK documents containing targets/tasks | Bare references | Project references |
| --- | ---: | ---: | ---: |
| ObjectPool | 19 | 1 | 0 |
| ObjectPool.Tests | 22 | 2 | 2 |
| Http.Abstractions | 19 | 3 | 2 |
| Pipelines | 24 | 0 | 8 |
| Pipelines.Tests | 23 | 0 | 3 |
| Immutable | 24 | 0 | 12 |

Counts include repository and NuGet SDK imports. Evaluation does not prove these
targets execute. All selected net10.0 Compile files exist after completing sparse
checkout inputs (including Testing and CoreLib shared sources).

```sh
python3 tests/project_sync/evaluation_inventory.py /checkout/aspnetcore /tmp/aspnet-evaluation.json \
  src/ObjectPool/src/Microsoft.Extensions.ObjectPool.csproj \
  src/ObjectPool/test/Microsoft.Extensions.ObjectPool.Tests.csproj
python3 tests/project_sync/evaluation_inventory.py /checkout/runtime /tmp/runtime-evaluation.json \
  src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj \
  src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj
```

The subsequent [upstream qualification](project-sync-upstream-qualification.md)
reviews these contracts and builds/tests ObjectPool plus Pipelines entries. Wider
graphs still need explicit review; do not bulk-convert inventoried items into
`evaluationItems` or auto-approve document hashes.
