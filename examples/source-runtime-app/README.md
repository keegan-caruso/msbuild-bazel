# App on a source-built runtime

Build the pinned Linux ARM64 or x64 .NET 10 runtime and run an ordinary app on it.
The downloaded SDK compiles the graph; the source-built host, CoreLib and BCL
execute the app. [Pins](source.json) identify the source and bootstrap SDK.

On Apple silicon, install Apple Container and provide 32 GiB free space:

```sh
container system start
python3 scripts/setup-source-runtime.py "$HOME/source-runtime" --worker-memory-gib 12
bash "$HOME/source-runtime/run.sh" --describe-runtime --verify-product
```

The SDK 11 workflow above explicitly selects 12 GiB: an 8 GiB qualification
run exhausted guest memory. The option defaults to 8 GiB for existing callers;
the selected budget is retained in the setup, and changing it requires a fresh
directory. General build containers retain their separate resource defaults.

Run from the rules checkout with Git, Python and download access. Setup builds the
[native environment](../../containers/runtime-demo.Dockerfile), creates an owned
worker, runs package update/check and graph sync/check, then builds and verifies
the app and runtime archive. On native Ubuntu 26.04 ARM64 with LLVM/Clang 18.1.8,
omit the Apple-only `--worker-memory-gib` option and configure the OS memory
budget separately. That path requires the same dependencies and nested user/mount
namespaces. Provision at least the 12 GiB used for Apple guest qualification;
the preflight minimum does not guarantee that the full graph fits. The Apple
guest result does not independently qualify a bare-host SDK 11 run.

## Native Linux x64

Use native Ubuntu 26.04 x64 with Git, Python, download access, `dpkg-deb`,
GCC/G++, and working nested user/mount namespaces. Host GCC/G++ are needed for
Bazel tool-launcher analysis (`rules_pkg` / `rules_cc`); native producers compile with the declared Clang
18.1.8 toolchain. Configure host memory and disk separately; the Apple-only
`--worker-memory-gib` option does not provision a native host.

```sh
python3 scripts/setup-source-runtime.py /build/source-runtime --system-bwrap
python3 scripts/setup-source-runtime.py /build/source-runtime --run --describe-runtime --verify-product
```

`--system-bwrap` is an explicit Ubuntu AppArmor handoff: the root-owned,
non-symlink `/usr/bin/bwrap` and its parents must pass permission checks, and
its SHA-256 must equal the declared launcher. Install the generic **amd64**
Bubblewrap **0.11.1-1ubuntu0.3** package from the
[x64 catalog](../../tests/runtime/native-packages-x64.json). Ubuntu's optimized
**amd64v3** package can have the same version but different bytes and is rejected.
Use the pinned package URL/hash rather than relying on version equality. This
retains the host's path-bound AppArmor policy. Hosts allowing the declared
launcher can omit `--system-bwrap`.

Native x64 qualification built the runtime and passed both forced product tests
after resuming the same setup. Independent remote recovery and a source-built
x64 SDK remain separate scopes; see [evidence and limits](../../docs/support.md#complete-source-runtime-product).

Rerun the same command to resume an owned setup with matching inputs. `--resume`
also remains available. Retain the setup
directory; Linux also retains a dependency on this rules checkout. Reports and
timings stay under the setup directory.

In the prepared Linux workspace, Bazel owns the remaining operations:

```sh
bazel build //:runtime_package
bazel test //:app_test //:runtime_test
```

Use the Bazel launcher and cache options recorded by setup. `runtime_test` checks
producer hashes, executable bits, SDK-absent execution and the extracted archive;
reports appear in Bazel's test outputs. Source downloads use Bazel's verified
repository cache. Native source selection, version headers, shared source archives
and the compiler/tool filesystem are declared Bazel outputs. The native tools come
from [locked Ubuntu packages](../../tests/runtime/native-packages.json); compilation
does not copy the worker's installed compiler files. Compiler selection is explicit for
CoreCLR, native libraries and the host. Graph sync remains a setup step.

The declared native environment uses Ubuntu 26.04 glibc 2.43. Deployment on
Ubuntu 22.04 or other older-glibc systems is unqualified. ARM64 and x64 producers
use separate pinned native catalogs and matching bootstrap SDKs.

Pass `--cache-url=http://CACHE:8080` to reuse Bazel actions and MSBuild project
snapshots during qualification and ordinary builds. The endpoint must be reachable
from the build worker. On Apple silicon, set `RULES_MSBUILD_SHARED_CACHE_SOCKET`
to an existing host UNIX relay socket and pass its HTTPS DNS URL with
`--cache-url` to route through the guest relay without changing TLS identity. The
socket and URL are frozen with the owned setup; use a fresh setup to change them.
For a consumer that must not upload whole Bazel actions, pass
`--bazel-cache-read-only` on initial setup; it is retained on resume and run.
This is separate from `RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1`, which controls
project snapshot publication. Set both for a consumer that should only read both
cache layers. A cold cache still requires the initial SDK Build.

The declared `//:runtime_package` output is exported as
`runtime-linux-arm64.tar.gz` or `runtime-linux-x64.tar.gz` in that directory. It is an unsigned IL developer
runtime with source provenance and upstream licenses. Qualification and platform
limits are in [support](../../docs/support.md).

For compilation with a source-built **SDK**, use the separate
[quick-start scenario](../quickstart/README.md#source-built-sdk).
The reusable declarations are [runtime selection](../../docs/api.md#build-and-artifacts).
