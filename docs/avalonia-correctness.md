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
negative controls must produce failing test cases, not merely a failed Bazel
command. Every restoration must recover the original passing outcomes without
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
or generation actions and explicitly reruns tests. It is not a cold-build result.
