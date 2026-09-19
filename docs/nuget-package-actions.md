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

## Integration still required

This rule is not wired into the owned Orchard workflow. Integrating it requires:

1. Separate archive acquisition from repository-time extraction.
2. Pass declared package-directory artifacts through restore, discovery and
   compilation, materializing contents only when an action executes.
3. Preserve logical package paths, hash checks, input ownership and publication
   validation; never substitute an undeclared global NuGet cache.
4. Measure per-package versus batched actions and a minimal runtime tool input.
   Extra action and SDK-input overhead could erase the extraction savings.
5. Narrow each project's package dependencies and qualify the complete Orchard
   producer/fresh-recovery path again before changing the default.

Bazel's remote cache stores [action outputs](https://bazel.build/remote/caching),
which is the reason to move extraction across this boundary. This does not replace
NuGet's resolver or by itself solve the 17-minute cold Orchard build.
