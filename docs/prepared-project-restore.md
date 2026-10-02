# Project-specific prepared Restore

`prepared_restore = True` splits an assembly rule into a Restore action and a
compilation action. Restore evaluates the **real project**, its declared imports,
configured project identities, locked packages and SDK. The compilation action
installs the resulting NuGet assets and generated props/targets, then runs Build.
The default remains the existing combined Restore-and-Build action.

```starlark
msbuild_library(
    name = "Library",
    project = "Library.csproj",
    target_framework = "net10.0",
    srcs = ["Value.cs", "RestoreInput.cs"],
    prepared_restore = True,
    restore_source_inputs = ["RestoreInput.cs"],
)
```

Restore receives every declared source **path**, but only the contents of
`restore_source_inputs` or files also declared through another Restore input
attribute. Other source paths are represented by empty files, so ordinary
source and dependency-reference edits do not change its cache key.
Imports, item files, package trees, selected SDK and configured dependency
Restore identities remain inputs. A custom Restore target that reads source
contents requires those files in `restore_source_inputs`; leave
`prepared_restore` off if its file reads cannot be declared completely. The
rule rejects a Restore-source label outside `srcs`/`source_paths`. Shared
`msbuild_restore`, assembly selections, `reference_projects`, generation and
local native tools cannot be combined with this mode yet.

ProjectSync accepts `preparedRestore` and `restoreSourceInputs` in a project
mapping or `projectDefaults`. It emits the corresponding rule attributes;
neither is inferred from a csproj. Enabling it for a graph is an explicit
source-independence assertion, not a general claim about arbitrary MSBuild
targets. The assembly action still stages packages and dependencies and still
evaluates and compiles the project. This split removes repeated Restore only.

## Validation

The pinned Linux ARM64 package fixture runs with
`python3 tests/explicit_msbuild/prepared_restore.py OUTPUT`, both as fresh
actions and with `RULES_MSBUILD_PREPARED_WORKER=1`. It verifies that:

- Baseline Restore runs for both projects and a NuGet build props import is
  present during compilation.
- A dependency API edit recompiles both projects without rerunning Restore.
- An edit to a declared `restore_source_inputs` file reruns the library Restore.
- A project version edit reruns both Restores through the changed dependency
  identity.
- An empty output base at a new workspace path recovers the cached actions;
  another API edit compiles successfully there without Restore.

The existing package semantics fixture was also run with this mode enabled:
all 19 cases passed, including central versions, private assets, generated
package paths and expected rejection cases. `scripts/check.sh` and
`scripts/check-dotnet.sh` passed in the pinned container. GitHub CI was not run.

## Orchard API-edit result

One matched run used the pinned 202-project Orchard CMS graph, SDK 10.0.400,
Bazel 9.2.0, Ubuntu ARM64 in an Apple container with six CPUs, 10 GiB RAM,
two build jobs and two persistent compiler workers. Packages, graph sync and
tool downloads were prepared before timing. The same local disk cache and
output base served control and prepared runs, in that order; the source edit
added a public class to `OrchardCore.Abstractions` and was reverted after each
run. Build profiling was off. These are **single samples**, not a statistical
speedup claim.

| Bazel run | Combined action | Prepared Restore |
| --- | ---: | ---: |
| Baseline graph | 139.042 s | 198.271 s |
| API edit | 124.324 s | **118.108 s** |
| API-edit compilations | 193 | 193 |
| API-edit Restore actions executed | — | 0 |
| Revert | 8.680 s | 9.012 s |

The API edit saved **6.216 s (5.0%)** while the baseline cost **59.229 s
(42.6%)** more. In the same container, raw `dotnet build -c Release -m:2
--no-restore -p:NuGetAudit=false` took **32.448 s** for the API edit. Prepared
Bazel is still **3.64×** raw MSBuild on this sample. The prepared edit spent
195.452 cumulative assembly-action seconds versus 204.260 in the control;
the split did not reduce the 193 compilation actions. Both Bazel reverts
compiled zero projects and restored the baseline reference hashes. The same
89 reference assemblies changed in both API-edit runs.

Reproduce with `api_edit_matrix.py WORKSPACE OUTPUT --cases shared
--repetitions 1 --output-base BASE --disk-cache CACHE`, first with
`projectDefaults.preparedRestore` absent, then with it set to `true` and
`bazel run //:sync` rerun. The disposable Orchard graph built successfully;
the HTTP smoke test and an independent remote-cache consumer were not rerun.
The cold cost makes this mode an opt-in experiment. Further large-graph gains
need to reduce compilation-action staging and MSBuild work, not just Restore.
