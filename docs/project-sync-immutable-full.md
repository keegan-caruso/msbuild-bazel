# Complete Immutable graph generation

Stage 2 of the [roadmap](roadmap.md) generates all 36 configured assembly
producers in the selected `System.Collections.Immutable.Tests` graph. Production
`msbuild_sync` emits their compilation declarations, including reference projects,
implementations, test utilities, analyzers and linker tools. The qualification
fixture retains package acquisition, reviewed task contracts and provider bindings.
It never patches generated output.

## Generic additions

- `platform` controls evaluation and emitted build properties together. CoreLib's
  ARM64 configuration must select the ARM64 linker inputs, rather than the inputs
  selected by `AnyCPU`.
- `packageReferencePaths` preserves exact assembly files in locked packages;
  file references are not converted into package-name references. Paths must be
  safe, present and declared. `transitiveCompileReferences` preserves the existing
  rule's direct-only compilation policy where requested.
- An `items` project-reference binding supplies explicitly declared item providers
  for an exact `Targets`/`OutputItemType`/`ReferenceOutputAssembly=false` contract.
  Sync does not execute the upstream target or guess its outputs.
- Resource `SubType` metadata survives evaluation and generation.

The public mapping API and examples are in [project synchronization](project-sync.md).
Runtime-specific conditions and custom-document hashes remain in the fixture.

## Bootstrap and boundaries

Sync needs the source-built ILLink task assembly to evaluate its declared binding.
A first production sync generates the five-project tool closure. After loading
that generated file, normal Bazel compilation builds the tools and the full sync
emits all 36 producers. Subsequent runs use only `//:sync`; `//:sync_tools` is the
initial bootstrap. Unknown task contracts continue to fail.

The fixture reviews seven additional project/import contracts and retains explicit
CoreLib header/XML inputs, reference/implementation pairs and assembly selections.
The NativeAOT directive remains a declared input; this does not qualify NativeAOT.
Tests still run on the installed runtime host with the generated Immutable assembly
substituted and verified by SHA-256. This stage does not qualify a source-only host,
independent cache recovery or remote execution for the generated graph.

## Reproduce and verify

Use pinned disposable checkouts and the Linux ARM64 toolchain described in
[the HTTP qualification](project-sync-http-full.md):

```sh
python3 tests/project_sync/upstream/expanded.py \
  ASPNET_CHECKOUT RUNTIME_CHECKOUT - FRESH_OUTPUT
```

The driver acquires its runner, prepares both upstream graphs, generates every
producer, and runs raw parity, body/API edits, repeat-sync, missing-input and
contract-drift controls. `runtime_graph_controls.py` additionally removes a task
source and the required assembly selections, then verifies repair. The assembly
ambiguity is rejected as a conflicting runtime input, not silently resolved.

[Compact evidence](project-sync-immutable-full-evidence.json) records the completed
runs, including one fresh end-to-end combined driver run. The full upstream scope is Linux ARM64, SDK 10.0.400, Bazel 9.2.0,
Release/net10.0 and runtime v10.0.0. The small sync/application acceptance also
covers Bazel 8.8.0, including an explicit platform, source addition and props edits.

The 22,544 raw/Bazel test outcomes use the existing bounded display-name
normalization. No normalization was added. Body edits preserve the public contract;
API edits change it; both rerun tests and load the generated implementation.
These are correctness runs, not new performance measurements.
