# Proposal: stable project paths and explicit reference boundaries

**Status: proposed full design; a [bounded synthetic prototype](stable-project-paths.md)
is implemented behind an internal gate.** Based on the
[Orchard measurements](orchard-reference-boundaries.md) at main `7d63ab9`.

## Decision

Separate the identity of a project from the identity of its current inputs.
MSBuild sees stable project/source/asset paths. Compiler references and loaded
tools retain content-versioned paths. Bazel still keys actions on every declared
input and owns scheduling, caching and test invalidation.

Then migrate selected application libraries to explicit direct references. These
are separate changes with separate measurements. Stable metadata alone cannot
remove the 193 compilations while C remains an input to those compiler actions.

## 1. Three identities with distinct jobs

| Identity | Changes when | Used for |
| --- | --- | --- |
| Logical project/configuration key | Target, framework, build configuration, platform or declared global configuration changes | Stable compiler-visible project and output roots |
| Input content identity | Any declared action input changes | Snapshot verification, diagnostics and request invalidation; never the project root |
| Artifact/load-group identity | A referenced DLL or an entire tool/analyzer closure changes | Versioned compiler reference and tool paths |

The logical key is a versioned hash of a normalized descriptor emitted by
Starlark: repository-qualified target label, project-relative path, framework,
configuration, platform/RID, output role and declared global configuration.
Exclude workspace/output-base locations, worker IDs, timestamps, source contents,
dependency contents and dependency membership. Do not hash the whole request JSON.
A source or reference-list edit must not rename the project directory. Use an
explicit internal descriptor, not an opaque Bazel output-directory hash.

Proposed child-visible layout:

```text
/__rules_msbuild/in/projects/<project-key>/src/...   # project, imports, assets
/__rules_msbuild/out/<project-key>/obj/...          # freshly cleared each request
/__rules_msbuild/out/<project-key>/out/...
/__rules_msbuild/in/artifacts/<digest>/B.dll        # explicit compiler reference
/__rules_msbuild/in/analyzers/<closure-digest>/...
/__rules_msbuild/in/tools/<closure-digest>/...
```

The descriptor's project-relative paths preserve the source layout below the
project root, including common imports. Package views may retain their required
NuGet directory layout, backed by verified versioned payloads. SDK mounts retain
their existing pinned locations. Stable generated-source/output roots prevent
moving the same problem from checked-in assets to generated assets.

An unchanged Setup asset therefore keeps the same physical path across a C API
edit. Its bytes, declared membership and resource metadata remain normal Bazel
inputs. An actual asset change still rebuilds the appropriate producer and runtime
consumers. No rewriting of compiled DLLs or special casing of Orchard attributes.

## 2. Preserve worker correctness explicitly

### Filesystem and request state

The broker retains its verified snapshot store and private physical storage.
It stages only the current request beneath the stable child roots, with input
mounts read-only and output mounts writable. The worker remains sequential;
separate worker processes retain separate mount namespaces.

Finish a request before clearing/replacing its trees. Clear output/intermediate
state on every request; stable paths do not authorize reusing `obj` files. Remove
undeclared files and stale generated directories before the next evaluation.
Failures, timeouts and child restarts must not publish partial outputs or leave a
request-dependent environment for the next request. Continue existing digest,
input/output-overlap and output-symlink checks.

### MSBuild XML and evaluation

Start with `reuseProjectRootElementCache: false` for the stable-path mode, using
fresh collections/instances for Restore and Build as today. A fresh collection
with singleton reuse enabled is not sufficient: `ProjectCompilation` currently
opts into that singleton specifically because request XML has content-versioned
paths. The rewritten project can also change when references change, even if the
original csproj bytes do not.

This deliberately gives up some XML parsing reuse to establish a correct baseline.
Measure it separately. A later optimization may reuse verified immutable SDK XML
or digest-validated request XML, but it must cover added/deleted imports, rewritten
projects and restore-generated imports. Do not base correctness on file size,
mtime, `UnloadAllProjects`, or an assumed complete import list. Prefer public
MSBuild APIs; do not introduce private cache surgery in the first implementation.
The [MSBuild implementation](https://source.dot.net/Microsoft.Build/Definition/ProjectCollection.cs.html)
distinguishes private root caches from the optional shared singleton.

### Compiler metadata, analyzers and tasks

Move explicit reference `HintPath` values out of the stable workspace's current
`.references/<name>.dll` locations and point them at verified digest-qualified
files. A same-name, same-size, same-mtime DLL replacement must get a different
compiler path. Preserve conflict detection and assembly selection rules. Keep
runtime copy/deps-manifest resolution consistent with the selected assemblies.

Retain `ProjectAnalyzers.WorkerRoots`' existing whole-closure identity: changing a
helper or resource must change the load-group identity, not just the entry DLL.
Apply that principle to build tools and package-provided compiler/task closures;
never relocate a mutable task DLL to a stable path merely for prettier output.

Fresh MSBuild evaluation does not unload arbitrary in-process tasks or their
static state. The first prototype must track a conservative task-host compatibility
identity (SDK/runner plus declared loadable task closures) and recycle the compiler
child when compatibility changes. Unchanged source/reference edits with unchanged
task closures should retain it. Cross-project task-closure changes may increase
restarts: measure and report them. Relax that rule only with proven load isolation;
do not assume versioned paths alone make arbitrary managed task loading safe.

These rules implement the distinction in Bazel's
[worker protocol](https://docs.bazel.build/versions/main/creating-workers.html):
request digests permit verified reuse, but retained process state is still the
worker's responsibility.

## 3. Dependency migration stays explicit

Keep SDK-compatible transitive references as the default. Use the existing
library attribute/mapping, or evaluated `DisableTransitiveProjectReferences`, for
reviewed opt-ins. Do not infer private dependencies from which types happen to be
used in today's source, and do not silently remove transitive inputs after a
successful trial compile.

For each selected Orchard library:

1. Inventory its direct references and compiler-visible transitive assemblies.
2. Trial direct-only compilation in a disposable workspace. Report missing assembly
   names, their producing labels, and ambiguous ownership; produce a reviewable
   mapping/project diff rather than mutating dependencies during a build.
3. Declare required project/package references explicitly. Preserve framework
   selection, friend-assembly, analyzer, private dependency and runtime roles.
4. Build that library and its consumers; test API exposure, missing-reference
   failure/repair, body edits, API edits and runtime/test invalidation.
5. Retain the opt-in only as an intentional dependency contract. New callers may
   need new direct references even if today's callers compile successfully.

Start with one real chain where B hides C and one where B exposes a C type, then
expand to higher-fan-out libraries. Binaries/tests retain their existing transitive
runtime-manifest boundary. No Orchard-specific production rule or global switch.
The 31 existing direct consumers of Abstractions are not a promised final rebuild
count: explicit migration can reveal more genuinely required references.

## 4. Rollout and acceptance

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| 1 | Synthetic path and cache regressions | Reproduce public FullPath metadata churn and stale-input hazards before changing behavior |
| 2 | Stable project/output roots, versioned artifacts, conservative cache policy | Source-only edits preserve asset paths; same-size/time XML/DLL/tool changes are observed; no stale files or state |
| 3 | Bazel 8.8/9.2 and independent HTTP-cache qualification | Producer stopped, different consumer path, empty local action state, matching deterministic outputs, cached and forced tests |
| 4 | Orchard path-only experiment | Unchanged asset-path lists remain identical; baseline CMS smoke/assets pass; attribute remaining reference changes separately |
| 5 | Selected explicit dependency migrations | Unchanged B reference stops A compilation when A does not consume C; exposed C types still require C |
| 6 | Matched large-graph timings and targeted profiling | Record recompilation counts and cost per action; preserve body-edit behavior and identify remaining API overhead |

Required synthetic cases include:

- A→B→C with unused public additions, propagated public constants, and a B API
  exposing C; include fan-out and an unrelated branch.
- A module-like library embedding `FullPath`, including body-only edits, changed
  dependency references, asset add/remove/content edits and generated assets.
- Same-size/same-mtime source, project, props/targets, reference, analyzer helper,
  package task and build-tool edits; file deletion and failure followed by repair.
- Same worker switching projects/configurations; multiple workers concurrently;
  child restart; read-only input mutation rejection; no undeclared old file access.
- Runtime closure and tests responding to implementation changes while compile
  actions stop at stable reference outputs.

Separate four benchmark variants: current baseline, path-only candidate,
explicit-reference-only candidate, and combined. Use identical declared SDK,
resources, cache settings, build/test scope and at least three alternating paired
samples. Measure XML evaluation, child restarts, compiler reuse, staging, reference
changes and wall time. The 154.178/29.798-second API comparison is a baseline,
not a prediction for the candidate.

Orchard's random interceptor generator remains an upstream limitation. Use unchanged
Orchard for the headline compatibility/timing result. If a deterministic generator
patch is needed to attribute path-only churn, record it as a separate diagnostic
fixture with its exact patch. Do not claim all 89 references will become stable
or hide remaining randomness in normalized output comparisons.

## 5. API and implementation surface

No new user-facing switch in the initial prototype. Use an internal path-layout
version during qualification; make the stable mode the default for qualified Linux
workers only after the gates pass. Runner/request changes must change action
identity and worker compatibility so old and new cache entries cannot be confused.
Existing cache entries can expire naturally; no global cache purge is required.
Non-worker platforms and remote execution need separate qualification before a
broader support claim.

Likely implementation areas:

- `msbuild/private/project.bzl` and `BuildRequest`: logical descriptor/layout version.
- `LinuxWorker`: stable mounts, artifact identities and child lifecycle policy.
- `BuildPreparation`/`ProjectDefinition`: separate project files from compiler/tool
  artifacts and generate digest-qualified paths.
- `BuildProperties`, `PreparedRestore`, generation/layout bindings: stable output
  paths, correct restore metadata, runtime closure and generated-file references.
- `ProjectCompilation`: private XML caches for the initial baseline.
- Analyzer/build-tool/package code: preserve load-group identity and isolation.

## Review decisions

Recommended choices are:

1. Implement generic stable project paths first, then explicit graph migrations.
2. Accept a measured temporary XML-parse/restart cost to establish correctness;
   optimize those costs only if they are significant in the large graph.
3. Preserve transitive defaults and require explicit per-library opt-ins.
4. Judge success first by stable metadata and correct invalidation, then by the
   full paired performance matrix. If genuinely required compilations remain
   expensive, profile execution overhead rather than continuing to prune valid inputs.
