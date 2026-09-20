# Orchard compatibility with the explicit Bazel rules

## Result

**The current explicit rules cannot yet build Orchard unchanged.** Raw MSBuild
builds the selected CMS application successfully on the same Linux SDK. Four
focused Bazel probes establish package/tooling blockers before meaningful Orchard
performance measurement can begin. No production rules or Orchard source were
changed to work around them.

- Orchard commit: `04467a3438d4255627c1a478598a1585b3ff2947` (existing clean checkout;
  this is a pinned snapshot, not a claim about current upstream HEAD).
- Rules commit: `ad86a0c`.
- Entry: `src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj`, Release.
- Platform: Ubuntu 22.04 Linux ARM64 Apple container, four CPUs/6 GiB, SDK 10.0.400,
  Bazel 8.4.2, native Linux filesystem.

## Evaluated workload

Recursively evaluated ProjectReference items, including imported declarations,
selecting each project's declared single target framework. This is an evaluation
inventory before restore, not a substitute for executing all build targets or
recording every NuGet-generated import.

| Property | Count |
| --- | ---: |
| Projects in the CMS dependency closure | 202 |
| net10.0 projects | 201 |
| netstandard2.0 source-generator project | 1 |
| Microsoft.NET.Sdk projects | 113 |
| Microsoft.NET.Sdk.Razor projects | 88 |
| Microsoft.NET.Sdk.Web projects | 1 |
| Projects using central package versions | 202 |
| Projects with private package references | 202 |
| Consumers with analyzer ProjectReference edges | 200 |
| Evaluated project edges, including analyzer edges | 1,400 |

There are 17 repository-owned imported props/targets files in this pre-restore
inventory. The pinned SDK satisfies Orchard's global.json request for 10.0.302
with latestMajor roll-forward.

## Confirmed explicit-rule blockers

| Feature | Probe and observed result | Required generic capability |
| --- | --- | --- |
| Project-built source generator | The real generator used through `analyzers` fails Bazel analysis: missing MSBuildPackageInfo provider | Allow declared project-built analyzer/tool outputs, including their runtime dependency closure |
| Separate tool framework | Treating that generator as an ordinary `deps` edge fails matching-framework validation: net10.0 versus netstandard2.0 | Keep analyzer/tool edges separate from compile-reference edges; preserve OutputItemType=Analyzer and ReferenceOutputAssembly=false |
| Private package propagation | Building the unchanged generator with declared locked packages fails `PrivateAssets package propagation is not qualified in this slice` | Preserve private/direct/transitive NuGet asset roles rather than rejecting or stripping metadata |
| Central package versions | An isolated centrally managed StyleCop reference fails NU1008 after the runner adds Version to PackageReference | Consume the locked resolution while respecting PackageVersion/central pinning semantics |

The first three use actual Orchard project files and their evaluated imports. The
central-version probe is deliberately a minimal synthetic fixture: Orchard's
private/global packages otherwise fail earlier and mask the independent NU1008
problem. It uses the same central-management flags and StyleCop version, with no
PrivateAssets declaration. It does not represent a successful Orchard conversion.

The generator also has an implicit NETStandard.Library version range and private
Roslyn packages. The current original-version validator compares literal strings
to the locked version; range handling needs qualification within the package work.
That additional issue is source-reviewed, not independently reached in these builds.

## Module/Razor behavior that still needs qualification

There is a concrete dependency-metadata gap beyond compiling DLLs. Orchard's
`OrchardCore.Application.Targets.targets`, target `ResolveModuleProjectReferences`,
calls `GetModuleProjectName` on `_MSBuildProjectReferenceExistent` and uses returned
items to emit `ModuleNameAttribute` assembly attributes. The explicit runner removes
ProjectReference items and substitutes Reference DLLs. Its assembly provider carries
reference/runtime/package files, but no generic referenced-target results. Merely
getting the compiler to succeed could therefore omit module discovery metadata.
This is a source-reviewed structural gap, not a measured runtime failure here.

Keep the solution generic: declared target-output/item metadata must be able to
cross an appropriate Bazel dependency edge. Do not introduce an Orchard-specific
module-name attribute or hard-code module discovery in the rule implementation.

The 88 Razor projects also need actual qualification for generated Razor items,
embedded resource names/assets, static web assets, and path-sensitive output reuse.
The module targets generate marker/asset attributes and transform resource logical
names. The web project's `EnsureWwwRootExists` target can create directories under
the project source path; its interaction with a read-only staged source tree needs
a test. None of these are certified by the existing package-free worker benchmark.

## Working raw-MSBuild control

The unchanged ContentPreview.Abstractions leaf and its SourceGenerators dependency
build successfully with zero warnings/errors. The full CMS application also builds
with zero warnings/errors, and the resulting application starts and returns HTTP
200 at `/` (50,175 response bytes). No tenant setup was submitted. The HTTP smoke
is a startup check, not a full functional/module-discovery assertion.

Packages were restored from existing cached archives exposed as a flat local feed;
no package versions or application files were changed. SDK/tool builds and NuGet
restore ran on native Linux storage. The raw control was not timed as a performance
baseline: prior leaf builds warmed state, and compatibility probes overlapped part
of the control. Do not compare its log's elapsed time to the synthetic benchmark.

## Recommended implementation order

1. **Package semantics:** central versions/pinning, locked version-range validation,
   and PrivateAssets/direct/transitive role propagation. Prove an unchanged ordinary
   Orchard library and the generator's package set.
2. **Project-built analyzer/tool edges:** carry implementation DLLs and tool runtime
   dependencies, allow the generator's independent netstandard2.0 framework, and
   test generated output plus generator edits. Do not relax normal dependency
   checks to pretend analyzer edges are ordinary references.
3. **Referenced-target metadata and Razor/module assets:** preserve imported SDK
   target behavior through generic declared inputs/outputs. Verify the CMS module
   inventory and startup, then test Razor/resource edits and fresh-worker cache reuse.

Only then collect comparative Orchard timings. The shared-restore optimization
used in the synthetic benchmark is intentionally unavailable here: Orchard has
packages, imports, framework references and custom targets.

## Reproduction and evidence

[Summary](evidence/orchard-explicit-compatibility/summary.json) includes the revision,
workload counts, import inventory, raw control and four expected failures. The same
directory contains concise project evaluations and full probe/raw-build logs.
The large per-source evaluation inventory remains local in
`artifacts/orchard-compatibility/evaluated.json`.

The harness is under `tests/explicit_msbuild/orchard_compatibility/`; its README
specifies Linux paths and commands. It is compatibility-test scaffolding, not a
production BUILD generator or an Orchard-specific rule API. The probes fail only
when the expected error appears; unrelated errors do not count as confirmation.

No production C#/Starlark files changed. Python syntax checks and `git diff --check`
pass. All four negative probes and both raw build controls completed successfully;
no GitHub CI ran. The task container was removed after saving evidence.
