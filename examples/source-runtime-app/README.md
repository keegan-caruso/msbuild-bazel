# App on a source-built runtime

Build the pinned Linux ARM64 or x64 .NET 10 runtime and run an app on it: the downloaded SDK compiles the graph, while the source-built host, CoreLib, and BCL run it. [Pins](source.json) identify the source and bootstrap SDK.

On Apple silicon (Apple Container + 32 GiB free):

```sh
container system start
python3 scripts/setup-source-runtime.py "$HOME/source-runtime" --worker-memory-gib 12
bash "$HOME/source-runtime/run.sh" --describe-runtime --verify-product
```

SDK 11 needs `--worker-memory-gib 12` (8 GiB exhausted guest memory; default remains 8 GiB for existing callers). Budget is frozen per setup; changing it requires a fresh directory. General build containers keep separate defaults.

Run from the rules checkout with Git, Python, and download access. Setup builds the [native environment](../../containers/runtime-demo.Dockerfile), creates an owned worker, runs package update/check and graph sync/check, then builds and verifies the app and runtime archive. On native Ubuntu 26.04 ARM64 with LLVM/Clang 18.1.8, omit `--worker-memory-gib`, configure host memory (provision ≥ 12 GiB; preflight minimum does not guarantee the full graph fits), and ensure nested user/mount namespaces. Apple guest runs do not qualify bare-host SDK 11 runs.

## Native Linux x64

Requires native Ubuntu 26.04 x64, Git, Python, download access, `dpkg-deb`, host GCC/G++ (for Bazel `rules_pkg`/`rules_cc` tool-launcher analysis; native producers use declared Clang 18.1.8), and nested user/mount namespaces. Provision host memory/disk separately (`--worker-memory-gib` is Apple-only).

```sh
python3 scripts/setup-source-runtime.py /build/source-runtime --system-bwrap
python3 scripts/setup-source-runtime.py /build/source-runtime --run --describe-runtime --verify-product
```

`--system-bwrap` is an Ubuntu AppArmor handoff: root-owned, non-symlink `/usr/bin/bwrap` and parents must pass permission checks, and its SHA-256 must match the declared launcher. Install the generic **amd64** Bubblewrap **0.11.1-1ubuntu0.3** from the [x64 catalog](../../tests/runtime/native-packages-x64.json) (same-version **amd64v3** has different bytes and is rejected; match URL/hash, not version). Omit `--system-bwrap` if the declared launcher is permitted.

Native x64 qualification built the runtime and passed both forced product tests after resuming the same setup; independent remote recovery and source-built x64 SDK remain separate ([evidence and limits](../../docs/support.md#complete-source-runtime-product)).

Rerun the same command (or `--resume`) to resume an owned setup with matching inputs. Retain the setup directory (Linux also depends on this rules checkout); reports/timings stay inside it.

In the prepared Linux workspace, Bazel owns remaining builds/tests (use the recorded launcher and cache options):

```sh
bazel build //:runtime_package
bazel test //:app_test //:runtime_test
```

`runtime_test` verifies producer hashes, executable bits, SDK-absent execution, and archive extraction (reports in Bazel test outputs). Source downloads use Bazel's verified repository cache. Native source selection, version headers, shared source archives, and the compiler/tool filesystem are declared Bazel outputs from [locked Ubuntu packages](../../tests/runtime/native-packages.json) (not copied from the worker). Compiler selection is explicit for CoreCLR, native libraries, and host. Graph sync remains a setup step.

Environment uses Ubuntu 26.04 glibc 2.43 (older glibc like Ubuntu 22.04 is unqualified). ARM64 and x64 use separate pinned native catalogs and bootstrap SDKs.

Pass `--cache-url=http://CACHE:8080` (reachable from worker) to reuse Bazel actions and MSBuild project snapshots. On Apple silicon, set `RULES_MSBUILD_SHARED_CACHE_SOCKET` to an existing host UNIX relay socket with an HTTPS DNS `--cache-url` to route via the guest relay preserving TLS identity (frozen per setup). Pass `--bazel-cache-read-only` on initial setup to disable Bazel action uploads (retained on resume/run); separately set `RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1` to disable project snapshot uploads (set both for full read-only). Cold cache still requires initial SDK Build.

`//:runtime_package` exports `runtime-linux-arm64.tar.gz` or `runtime-linux-x64.tar.gz`: an unsigned IL developer runtime with source provenance and upstream licenses. See [support](../../docs/support.md) for qualification/limits, [quick start](../quickstart/README.md#source-built-sdk) for source-built **SDK** compilation, and [runtime selection](../../docs/api.md#build-and-artifacts) for reusable declarations.
