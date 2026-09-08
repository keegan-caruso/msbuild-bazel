# RUL-5: observed dependencies for preparation identity

Status: the recorder and the selected [discovery identity/eligibility
contract](discovery-contract.md) are implemented. Production reuse remains RUL-6.
The measured read-hook gaps require a sealed full-tree fallback for this first
qualified slice; an observation-only key remains unqualified.

## Decision

Use MSBuild's evaluation APIs to record the filesystem observations that determine
the evaluated graph. Before reusing preparation, recheck those observations.
MSBuild remains responsible for expanding properties, evaluating conditions,
resolving imports and matching globs. The adapter does not implement a second
import resolver.

This replaces whole-directory-tree hashing as the preferred starting design.
Conservative tree hashing remains an explicitly scoped fallback/comparison for
an uninstrumented domain; it does not establish complete read coverage. The
older content-identity prototype at `38680bb` remains preserved separately.

## MSBuild integration points

- `ProjectInstance.ImportPaths` supplies the actual nested import closure for each
  configured project. Include the root project separately. Use this as a content
  inventory and cross-check, not as the complete observation set: false conditions
  and unsuccessful existence probes are not represented by this list.
- `EvaluationContext.Create(SharingPolicy.Shared, MSBuildFileSystemBase)` permits
  a host-supplied filesystem implementation. Implement a thread-safe forwarding
  recorder for the filesystem operations exposed by this API. Allocate its state
  per capture; the API's Shared policy is not permission to reuse stale state
  across independent captures.
- `IDirectoryCache` / `IDirectoryCacheFactory` are additional integration points
  for evaluation existence probes and directory enumeration. Compare coverage
  and host wiring before selecting one implementation or combining them.
- `Project.GetAllGlobs()` can help inspect item globs. It is not a complete import
  or arbitrary-condition dependency recorder.

The first experiment must establish which hooks the pinned SDK 10.0.400 actually
uses. In particular, graph construction must use the recording evaluation context
for every configured node; do not assume an unrelated evaluation context affects
an already-created ProjectGraph.

## Observation contract

Each observation records the operation, normalized logical path, operation
arguments and observed result. Associate observations with the configured node
and evaluation when available; otherwise retain a conservative capture-wide
union. Preserve import order and actual enumeration results in diagnostic evidence.
Only normalize ordering for identity after qualifying that it cannot change the
selected operation's semantics.

| Observation | Recorded result | Revalidation |
| --- | --- | --- |
| Project/import/file read | Content digest of the bytes actually consumed | Re-read and compare content |
| File/directory existence | True or false, including absent paths | Repeat the same probe |
| Enumeration | Directory, pattern, recursion options and returned names/types | Repeat the same query and compare its qualified result representation |
| File attributes | Returned attributes used by evaluation | Compare under the qualified filesystem policy |
| Timestamp query | Value returned to evaluation | Apply the separately qualified timestamp policy; reject eligibility if none exists |

For example, an absent `optional.props` records `Exists=false`. Its later
appearance invalidates reuse even though no previously imported file changed.
An import of `extensions/*.props` records the enumeration, so a new matching file
invalidates reuse without parsing the Import expression ourselves.

The observation set supplements explicit invocation identity: entry points,
global properties, declared environment and build context, SDK/resolver/tool
identity, restore/package inputs, and recorder/preparation schema versions.
Consumer-declared extra inputs remain additive. A changed explicit build ID or
random invalidation value changes identity through this existing input contract;
no new MSBuild property is required.

## Capture and reuse sequence

1. Establish the explicit invocation and qualified evaluation environment. Start
   a fresh recorder and control MSBuild evaluation/project-root/SDK resolver
   caches so relevant observations cannot disappear behind prior process state.
2. Evaluate through MSBuild with the recorder attached. Record negative probes,
   nested imports and enumeration results as well as successful file reads.
   Cross-check imported paths against the recorded content inputs. Generated
   NuGet import wrappers must be observed too; the current diagnostic inventory's
   wrapper omission is not an allowed hole in the reuse design.
3. Validate capture completeness and stability. Hash consumed bytes, rather than
   reading a potentially different file afterward. Inconsistent repeated reads,
   changing enumerations or unsupported access paths make capture ineligible.
4. Use explicit invocation identity to find a candidate prepared result and its
   recorded dependency set. Revalidate the candidate's observations before reuse;
   the discovery set itself is learned by evaluation, so it cannot be assumed
   known before the first capture.
5. Reuse only if invocation, observations, eligibility contract and prepared
   artifact integrity all match. Otherwise reevaluate and record a replacement.
   RUL-6 owns atomic publication, interruption recovery and concurrent consumers.

Rechecking observations is not an atomic filesystem snapshot. Qualification
must use an immutable staged input view or a proven consistency protocol across
validation and consumption. A before/after check alone does not rule out all
concurrent changes. Relocation requires logical root mapping and independent
qualification of path-sensitive observations; this design does not assume it.

## Coverage and time boundary

These hooks expose some filesystem operations; they are not an operating-system
sandbox or a complete dependency log for arbitrary managed code. Test SDK
resolvers, property functions, project-root caches, environment reads and any
preparation-time target/task/process execution for bypasses. Record their inputs
through separately qualified contracts, enforce an allowed read domain, or reject
reuse for the affected slice. A clean XML diagnostic report is not eligibility.

Content hashes remain the default file identity. This proposal does not adopt
mtime-based cache keys. If evaluation reads timestamps, recording reveals that
dependency but does not settle how timestamps should be staged or recovered.
Retain the equal-content/different-timestamp negative control and the existing
[deterministic CI contract](deterministic-ci-contract.md). Explicit build dates
are ordinary inputs; Git-derived values require their Git inputs; application
runtime clocks remain outside build-discovery diagnostics.

## Implementation and acceptance

The forwarding-recorder experiment and discovery contract exercise:

- Compare plain MSBuild and recorded evaluation for identical configured graphs.
- Import props through nested, property-selected and wildcard imports; modify an
  imported file and verify invalidation.
- Add/remove optional imports and wildcard matches, including previously absent
  directories; negative probes must appear in the recording.
- Change configuration and declared build context; record SDK/package/generated
  NuGet imports and verify ownership across configured nodes.
- Exercise fresh and warmed project/evaluation/SDK caches. Missing hook coverage
  must reject eligibility rather than silently produce a smaller dependency set.
- Test property-function and resolver bypasses, symlinks, timestamps, concurrent
  mutation and malformed observation state, retaining explicit negative controls.

RUL-5 closes only when the selected invocation identity and observation/eligibility
boundary pass those controls. RUL-6 then qualifies actual preparation reuse and
publication; RUL-7 measures validation cost versus reevaluation. Neither a smaller
input list nor successful recording alone establishes a performance improvement.

## API/source references

- [ProjectInstance import APIs](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.execution.projectinstance?view=msbuild-17-netcore)
- [EvaluationContext.Create](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.context.evaluationcontext.create?view=msbuild-17-netcore)
- [MSBuildFileSystemBase](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.filesystem.msbuildfilesystembase?view=msbuild-17-netcore)
- [Directory-cache interfaces](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.filesystem?view=msbuild-17-netcore)
- [Exists condition implementation](https://source.dot.net/Microsoft.Build/Evaluation/Conditionals/FunctionCallExpressionNode.cs.html)
- [Project.GetAllGlobs implementation](https://source.dot.net/Microsoft.Build/Definition/Project.cs.html)
