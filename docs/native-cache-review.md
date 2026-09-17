# Native-cache merge review and real-project boundary

The accumulated performance work remains experimental and opt-in. The default
package-capable adapter is retained. This review covers preparation hashing and
output-collision checks, the reference/runtime split, whole-graph experiments,
the native project cache, remote snapshot transport and startup orchestration.

## Review fixes

Malformed cache metadata could escape cache-miss handling as a schema/runtime
error. The snapshot broker now rejects JSON objects/arrays with invalid shapes
and non-string keys. The .NET bundle reader uses the existing strict typed JSON
reader for seals and rejects null artifact entries. The native plugin uses strict
constructor/null/duplicate-property validation and checks null target items and
metadata values before replay. These failures remain rejected cache entries;
normal compilation can replace them. Regression cases cover malformed sealed
metadata through real loopback HTTP and malformed .NET seals.

## Local validation

- All repository-owned .NET projects: warning-free builds and required style checks.
- ActionRunner contract/process tests, including compile/runtime composition and
  malformed-seal rejection: passed.
- Native-cache unit tests: 20 passed; preparation-reuse tests: 68 passed;
  compile-boundary eligibility test: passed; code-style enforcement tests: 5 passed.
- Starlark formatting/lint: 11 files passed.
- Fresh ten-project native/Bazel fault matrix: passed, including relocation,
  body/API edits, corrupt/missing data, SDK identity changes, service outage,
  failed-build publication prevention and sandbox probes.
- A final two-project fresh-consumer smoke checks the last metadata guard.

The scale evidence remains in the linked performance findings; this review did
not reclassify single cold timing observations as statistical speedups. No GitHub
CI was dispatched.

## Representative package project

The unmodified upstream Serilog revision
`49b5339ce85385dc52d4d8e8f2b8308becf23506` was validated with the existing native
Bazel Build/Test adapter, using `tools/probe_serilog_test_adapter.py`. The
`Serilog.ApprovalTests` project and its Serilog dependency passed the cold,
unchanged, changed-test-data, expected-exception and relocated-recovery cases.
The harness also exercised rejection controls for changed source/package inputs
and missing test data. Relocated recovery removes producer preparation, output
base and source state before verifying disk-cache recovery and the actual test.

The new native project-cache qualifier rejects the same unmodified source with
`unqualified SDK selection`: upstream selects SDK 10.0.100 with latestFeature
roll-forward, while this prototype admits only the owned 10.0.400 fixture policy.
No native-cache build of Serilog was attempted after rejection. This is boundary
validation, **not native-cache package support**.

Changing that SDK check alone is insufficient. Serilog also uses nested project
layout, conditional framework selection, imported properties/targets, embedded
resources and the PolySharp package generator. Its approval project includes
runtime/test packages and imported targets. The native cache currently admits a
much narrower authored grammar and composes project-only runtime metadata.

## Next qualification slice

Use this pinned Serilog revision as the acceptance target, while keeping the
existing adapter as the reference behavior:

1. Build native-cache sessions from the existing evaluated graph and verified
   package manifests, rather than relaxing the synthetic fixture parser ad hoc.
2. Include selected package compile/runtime/analyzer assets, imports, resources
   and relevant SDK configuration in cache identity and declared action inputs.
3. Preserve SDK package runtime metadata and current project implementations when
   composing runtime outputs. Qualify generator behavior before allowing API-only
   dependency keys; use full implementation dependencies where required.
4. Prove cold and relocated recovery, source/API changes, package-version and
   generator changes, damaged/missing cache fallback, runtime byte parity and the
   real approval test. Only then broaden eligibility for this named slice.

The optimization prototype can merge without claiming these gates have passed.
