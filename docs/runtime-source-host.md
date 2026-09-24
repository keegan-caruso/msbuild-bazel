# Source-only runtime test host

The selected dotnet/runtime v10.0.0 test host now uses **10.0.0** metadata and
contains **131 source-built binaries**: 121 shared managed assemblies, one private
formatter, eight native products and the qualification probe. No installed SDK
runtime binaries remain in its template. The 58 unused template components are
excluded explicitly, and the startup observer rejects loads of those components
from outside the host.

This is a selected test host, not a complete redistributable framework. SDK build
tools, targeting packs and operating-system libraries retain their existing
pinned toolchain/platform boundary. Excluded components require further source
producers and qualification before a new suite can use them.

## Evidence

Same pinned upstream revision and tools as [Pipelines qualification](runtime-pipelines.md):
Linux ARM64, SDK 10.0.400, Bazel 9.2.0. Eight raw and Bazel suites retain normalized
case-name/outcome parity: **118,952 passes, 64 skips**, with no installed runtime
components observed across 96 processes per execution set.

The producer reused all 281 managed and five native actions, changed only the
runtime host layout, and executed all eight suites. An exact binary inventory
check compares every DLL, SO and dotnet executable to its declared producer hash.
The positive host-launch control passes; explicitly loading the excluded installed
`System.Text.Encoding.CodePages.dll` terminates with the expected wrong-binary
error. See [compact evidence](runtime-source-host-evidence.json).

An independent consumer at a different workspace path, with the producer stopped,
recovered all **281 managed actions, five native actions, 121 layouts and eight
test results** from HTTP cache. All **2,758 output hashes** matched. Forced
execution again passed all suites with no installed runtime loads; the exact
inventory and forbidden-SDK-fallback controls also passed on recovered outputs.
Disk caching and consumer uploads were disabled.

## Reproduce

After the [Pipelines fixture preparation](runtime-pipelines.md), copy its declared
workspace into a fresh directory, excluding Bazel output symlinks. Run:

```sh
python3 tests/explicit_msbuild/runtime/source_host.py "$workspace"
python3 tests/explicit_msbuild/runtime/subset_raw.py \
  "$source" "$inventory" "$workspace" "$raw_native_products" "$raw"
python3 tests/explicit_msbuild/runtime/subset_remote.py \
  "$workspace" "$base" "$report" "$raw" --cache "$cache" --seed
python3 tests/explicit_msbuild/runtime/source_host_control.py "$workspace" "$controls"
python3 tests/explicit_msbuild/runtime/loaded_inventory.py \
  "$parity" "$loaded" --require-empty
```

Set `RULES_MSBUILD_DOTNET_ROOT` and `RULES_MSBUILD_BAZEL` to the verified tools.
`source_host.py` is a one-time conversion of this pinned qualification fixture;
it is not a production packaging API. The existing generic `msbuild_layout` and
`msbuild_runtime` rules compose and expose the host without runtime-specific logic.
