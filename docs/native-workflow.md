# Native-cache Build/Test workflow

The .NET controller in `tools/Preparation` prepares the qualified Release/net10.0
input graph, generates `//:build` and optionally `//:test`, runs Bazel, and publishes
verified project bundles after successful input checks and tests. The measured
platform is macOS ARM64 with the pinned Nix SDK. Production commands need no Python.

## Use

Restore the selected entry normally. Packages may reside in the ordinary NuGet
global cache or in the source checkout's `.nuget/packages`. The controller copies
only the restored package closure into private build inputs and verifies it;
it does not modify the global cache. Override its location with `--nuget-packages`
or `NUGET_PACKAGES`.

Keep source, controller checkout, owned state and report output paths disjoint.
Use short paths on macOS and run inside `nix develop`. For the pinned Serilog
approval entry, save this test declaration as `/private/tmp/tests.json`:

```json
{
  "data": [
    "test/Serilog.ApprovalTests/ApiApprovalTests.cs",
    "test/Serilog.ApprovalTests/Serilog.approved.txt"
  ],
  "expectedTests": ["ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally"]
}
```

```sh
bash scripts/build.sh --bootstrap --reuse --incremental-sources \
  --workspace /private/tmp/serilog --state /private/tmp/native-state \
  --entry test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  --tests /private/tmp/tests.json --operation test --force-tests \
  --output /private/tmp/native-run1
```

Repeat without `--bootstrap` and with a new `--output`. `--bootstrap` builds the
owned action/export tools. The shell wrapper builds the controller incrementally;
for repeated calls use the selected .NET host directly:

```sh
"$RULES_MSBUILD_DOTNET_ROOT/dotnet" \
  tools/Preparation/bin/Release/net10.0/Preparation.dll workflow \
  --repository "$PWD" --workspace /private/tmp/serilog \
  --state /private/tmp/native-state \
  --entry test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  --operation build --reuse --incremental-sources \
  --output /private/tmp/native-run2
```

`--operation build` selects `//:build`; `--operation test` selects `//:test` and
requires a test declaration. `--force-tests` executes VSTest even if Bazel's test
cache could satisfy the request. Tests consume verified current runtime artifacts
and declared test data; they never build or restore. Reports include timings,
compiler invocations, runtime hashes and test results. Generated files live at
`<state>/g` and persist by content.

## Local and remote reuse

`--reuse` retains a native preparation plan in owned state. Unchanged inputs skip
discovery and materialization. `--incremental-sources` permits content changes to
existing C# source-only inputs; new files, imports, package changes and other
unsupported changes require fresh discovery. The API/runtime boundary retains
zero downstream compilation for implementation-only edits while tests run the
current runtime bundle.

For remote reuse add `--remote-endpoint https://cache.example/native`. A successful
run publishes an immutable root digest as `remote.publishedSnapshot` in its report.
Select that exact digest on a fresh consumer with `--remote-snapshot <sha256>`.
Remote consumers use guarded source refresh automatically. The selected cache
endpoint and snapshot are trusted inputs; there is no mutable latest-pointer or
remote execution. HTTPS is recommended outside a local test server.

Preparation is split into source groups, metadata and per-package objects. Local
NuGet bytes reconstruct package objects only after content checks. Downloads,
ZIP members, result identities and artifacts are checked before use. Missing or
corrupt objects become cache misses. Failed compilation, failed tests, or changed
leased inputs prevent publication. Source, package, controller, policy and SDK
snapshots are checked again after consumption.

The .NET formats are `dotnet-native-workflow-v1` for owned state,
`dotnet-native-discovery-v1` for discovery proofs, and `dotnet-native-snapshot-v1`
for remote snapshots. Start with a new state directory when migrating from the
Python controller. Old Python remote snapshots miss and require fresh preparation;
they are not silently adopted. `--trust-system-nix-store` is accepted for command
compatibility but does not skip any verification in the .NET controller.

## Qualification

See [the migration record](python-removal.md#steps-3-and-4-production-workflow-and-bootstrap)
for the current .NET acceptance cases. The qualified discovery grammar, reviewed
package imports and fixed SDK inputs remain deliberately narrow. Unsupported
discovery can fall back to fresh preparation without publishing a reusable
preparation proof. Code coverage, remote execution, general NuGet support and
cross-host/platform cache reuse remain outside this qualification.

Earlier Python measurements remain in [workflow performance](native-workflow-performance.md),
[overhead optimization](native-workflow-optimization.md), and
[remote preparation](remote-preparation.md). They are historical evidence, not
measurements of this .NET controller. Python probes and reference implementations
remain available for differential tests and experiments.
