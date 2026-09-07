# SDK input discovery (R04)

The exporter now runs the pinned SDK's `ProcessFrameworkReferences`,
`ResolvePackageAssets`, `ResolveLockFileAnalyzers`, and
`ResolveTargetingPackAssets` before collecting inputs. These targets discover
package analyzers and framework generators without requesting Build/CoreCompile.
Discovery is local target execution and may write SDK resolution caches under
obj; it is no longer evaluation-only. Project-authored overrides and hooks can
execute code, so this surface is trusted and does not establish hermeticity.
SDK task dependencies resolve from the selected pinned SDK directory. The
resolved implicit PackageReference items also feed restore consistency checks.

The existing input path/hash contract now includes signing keys when
`SignAssembly=true`, evaluated editorconfig files, and resolved analyzers.
Resources and AdditionalFiles retain selected explicit metadata (LogicalName,
ManifestResourceName, Link, DependentUpon, WithCulture, Culture). A node's
`discovery` records SignAssembly, PublicSign, and DelaySign booleans. A signed
build without an explicit key path is rejected. Removing a conditionally enabled
key changes fresh discovery to unsigned; an unconditionally required absent key
is rejected. These declarations feed preparation's existing input hash checks.
Dependency key staging is a separate coordinated change.

Focused controls in `tests/graph/test_export_graph.py` compare resolved analyzer
names to ordinary SDK ResolveReferences, require no compiled output, preserve
resource metadata, hash an altered analyzer, reject a missing analyzer and an
unconditionally missing signing key, and record a conditional unsigned state.
The key/analyzer bytes in this discovery-only fixture are intentionally dummy
payloads; no signing or generator execution is claimed by this test. Native
Serilog acceptance separately measures real signing and generator behavior.

Generated editorconfig and generated sources remain action outputs; they are
not collected from stale obj directories. Arbitrary custom target-generated
inputs and arbitrary Exists-based conditions still require the explicit
BazelExtraInput contract. This change is a pinned SDK discovery slice, not a
general execution sandbox for arbitrary discovery targets. Linux is deferred.

On macOS ARM64 with pinned SDK 10.0.100, `MSBUILDDISABLENODEREUSE=1 python3
-m unittest discover -s tests/graph -v` passed all 15 tests in 75.273 seconds.
The generated/ordinary analyzer-set comparison and all focused missing/changed
input controls passed. This is discovery evidence, not native build acceptance.
