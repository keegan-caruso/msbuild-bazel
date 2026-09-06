# Pinned NuGet build-package inputs

The two-target Bazel adapter now stages a checksum-verified NuGet build package
into each action's own package root. Package data and build-target upgrades
invalidate both actions; App continues to replay Shared without rerunning the
package target. These are macOS ARM64 measurements for a controlled build-only
package, not general NuGet support.

## Run and package construction

```sh
python3 tools/probe_bazel.py --package-probe --output artifacts/package-probe
python3 -m unittest discover -s tests/e2e -v
```

The [acceptance contract](package-input-plan.md) and black-box assertions preceded
the runner changes. The original two-project fixture is unchanged. Preparation
adds an exact inline PackageReference to Shared in a copy of that fixture.

`tests/fixtures/package-inputs` contains the source payloads and archive SHA-256
pins for `Spike.BuildInputs`:

| Version | Packaged data | Generated target value |
| --- | --- | --- |
| 1.0.0 | package-v1 | target-v1 |
| 1.0.1 | package-v2 | target-v1 |
| 1.0.2 | package-v2 | target-v2 |

`tools/package_inputs.py` creates ZIP_STORED archives with sorted entries, a fixed
1980 timestamp and fixed file modes, then verifies their checked-in hashes.
Only source payloads and pins are committed. NuGet restores the archives through
a local feed; preparation verifies both the restored archive hash and each
extracted payload file. Traversal restore still requires its existing NuGet source.

The package has a normal `build/Spike.BuildInputs.targets` import. NuGet's generated
`.nuget.g.targets` activates it; the runner does not inject the package import.
The target reads packaged `data/value.txt` and generates a C# constant in Shared
obj. Shared includes the value in its public message. The package has no DLLs,
analyzers, native assets or package dependencies.

## Prepared inputs and action boundary

For each project, preparation reads the package libraries in project.assets.json
and produces a versioned package manifest. Each entry records ID, exact version,
package-root-relative path, archive hash and payload filenames/sizes/hashes.
The Bazel rule declares that project's manifest and its payload file set. Both
App and Shared resolve this package; App needs the files when evaluating Shared's
project and generated NuGet imports, even though it does not run Shared's build.

Before MSBuild graph evaluation, the runner:

1. Checks the manifest's package identities and paths against restore assets.
2. Rejects direct PackageReferences without an exact inline version or with a
   version absent from the restore results.
3. Checks the complete declared payload set, sizes and SHA-256 hashes.
4. Stages the files under the fresh workspace's `.nuget/packages` directory.

The archive, NuGet extraction metadata and the source feed are not compilation
inputs. The source feed is excluded when copying sources. Preparation workspaces
and their feeds are deleted before each Bazel build, including both version
upgrades. Restore metadata is expanded with the action workspace and SDK roots;
source-feed provenance can still name deleted locations, but compilation neither
restores nor consumes those feeds. Actions retain native sandboxing, network
blocking and strict MSBuild project isolation. No cache-miss fallback builds Shared
inside App or downloads a missing package.

## Results

Measured with SDK 10.0.100, MSBuild 18.0.2.52411 and Nix Bazel 8.4.2 on macOS ARM64.
The original cold/unchanged/App-edit/Shared-edit/disk-cache/new-output-base matrix
passes with the package present. The initial baseline prints
`shared-v1/package-v1/target-v1/app-v1` through both the DLL and native app host.

After the existing source-edit scenarios, the package probe observes:

| Scenario | Actions executed | Observation |
| --- | --- | --- |
| Restore exact version 1.0.1 at a fresh path | Shared, App | `shared-v2/package-v2/target-v1/app-v2` |
| Restore exact version 1.0.2 at another fresh path | Shared, App | `shared-v2/package-v2/target-v2/app-v2` |
| Omit package payloads from action inputs | Shared action rejects | Package diagnostic; no compilation |
| Corrupt packaged data without changing manifest | Shared action rejects | Hash mismatch; no compilation |
| Change Shared reference to 1.0.0 with 1.0.2 restore state | Shared action rejects | Restore-version mismatch; no compilation |

Execution reports record `SPIKE_PACKAGE_TARGET:Shared` in Shared builds and no
package-target marker in App. The test checks markers for actions that execute,
including both package upgrades; cache reuse is checked through Bazel execution
logs. A cached dependency tree can remain unmaterialized when App also comes from
cache, so reporting does not require Shared's cached `action.json` to exist.
The test also inspects declared target/data inputs and verifies
that all three preparation workspaces are absent. The missing-input control keeps
the package files in the copied checkout but removes them from the action input
list; the action must reject them rather than discover an undeclared host cache.

The version upgrades intentionally change project, restore and package inputs
together. They do not claim to isolate the effect of package bytes from a version
change. Corrupting only staged data does invalidate the action and trigger hash
validation, providing the separate content-input check.

## Validation

With the pinned Nix SDK and Bazel overrides, the full command
`python3 -m unittest discover -s tests/e2e -v` passed all ten existing tests;
the new package test failed while reporting an unmaterialized cached dependency
tree. After fixing that reporting assumption, the focused rerun
`python3 -m unittest discover -s tests/e2e -p test_bazel_boundary.py -k pinned_package -v`
passed in 61.753 seconds. Native sandbox tests ran outside the outer tool sandbox.
The full suite was not rerun after this package-reporting-only fix.

`bash scripts/check.sh`, Python syntax compilation of the changed tools/test, and
`git diff --check` passed. The environment check is not an integration test.

## Limits and next

Preparation currently accepts only this package's pinned versions. Direct
references must use exact inline versions; central versions, conditional
references, floating/ranged versions and arbitrary package dependency closures
need another contract. This probe exercises build assets and packaged data,
not binary library/runtime resolution, analyzers, native assets, buildTransitive
or publishing. Package manifests are trusted prepared inputs, not signed bundles.

The next work remains native runtime/toolchain closure and deterministic output
staging, with ordinary package DLL assets needing separate coverage before
claiming general NuGet support. Linux validation remains with the user; no Linux
workflow was changed or rerun for this milestone. Remote execution and remote
cache use remain disabled.
