# Pinned package-input experiment

Implemented on macOS ARM64; see [findings](package-input-findings.md). The contract
below was written before the runner changes.

Extend the copied fixture with an exact PackageReference to a small, repository-
authored build package. Three deterministic archives have checked-in SHA-256
pins: initial contents, changed data, and changed build target. No generated
.nupkg or restored package cache is committed. NuGet restores the archives from
a local feed before compilation; Traversal acquisition remains preparation-only.

`probe_bazel.py --package-probe` must run the existing scheduling/cache matrix,
then reprepare at new paths for each package version. Delete the producer restore
workspace and feed before consuming each prepared input set. Declare the complete
archive payload of every resolved package in project.assets.json as Bazel inputs.
Stage and hash-check those payloads into each action's own NuGet root before
MSBuild graph evaluation. Restore bookkeeping and the archive itself are not
compilation inputs. Use normal generated NuGet imports for the package target.

Acceptance: both project actions run on either package version change; the data
and target changes separately alter runtime output. Missing declared package
inputs, corrupted payload bytes, and project/package-version versus restore
mismatches fail without any compilation. The original no-package and input-
identity probes remain independent controls. DLL and native app-host execution,
strict isolation, native action sandboxing and local disk-cache recovery stay
required. Package build logic must run only in Shared's producer action, never
again in App's replay action.

Scope: one exact inline PackageReference, one build-only package, one framework,
Release. This is a real NuGet build-package boundary, not a binary-library,
analyzer, native-asset, arbitrary-package or complete restore-key claim.
