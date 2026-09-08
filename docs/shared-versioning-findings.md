# Shared R05 versioning inputs

**Follow-up:** [default target caching is now qualified](default-versioning-findings.md).
The default-mode rejection below records the initial RUL-93 checkpoint; RUL-94
adds support without requiring the explicit cache-mode setting.

The two-project `Shared -> App` fixture passes 13 cases for each of
Microsoft.SourceLink.GitHub 8.0.0 and 10.0.300, using
Nerdbank.GitVersioning 3.9.50 and DotNet.ReproducibleBuilds 2.0.2.
Evidence is native macOS ARM64, SDK 10.0.400, Bazel 8.4.2; Linux, Windows,
remote cache, and the complete CommunityToolkit/Dapper.AOT graphs remain open.

## Qualified invocation and default-mode limitation

The qualified invocation explicitly supplies the existing Nerdbank property
`NBGV_CacheMode=None`. This computes versions within each project, retaining
MSBuild graph isolation and filesystem sandboxing. The fixture compares its
cold ordinary-build versions with an ordinary build using Nerdbank's default
mode and requires equality. No automatic adapter override was added.

Nerdbank's default `MSBuildTargetCaching` mode introduces a package-owned
`PrivateP2PCaching.proj` reference when `IsGraphBuild=true`. The reference has
`BuildReference=false` and custom version-computation targets. The exporter
currently rejects it with `unsupported-project-reference-role`. This rejection
is an acceptance control; supporting that auxiliary project is tracked in
[RUL-94](https://linear.app/rules-msbuild/issue/RUL-94).
The explicit-mode shared qualification is
[RUL-93](https://linear.app/rules-msbuild/issue/RUL-93).

## Input contract

The fixture declares `version.json` using the existing item contract:

```xml
<BazelExtraInput Include="$(MSBuildThisFileDirectory)version.json" />
```

Existing standalone Git discovery stages HEAD, index, configuration, refs and
objects. Each action receives its declared Git snapshot and verified package
payloads after the preparation source has been removed. The preparation and
runner property allowlists now accept `NBGV_CacheMode=None` and boolean
`PublicRelease`; both remain part of configured-node/action identity. Other
cache modes and nonboolean release values remain rejected.

Package policy adds exact archive SHA-256 and restore content-hash pins for the
selected Nerdbank, reproducible-build, SourceLink and transitive Git/hash tasks.
There is no broad permission for arbitrary build packages. Existing package
staging checks every extracted payload against its pinned archive.

This retains Nerdbank's computation rather than inventing an adapter version
property. A clean commit fixes its tree and ancestry; the declared version
configuration, branch/release context and invocation still matter. The fixture
uses one root version file. Nested/inherited version files must likewise be
explicitly declared; general automatic Nerdbank configuration discovery is not
established here. Raw Git object/index bytes remain conservative inputs, so
repacking an otherwise equivalent repository may cause extra invalidation.

## Measured cases

| Case | Observed result, in both package lanes |
| --- | --- |
| Cold | Two native sandbox actions; versions and SourceLink equal ordinary MSBuild |
| Unchanged | No project action executes |
| Commit-only change | Both projects execute; package version height changes from 2 to 3 |
| Uncommitted version.json change | Both execute; base version changes from 1.2 to 2.3 |
| PublicRelease=true | Both execute; package commit suffix is removed |
| Release branch, same commit | Both execute; configured public-release branch removes package suffix |
| Relocated | Remove old generated workspace and Bazel output base; both bundles recover explicitly from disk cache, with identical file bytes/modes |
| Consumer-only source edit | Only App executes; dependency replay avoids recompiling Shared |
| Default graph cache mode | Export rejects unsupported auxiliary project reference |
| Missing history object | Delete a declared parent commit object after export; preparation rejects missing input without publishing output |
| Missing version.json | Delete declared version file after export; preparation rejects without publishing output |
| Missing task DLL | Delete Nerdbank task payload after export; preparation rejects without publishing output |
| Corrupt task DLL | Change extracted task bytes after export; preparation rejects hash mismatch without publishing output |

The runtime oracle compares assembly/file/informational versions and SourceLink
URLs for both assemblies. A fixture-only assembly metadata attribute exposes
`NuGetPackageVersion` computed by `GetBuildVersion`, because public-release
selection need not change the other assembly version attributes. Ordinary and
adapter builds use this same oracle. Recovered bundle comparison covers all
bundle contents; ordinary/adapter parity is an observable comparison, not a
claim of byte-identical ordinary assemblies or package/pack acceptance.

Evidence reports from the accepted runs:

- `/private/tmp/r05-shared-evidence-6/report.json` — SourceLink 10.0.300, 13/13.
- `/private/tmp/r05-shared-evidence-8/report.json` — SourceLink 8.0.0, 13/13.

The harness generates fresh local Git commits, so their hashes differ between
runs; comparisons within a run use the same commits. Failed exploratory runs
are not acceptance evidence. In particular, changing the runner's embedded
package policy during a run correctly prevented cache recovery; final runs
kept tool inputs fixed throughout.

## Repeatable run

Use `bash scripts/setup.sh` or the repository's pinned Nix environment. Run
acquisition in a disposable directory, never in the tracked fixture directory.
For each version, use a new evidence output directory:

```bash
acquisition_dir="$(mktemp -d /tmp/r05-version-packages.XXXXXX)"
cp tests/fixtures/shared-versioning/Acquire.csproj "$acquisition_dir/"
bash scripts/dotnet.sh restore "$acquisition_dir/Acquire.csproj" \
  -p:SourceLinkVersion=10.0.300 --packages "$acquisition_dir/packages"
python3 tools/probe_shared_versioning.py \
  --packages "$acquisition_dir/packages" --sourcelink-version 10.0.300 \
  --output /tmp/r05-version-evidence-10
```

Repeat with `8.0.0`, a fresh acquisition directory and a fresh evidence path.
The probe requires native Bazel sandbox access. Restore may use the network;
build actions receive staged packages. `report.json` records acceptance,
per-case observations, actions, rejection diagnostics, and failure stage.

Validation also passed `bash scripts/check.sh`, `bash scripts/check-dotnet.sh`,
18 preparation rejection tests, six standalone Git input tests and two package
policy tests. The environment-gated Serilog package integration test was skipped.
The preparation rejection fixtures were refreshed with selected-framework
restore metadata so they reach the intended rejection rather than failing
prematurely at the restore guard.

This shared fixture enables an explicit-mode path for the two R05 tracks. Their
actual framework selections, generator/interceptor behavior, signing and
track-specific package closures still need qualification. Default Nerdbank
auxiliary-project support remains a distinct prerequisite for unchanged default
invocations; neither real-project issue is completed by this fixture.
