# Smallest authored CoreCLR/JIT bootstrap probe

This is an **unqualified boundary**, not a passing JIT result. The additional
[Pipelines suite](runtime-pipelines.md) is the completed runtime-coverage extension.

At pinned runtime v10.0.0 revision `60629d14374c56f1cb51819049ad1fa529307f8d`,
probe `src/tests/JIT/CodeGenBringUpTests/Add1_ro.csproj` with SDK 10.0.400 on Linux
ARM64. Preserve the authored project, source and CoreCLR imports:

```sh
dotnet msbuild src/tests/JIT/CodeGenBringUpTests/Add1_ro.csproj \
  -restore -t:Build -p:Configuration=Release -p:TargetOS=linux \
  -p:TargetArchitecture=arm64 -p:BuildAllTestsAsStandalone=true \
  -p:CLRTestPriorityToBuild=1 -v:minimal
```

Observed sequence:

1. Build without restore fails for the shared
   `artifacts/tests/coreclr/packages/Common/test_dependencies/test_dependencies/project.assets.json`.
2. Restoring the authored `src/tests/Common/test_dependencies/test_dependencies.csproj`
   succeeds, then Build requires `XUnitWrapperGenerator` assets.
3. Restoring/building the test's authored graph builds `XUnitWrapperGenerator`,
   but the test compilation still lacks `Xunit` / `FactAttribute` references.

The next increment must reproduce upstream's test-dependency reference generation,
then declare those products and the wrapper-generator analyzer in Bazel. First
establish a passing raw authored-project control. Do not substitute a new SDK
project and infer support for CoreCLR's test infrastructure.

The source test entry point returns **100** for success and **-1** for failure.
Retain the upstream generated wrapper's semantics, or prove a generic exit-code
adapter with synthetic pass/fail tests before exposing it to Bazel. The current
executable-test protocol treats nonzero process exits as failures.

No Bazel build, execution, invalidation, remote recovery, JIT stress or timing
claim is made for this probe. Full logs were preserved at
`/private/tmp/runtime-jit-boundary-evidence.tar.gz`, SHA-256
`ca77d21f10a22ee1f8095205dec8c2e64ced07eef81a981422b5997c83e9523c`.
