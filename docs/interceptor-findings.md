# Dapper.AOT interceptor acceptance

The selected package-delivered interceptor slice passes 11 ordinary/native
macOS ARM64 cases with .NET SDK 10.0.400 (MSBuild 18.9.6) and Bazel 8.4.2.
Dapper.AOT is acquired from upstream commit
`bebc9e49bcb8c5e24474e678f3e6716373db7f09`, package
`1.0.85-gbebc9e49bc`; Dapper is exactly 2.1.72. The generated location encoding
is `InterceptsLocationAttribute(string path, int lineNumber, int columnNumber)`.
`InterceptorsPreviewNamespaces` opts in to `Dapper.AOT`.

## Behavioral oracle and controls

The consumer calls Dapper's ExecuteScalar with a fake ADO connection. Its
NoInlining scalar implementation inspects the executing stack, requiring
Dapper.Command and rejecting Dapper.SqlMapper. The positive Release run returns
`intercepted:42`. Disabling the module's DapperAot setting builds successfully but
fails this execution oracle through the ordinary SqlMapper path. There is no
external database or runtime network dependency.

Cold execution, renamed source, inserted lines, changed query (`43`), removed
call (`removed:0`), module opt-out, missing namespace opt-in and C# 11 each execute
one native action. Unchanged execution does no work. Incompatible compiler/feature
settings produce the same compiler error codes as ordinary MSBuild and publish
no successful bundle. Removed/disabled calls have no generated location binding.

Recovery deletes the original generated workspace and Bazel output base and
requires an explicit local disk-cache hit and an identical bundle inventory.
The recovered executable passes the interception oracle. A subsequent consumer
edit forces fresh compilation at the relocated path and passes again. Every
preparation source tree is deleted before the corresponding action. Runtime
assemblies are exactly App.dll, Dapper.dll and Dapper.AOT.dll; analyzer and ScriptDom
support assemblies do not become runtime references.

## Package boundary

Both `analyzers/dotnet/cs/*.dll` and language-independent
`analyzers/dotnet/*.dll` are accepted. The Dapper package's analyzer and ScriptDom
support DLL are declared package inputs with per-file size/hash verification.
NuGet omits OPC bookkeeping from extracted caches; preparation reconstructs only
those known metadata entries from the verified archive. Missing actual payload,
corruption, unqualified analyzer layouts and executable tools remain rejected.
Python and direct runner controls cover both permitted analyzer layouts.

Dapper's signed archive has an explicit archive/content pin. The locally acquired
Dapper.AOT archive is checked against restored SHA512 and its repository revision;
its archive SHA256 is recorded in each report. Acquisition runs normal upstream
MSBuild pack for the selected net10.0 runtime. Archive timestamps are not claimed
to be reproducible across independent acquisitions. Every case in a run reuses
the exact acquired bytes. Package creation is preparation, not an R06 Pack or
Native AOT publishing qualification.

## Reproduction

Use the repository's pinned tool environment and a full upstream clone:

```sh
git clone https://github.com/DapperLib/DapperAOT /tmp/dapper-source
cd /tmp/dapper-source
git checkout --detach bebc9e49bcb8c5e24474e678f3e6716373db7f09
dotnet restore src/Dapper.AOT/Dapper.AOT.csproj \
  -p:TargetFrameworks=net10.0 --packages "$PWD/.nuget/packages"
dotnet restore src/Dapper.AOT.Analyzers/Dapper.AOT.Analyzers.csproj \
  --packages "$PWD/.nuget/packages"
dotnet pack src/Dapper.AOT/Dapper.AOT.csproj -c Release --no-restore \
  -p:TargetFrameworks=net10.0 -p:GeneratePackageOnBuild=false \
  -p:RestorePackagesPath="$PWD/.nuget/packages" -o /tmp/dapper-feed
```

The second restore retains the analyzer's actual netstandard2.0 selection.
Copy `tests/fixtures/dapper-interceptors` to an independent directory and restore
it with the local feed and NuGet.org into its own `.nuget/packages`. From this
repository, run:

```sh
python3 tools/probe_interceptors.py \
  --packages /path/to/restored/consumer/.nuget/packages \
  --output /tmp/interceptor-acceptance
```

Final full evidence: `/private/tmp/r05-interceptors-final/report.json` (11 cases,
accepted). Missing feature opt-in fails CS9137; C# 11 fails CS9058. Package
regressions pass 22 tests with two existing acquired-Serilog prerequisites
skipped. Direct runner contracts, scaffold/Starlark validation, owned .NET
style/build and five style enforcement controls pass. Ordinary generated source, compiler errors, runtime output, Bazel
execution logs and bundle hashes are retained beside the report.

Linux, Windows, other compiler/generator revisions, Native AOT, databases and
remote caches remain outside this selected slice. The fixture's stack oracle is
specific to this pinned Release implementation; it is validated by the opt-out
negative control on every run.
