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
causing a test-cache miss after relocation even when every compilation hit. This is a selected graph and a runtime smoke test, not
Avalonia's authored test suite, native UI backends, or whole-repository support.

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
