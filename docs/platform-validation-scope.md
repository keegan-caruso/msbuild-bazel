# Platform validation scope

Support claims follow measured slices, not just successful tool installation.
SDK 10.0.400 and exact Bazel releases 8.8.0/9.2.0 are the current baselines;
9.2.0 is the default.

| Environment | Evidence and boundary |
| --- | --- |
| Ubuntu 22.04 ARM64 | [Persistent workers](explicit-linux-workers.md), [Orchard](orchard-explicit-performance.md), selected [runtime suites](runtime-loaded-closure.md) and independent HTTP-cache recovery |
| Native macOS ARM64 | Non-worker explicit-rule acceptance and [Bazel version checks](bazel-8.8-upgrade.md); not Linux worker evidence |
| Linux x86-64 | Bootstrap/Nix configurations and manual CI entry points exist; ARM64 qualification does not validate these workloads on x86-64 |
| Windows / cross-compilation | Not qualified by the current acceptance boundary |

The full runtime closure used Bazel 9.2.0. Generic regression fixtures also ran
on 8.8.0; that does not make the full runtime result an 8.8.0 measurement. Earlier
reports retain their original version pins, including retired 8.4.2 measurements.

Local sandboxing still depends on declared/allowed platform libraries and host
files. Remote-cache recovery is qualified for the reported producer/consumer
pairs. A [small remote-execution fixture](remote-execution.md) now passes on a
separate Linux ARM64 worker without a preinstalled SDK, on both Bazel baselines.
This does not qualify the full upstream graphs or arbitrary cross-platform cache reuse.
Windows additionally lacks an implemented runner sandbox, not just qualification hardware.
See [worker isolation](explicit-linux-workers.md) for the exact boundary.

Use the [Apple container runbook](apple-container-runbook.md) for Linux on Apple
silicon. GitHub [CI is manual-only](ci-scope.md); workflow availability is not
passing evidence. The retired platform decisions remain in the
[implementation history (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/implementation-history.md).
