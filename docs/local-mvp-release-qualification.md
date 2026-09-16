# Pinned local MVP candidate qualification (#64)

This qualifies the single combination in the [support contract](local-mvp-contract.md),
including the #7 traversal optimization. The clean candidate uses a new detached
checkout, empty owned HOME and package/output/cache directories, the locked
Nix shell and newly built adapter tools. The machine's existing Nix daemon/store
is shared; this is a clean user-state acquisition, not a fresh OS or empty-store
download benchmark. File Provider-managed storage is excluded as documented.

The qualifying source is the candidate code commit recorded in the evidence.
Serilog is independently acquired at
`49b5339ce85385dc52d4d8e8f2b8308becf23506`; packages are restored into a new
owned cache, including the explicitly tested PolySharp 1.16.0 mutation.

Required gates:

- Locked toolchain acquisition, source/package receipts and exact SDK/runtime/
  MSBuild/Bazel identities; RUL-6 ancestor verification.
- Owned .NET builds/style and runner tests, preparation/schema/identity tests,
  Starlark core/extensions and generated-workspace analysis.
- The complete #6 native input, corruption, publication, concurrency, fallback
  and producer-free recovery matrix under the optimized candidate.
- Serilog ordinary/adapter mutation behavior, signing/resource/generator controls,
  exact approval-test failure diagnostics and forced relocated cache recovery.
- Same-candidate paired preparation qualification and 40 Build/Test comparison
  samples, with acquisition/restore/warm-up reported separately.
- Old-controller cache invalidation, current schema/request rejection and
  lifecycle/entry-point dispositions from the frozen contract.

Execution is in progress. Final results, reproduction commands, evidence hashes
and limitations will be recorded here before this issue is considered complete.
No GitHub CI has been requested or dispatched. Release packaging, version/tag
selection and sign-off remain #65.
