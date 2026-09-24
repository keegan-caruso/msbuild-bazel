# Bazel test execution

`msbuild_test` builds one assembly/framework with the normal explicit project
inputs, then runs a separate Bazel test action. Test execution never restores,
evaluates a project, or compiles. The test action consumes implementation/runtime
closures; reference assemblies remain compilation inputs only. Consequently a
body-only dependency edit can rerun tests without recompiling their assemblies.

## Tests across frameworks

`msbuild_test_project` expands the same explicit inputs into one `msbuild_test`
per framework and a native Bazel `test_suite`:

```starlark
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test_project")

msbuild_test_project(
    name = "CoreTests",
    project = "CoreTests.csproj",
    target_frameworks = ["net8.0", "net10.0"],
    srcs = ["Tests.cs"],
    deps = [":Core"],
    test_protocol = "vstest",
    test_runner = ":vstest",
    test_adapters = [":xunit_adapter"],
)
```

`bazel test :CoreTests` runs both tests; `:CoreTests_net8_0` and
`:CoreTests_net10_0` remain individually addressable. The macro shares the
[project facade's override semantics](explicit-bazel-rules.md#project-facade).
Runner, adapter, runtime host, package and source inputs remain explicit. Runtime
selection is independent of the compile TFM; declare any required roll-forward
policy through the existing test environment or runtime host.

The remote synthetic `tests/explicit_msbuild/project_facades.py` covers exact and
.NET Standard fallback selection, aggregate test execution, shared and
variant-specific body edits with unchanged public references, restoration, and
fresh-output-base cache recovery. Its `net10.0-windows` variant uses only portable
managed APIs on Linux; it does not qualify Windows execution or Windows APIs.
Run it against the [qualified worker](remote-execution.md):

```sh
python3 tests/explicit_msbuild/project_facades.py /tmp/facades \
  --executor grpc://WORKER_IP:8980
```

## Protocols

- `test_protocol = "executable"` (the compatibility default): execute the managed
  application and propagate its exit status. No filter, settings or shard support.
- `test_protocol = "mtp"`: execute the managed application, request a TRX report,
  and convert it into Bazel test XML. Explicitly reference a compatible
  `Microsoft.Testing.Extensions.TrxReport` package and its build registration.
- `test_protocol = "vstest"`: build a library with SDK-generated runtime config;
  invoke an explicitly declared VSTest runner against it. Set
  `test_output_type = "exe"` when the project requires executable compilation;
  this retains SDK entry-point and analyzer behavior. No `dotnet test` or
  MSBuild invocation occurs during test execution.

Example VSTest bindings (package targets are normal checksum-locked archives):

```starlark
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test", "msbuild_test_tool")

msbuild_test_tool(
    name = "vstest",
    package = "//packages:microsoft.testplatform.cli",
    path = "contentFiles/any/net9.0/vstest.console.dll",
)
msbuild_test_tool(
    name = "xunit_adapter",
    package = "//packages:xunit.runner.visualstudio",
    path = "build/net8.0",
)
msbuild_test(
    name = "Tests",
    project = "Tests.csproj",
    target_framework = "net10.0",
    srcs = ["Tests.cs"],
    # Declare the project's normal deps/build_deps/analyzers/package metadata.
    test_protocol = "vstest",
    test_runner = ":vstest",
    test_adapters = [":xunit_adapter"],
    test_settings = "tests.runsettings",
    data = ["fixture.json"],
    env = {"TEST_MODE": "offline"},
    size = "small",
)
```

Paths above are version-specific, not implicit conventions: the qualification
uses Microsoft.TestPlatform.CLI 17.14.1 and xunit.runner.visualstudio 3.1.1.
A binding declares the package closure as runfiles without making it a compilation
dependency. The launcher composes declared adapter files beside the test assembly
with collision checks: VSTest's .NET host discovers adapters there even when the
console has an explicit adapter path ([host implementation](https://github.com/microsoft/vstest/blob/v17.14.1/src/Microsoft.TestPlatform.TestHostProvider/Hosting/DotnetTestHostManager.cs#L582)).
Adapter packages may additionally be project build/runtime dependencies
when their own targets require it. `test_runner` and `test_adapters` are VSTest-only.

## Bazel contract

- `--test_filter` uses native VSTest `TestCaseFilter` syntax. MTP requires explicit
  `test_filter_argument = "--filter"` or `"--filter-query"` to select an option
  actually supported by the framework. No universal cross-framework filter syntax
  is inferred. Unsupported filtering fails.
- `args`/`--test_arg` are forwarded. Reporting locations, settings and verdict
  overrides owned by the adapter are rejected rather than silently overridable.
- `test_settings` is a declared MTP JSON config or VSTest runsettings file.
- `test_settings_output` instead selects a relative file from the built runtime
  output (for example `.runsettings`). Missing files fail the test; the two
  settings attributes are mutually exclusive. VSTest child processes use the
  declared runtime host, overriding any host path captured in runsettings.
  `env`, settings, test arguments and data affect execution without entering the
  compilation request.
- `test_output_dirs = ["logs"]` exposes a writable relative directory in the
  private runtime, backed by `TEST_UNDECLARED_OUTPUTS_DIR/files/logs`. This supports
  programs whose output directory is configured at build time. Paths are explicit,
  relative, and must not collide with runtime inputs. `test_diagnostics = True`
  retains VSTest console/testhost diagnostics with the test outputs.
- Writable staging is private under `TEST_TMPDIR`. The runtime closure contains
  declared assemblies, native/package files and data. No host package cache is
  consulted by the launcher.
- stdout/stderr stream directly. SIGTERM/SIGINT terminate the child process tree;
  cancellation is always failure. Bazel owns timeout, retries and scheduling.
- TRX becomes per-case XML at `XML_OUTPUT_FILE`; TRX and attachments written in
  `TEST_UNDECLARED_OUTPUTS_DIR` survive staging cleanup. Assertion failures become
  XML failures; runner/report problems become errors. A failed report cannot turn
  a zero process exit into success, and a passing report cannot hide a nonzero exit.
- Missing/malformed reports fail. Zero discovered tests fail unless
  `allow_empty_tests = True`. For MTP only, a valid empty TRX and no-tests exit 8
  can then produce success; other nonzero exits remain failures.
- Sharding is explicitly rejected, including command-line-forced sharding.
  Coverage and a universal test-discovery API are not implemented.

Test result caching is Bazel's normal test cache. External-service tests still
need explicit nonhermetic execution/cache policy; merely declaring a test does
not make an external service reproducible. Windows and cross-platform execution
are not qualified by this Linux ARM64 work.

## Small-project qualification

Run in the qualified Linux ARM64 worker container, with explicit SDK and Bazel:

```sh
bash scripts/dotnet.sh build tools/ExplicitBuild -c Release
python3 -m unittest discover -s tests/explicit_msbuild -p test_test_execution.py -v
python3 tests/explicit_msbuild/protocol.py /tmp/test-protocol
python3 tests/explicit_msbuild/vstest.py /tmp/test-protocol
python3 tests/explicit_msbuild/protocol_cache.py seed /tmp/test-protocol --cache "$CACHE_URL"
python3 tests/explicit_msbuild/protocol_controls.py /tmp/test-protocol
```

`protocol_cache.py serve <directory>` supplies a disposable fixture HTTP cache.
For independent recovery, copy only the prepared `src` workspace and pinned rule
and SDK inputs into a fresh container, stop the producer, then run `consume` with
the same cache URL. Do not copy output bases, NuGet caches or test results.

The synthetic cases exercise real MTP/xUnit, VSTest/xUnit, NUnit and MSTest:
pass, assertion failure, parameterized cases, skipped tests, filters, and empty
selections. MTP additionally exercises crash, timeout, and empty-suite opt-in.
Report boundary controls cover missing/malformed reports, hostile XML, false
success, nonzero exit, and cancellation. Missing runner/adapter bindings and
forced sharding fail. Body edits rerun the test while preserving the reference
assembly; settings/data/filter edits execute no compilation actions.

References: [Bazel test contract](https://bazel.build/reference/test-encyclopedia),
[MTP reports](https://learn.microsoft.com/en-us/dotnet/core/testing/microsoft-testing-platform-test-reports),
[VSTest CLI](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-vstest).

## Measured qualification

Results are recorded in [bazel-test-evidence.json](bazel-test-evidence.json).
Linux ARM64, SDK 10.0.400: the seven MTP scenarios and twelve VSTest scenarios
passed their expected success/failure assertions on both Bazel 9.2.0 and 8.8.0.
VSTest covers xUnit, NUnit and MSTest; MSTest also exercises executable compilation.
The xUnit fixture supplies its adapter solely through `test_adapters`.
Seven report/lifecycle boundary unit tests pass. The repository .NET/style checks
and existing explicit build/run/cache acceptance suite also pass on 9.2.0.

Cache controls on 9.2.0 verify unchanged local reuse, implementation-only dependency
invalidation with an unchanged reference DLL, and settings/data/filter changes
without compilation. A fresh output base seeds the full HTTP action cache with
synchronous uploads before independent-container recovery. With the producer stopped,
the fresh consumer recovered all 17 actions (14 package extractions, two assemblies
and the test) remotely, including XML/TRX; no worker or sandbox action executed.

### Real projects, evaluated after the synthetic controls

These are selected managed test configurations, not qualification of every target,
framework, operating system or integration service in each repository. Each uses
pinned source and compares test names/outcomes with raw SDK build plus the same
VSTest runner. Serilog and Spectre disposable copies select/retarget `net10.0`,
including Serilog's helper project; Spectre retains the documented generator/MinVer
fixture setup. No failing tests were filtered out.

| Project / selected suite | Cases | Bazel outcomes | Raw outcomes |
| --- | ---: | --- | --- |
| Serilog | 816 | 815 pass, 1 fail | 816 pass |
| Spectre.Console.Ansi | 454 | 454 pass | 454 pass |
| Spectre.Console | 742 | 492 pass, 250 fail | 742 pass |
| ASP.NET Core, 12 suites | 6,692 | 6,599 pass, 40 skip, 53 fail | 6,652 pass, 40 skip |

Pinned revisions:

- Serilog: `bebc7719004f76187ae72e64ce138ec2540f2070`.
- Spectre.Console: `76b673337fe9d03ec41d0498987e53c4d5e7b33a`.
- ASP.NET Core v10.0.0: `7387de91234d3ef751fa50b3d1bfede4130213ff`.

ASP.NET's selection covers Headers, Http.Abstractions, Http.Extensions,
Http.Results, Http, Routing.Abstractions, WebUtilities, DataProtection.Abstractions,
Cryptography.Internal, Cryptography.KeyDerivation, RequestDecompression and
ResponseCompression. Eleven suites match raw test names/outcomes exactly.
All 53 Http.Extensions failures read RequestDelegateGenerator baselines through
embedded absolute compilation paths. Serilog's `ArgumentNullTests.Run` similarly
expects a source checkout through `CallerFilePath`. All 250 Spectre failures
attempt snapshot writes beneath the read-only embedded build root.
These remain compatibility limits: declared runfiles do not recreate arbitrary
absolute build-time paths. A follow-up should make these source/baseline inputs
explicit and relocatable, rather than expose the original checkout to tests.

Real-project evaluation produced three generic fixes, each checked synthetically:

- Compose explicitly bound VSTest adapters beside the test assembly, where the
  .NET test host actually discovers them.
- Validate central package versions against active project references, retaining
  closure validation when central transitive pinning is enabled. The 17-case
  package-semantics fixture passes; an unused central version no longer rejects
  Spectre's legitimate transitive version.
- Preserve executable test compilation and expose explicitly declared writable
  relative output directories. ASP.NET's fixture configures its build-time log
  path through a declared late targets file and retains logs in test outputs.
  Http.Results additionally declares its generated-source runtime data file.

Reproduction harnesses: `real_tests.py` runs Serilog/Spectre against checkouts at
these revisions. `aspnetcore/tests.py` consumes the prepared ASP.NET workspace from
its existing scale fixture; `aspnetcore/raw_tests.py` supplies the paired raw
control. Their module docstrings and command-line arguments describe the inputs.
This is correctness evidence, not a controlled performance benchmark.

[Friend-assembly qualification](internals-visible-to.md) separately verifies
`InternalsVisibleTo`, including internal API versus body invalidation, signed
friend identity, and actual test execution after relocated assembly recovery.
