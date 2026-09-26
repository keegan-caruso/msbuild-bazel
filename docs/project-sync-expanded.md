# Generated Http.Abstractions and Immutable qualification

This records the original hybrid baseline. The [complete generated HTTP graph](project-sync-http-full.md)
supersedes its HTTP coverage and verifies the self-contained combined driver.

The next two pinned upstream slices now build and test through `msbuild_sync` on
**Linux ARM64, SDK 10.0.400, Bazel 9.2.0, Release/net10.0**. Revisions are unchanged
from the [initial inventory](project-sync-upstream.md).

| Slice | Configured assembly producers | Generated entries | Raw/Bazel test outcomes |
| --- | ---: | ---: | ---: |
| ASP.NET Core Http.Abstractions | 44 | library + tests; 42 authored dependencies | 714 passes, exact names/outcomes |
| System.Collections.Immutable | 36 | library + tests; 34 authored dependencies | 22,544 passes, normalized names/outcomes |

Both pass warm local test-cache reuse, library body-edit test invalidation,
unchanged public reference assembly, restoration, and custom-document drift
rejection. Immutable's startup hook verifies the actual loaded DLL against the
source producer after each edit. Its implementation hash changes on the body edit
and returns to the baseline after restoration. See [recorded controls](project-sync-expanded-evidence.json).

Immutable reuses the earlier qualification's narrowly defined display-name
normalization: four theory methods deliberately shuffle their data (32 cases),
and two debugger-display methods can print dictionary entries in either order.
Counts and outcomes remain significant; every other full test display is compared
exactly. This is not byte-for-byte equality of raw and Bazel assemblies.

## Changes needed

- **Checked-in generated C#:** accept IDE metadata (`DesignTime`, `AutoGen`,
  `DependentUpon`) and source copy metadata while keeping the source file explicit.
  Sync does not run a T4 generator merely because a project contains IDE metadata.
- **Global usings:** retain SDK `Using` items, including `Alias` and `Static`.
  Unknown metadata is rejected.
- **SDK-backed test host:** `runtime_host = "@dotnet//:sdk_host"` declares the full
  pinned SDK for tests which invoke a compiler. Http.Abstractions' T4 freshness test
  failed with the runtime-only host (713 passes, one failure), then passed with
  this declared host. The default runtime stays small; no host SDK lookup is added.
- **Assembly selection:** `assemblySelections` in sync mappings emits the existing
  Bazel `assembly_selections` attribute. Immutable explicitly chooses the paired
  Collections and Threading variants where dependency paths converge.
- **Paired-contract validation:** reference-only dependency projects carried by a
  pair are not competing runtime implementations. Selection retains their full
  assembly-identity checks; unrelated active runtime projects still fail analysis.

Http.Abstractions also declares its PublicAPI analyzer baselines and the complete
package set needed when restore evaluates dependency records, including private
package edges. Its original bootstrap runs as a Bazel generation action, reused
from the ObjectPool fixture. Authored dependency warning overrides were removed;
raw and Bazel builds pass with upstream warning policy.

Immutable retains explicit analyzer/tool edges and declares its `RdXmlFile` as an
input even though this is a JIT qualification. Generator names are scalar routing
items, with their actual analyzer projects bound separately. No new custom-document
hashes were auto-approved: both slices match the existing frozen contract sets.

## Reproduce

First complete the [base qualification](project-sync-upstream-qualification.md).
Use the same disposable source checkouts; Http.Abstractions tests need the broader
ASP.NET `src` tree, including hosting, routing and generator sources.

```sh
source scripts/env.sh
python3 tests/project_sync/upstream/expanded.py \
  /checkout/aspnetcore /checkout/runtime /tmp/base-qualification /tmp/fresh-expanded
```

The driver runs Http.Abstractions first, then Immutable, recording per-step logs
and control summaries. It uses evaluation inventories and the existing authored
adapters to prepare explicit mappings. Production sync emits the two entry rules
per slice; its generated `.bzl` files are never hand-edited.

The recorded work used these stages with targeted retries while resolving the
reported blockers; it was not a single fresh invocation of the combined driver.
An SDK repository regeneration during development required restarting the existing
HTTP worker server. Final checks used the stable repository definition.

## Validation and limits

- 43 Bazel analysis tests pass, including paired-contract selection and rejection
  of an unrelated implementation. Generator tests cover new mappings and unknown
  metadata; display normalization has count/outcome rejection controls.
- Owned-code checks pass on macOS and Linux ARM64: 5 style, 7 tooling, 35 runner,
  31 generator and one display-normalization test.
- SDK extension validation passes all 10 cases. Toolchain/Starlark checks pass.
- These are correctness runs, not performance or remote-cache relocation evidence.
  No GitHub CI was dispatched; no macOS or x86-64 execution claim is made here.
- Immutable uses installed native/runtime host 10.0.11 with its source-built
  assembly substituted and verified. This does not expand the separately
  qualified complete source-built host.
- Most dependency producers remain authored. Wider generator migration, independent
  cache consumers and the macOS MSBuild task-host limitation remain follow-ups.
  The [ordered delivery plan](roadmap.md) defines their scope and completion criteria.
