# Open-source build comparisons

This comparison adds Serilog, Spectre.Console and Polly to the existing Orchard
measurements. It exercises smaller graphs with source generators, analyzer
configuration, NuGet-provided C# sources and restore-only package downloads.
It is not a replacement for the 202-project Orchard scaling benchmark.

## Configuration

- Ubuntu 22.04 ARM64 Apple container, four CPUs, 8 GiB RAM; builds on native Linux
  storage. Linux x86-64 and macOS execution are not qualified by this run.
- .NET SDK 10.0.400; Bazel 9.2.0; normal untrimmed, non-ReadyToRun runner.
- Four persistent MSBuild workers, four Bazel jobs; raw `dotnet build -m:4`.
- Release, portable PDBs and reference assemblies on both sides.
- No disk/remote action cache for cold/no-op/edit comparisons. Packages,
  repository downloads and OS filesystem caches are warm.
- Three repetitions, alternating which engine runs first. Cold means cleared
  project outputs and stopped build processes; process startup is timed.
- Source acquisition, NuGet acquisition, graph inventory and explicit BUILD
  authoring happen before timing. These results model an already-authored Bazel
  workspace, not the cost of importing a new repository.

| Repository | Pinned revision | Selected graph | Projects | Evaluated Compile items | Locked packages |
| --- | --- | --- | ---: | ---: | ---: |
| Serilog | `bebc7719004f76187ae72e64ce138ec2540f2070` | Serilog, net10.0 | 1 | 113 | 2 |
| Spectre.Console 0.56.0 | `76b673337fe9d03ec41d0498987e53c4d5e7b33a` | Console + Ansi net10.0, generator netstandard2.0 | 3 | 338 | 26 |
| Polly 8.6.5 | `74bf31fff0e0907034994be4df22424aa71818f1` | Core + Extensions + RateLimiting + Testing, net8.0 | 4 | 205 | 16 |

All source pins and modifications are explicit in
[`projects.json`](../tests/explicit_msbuild/oss/projects.json). The stable Spectre
and Polly versions avoid their newer main-branch SDK/compiler requirements.
These are selected library graphs, not entire upstream solutions or test suites.

### Symmetric upstream adjustments

The disposable raw and Bazel copies both use SDK 10.0.400 and a single selected
framework per multi-targeted project. The netstandard2.0 source-generator project
retains its original framework. NuGet audit is disabled on both sides. The .NET 8
reference packs (8.0.30) are acquired before measurement and included in the SDK's
declared Bazel tool inputs.

The copies omit `.git`; Spectre and Polly skip MinVer. SourceLink reports missing
source-control information and emits empty mappings on both sides. These runs do
not measure Git-driven versioning or validate release publishing.

Spectre normally writes generated source into its source tree. Both copies move
that output under `$(IntermediateOutputPath)Generated`, retaining exclusion of
tracked `Generated/**/*.cs` files. This permits read-only source inputs without
disabling any generators. Polly sets `UseArtifactsOutput=false` on both sides so
ordinary per-project bin/obj paths are used. The temporary raw solution lists all
selected graph projects to ensure dependency configuration also remains Release.

## Results

Wall-time medians in seconds (raw MSBuild → Bazel):

| Project | Cold | No-op | Method-body edit |
| --- | ---: | ---: | ---: |
| serilog | 1.64 → 4.48 | 0.52 → 0.22 | 1.11 → 1.24 |
| spectre | 5.33 → 11.57 | 0.63 → 0.27 | 1.31 → 1.05 |
| polly | 4.23 → 11.05 | 0.62 → 0.17 | 3.37 → 4.19 |

Cold builds are 2.17–2.73× raw MSBuild on these small graphs. No-ops are
2.37–3.66× faster. Spectre edits are about 19% faster; Serilog and Polly edits
are about 12% and 24% slower. Every Bazel edit executes one assembly action;
all reference hashes stay unchanged within each engine.

Fresh-client cache recovery took 4.59s (Serilog), 6.53s (Spectre) and 7.41s
(Polly), with 1/1, 3/3 and 4/4 assembly cache hits respectively. The checks
compare 5, 58 and 25 runtime files, plus all reference DLLs, with the deleted
producer outputs.

Serilog and Polly reference DLLs are byte-identical between raw and Bazel.
Spectre reference DLLs are **not** byte-identical. An untimed control mapping raw
source/package paths to Bazel's logical paths makes its file-local type names
agree, but does not eliminate all reference hash differences. Full semantic
equivalence of Spectre outputs is not established by this experiment; do not
interpret its timings as release qualification. The user redirected further
investigation toward larger project graphs.

[JSON evidence](oss-build-benchmarks.json) includes every sample, median,
reference hash and package lock.

## Compatibility fixes exercised

The benchmark exposed generic package handling gaps, now covered by regressions:

1. Compare nuspec versions using NuGet version identity: `1.15.0+commit` and
   `1.15.0` identify the same package. Archive hashes and actual version/prerelease
   mismatches are still checked.
2. Preserve compile `contentFiles` supplied by a locked archive, including item
   metadata. Validation allows sources inside exact declared package roots;
   forged package metadata cannot authorize an undeclared project source.
3. Preserve valid `GeneratePathProperty` metadata so upstream targets can use
   NuGet-generated package paths. Invalid boolean values remain rejected.
4. Avoid synthesizing central versions for packages that SDK restore targets add
   implicitly later. Validate central pins for active package roles, allowing an
   independent restore-only baseline download with an otherwise unused central ID.

No production rule knows about these repositories. The test-only fixture author
also declares analyzer configuration files, package downloads and package hashes
explicitly. It retains MSBuild's SDK behavior rather than disabling analyzers,
source generators or package validation to obtain a successful build.

## Reproduction and scope

Commands and methodology are in the
[benchmark harness README](../tests/explicit_msbuild/oss/README.md). Use pristine
checkouts at the recorded commits and compare the generated package locks with
the evidence. Keep setup and validation outside measured commands.

Remote recovery uses a loopback HTTP action cache with full output downloads,
a deleted producer checkout/output base, and an independent relocated client.
Its single sample includes fresh Bazel server/repository startup. It demonstrates
cache reuse and matching artifacts; it is not WAN throughput, remote execution,
or a package-download benchmark. The SDK and OS caches remain available.

Neither byte checks nor successful compilation replace the upstream projects'
functional test suites. No upstream tests, packing, publishing, CI or network
cache service were run for this comparison.

## Repository validation

Linux `check-dotnet.sh` passed owned-code builds with warnings as errors, formatting,
five code-style checks, six tooling checks and thirteen explicit unit checks.
Worker acceptance passed including forged package-source rejection, read-only
inputs, failure recovery and relocated cache recovery. Eleven package-semantics
cases passed, including content files, path properties, late implicit packages
and baseline-download/central-version separation. `check.sh` passed toolchain and
Starlark checks using the verified 9.2 binary (the older image's prebuilt-Bazel
stamp does not describe that override). Python syntax and `git diff --check` passed.
