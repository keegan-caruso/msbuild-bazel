# Spectre central package and build input prerequisites

This change enables the narrow central package version contract needed by pinned
Spectre.Console revision `2dc90b90add956c2f6777cb659120900ac2eb740`. It does not
claim end-to-end Spectre adapter acceptance.

Graph export reads the evaluated `PackageVersion` for each explicit centrally
managed `PackageReference`, preserving imports, conditions and property evaluation.
It compares the request with both the project's assets and consumer restore
snapshots. Version overrides, central transitive pinning, ambiguous central versions,
and inline versions combined with central management are rejected. Exact version
ranges or explicitly pinned pilot versions remain required. SDK implicit package
versions remain SDK-owned. Python preparation and the action runner defer missing
inline versions to this evaluated validation rather than trying to evaluate raw XML.

The selected Console/Ansi net10.0 and generator netstandard2.0 package closures add
25 exact archive SHA-256 and restore-content-hash pins. Each pin enumerates its
payload roots and restored asset roles. This includes Wcwidth source content,
Roslyn analyzers, NETStandard reference assemblies, MinVer and SourceLink tasks.
Existing archive/payload integrity verification remains in place. Package sources,
imports, analyzers and the signing key use existing graph input discovery; this
change does not admit arbitrary package-owned build inputs.

## Evidence

On macOS ARM64 with SDK 10.0.400, an unmodified disposable source archive restored
successfully using:

```sh
dotnet restore src/Spectre.Console/Spectre.Console.csproj \
  -p:Configuration=Release --packages "$PWD/.nuget/packages"
```

The full restore preserves the generator's netstandard2.0 target. Setting the global
`TargetFrameworks=net10.0` instead changes the generator restore to net10.0 and is
not a valid way to select this graph.

The existing 12 restore-semantics tests passed. Focused central-version tests cover
successful graph preparation and rejection of a changed central version without
restore, including a dependency-only restore that leaves its consumer snapshot stale.
All three focused central-version tests passed. Package policy tests retained
repacked-archive rejection (two passed; the optional Serilog test was skipped).
All 25 new package archives and extracted payloads matched the recorded hashes.
GraphExport and ActionRunner formatting checks and `git diff --check` passed.

## Remaining boundary

MinVer and SourceLink can read Git repository state. An archive without `.git`
exercises their fallback behavior, not ordinary Git-checkout version/source-link
parity. Git inputs and resulting assembly metadata need explicit acceptance before
claiming that boundary. The full multi-framework restore also contains packages
outside the selected closure; the integration harness must preserve selected
framework semantics rather than silently flattening or changing project files.

Native adapter execution, generator dependency loading, mutation worksets and
producer-free relocation are owned by the subsequent integrated acceptance slice.
No Linux CI or remote-cache correctness is claimed here.
