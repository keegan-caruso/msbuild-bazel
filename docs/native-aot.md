# Native AOT: first Linux build

An SDK-style `net10.0` console app can now publish a runnable Linux ARM64
Native AOT executable through a Bazel action. MSBuild still owns `Publish` and
the ILCompiler invocation. Bazel owns the project source, SDK, six pinned NuGet
package archives, and the declared binary output. The native C compiler and
system libraries are taken from the **local Linux build machine** in this first
slice. Consequently, this action is not remotely executable or cacheable.

## Rule shape

The project sets `RuntimeIdentifier=linux-arm64`, `PublishAot=true`, and
`SelfContained=true`, and defines an export target that depends on `Publish` and
copies its executable to the `NativeBinaryOutput` property. The BUILD declaration
is ordinary `msbuild_generate`:

```starlark
msbuild_generate(
    name = "aot",
    executable = True,
    project = "Hello.csproj",
    srcs = ["Program.cs"],
    target_framework = "net10.0",
    targets = ["ExportAot"],
    outputs = ["Hello"],
    output_properties = {"NativeBinaryOutput": "Hello"},
    package_lock = ":aot_lock",
    build_deps = [":compiler", ":compiler_runtime", ":nativeaot_runtime", ":runtime_pack", ":aspnet_runtime_pack", ":illink"],
    local_native_tools = True,
)
```

Each `build_deps` entry is a `msbuild_nuget_package` with its archive SHA-256,
NuGet content hash, ID and version declared. The exact six packages chosen by
SDK 10.0.400 for runtime 10.0.11 are in the
[acceptance fixture](../tests/explicit_msbuild/native_aot.py). Removing the
ILCompiler package makes the closed restore fail with `NU1100`.

`local_native_tools` exposes the Linux machine's `/usr` read-only inside the
runner's existing Bubblewrap namespace, plus `/bin` and `/lib` links. The
workspace, SDK and packages remain separately mounted. The Bazel action has
`no-cache` and `no-remote` execution requirements. It requires a fresh local
action; persistent workers and remote execution are rejected.

## Measured proof

On the Apple Container Ubuntu 22.04 ARM64 toolchain image, with SDK 10.0.400,
Bazel 9.2.0 and native Linux sandboxing, the acceptance script built an ARM64
ELF executable and ran it successfully. A body edit rebuilt the binary, changed
its SHA-256 from
`2024acd2d33735eb83a9f6e11b0cec10d28966d614572098478712327ff34c79`
to `f0cdfbad3bf96be3a13fd3cfb64b944117e33b1cc942a4ba35e94817d4eb3e7f`,
and changed its output. Omitting the compiler package failed during offline
restore. The [report](native-aot-evidence.json) records these outcomes; it is
one qualification run, not a benchmark.

To repeat inside a Linux ARM64 environment with `clang`, `llvm-objcopy`, zlib
headers, the pinned Bazel binary, and a working Bubblewrap namespace:

```sh
export RULES_MSBUILD_BAZEL=/path/to/bazel-9.2.0
python3 tests/explicit_msbuild/native_aot.py /tmp/native-aot-qualification
```

The script fetches the six hash-pinned NuGet archives before constructing its
closed Bazel workspace. `--package-cache /path/to/nuget/packages` reuses a
verified local package cache instead. The resulting binary is
`source/bazel-bin/aot.generated/Hello` under the supplied output directory.

## Next boundary

The local compiler and system libraries are not Bazel inputs. To enable remote
caching and execution, supply a pinned native C toolchain/sysroot through a
Bazel toolchain, pass its files into this action, and remove
`local_native_tools`. Then prove independent cache recovery at a new workspace
path and execution in a worker without an ambient compiler. Support for a
source-built SDK additionally needs its matching ILCompiler, NativeAOT runtime,
runtime-pack and ILLink package outputs declared from source; this test uses
the downloaded SDK and packages. macOS, x64, cross-compilation, dynamic library
exports and ASP.NET AOT are not qualified here.
