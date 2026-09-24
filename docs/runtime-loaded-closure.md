# Loaded runtime dependency closure

This report records the seven-suite step. The [Pipelines extension](runtime-pipelines.md)
and [source-only host](runtime-source-host.md) are the current cumulative boundary;
the latter replaces the installed template and 10.0.11 layout described below.

Qualified runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
Linux ARM64, SDK 10.0.400 and Bazel 9.2.0. This extends the seven suites in
[runtime subset qualification (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/runtime-subset.md), without expanding their test filter.

The final independent-consumer baseline observed 63 installed components:
61 managed assemblies and two native libraries. See
[ranked baseline](runtime-loaded-baseline.json). Counts include the startup hook,
VSTest and helper infrastructure. In particular, hashing and JSON serialization
load dependencies in the observer itself; these counts are evidence of a loaded
runtime dependency, not proof of upstream API coverage.

The private source-built net8 formatter and installed shared net10 formatter are
classified by their observed declared paths, not merely by their common filename.

## Sequence and gates

1. Common managed dependencies: pipelines, reflection helpers, encodings, JSON,
   component-model primitives and runtime loader.
2. Platform-specific implementations plus source-built OpenSSL and compression
   runtime wrappers (the OS libraries remain declared platform prerequisites).
3. Remaining managed implementations and compatibility forwarding assemblies.
4. Repeat loaded-inventory collection until no installed runtime binary is
   observed in the selected execution; record any remaining boundaries explicitly.

Each batch preserves unchanged upstream raw compilation and exact/previously
qualified normalized case-outcome parity. Final acceptance includes mutation
invalidation and fresh-container HTTP recovery with the producer stopped, followed
by forced execution and producer-hash verification. No full-runtime, other-platform
or remote-native-execution qualification is implied.

## Final acceptance

The same seven suites pass against the expanded source-built host: **118,375
passed, 64 skipped**, with unchanged raw/Bazel outcome comparison. All **93
observed processes**, including **72 RemoteExecutor children**, load no installed
runtime component. The host declares **121 shared managed replacements**, one
private net8 formatter, and **eight native products**. This closes the observed
mixed-runtime gap for these suites. See [compact evidence](runtime-loaded-closure-evidence.json).

- A missing formatter contract member fails APICompat with `CP0002`; restoring it
  succeeds. Forwarding support does not disable API validation.
- A Pipelines body edit rebuilds only its managed producer, leaves its public
  reference bytes unchanged, and reruns all seven suites. Restoring it reuses cache.
- An OpenSSL wrapper version-input edit rebuilds only `//native_crypto:runtime`,
  recompiles no managed assembly, and reruns all seven suites. Restoring it reuses cache.
- All seven suites reject an intentionally incorrect CoreLib hash.
- With the producer stopped, a fresh independent container recovers **280/280
  managed actions, 5/5 native actions, 121/121 layouts**, and all seven cached test
  results over HTTP. All **2,806 output files** match the clean producer's hashes.
  Forced execution then passes every suite and verifies loaded producer hashes
  and zero installed runtime components again. Local-result upload is disabled
  on the consumer.
- Generic configured-restore and platform-contract regressions pass on both
  Bazel **8.8.0** and **9.2.0**: seven and 21 cases respectively. The cumulative
  runtime graph above is qualified on **9.2.0**. Repository scaffold/Starlark and
  owned .NET checks pass.

The toolchain image index is pinned at
`sha256:47a9e2fed01824f5470f26e75a2fb74017acc1967c637e7793be028f31a8aeee`.
Producer and consumer use separate Linux ARM64 containers with 8 CPUs and 16 GiB
RAM, no shared checkout/output mounts, and separate Bazel output bases. Native
compilation remains local within its declared nested namespace; HTTP recovery
of its products is qualified, not native remote execution.

The boundary is observed runtime loads in these selected suites. Unobserved
installed template files remain declared, the SDK/build tools still use the pinned
installed toolchain, and OS libraries such as OpenSSL remain platform prerequisites.
The host retains the declared shared-framework directory version 10.0.11 around
source-built v10.0.0 products. This is not a fully source-built distribution or
qualification of additional APIs, CoreCLR/JIT stress tests, other architectures,
NativeAOT, Mono/WASM, cross-compilation, or crossgen/R2R.

Full local artifacts are retained as `/private/tmp/closure-final-inputs.tar.gz`,
`/private/tmp/closure-final-producer-evidence.tar.gz`,
`/private/tmp/closure-final-consumer-evidence.tar.gz`, and
`/private/tmp/closure-final-generic-evidence.tar.gz`. Intermediate common/platform
results and raw native controls are retained separately. The input bundle excludes
Bazel output bases and output links; the consumer evidence includes full test XML
and loaded-process proofs. These archives are local evidence, not repository files.

## Declaration corrections

Root selection now uses both project path and the authored target framework.
Previously, adding a multi-targeted root selected every evaluated framework of
that project, including browser/WASI and older-framework variants. Redundant roots
already reached through authored dependency edges are omitted. Distinct global
configurations are still rejected rather than silently merged.

Host composition has explicit shared/private framework choices. Build-tool
dependencies can compile neutral platform-not-supported implementations; those
are not suitable runtime replacements on Linux. The selection declares the Unix
implementation for each such runtime component, retaining its installed binary
until that selected producer is added. Older-framework tool dependencies are not
automatically added to the test host's private assembly directory.

The first expansion also exposed duplicate public-contract and implementation
references in a CoreLib consumer. Upstream disables transitive dependency
discovery for these projects. `transitive_compile_references=False` now represents
that direct compiler input set for libraries, without dropping the exported
reference/runtime closure used by downstream applications. Small positive and
negative fixtures cover compiler visibility and transitive runtime execution on
both Bazel 8.8 and 9.2.

## First batch

The common managed batch passed all seven unchanged suites with raw/Bazel parity:
118,375 passes and 64 skips. The host contains 41 source-built shared assemblies
(up from 24), and observed installed components fell from 63 to 47. See
[common batch evidence](runtime-loaded-common-evidence.json).

Raw builds now use upstream's default inner-build API-compatibility behavior.
The old harness unconditionally forced inner-build validation; Pipes' suppression
file contains Windows-specific entries that the isolated Unix inner build rejects
as unused. No upstream sources or suppression files were changed. Explicit
contract pairing and the existing CoreLib-consumer validation remain in place.

The Linux platform expansion exposed another discovery error: using a plain NuGet
framework reducer selected neutral assemblies where MSBuild selected Unix
implementations. Inventory now runs the SDK's reference-framework selection
targets against evaluated instances and records the resolved choices for authored
edges. Graph-added transitive edges are not treated as direct project references.
This metadata acquisition happens only in qualification setup; generated Bazel
actions consume the resulting explicit framework declarations.

The raw platform restore graph selects neutral frameworks even where SDK
compilation selects Unix implementations. Paired assemblies now publish their
contract's framework metadata with their implementation's project identity and
dependency graph. This avoids inventing Linux-to-Unix NuGet compatibility.
Implementation configuration checks remain separate. Executable dependency
manifests receive implementation-only references through SDK runtime dependency
items, without promoting them to compiler references.

## Platform and forwarding expansion

The platform batch passes the same seven raw/Bazel suites and loaded-producer
checks. It contains 58 source-built shared managed assemblies and eight native
products; 32 installed components remain observed. See
[platform evidence](runtime-loaded-platform-evidence.json).

The cumulative library/forwarding declaration contains 273 selected framework
nodes and composes 121 managed shared-framework replacements plus the private
net8 formatter and eight native products. All seven raw and Bazel suites pass with outcome parity: 118,375 passes and
64 skips. The 93 process proofs contain no installed runtime component. Edit
controls and independent recovery also pass; see the final acceptance results below.

Upstream shims explicitly disable APICompat and allow source/stub dependencies
from reference projects. The adapter retains that policy instead of imposing
the pure-reference-closure layout used for ordinary CoreLib consumers.
Every ordinary paired producer now declares its full contract dependency
layout. This also covers non-CoreLib facades such as XmlSerializer and XDocument,
whose contract dependencies differ from their implementation references. For
contracts with actual assembly type-forwarding attributes, the adapter retains
APICompat's normal implementation-reference fallback. This gives both
sides the same definition of forwarded types while retaining validation of
members owned by the contract. The negative formatter contract control checks
that an added member without an implementation is still rejected.

## Reproduction

Use the pinned checkout and Linux ARM64 toolchain preparation in
[runtime native qualification (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/runtime-native.md) and the raw/Bazel comparison
workflow in [runtime subset qualification (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/runtime-subset.md). Build the earlier
slice roots first, then run `subset_prepare.py SOURCE SLICE OUTPUT --vstest ARCHIVE`
for `loaded-common`, `loaded-platform`, `loaded-libraries`, and `loaded-shims` in
that order. Each output contains the cumulative explicit graph; raw compilation
in each invocation builds that slice's new roots. Source selection uses the
upstream commit recorded in `subset_slices.json`.

Prepare `native_support`, `native_host`, `native_crypto`, and
`native_compression` with `native_component_prepare.py NATIVE_INPUTS OUTPUT
support|host|crypto|compression`. Pass all four directories to
`subset_host.py WORKSPACE NATIVE_INPUTS ...`. Independently build those native
archives for the raw control and collect the eight products in one directory.
Then run `subset_raw.py SOURCE INVENTORY WORKSPACE RAW_NATIVE OUTPUT`.

With `RULES_MSBUILD_BAZEL` pointing to pinned Bazel 9.2.0, run:

```sh
python3 tests/explicit_msbuild/runtime/subset_remote.py \
  WORKSPACE BASE seed.json RAW_RESULTS --cache CACHE_URL --seed
python3 tests/explicit_msbuild/runtime/loaded_inventory.py \
  seed.parity.json installed.json --require-empty
python3 tests/explicit_msbuild/runtime/subset_contract_control.py \
  WORKSPACE BASE contract-controls --cache CACHE_URL
python3 tests/explicit_msbuild/runtime/subset_controls.py \
  WORKSPACE BASE managed-controls --cache CACHE_URL \
  --source src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs \
  --old 'UseSynchronizationContext = useSynchronizationContext;' \
  --new 'UseSynchronizationContext = useSynchronizationContext; GC.KeepAlive(this);' \
  --target //upstream:src_libraries_System.IO.Pipelines_src_System.IO.Pipelines_net10.0 \
  --contract //upstream:src_libraries_System.IO.Pipelines_ref_System.IO.Pipelines_net10.0
python3 tests/explicit_msbuild/runtime/subset_native_controls.py \
  WORKSPACE BASE native-controls --cache CACHE_URL --native-package native_crypto
```

Copy declared inputs, the rules/toolchain, raw reports, and `seed.json` to a fresh
container, excluding output bases and Bazel output links. Stop the producer before
running `subset_remote.py WORKSPACE FRESH_BASE consumer.json RAW_RESULTS --cache
CACHE_URL --expect seed.json`. It requires HTTP hits for managed/native/layout
outputs and all test results, compares output hashes, then forces every test to
execute and checks raw outcome parity and loaded producer hashes. Apply
`loaded_inventory.py consumer.parity.json installed.json --require-empty` to
that forced execution too. The consumer cannot upload local results.

The neutral Security and Quic generators also require their authored
`ApiExclusionListPath` files. The fixture now exports this property and declares
its file alongside other property-valued task inputs. Omitting it changed an
`Exists()` branch and generated duplicate types in Security. No upstream sources
or generator policy were changed. The expanded graph uses a 1.5 GiB Bazel JVM
heap in these qualification drivers; the former 768 MiB cap was exhausted while
reporting the large-graph compilation failure.

CoreLib consumers normally compile against implementation references, but
`CompileUsingReferenceAssemblies=true` is an authored exception. Inventory now
records that property. The generated graph preserves it together with individual
`SkipUseReferenceAssembly` overrides. Data.Common needs this mixed selection:
its XML references use public contracts while selected friend-API references use
implementations. The direct-only compiler input policy remains in effect.
