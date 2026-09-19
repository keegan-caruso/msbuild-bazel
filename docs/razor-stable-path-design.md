# Razor stable paths across cache workers

Status: design only. No sandbox settings or build behavior changed, and the
experiments below have not been run.

## Problem

The cold-build investigation found physical workspace paths in Razor-generated
source embedded in PDBs, including `#line` and checksum directives. Changing the
workspace prefix also shifted generated tag-helper ID offsets. Independent cold
builds differed in 82 DLLs and 82 PDBs; these differences must not be described as
byte-identical builds. See [cold-build findings](cold-build-performance.md).

Our existing C# `PathMap` maps the private workspace to `/_/workspace`. It
normalizes PDB document names in the observed builds, but does not normalize all
embedded Razor-generated source text.

Successful remote-cache recovery is a separate property: a consumer can retrieve
the producer's exact output bytes without running Razor. That does not prove two
independent executions produce identical bytes.

## Razor path controls

For the source-generator mode we use, `EmitCompilerGeneratedFiles=true` and
`CompilerGeneratedFilesOutputPath` control where generated C# copies are written
to disk. Normally generator output stays in memory. This output location does
not itself replace the original source path embedded in generated code.

The upstream generator source inspected during research distinguishes:

- A logical view path, supplied through `AdditionalFiles.TargetPath` metadata.
- The physical source path, taken from `AdditionalText.Path` and retained when
  constructing the Razor source document.

Changing `TargetPath` alone therefore does not replace the physical source path.
No source-path mapping option was found in the generator configuration inspected.
This is not a claim that every Razor version lacks such a facility: the upstream
source browser can differ from our pinned SDK 10.0.400. The installed SDK's Razor
source-generator targets were also inspected, but the pinned generator's full
implementation has not been independently verified.

Sources:

- [Generated-file output properties](https://learn.microsoft.com/en-us/dotnet/core/project-sdk/msbuild-props#compilergeneratedfilesoutputpath)
- [Razor project-item construction](https://source.dot.net/Microsoft.CodeAnalysis.Razor.Compiler/SourceGenerators/RazorSourceGenerator.RazorProviders.cs.html)
- [Razor source-document and physical-path handling](https://source.dot.net/Microsoft.CodeAnalysis.Razor.Compiler/SourceGenerators/SourceGeneratorProjectItem.cs.html)

## Candidate: stable paths supplied by Bazel

Two Apple containers can use identical checkout and Bazel state paths, but normal
Linux sandbox paths still contain a per-execution identifier:

```text
/state/b/sandbox/linux-sandbox/570/execroot/_main/...
```

Cache hits and scheduling can change which identifier an action receives.
Matching container checkout paths alone is therefore insufficient.

Bazel 8.4.2 supports the experimental option:

```text
--experimental_use_hermetic_linux_sandbox
```

Source inspection shows this mode changes the filesystem root to the action's
sandbox and strips that sandbox prefix when entering the working directory. The
resulting action-visible working directory can be `/execroot/_main`, without the
outer state path or sandbox number. Each concurrent action retains its own
isolated filesystem.

This is the preferred first experiment. It could stabilize the source paths seen
by unmodified Razor while leaving action isolation under Bazel's control. It is
not yet a validated fix: action arguments, staged metadata, SDK paths, and other
absolute paths must also resolve correctly inside the new root.

The mode does not expose the host root automatically. Required SDK files, runtime
libraries, shell tools, and other dependencies need declared inputs or explicit
mounts. The implementation uses hardlinks for inputs where possible and copies
across filesystems, so qualification must also measure staging cost and verify
input integrity. Do not assume this has the same performance as the current
sandbox or that a successful build alone proves complete input declaration.

Pinned implementation references:

- [Bazel 8.4.2 sandbox option](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/sandbox/SandboxOptions.java)
- [Linux sandbox construction](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/java/com/google/devtools/build/lib/sandbox/LinuxSandboxedSpawnRunner.java)
- [Filesystem root and working-directory handling](https://github.com/bazelbuild/bazel/blob/8.4.2/src/main/tools/linux-sandbox-pid1.cc)

## Proposed qualification sequence

1. Use two Apple containers with the same pinned Linux image, architecture, SDK,
   Bazel, source revision, NuGet inputs, and build configuration. Give them private
   source and build state; share only the remote cache service. Start with a small
   Razor fixture that includes imports and tag helpers.
2. Build independently in both containers with action-cache reads disabled and
   empty local action state. Deliberately vary outer checkout/state paths and
   execution ordering. Record the actual paths seen by MSBuild and Razor.
3. Compare generated C# and final DLL/PDB bytes without rewriting or normalizing
   outputs. Require byte equality and verify application behavior. Diagnostic
   normalization may explain a mismatch, but cannot count as a passing result.
4. Repeat independent-build qualification on Orchard. Measure cold wall time,
   staging cost, and input-integrity checks against the existing sandbox mode.
5. Separately test remote-cache portability: container A seeds the cache, then
   container B starts with fresh local build state and consumes it. Verify cache
   hits, absence of compile execution for cached actions, recovered output hashes,
   and runtime behavior.

Keep the independent-build and cache-consumption results separate. Linux evidence
does not establish macOS sandbox behavior or cross-platform artifact equivalence.
If Bazel's experimental mode cannot support the required toolchain efficiently,
the fallback design to investigate is an action-private mount namespace exposing
a stable source root; that alternative is also unimplemented.
