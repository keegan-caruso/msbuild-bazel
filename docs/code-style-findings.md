# .NET code style and warnings

The shared tooling properties enable `EnforceCodeStyleInBuild` and
`TreatWarningsAsErrors`. All five tools and `ActionRunner.Tests` use this policy,
including ReplayPlugin and SerilogApiOracle, which previously did not require
warnings to be errors. No additional analyzer package is needed.

## Policy boundary

The root `.editorconfig` specifies System-first imports, using directives outside
namespaces, file-scoped namespace style, explicit accessibility except for interface
members, readonly fields where possible, and two-space indentation for MSBuild XML.
C# defaults remain suggestions. Only `tools/**.cs` and
`tests/ActionRunner.Tests/**.cs` give the selected language options and diagnostics
warning severity. Both are explicit: with this SDK, leaving an option at `suggestion` did not make its language
rule fail compilation even when the diagnostic severity was `warning`. The rules are:

- IDE0040: accessibility modifiers.
- IDE0044: readonly fields.
- IDE0055: formatting.
- IDE0065: using-directive placement.
- IDE0161: file-scoped namespace declarations.

`tools/Directory.Build.props` supplies build enforcement; the unit-test directory
imports that file. There is no repository-root Directory.Build.props to change
experimental fixture builds. Existing code received formatter changes and explicit
private modifiers to satisfy the policy, without changing compilation algorithms
or replay contracts.

The [SDK build enforcement](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/overview)
uses the analyzers supplied by the pinned SDK. Diagnostic warnings become errors
through `TreatWarningsAsErrors`. The CI check also uses MSBuild's `-warnaserror`
switch so task warnings fail that check. The SDK does not report import ordering
as an IDE0055 build diagnostic; `dotnet format --verify-no-changes` checks it as
`IMPORTS`. The dedicated check runs this formatter verification for every project
as well as compilation, so CI rejects misordered imports.

## Reproduction

With the pinned toolchain installed or inside `nix develop`:

```sh
bash scripts/check-dotnet.sh
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
python3 -m unittest discover -s tests/e2e -p test_msbuild_replay.py -v
```

The dedicated check rebuilds every owned project with `--no-incremental`, verifies
formatter output, then runs the isolated enforcement regression suite. Setup and Nix CI invoke the same
script. CI configuration is not evidence of a hosted run.

## Measured validation

Native macOS ARM64 with .NET SDK 10.0.100 and Bazel 8.4.2:

- `bash scripts/check-dotnet.sh` passed: all six projects rebuilt with zero warnings
  or errors, all formatter verifications passed, and all five enforcement tests
  passed in 8.399 seconds. Log: `/private/tmp/rules-msbuild-style-checks/integrated.log`.
- Enforcement tests prove each of the five diagnostics fails as an error in both
  owned scopes (ten negative cases), and CS1030 compiler warnings fail in both.
  These builds use no command-line warning-as-error override, so they verify the
  actual shared project policy. A clean control succeeds in both scopes.
- The fixture control confirms the enforcement properties are not enabled and its
  compiler warning remains nonfatal. Import-order verification fails specifically
  with `IMPORTS: Fix imports ordering.`
- Action runner contracts passed; public dependency-result replay passed in
  13.461 seconds; the native test-action suite passed its pass/changed/missing/zero-test
  cases in 20.5 seconds, with no skips.
- Scaffold/toolchain checks, pinned Starlark formatting, shell syntax, workflow YAML,
  Python syntax and `git diff --check` passed.

The first build rejected eight formatting violations. The initial policy test
then exposed that option-level suggestions did not fail language-style builds;
owned-scope option severities were raised to warnings, with all negative controls
subsequently passing. The synthetic test workspace also resolves its physical
path before invoking Roslyn so EditorConfig matching does not cross macOS path
aliases. No analyzer was disabled to obtain passing builds.

Logs are retained under `/private/tmp/rules-msbuild-style-checks`. Final enforcement
fixtures are under
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/rules-msbuild-code-style-ugxxs6c3`.
The independent subagent run also passed all five tests in 8.967 seconds. Linux
and hosted CI were not run for this change.
