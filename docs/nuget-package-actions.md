# Cacheable NuGet package extraction prototype

NuGet still owns dependency resolution and lock-file semantics. The current
owned workflow acquires and extracts all packages in one Bazel repository rule.
That setup cost 15.751 seconds in the fresh Orchard worker profile, even though
all 202 compile actions were remote hits.

This isolated prototype adds `nuget_extract_package` and the .NET
`owned-extract-package` command. A checksum-pinned archive and its lock hash are
inputs; the extracted NuGet directory is a declared Bazel tree output. Execution
has no network access and uses the native sandbox. Qualified signed-package pins
retain the existing distinction between restore content hash and archive hash.
Path normalization decodes `%2B`, normalizes the root nuspec filename, and rejects
collisions, traversal and non-regular ZIP entries. Resolver and executable-package
qualification remain responsibilities of the existing restore/discovery pipeline.

## Measured proof

On macOS ARM64, pinned .NET SDK 10.0.400 and Bazel 8.4.2:

- GeoAPI 1.7.5 and Newtonsoft.Json 13.0.3 each executed once in `darwin-sandbox`.
- A second checkout with an empty Bazel output base and read-only HTTP cache
  recovered both package outputs: two remote hits, zero extraction executions.
- All 35 files matched the producer byte-for-byte. Archive payload files matched
  the current repository rule; generated `.nupkg.metadata` was semantically equal
  with different JSON whitespace.
- Integrity, path/collision/symlink rejection, repeat determinism and qualified
  signed-hash mapping tests pass. The full owned .NET check suite passes (55
  workflow tests, one platform-specific skip, plus preparation/style checks).

The two-package producer took 7.671s Bazel wall time (1.21s critical path), and
recovery took 5.787s (0.29s critical path). These include startup and full declared
SDK inputs, share the machine with Orchard qualification, and are not a speedup
estimate for the 287-package graph. The cache is local loopback.

## Owned workflow integration

The owned workflow now supports `"package-actions": true` with locked restore
and a declared project layout. It downloads verified archives in the repository
rule, emits one extraction target per locked package, and passes typed directory
artifacts into restore, discovery and project compilation. Compilation resolves
only the prepared payload paths inside those declared directories and checks
every selected file hash. It does not enumerate package files during Bazel
analysis or substitute an undeclared global cache.

The option remains explicit while the full Orchard graph is qualified. The
repository-extraction path remains available for comparison. Package directories
are still shared across all compile targets at this step; per-project package
ownership is next.

### Integrated acceptance

`tests/remote_workers/package_action_probe.py` exercises a four-project graph
using Newtonsoft.Json 13.0.1 and PolySharp 1.15.0 through the real owned pipeline:

- Legacy repository extraction and package actions produce identical DLL/PDB
  hashes and application output (`11`). Their recorded totals were 14.909 and
  14.934 seconds respectively; these are small-fixture samples, not an Orchard
  performance claim.
- The package producer performs two native sandbox extraction actions and four
  compilations, then its source and local Bazel state are deleted.
- A different checkout with fresh Bazel state and a read-only HTTP cache recovers
  both package actions and all compilations remotely in 3.729 seconds. Bazel
  creates two empty package-directory placeholders but downloads zero extracted
  package files (`--remote_download_outputs=toplevel`).
- A subsequent source-body edit compiles one project, performs no extraction or
  discovery, and produces the changed application output (`21`) in 3.502 seconds.
- The full local check suite passes: 57 workflow tests, one Linux-only skip on
  macOS, preparation/style checks and warning-free builds. Starlark checks pass.
  Directory traversal/duplicate identities, staging overlap and changed package
  payload hashes have rejection controls.

The cache is local loopback. Full Orchard and independent-machine/WAN performance
remain unproven for this option. Archive downloads are still repository work;
this moves extraction and the resulting file trees into the action cache.

Bazel's remote cache stores [action outputs](https://bazel.build/remote/caching),
which is the reason to move extraction across this boundary. This does not replace
NuGet's resolver or by itself solve the 17-minute cold Orchard build.
