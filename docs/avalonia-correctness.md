# Avalonia edit and Headless qualification

This continues the pinned [expanded Avalonia graph](avalonia-expanded.md).
The controls exercise dependency correctness, not performance.

The four edit/restoration controls pass on **Bazel 8.8.0 and 9.2.0**, using
the SDK-free Linux ARM64 worker. [Evidence](avalonia-invalidation-evidence.json)
records exact executed targets and negative-control failure counts.

## Edit contracts

`tests/explicit_msbuild/avalonia/invalidation.py` starts from the expanded
source-only workspace and its producer cache namespace. It makes one edit at a
time, checks the exact executed compilation/generation/test targets, and restores
the original bytes in a `finally` block.

| Input edit | Expected compilation/generation | Expected tests |
| --- | --- | --- |
| Native IDL internal enum value | Native IDL generator, Native, Desktop | None |
| Simple theme unused XAML color resource | Both configured Simple theme assemblies | All five suites |
| Corrupt rendering baseline | None | Skia rendering fails |
| Corrupt declared Fontconfig library | None | Both Skia suites fail |

The IDL changes its generated output and friend-visible reference contract.
The XAML changes the runtime assembly while preserving reference bytes. The
negative controls must produce failing test cases or, for the corrupt native
library, an aborted test host that reports the exact Fontconfig loader error.
An unrelated failed Bazel command does not satisfy the control. Every restoration must recover the original passing outcomes without
executing compilation, generation, or tests.

```sh
python3 tests/explicit_msbuild/avalonia/invalidation.py /path/to/expanded/bazel \
  /tmp/fresh-edit-results --executor grpc://WORKER_IP:8980
```

Set `USE_BAZEL_VERSION` to the producer's version. `--instance` can select another
producer cache namespace containing the same inputs. Use a fresh result directory;
its name distinguishes mutation bytes so earlier runs cannot cache the edit
controls themselves.

## Headless execution

On Bazel 9.2.0, two small source-built controls pass under both XUnit and NUnit:
UI-thread access, text input and offscreen frame capture; and VNC framebuffer
capture plus a loopback RFB handshake. TurboJPEG is a declared runtime dependency
of the pinned VNC session. This does not qualify password authentication, remote
network deployment, or all VNC encodings.

All four upstream Headless suites (XUnit/NUnit, per-test/per-assembly isolation)
have a passing raw/remote comparison: **264 passes and 4 skips** across 26
configured projects. The subsequent no-op executes nothing. The small controls
add **4 passes** across 25 configured projects. See
[Headless evidence](avalonia-headless-evidence.json).

**Stability limit:** NUnit's per-assembly
`Should_Not_Crash_On_CombinedGeometry` intermittently captures a null frame.
It failed in two remote cold runs and in **6 of 20 unmodified raw runs** with two
concurrent processes. Three isolated remote repeats and three serial raw repeats
passed. The full passing comparison followed cached compilation and executed all
tests afresh. No test is patched, filtered, or automatically retried; a failing
raw or remote run still fails the qualification command. Passing parity does not
establish a flake-free upstream suite.

```sh
python3 tests/explicit_msbuild/avalonia/setup.py /path/to/avalonia /tmp/headless-smoke \
  --headless-controls
python3 tests/explicit_msbuild/avalonia/expanded.py /tmp/headless-smoke /tmp/smoke-results \
  --test Qualification.Headless.XUnit --test Qualification.Headless.NUnit \
  --executor grpc://WORKER_IP:8980

python3 tests/explicit_msbuild/avalonia/setup.py /path/to/avalonia /tmp/headless \
  --entry tests/Avalonia.Headless.XUnit.PerTest.UnitTests/Avalonia.Headless.XUnit.PerTest.UnitTests.csproj \
  --entry tests/Avalonia.Headless.XUnit.PerAssembly.UnitTests/Avalonia.Headless.XUnit.PerAssembly.UnitTests.csproj \
  --entry tests/Avalonia.Headless.NUnit.PerTest.UnitTests/Avalonia.Headless.NUnit.PerTest.UnitTests.csproj \
  --entry tests/Avalonia.Headless.NUnit.PerAssembly.UnitTests/Avalonia.Headless.NUnit.PerAssembly.UnitTests.csproj
python3 tests/explicit_msbuild/avalonia/expanded.py /tmp/headless /tmp/headless-results \
  --test Avalonia.Headless.XUnit.PerTest.UnitTests \
  --test Avalonia.Headless.XUnit.PerAssembly.UnitTests \
  --test Avalonia.Headless.NUnit.PerTest.UnitTests \
  --test Avalonia.Headless.NUnit.PerAssembly.UnitTests --executor grpc://WORKER_IP:8980
```

For a separate test-execution check against already-cached compilation, pass
`--reuse-compilation-from PRODUCER_INSTANCE`. It asserts zero executed compilation
or generation actions: it recovers compilation first, then disables remote cache
reads for the test invocation. Successful test results can still be published.
It does not use `--nocache_test_results`, which prevented remote reuse in the
initial harness control. This mode is not a cold-build result.

## Native input acquisition

The fixture now uses `native_packages.bzl`, a repository rule built from Bazel's
[download and extraction APIs](https://bazel.build/versions/8.0.0/rules/lib/builtins/repository_ctx).
`native-packages.json` pins package URLs, versions, archive SHA-256 digests,
exported paths, and expected file hashes. The rule extracts Debian archives and
their data archives with Bazel APIs, then exports individual file labels. It
invokes no host package manager, shell, Python, or native executable.

Fontconfig and its dependencies plus six DejaVu fonts come from eight locked
Ubuntu packages; the VNC graph adds a ninth, TurboJPEG. The client and executor
still supply the qualified platform's base C runtime. This is not a
cross-platform sysroot or a promise that these ARM64 files work on other targets.
No downloaded libraries or fonts are committed to this repository.

Remote tests consume `@avalonia_native` file labels through `data_paths`. Raw
controls copy and hash-check those same acquired files. The old reads from the
client's `/usr/lib` and `/usr/share/fonts` are removed. Previously copied native
files are removed from prepared source workspaces. Independent recovery registers
the copied repository declaration again after relocating the rules checkout.

The new lock updates libexpat and libuuid to downloadable Ubuntu patch versions;
all other library/font bytes match the previous controls. Acquisition controls
pass on **Bazel 8.8.0 and 9.2.0**: fresh download, identical exported bytes with
repository downloads disabled and a shared repository cache, and rejection of an
incorrect archive checksum.

```sh
python3 tests/explicit_msbuild/avalonia/native_repository_controls.py \
  /tmp/fresh-native-controls
```

The edit fixture overrides the native file's declared label with a corrupt local
input for its negative control. It never edits Bazel's external repository cache.

With repository-acquired inputs, the five-suite, 53-configured-project graph on
Bazel 9.2.0 matches raw MSBuild/VSTest at **5,882 passes / 42 skips**. Compilation
is recovered from cache for this check; all five suites execute afresh, followed
by a no-op with no executed actions. All four edit/restoration controls pass.
A separate source-only client recovers all **291 observed actions** from the
remote cache and verifies the same individual test outcomes.

On Bazel 8.8.0, the smaller Headless/VNC control qualifies a cold build of
25 configured projects (27 compilation actions), four passing tests, and a
no-op. This does not claim the entire expanded graph was rerun on 8.8 with the
new package lock. The upstream Headless NUnit stability limit above still applies.
The separate Bazel 8.8 client also recovers every observed action from cache and
matches all four test outcomes. [Native acquisition evidence](avalonia-native-acquisition-evidence.json)
records the version-specific scope, action counts, and edit/restoration checks.
