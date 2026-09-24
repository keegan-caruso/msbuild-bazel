# Project-built analyzers

`analyzers` accepts `msbuild_library` targets as well as package targets. The
project edge consumes the implementation/runtime output and its declared runtime
closure, independently of the consumer's target framework. It does not export
compile references, packages, or runtime files to the application.

The evaluated ProjectReference must declare `OutputItemType="Analyzer"` and
`ReferenceOutputAssembly="false"`. Ordinary compile references retain the existing
matching-framework requirement. Ambiguous roles and unsupported reference
metadata fail closed.

The runner composes each tool's runtime closure in its own read-only input
directory, rejecting conflicting files. Managed DLLs are registered as compiler
analyzer inputs so Roslyn can resolve helper dependencies; adjacency alone did
not resolve a project-built helper in the execution test. Native DLLs are not
passed as analyzers. Conflicting assembly identities between independently loaded
analyzers and native tool dependency behavior are not qualified by this slice.

Linux workers stage project analyzers at a content-addressed path for the entire
load group: entry assembly, declared runtime closure, logical names and verified
input digests. Editing only a consumer keeps that path stable, allowing Roslyn to
reuse its loaded analyzer. A helper/resource change changes the whole group's
path. Every request recreates only its declared groups beneath the read-only
input mount; earlier groups are not left visible. Registrations from different
groups are never deduplicated by DLL name: doing so broke runtime generator
dependency resolution in the qualification experiment.

## Linux evidence

SDK 10.0.400, Bazel 8.4.2, ARM64, persistent workers:

- The unchanged OrchardCore.ContentPreview.Abstractions net10.0 project builds
  using the unchanged OrchardCore.SourceGenerators netstandard2.0 project.
- `tests/explicit_msbuild/project_analyzers.py` proves generated code executes,
  helper body edits invalidate the consumer, tools do not become application
  compile references, role mismatches reject, and a fresh Bazel output tree can
  compile a changed consumer using cached generator/helper outputs.
  The Bazel 8.8/9.2 controls additionally check stable consumer-edit paths, changed
  helper paths, and removal of a preceding request's group in a retained worker.
- Existing worker/shared-restore isolation and deleted-producer cache controls
  remain the regression suite; the Orchard compatibility probe includes the new
  successful analyzer edge and retains the ordinary cross-framework rejection.

Run the analyzer controls after the explicit acceptance fixture is initialized:

```sh
python3 tests/explicit_msbuild/project_analyzers.py /tmp/package-check
```

This qualifies analyzer execution, not full Orchard CMS compatibility or timing.
