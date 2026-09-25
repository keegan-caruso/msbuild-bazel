# Avalonia remote compilation and tests

This extends the [Simple theme slice](avalonia-xaml-subset.md) from local
compilation and HTTP caching to execution on an SDK-free Buildbarn worker.
The production rules remain generic; the upstream-specific declarations and
controls live in `tests/explicit_msbuild/avalonia/remote_execution.py`.

## Scope

The fixture pins Avalonia `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0` (v11.3.12)
and SDK 10.0.400. Its 11 upstream projects contain 1,979 evaluated source files
and use 71 locked package archives. They include project-built analyzers and a
source generator, the Avalonia build tasks, embedded resources and compiled XAML.
A separate executable Bazel test constructs `SimpleTheme` and exercises
`DefaultMessageTypeResolver`.

The executor is Ubuntu 22.04 ARM64 with bubblewrap and two execution slots.
Its installed SDK directory is removed; it receives the SDK, runner, packages,
tools and sources through Bazel action inputs. Local fallback and local cache
uploads are disabled. Strict action environment is enabled: without it, Bazel
8.8 inherited client-specific Bazelisk/SDK paths in the test action `PATH`,
causing a test-cache miss after relocation even when every compilation hit.
The theme fixture is a runtime smoke test; the authored suite below extends test
coverage. Neither qualifies native UI backends or whole-repository support.

## Controls

- Force remote execution with action-cache reads disabled for the initial build.
- Compare all 11 reference assemblies byte-for-byte against raw MSBuild.
  Compare embedded resources and compiled XAML method identities, then construct
  the theme from both raw and Bazel outputs. Runtime DLL byte equality is not
  required because debug paths and post-compilation rewrites can differ.
- Run the same executable probe against the raw MSBuild output closure.
- A no-op executes no compilation or tests.
- Change the protocol library's missing-GUID exception message. Its reference
  hash must stay unchanged; only that library recompiles, and the downstream test
  must observe the new implementation. Test sources and data stay unchanged;
  only the library edit can invalidate the cached test.
- Add a public method. Its reference hash must change; affected consumers
  recompile and the downstream test must see the added runtime API.
- Copy only the prepared source/package workspace to an independent consumer
  at different paths. A fresh Bazel output base must recover all observed
  build/test actions from remote cache and match the producer's upstream DLL
  hashes in both target and execution configurations.

## Measured results

Bazel **8.8.0 and 9.2.0** pass every control. Each independent consumer recovers
all **101 recorded actions** from remote cache and matches **24 DLL hashes**.
The 13 compilation actions cover 11 upstream projects, the test probe, and
`DevGenerators` in both target and execution configurations. The 84 package
extractions similarly include packages needed in both configurations. Two
`TestRunner` records represent the test and its XML generation.

Client wall-clock samples, in seconds:

| Case | Bazel 8.8 | Bazel 9.2 |
| --- | ---: | ---: |
| Action-cold build and test | 68.24 | 46.78 |
| Warm no-op | 0.34 | 0.31 |
| Body edit and dependent test | 2.49 | 2.33 |
| API edit and dependent test | 14.11 | 14.14 |
| Independent cache recovery | 23.21 | 24.08 |

These are single correctness-run samples, not a Bazel-version regression
comparison. Action-cold uses a fresh output base and disables action-cache
reads; repository downloads, OS caches and worker CAS can be warm. Cold and
recovery include fresh-server startup. Every case downloads all outputs,
including intermediate package trees, so recovery is not a minimal-download
measurement. No claim of an empty infrastructure cache is made.

Raw setup builds took 11.74–15.74 s after separate restores of 5.47–5.96 s.
Those use MSBuild `/m:4`; the remote fixture uses two action slots and additionally
bootstraps its runner, extracts packages and runs the probe. These timings have
different scopes and are not a speedup comparison. See the
[compact evidence](avalonia-remote-evidence.json) and [performance guide](performance.md).

## Reproduce

Use the [Buildbarn executor](remote-execution.md#reproduce-with-buildbarn) and a
Linux ARM64 client with `RULES_MSBUILD_DOTNET_ROOT` and `RULES_MSBUILD_BAZEL` set.
The client needs the SDK for raw controls and one-time fixture preparation.

```sh
python3 tests/explicit_msbuild/avalonia/setup.py /path/to/pinned/avalonia /tmp/theme
python3 tests/explicit_msbuild/avalonia/remote_execution.py /tmp/theme /tmp/theme-rbe \
  --executor grpc://WORKER_IP:8980
```

Use fresh, uniquely named output directories (the name scopes remote cache entries). Set `USE_BAZEL_VERSION=8.8.0` or `9.2.0` to select
the baseline. Preparation performs restore, a raw Release build and evaluation,
then writes explicit BUILD declarations. None runs inside the Bazel build.
The remote fixture switches those declarations to the downloaded SDK toolchain
and enables remote execution explicitly.

For independent recovery, copy `/tmp/theme/bazel` without its `bazel-*` symlinks
or any output bases to another client. Then run:

```sh
python3 tests/explicit_msbuild/avalonia/remote_execution.py \
  /consumer/theme /consumer/theme-recovery --recover \
  --executor grpc://WORKER_IP:8980
```

The local rules override is rewritten for the consumer. Reports and execution
logs are written to the output directory; raw parity is `/tmp/theme/parity.json`.

## Reduced-download qualification

`tests/explicit_msbuild/avalonia/downloads.py` starts a fresh consumer output base
for each of `all`, `toplevel` and `minimal`, using the completed remote fixture's
workspace and seeded instance. Each mode must recover the test from cache,
launch it locally with `bazel run`, then correctly rebuild and rerun the test
following body and API changes. Test sources remain unchanged.

```sh
python3 tests/explicit_msbuild/avalonia/downloads.py /consumer/theme /tmp/downloads \
  --executor grpc://WORKER_IP:8980
```

The full-output parity fixture still uses `all` to inspect every DLL. Reduced
modes verify runtime behavior and execution logs instead of forcing all the
intermediate files to download for hash checks. Local launch is a separate case:
it can fetch runtime inputs that a cached remote test did not need locally.

All three modes pass recovery, local launch and both edits on Bazel 8.8 and 9.2.
The 8.8 materialization check found 84 extracted archives after `all` recovery
and zero after `toplevel`/`minimal` recovery. A later local launch can download
additional inputs. Single-run timings are exploratory; use the repeated profile
below before attributing a speedup to download policy.

### Repeated recovery profile

Bazel 9.2, three fresh-server samples per mode, rotating mode order on the same
ARM64 consumer. Every sample recovered all 101 remote actions; the repository
cache and worker CAS were already warm. No local launch runs inside this timing.

| Mode | Median wall time | Client bytes received | Download interval union |
| --- | ---: | ---: | ---: |
| `all` | 13.42 s | 927.09 MB | 3.78 s |
| `toplevel` | 9.57 s | 2.91 MB | 0.08 s |
| `minimal` | 9.93 s | 2.90 MB | 0.07 s |

`toplevel` reduced recovery time by about **29%** and client traffic by **99.7%**
in these matched samples. There is no demonstrated advantage for `minimal` over
`toplevel` here. Prefer `--remote_download_outputs=toplevel` for normal usage;
retain `all` for complete-output parity checks. This test-target result does not
predict transfer size for applications with large top-level outputs.

For `toplevel`, median analysis time was 3.19 s, other in-command work 2.75 s,
and time outside the command (including client/server startup) 1.81 s. The
execution phase, which includes cache recovery, was 1.90 s. Cache-lookup intervals
covered 0.35 s and Merkle-tree construction 0.21 s. These trace intervals overlap;
they must not be added to phase times. Independently calculated medians also
need not sum to median wall time. Remaining time is mainly startup and analysis,
not bulk downloads. Network counters cover all non-loopback client traffic,
including RPCs, rather than only CAS payloads.

```sh
python3 tests/explicit_msbuild/avalonia/profile_recovery.py \
  /consumer/theme /tmp/recovery-profile --executor grpc://WORKER_IP:8980
python3 tests/explicit_msbuild/avalonia/summarize_recovery.py /tmp/recovery-profile
```

The driver records BEP metrics, JSON traces, command logs and container network
counters. See [compact measurements](avalonia-download-evidence.json).

## Authored test suite

`tests/explicit_msbuild/avalonia/authored_tests.py` qualifies the complete authored
`Avalonia.Generators.Tests` suite, with no test filter or source changes for the
baseline. Its graph contains 15 projects and 2,254 evaluated source files. The
checkout must include its pinned submodules, including DataGrid revision
`85a0b32ef6d963c1d67619ca3e2f6da0bc43ac9a` used by Diagnostics resources.

The suite keeps its `net8.0` target. Raw and Bazel executions both use the declared
SDK's .NET 10 runtime with explicit `DOTNET_ROLL_FORWARD=Major`; this does not
qualify execution on a .NET 8 runtime. VSTest CLI 17.14.1 is checksum-pinned and
the upstream xUnit adapter is 2.8.2. Executable test compilation is retained.

Both Bazel 8.8.0 and 9.2.0 passed all 59 authored tests with matching raw/remote
names and outcomes. The negative control rebuilt only the generator and failed
45 tests while preserving its reference assembly. Restoring the source recovered
the passing result from cache. Each independent consumer recovered all 122
recorded actions from cache and the same 59 passing results. See the
[qualification evidence](avalonia-authored-evidence.json).

```sh
git -C /path/to/pinned/avalonia submodule update --init --recursive
python3 tests/explicit_msbuild/avalonia/setup.py /path/to/pinned/avalonia /tmp/authored \
  --entry tests/Avalonia.Generators.Tests/Avalonia.Generators.Tests.csproj
python3 tests/explicit_msbuild/avalonia/authored_tests.py /tmp/authored /tmp/authored-rbe \
  --executor grpc://WORKER_IP:8980
```

The fixture compares individual raw/remote TRX names and outcomes. A deliberate
body-only exception in `XamlXViewResolver.ResolveView` must rebuild only the
generator, preserve its reference hash and cause authored tests to fail.
Restoring the source must recover the passing result. Full downloads are used
where reference hashes are inspected; no-op/restoration/recovery use `toplevel`.
For independent recovery, copy only `/tmp/authored/bazel` without `bazel-*` links
and run the same script with the copied workspace and `--recover`.

### Mixed-framework Markup suite

The configured fixture now qualifies `Avalonia.Markup.UnitTests` without retargeting
its `netstandard2.0` helper. It preserves **25 configured project nodes**,
**107 package targets** and **3,894 evaluated source entries**. Four projects have
both net8.0 and .NET Standard variants. Target/execution configurations require
27 compilation actions, including separate build-task and generator instances.

Both Bazel **8.8.0 and 9.2.0** pass all **287 authored tests**, matching raw MSBuild
by individual test name and outcome. There is no baseline test filter or source
patch. The SDK/runtime and VSTest pins are the same as the generator qualification
above; Markup retains its library output type.

The fixture declares the modern variant at each mixed-framework convergence and
honors private project compiler dependencies. Runtime staging excludes strictly
older inherited package assemblies listed in the application's SDK platform
manifest. These are [generic rule contracts](configured-graphs.md), not Avalonia
exceptions.

| Control | Observed result on both baselines |
| --- | --- |
| No-op | No compilation or test execution |
| Body exception in `Binding()` | Both Markup variants rebuild; 43 tests fail; reference hash unchanged |
| Restore body | Passing compile/test outputs recovered from cache |
| Add public API to `Binding` | 10 affected projects rebuild; all 287 tests pass |
| Restore API | Passing compile/test outputs recovered from cache |

On each baseline, an independent consumer with a different workspace path and
fresh output base recovered **all 168 recorded actions** from the remote cache,
including the same 287 passing test results. Neither compilation nor tests ran
on the consumer. The producer and consumer had separate disks and no shared mount.

See [compact evidence](configured-graphs-evidence.json) for per-case actions and
qualification wall times. These runs establish correctness and cache behavior,
not a controlled raw/remote performance comparison. The raw control and remote
execution use different scheduling and cache conditions.

```sh
python3 tests/explicit_msbuild/avalonia/setup.py /path/to/pinned/avalonia /tmp/markup \
  --entry tests/Avalonia.Markup.UnitTests/Avalonia.Markup.UnitTests.csproj
USE_BAZEL_VERSION=9.2.0 python3 tests/explicit_msbuild/avalonia/authored_tests.py \
  /tmp/markup /tmp/markup-rbe92 --suite markup --executor grpc://WORKER_IP:8980
```

Repeat with `USE_BAZEL_VERSION=8.8.0` and a new output directory. For independent
recovery, copy only the prepared `bazel` workspace without `bazel-*` links, and
run `authored_tests.py` with `--suite markup --recover` against a fresh output
base. The workspace records its remote instance and expected test outcomes.

This qualifies the selected Markup suite on Linux ARM64, not all Avalonia projects,
.NET 8 runtime execution, platform-specific graphics, or arbitrary framework
variant unification. See [configured graph limits](configured-graphs.md#scope).
