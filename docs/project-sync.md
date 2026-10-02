# Project synchronization

`msbuild_sync` evaluates entry `.csproj` files and their configured MSBuild graph,
then writes committed `graph.generated.json` and `graph.generated.bzl`. Bazel
supplies the SDK and generator; application developers run `bazel run //:sync`.
There is one graph backend. `.sln`/`.slnx` orchestration can select entries but does
not replace each project's evaluated MSBuild semantics.

## Update cycle

- Body edits: build/test normally.
- Project/props/targets, source lists, package or configuration changes: run sync and
  commit both generated files.
- Build servers: `bazel run //:sync -- --check` fails on stale declarations without
  rewriting them.

Keep the sync target in the workspace-root BUILD file. Generated files do not
modify that authored file. Use the [quickstart](../examples/quickstart/README.md).

## Attributes

| Attribute | Contract |
| --- | --- |
| `projects` | Entry project paths relative to the workspace |
| `configuration` | Persistent graph configuration; default `Release` |
| `framework` | Optional entry framework; empty retains authored frameworks |
| `inputs` | Producer labels mapped to logical input-file paths |
| `package_lock` | Closed package inventory, including package SDKs |
| `package_build` | Allow disposable offline Restore and package target/content evaluation |
| `package_inputs` | Additional files read by reviewed package tasks |
| `bindings` | Complete declared tool layouts bound to task properties |
| `mappings` | Reviewed JSON input/output/dependency contracts |

Complex conditions remain explicit through configuration and contracts. MSBuild
selects project-reference configurations and NuGet assets. Sync rejects unsupported
metadata and custom tasks without contracts instead of flattening them.

## Reviewed mappings

`projectDefaults` shares contracts; `projects` overrides by project path;
`frameworkOverrides` refines a project's configured variants. Defaults merge
recognized dictionaries; overriding a document replaces the whole record so an
old digest cannot survive a partial override. Duplicate/case-ambiguous fields,
unknown fields and unsafe paths fail.

Supported project contracts:

- `documents`: SHA-256, target/task names and extra inputs for authored build documents.
- `inputItems` / `evaluationItems`: declared custom file items or reviewed evaluation-only items.
- `outputFiles`, `inputDirectories`, `temporaryDirectories`: additional owned products,
  generated input trees and disposable task scratch.
- `referenceBoundary`, `implementationDependencies`, `compilerReference`,
  `compilerReferences`: reviewed compiler/implementation roles, including separate
  contract/implementation projects and configured producer selection.
- `preparedRestore`, `restoreInputs`, `restoreOutputs`: separately reusable offline Restore.

`projectDefaults.properties` supplies graph-wide properties. `entryProperties`
specifies root properties without flattening authored coordination frameworks.
SDK paths, PathMap and Restore locations/sources remain controlled by declared inputs.
A document digest approves only the listed contract at that content; new build logic
requires review and a new digest.

## Limits

Sync is an explicit local job, not analysis-time XML parsing. It may evaluate
configured variants and, when requested, Restore in a disposable workspace.
It does not fetch missing packages, infer every custom task's filesystem reads,
or qualify arbitrary SDKs/workloads. Use small independent fixtures when extending
contracts. [Runtime qualification](runtime-qualification.md) records the larger
reviewed slice and its translations.
