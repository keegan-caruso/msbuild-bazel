# Pinned approval-test build inputs

The unchanged pinned `test/Serilog.ApprovalTests` Release/net10.0 restore selects
20 packages. Their exact identity/version, archive SHA256 and NuGet content hash
are recorded in the shared pilot policy alongside the existing two library pins.
Each acquired archive's content hash was independently recomputed using the pinned
SDK's `NuGet.Packaging.PackageArchiveReader.GetContentHash` and matched the assets
file. Signed archive SHA512 is not substituted for NuGet's content hash.

Policy now separates archive directory permissions (`additionalRoots`) from
restored asset categories (`assetRoles`). Exact pins permit the measured build,
buildMultiTargeting, localized resource and System.Management runtimeTargets
roles. This does not grant any other package those permissions. Preparation stages
and checks the entire archive payload plus archive and hash marker; runtime uses
the same shared archive pins and complete-payload verification. No Windows runtime
asset is omitted merely because the macOS approval test does not load it.

The focused unchanged restore/staging check passes with 20 packages and 564 staged
files, including all 65 selected localized resources, TestSDK's Program source,
EmptyFiles content, xUnit analyzers and the Windows runtime payload. It also rejects
an unqualified asset category, a changed pinned archive and a changed extracted
Program source. The existing three library policy checks pass. Commands use the
pinned SDK and `RULES_MSBUILD_SERILOG_SOURCE`/`RULES_MSBUILD_SERILOG_PACKAGES` acquired-cache inputs:

```sh
python3 -m unittest discover -s tests/graph_packages -p test_approval_inputs.py -v
python3 -m unittest discover -s tests/graph_packages -p test_pilot_package_policy.py -v
```

Initial evidence: `serilog-approval-inputs-zfrzmnms` in the native temporary folder;
independent content hashes: `/private/tmp/approval-package-content-hashes.log`.

Exporter post-resolution discovery adds `ContentWithTargetPath` and preserves its
TargetPath/copy metadata. Package-owned source/resource/content/additional inputs
require a qualified package identity, and their bytes remain declared and verified.
TestSDK's InitialTargets-generated Compile item is collected from resolved state.
Integrated unchanged-test export now passes with the selected-reference discovery
prerequisite at `a0c8a76`. The focused test checks exactly two net10.0 nodes
(approval test and Serilog), no compiled project DLLs, and the exact 20 identity/version
package set in both restore and exported inputs. It verifies TestSDK's generated
`Microsoft.NET.Test.Sdk.Program.cs` source hash and all 42 EmptyFiles content hashes,
`TargetPath` values, and `CopyToOutputDirectory=PreserveNewest` metadata.

`Serilog.approved.txt` is upstream test data, not an implicit graph build input.
The focused check proves it is absent from compilation input discovery and is
explicitly copied and hashed by the test-plan declaration. This preserves separate
build and test invalidation without changing upstream sources.

Measured on native macOS ARM64 with SDK 10.0.100: the extended focused test passed
in 4.321 seconds. Evidence is `serilog-approval-inputs-cjrydiio` in the native
temporary folder, including `graph.json`, `request.json`, test-plan metadata, and
restore/export logs. This was a correctness check concurrent with other track work,
not a performance result. No input-track project compilation, xUnit execution,
remote cache, general NuGet or Linux qualification is claimed here.
