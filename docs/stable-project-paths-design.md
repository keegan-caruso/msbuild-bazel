# Stable project paths and reference boundaries

**Proposed beyond the [bounded synthetic prototype](stable-project-paths.md).**
The [Orchard API-edit measurements](orchard-reference-boundaries.md) found two
causes of extra compilation. A middle project embeds changing file paths in its
reference assembly. Consumers also receive transitive compiler inputs required
by current MSBuild semantics. First stabilize those paths; then review direct
references project by project. Stable paths alone cannot skip a compile while
the changed leaf remains a declared compiler input.

## Identity and state

| Identity | Stable across | Changes for |
| --- | --- | --- |
| Logical project/configuration key | Source and dependency content edits | Target, project path, framework, configuration, platform/RID, global configuration |
| Input digest | Workspace relocation | Any declared action input change; verification and action caching |
| Artifact/load-group digest | Unrelated project edits | Referenced DLL or executable tool/analyzer closure change |

Bazel still owns declared inputs, action caching and scheduling. MSBuild sees a
stable project/source/asset/output root; compiler references and loaded
analyzers/tools retain digest-qualified paths. The logical key must exclude
workspace/output-base locations, timestamps, input bytes and dependency
membership. A source edit must not rename an asset path that upstream code
embeds in metadata.

The worker must stage only the current request, keep input mounts read-only,
clear intermediate/output state each time, and remove stale files after failure.
It must verify digests and reject input/output overlap or escaping links.
Start with fresh MSBuild project/XML collections for mutable stable paths;
size/mtime checks and `UnloadAllProjects` are insufficient. Measure lost XML
cache reuse before optimizing it. Loaded tasks may retain process state:
recycle the compiler child on incompatible SDK/task closures until isolation is
proved. A versioned file path alone does not unload a managed task.

Compiler `HintPath` values should point to digest-qualified references so a
same-name, same-size, same-mtime replacement cannot reuse stale compiler data.
Analyzer and tool helpers need whole-closure identities. Runtime copies and
dependency manifests must continue selecting the matching implementation.
These constraints keep path stability from weakening input correctness.

## Dependency migration

Preserve SDK-compatible transitive references by default. A direct-reference
opt-in must be reviewed per library; do not infer dependencies from today's
source or silently remove them after a successful compile. For each candidate,
compare its direct and transitive compiler inputs, trial direct-only compilation,
make missing project/package edges explicit in both csproj and BUILD, and check
API exposure, friend assemblies, analyzer/tool inputs, runtime data and tests.
A hidden C in A→B→C may stop A recompilation when B's public reference stays
stable. If B exposes a C type, A still needs C or must fail clearly. Executable
runtime closure remains separate from the compile boundary.

## Qualification before defaulting the mode

1. Prove a synthetic chain, fan-out and unrelated branch with body, API,
   constant, resource and props edits; include delete/re-add, failure/repair,
   same-size/timestamp replacement and worker restarts.
2. Check both Bazel 8.8.0 and 9.2.0 and independent HTTP-cache recovery from
   another workspace with no producer outputs or local action cache. Match
   reference/implementation/PDB bytes and force dependent tests to run.
3. Qualify package, task, analyzer, generated and prepared input roles. Keep
   unknown roles behind the prototype gate; do not permit them by default.
4. Measure Orchard with paths alone, direct references alone, and both changes.
   Attribute reference changes and compilation counts separately. Use at least
   three paired samples with equal SDK, resources, cache state and build scope.

The prototype remains off by default via
`--define=rules_msbuild_stable_path_prototype=1`. No user-facing rule attribute
should be added before the gates pass. A layout-version change must affect
Bazel action and worker compatibility; existing cache entries can expire
naturally. Remote execution and non-worker platforms require their own
qualification. The original detailed implementation sketch and full scenario
matrix remain in the
[pre-condensation design](https://github.com/keegan-caruso/msbuild-bazel/blob/4ab387c59ddf5fda46d15646cf0f738d9a0026a0/docs/stable-project-paths-design.md).
