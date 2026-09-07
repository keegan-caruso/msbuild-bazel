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
pinned SDK and `SPIKE_SERILOG_SOURCE`/`SPIKE_SERILOG_PACKAGES` acquired-cache inputs:

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
Integrated unchanged-test export awaits the separate downstream framework-selection
prerequisite: the original ProjectGraph construction expands Serilog's outer build,
while ordinary SDK Build selects its net10.0 dependency. No input-track build,
xUnit execution, remote cache, general NuGet or Linux qualification is claimed here.
