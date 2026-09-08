# Nerdbank default target caching

RUL-94 qualifies Nerdbank.GitVersioning 3.9.50's default
`MSBuildTargetCaching` mode on macOS ARM64, retaining native sandboxing and
MSBuild project isolation. It builds the package-owned `PrivateP2PCaching.proj`
inside the owning Bazel action, where its custom targets compute version values.
No cache-mode override is supplied and no project edge is silently removed.

The exporter recognizes only the pinned package path and expected reference
metadata (NBGV marker, two version targets, disabled build/reference output and
PrivateAssets=all). Custom auxiliary imports remain unsupported. Package archive
and extracted-file integrity checks still run before action publication.
The replay plugin lets this computation-only project execute normally instead
of looking for a dependency assembly bundle. Ordinary compilation dependencies
still replay from verified bundles; each action compiles only its own csproj.

The default-mode matrix passed 12 cases with SourceLink 10.0.300, and 13 with
SourceLink 8.0.0 including the added custom auxiliary-import rejection control:

- Ordinary/default version and SourceLink parity, cold and unchanged builds.
- Commit-only, version.json, explicit public release and release-branch mutations.
- Relocated two-project disk-cache recovery with byte/mode-identical bundles.
- Consumer-only rebuild with Shared recovered through dependency replay.
- Missing declared history/version/task and corrupt task rejection before publication.
- Custom auxiliary targets rejected with `unsupported-project-reference-role`.

Reports: `/private/tmp/r05-default-evidence-1/report.json` and
`/private/tmp/r05-default-evidence-8/report.json`. The first report predates only
the additional negative harness control; the production implementation is the
same. `bash scripts/check-dotnet.sh` passed all owned builds, style checks and
five policy-enforcement tests.

Reproduce using the acquisition steps in [shared-versioning-findings.md](shared-versioning-findings.md)
and add `--default-cache` to the probe invocation. Without that flag the harness
continues to exercise explicitly supplied `NBGV_CacheMode=None`; it no longer
expects default-mode export to fail. The custom-target restriction is package-
specific; this is not general support for arbitrary auxiliary MSBuild projects,
custom reference targets, or custom Nerdbank auxiliary imports. Linux and Windows
qualification remains separate.
