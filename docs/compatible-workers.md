# Compatible-worker cache contract

Related: #41 / RUL-60; acceptance of a real worker pair belongs to #42 / RUL-61.

`--independent-workers` selects the conservative `darwin-arm64-worker-v1`
execution-host contract. Output TFM/RID remains a separate project graph input;
matching net10.0 alone never establishes worker compatibility.

## Bound inputs

- Exact native macOS ARM64 process/OS architecture, OS build and kernel description.
- CPU model, brand and visible logical CPU count. Different hardware misses until
  a broader equivalence contract is separately qualified.
- Complete pinned Nix SDK/runtime reference closure, controller/action/test tools,
  Starlark, external SDK imports and reviewed package/discovery policies by bytes.
- Bazel binary and system sandbox/signing/shell tools by bytes.
- Controlled compiler/discovery environment policy and independent-worker scope.

Source/project/package/configuration and dependency reference-assembly identities
remain in project keys. Controller checkout names, worker hostnames and source
paths are not compatibility inputs; exact compiled tool bytes are. Distribute the
same built controller artifact to workers, since independently built PDBs may differ.

The descriptor is emitted in `report.worker`, included in the project toolchain
key and discovery context, and carried in the immutable remote root. A differing
or missing descriptor rejects the root before downloading preparation/project
objects. Existing roots without a descriptor become misses. Recheck the worker
and all input/tool bytes before publication. Local plans cannot bypass this check:
the worker digest participates in their discovery context and project manifest.

Independent-worker mode only consumes remote project seeds and publishes snapshots
when sandboxed discovery qualifies the complete input grammar. Unsupported discovery
retains fresh execution but emits `remote.publicationSkipped`; it cannot turn a
fresh fallback into cross-worker cache evidence. Ordinary same-host mode has a
distinct identity and retains its previous fresh-fallback behavior.

## Host reads and assumptions

| Read class | Constraint |
| --- | --- |
| .NET SDK, tasks, runtime libraries, tools | Complete byte snapshots; pinned Nix paths and external imports |
| Authored XML, globs, source and restore metadata | Sealed discovery grammar, namespace snapshot, negative-observation checks |
| Generators/analyzers/package targets | Exact archive and reviewed import policy; unqualified packages cannot publish in independent mode |
| Environment, HOME, temp, NuGet | Cleared compiler/discovery environment; private roles; no action restore |
| System libraries, dyld, ICU, signing services | Same OS build and hardware; provisioned, unmodified system installation assumed |
| Other absolute filesystem reads / localhost | Darwin sandbox is not a complete read/localhost boundary; only the reviewed SDK/package/task slice is eligible |
| Clock, randomness, network, arbitrary user tasks | No equivalence claim for authored consumers of these inputs; outside qualified grammar |

This is a constrained compatible-host policy, not a general hermeticity claim.
Do not enable it for arbitrary SDKs, workloads, native assets or custom tasks.
System, home and workspace Bazel RC files are disabled for the managed invocation.
Remote compilation remains disabled by the Bazel rule. Tests execute against the
current runtime bundle. Cross-OS, cross-architecture and SDK relocation are excluded.

## Acceptance

Unit controls cover equality, each changed identity role, absent worker descriptors,
and rejection before any artifact fetch. A real separate-host run is required to
close #42. Local process/check-out isolation is useful rehearsal evidence only.


Measured on native macOS ARM64: owned .NET build/style checks, 32 preparation
and 19 workflow tests passed. Real four-project diamond controls passed: compatible
recovery compiled 0; changed OS build, SDK closure, Bazel identity and a legacy
root each compiled 4 and fetched only the selected root before rejecting it.
Unqualified XML compiled fresh and issued no PUT. These six consumer controls
are same-host evidence; reports are retained at `/private/tmp/wi2/report.json`.
The diamond uses a single `TargetFrameworks` entry to retain explicit framework
global properties; broader configured-graph qualification is unchanged.
