# Ordinary Spectre baseline

The unchanged upstream selected graph builds with SDK 10.0.400 on native macOS
ARM64. Console and Ansi select net10.0; their source generator retains
netstandard2.0. No upstream project declarations were edited, and build-time
tools remained enabled. This is ordinary MSBuild evidence, not adapter acceptance.

## Repeatable command

With the repository's pinned SDK selected through RULES_MSBUILD_DOTNET_ROOT:

```sh
python3 tools/probe_spectre_baseline.py \
  --source /path/to/pinned-spectre-checkout \
  --packages /path/to/restored/packages \
  --output /path/to/new-evidence-directory
```

The helper makes a standalone local clone with independent Git objects, checks out
revision `2dc90b90add956c2f6777cb659120900ac2eb740`, preserves the source repository's
origin URL, copies packages to its own writable cache, and performs a full restore.
It builds the selected Console graph, repeats that build, queries evaluated items
and post-build identity, saves preprocessed projects, and runs the same Spinner/Color
reflection oracle prepared for the acceptance harness. It does not mutate or build
in the supplied checkout. Output directories must be new.

Validation on 2026-09-07 used `/private/tmp/run-sdk-latest`,
`/private/tmp/msbuild-pilot-spectre` and
`/private/tmp/spectre-package-probe/.nuget/packages`. Final retained evidence is
`/private/tmp/spectre-ordinary-baseline-final/report.json` and adjacent command logs.
These local paths are evidence locations, not portable artifacts.

## Observed inputs and results

- Cold and unchanged builds succeeded with zero warnings and zero errors. All
  three `CoreCompile` targets skipped on the unchanged invocation; MinVer still
  ran for dependencies. This is an incremental MSBuild control, not a timing claim.
- The output reflection oracle found 90 generated spinners and 291 colors.
  `Spinner.Known.Default` has an interval of 100 milliseconds and eight Unicode
  frames. The helper retains complete observed values for comparison.
- Console's AdditionalFiles are `spinners_default.json`,
  `spinners_sindresorhus.json`, and `emoji.json`; Ansi's is `colors.json`.
  The generator has no AdditionalFiles of its own.
- Console has two project references, Ansi has one, and the generator has none.
  Post-build Compile item counts were 311, 37, and 13 respectively; analyzer counts
  were 19, 19, and 11. These include SDK/package-generated inputs and are not a
  complete filesystem read inventory.
- `src/Directory.Build.props` and `src/Directory.Packages.props`, SDK imports,
  generated NuGet imports and package build imports participate in evaluation.
  The saved preprocessed projects preserve the actual import paths and contents;
  `MSBuildAllProjects` alone is insufficient as a complete import inventory.
- The reports retain each project's full restore library list, including
  nonselected framework entries. Packages include MinVer 8.0.0, SourceLink
  10.0.400, Roslynator 5.0.0, Polyfill 11.2.0, Wcwidth.Sources 4.0.1,
  NETStandard.Library 2.0.3, and the generator's Roslyn 5.9.0/System.Text.Json
  10.0.11 dependencies. `resources/spectre.snk` remains the signing input.

## Git identity discrepancy and integration requirement

A plain local clone changes `origin` to the local source path. The first baseline
therefore built successfully but emitted six SourceLink warnings and empty
SourceLink mappings. Restoring the original
`https://github.com/spectreconsole/spectre.console.git` remote resolved those
warnings and produced mappings to the exact pinned revision on GitHub. Acceptance
must preserve and validate this metadata, not accept successful compilation with
empty SourceLink output.

The supplied source is shallow and has no tags. Its measured MinVer version is
`0.0.0-alpha.0`, assembly/file version `0.0.0.0`, and informational version
`0.0.0-alpha.0+2dc90b90add956c2f6777cb659120900ac2eb740` for all three projects.
`SourceRevisionId` is the pinned revision while evaluated `RepositoryCommit` is
empty. The helper records shallow state, tags and hashes of Git metadata files.
Changing history depth or available tags changes the input boundary; these values
are not evidence of release-version correctness with a full repository history.

Adapter qualification must preserve Git-dependent behavior, declared package/task
inputs, selected frameworks, generated API behavior, exact invalidation worksets,
and producer-free relocated recovery. The ordinary baseline does not establish
sandboxed Git access, deterministic Git staging, remote correctness, full host
closure, broader frameworks, or a complete upstream test-suite result.
